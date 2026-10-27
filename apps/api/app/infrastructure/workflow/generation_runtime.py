import asyncio
import logging
import os
from datetime import timedelta

from .nasus_generation_workflow import NasusTestDesignGenerationWorkflow
from ..config.agent_runtime_config import temporal_gateway_config_from_env

logger = logging.getLogger(__name__)


class TemporalGenerationRuntime:
    def __init__(self, config=None, client=None):
        self.config = config or temporal_gateway_config_from_env()
        self.client, self.loop = client, None

    @property
    def task_queue(self):
        return self.config.task_queue + "-test-design-generation"

    async def _client(self):
        if os.getenv("NASUS_AGENT_WORKFLOW_RUNTIME", "local") != "temporal":
            raise ValueError("durable test-design generation requires Temporal")
        if self.client is None or (self.loop is not None and self.loop is not asyncio.get_running_loop()):
            from temporalio.client import Client
            self.client = await asyncio.wait_for(Client.connect(self.config.address, namespace=self.config.namespace), 10)
        self.loop = asyncio.get_running_loop()
        return self.client

    async def start(self, invocation_id):
        from temporalio.client import WorkflowExecutionStatus
        from temporalio.common import WorkflowIDReusePolicy
        from temporalio.exceptions import WorkflowAlreadyStartedError
        client = await self._client()
        ident = "nasus-test-design-generation:" + invocation_id
        try:
            await client.start_workflow(NasusTestDesignGenerationWorkflow.run, invocation_id, id=ident,
                task_queue=self.task_queue, id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                rpc_timeout=timedelta(seconds=10))
        except WorkflowAlreadyStartedError:
            description = await client.get_workflow_handle(ident).describe(rpc_timeout=timedelta(seconds=10))
            return description.status == WorkflowExecutionStatus.RUNNING
        return True

    async def cancel(self, invocation_id):
        from temporalio.service import RPCError, RPCStatusCode
        client = await self._client()
        try:
            await client.get_workflow_handle("nasus-test-design-generation:" + invocation_id).cancel(rpc_timeout=timedelta(seconds=10))
        except RPCError as exc:
            if exc.status != RPCStatusCode.NOT_FOUND:
                raise


def build_generation_activities():
    from temporalio import activity

    @activity.defn(name="run_test_design_generation")
    async def run_test_design_generation(invocation_id: str):
        from ...bootstrap import get_application_container
        stop = asyncio.Event()

        async def heartbeat():
            while not stop.is_set():
                activity.heartbeat({"invocation_id": invocation_id})
                try:
                    await asyncio.wait_for(stop.wait(), 5)
                except asyncio.TimeoutError:
                    pass

        task = asyncio.create_task(heartbeat())
        try:
            try:
                return await get_application_container().test_design_jobs.run(invocation_id)
            except Exception:
                from temporalio.exceptions import ApplicationError
                raise ApplicationError("Generation infrastructure failed; archived replies are revalidated before retry.",
                    type="GenerationInfrastructureFailure") from None
        finally:
            stop.set()
            await task

    @activity.defn(name="fail_test_design_generation")
    async def fail_test_design_generation(invocation_id: str):
        from ...bootstrap import get_application_container
        try:
            return await get_application_container().test_design_jobs.fail(invocation_id)
        except Exception:
            from temporalio.exceptions import ApplicationError
            raise ApplicationError("Generation termination receipt unavailable; reconciliation will retry.",
                type="GenerationTerminationFailure") from None

    return [run_test_design_generation, fail_test_design_generation]


async def reconcile_generation_jobs_once(runtime, repository):
    for cancelling in (True, False):
        after_id = None
        query = repository.pending_cancellations if cancelling else repository.pending
        while True:
            pending = await asyncio.to_thread(query, after_id=after_id)
            if not pending:
                break
            for invocation_id, project_id in pending:
                try:
                    if cancelling:
                        await runtime.cancel(invocation_id)
                        await asyncio.to_thread(repository.cancellation_delivered, project_id, invocation_id)
                    elif not await runtime.start(invocation_id):
                        await asyncio.to_thread(repository.finish, project_id, invocation_id, "failed",
                            "Generation workflow terminated. Inspect the archived reply before explicitly requesting recovery; unknown calls are never resent.")
                except Exception:
                    logger.warning("Generation workflow delivery deferred for invocation %s", invocation_id)
            after_id = pending[-1][0]


async def reconcile_generation_jobs(runtime):
    from ...bootstrap import get_application_container
    repository = get_application_container().test_design_jobs.repository
    while True:
        try:
            await reconcile_generation_jobs_once(runtime, repository)
        except Exception:
            logger.warning("Generation workflow reconciliation deferred")
        await asyncio.sleep(5)
