import asyncio
import logging
import os
from datetime import timedelta

from ..config.agent_runtime_config import temporal_gateway_config_from_env
from .nasus_structure_workflow import NasusStructureBuildWorkflow

logger = logging.getLogger(__name__)


class TemporalStructureRuntime:
    def __init__(self, config=None, client=None):
        self.config = config or temporal_gateway_config_from_env()
        self.client, self.loop = client, None

    @property
    def enabled(self):
        return os.getenv("NASUS_AGENT_WORKFLOW_RUNTIME", "local") == "temporal"

    @property
    def task_queue(self):
        return self.config.task_queue + "-structure-builds"

    async def _client(self):
        if not self.enabled:
            raise ValueError("Durable structural work requires Temporal.")
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
        ident = "nasus-structure-build:" + invocation_id
        try:
            await client.start_workflow(NasusStructureBuildWorkflow.run, invocation_id, id=ident,
                task_queue=self.task_queue, id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                rpc_timeout=timedelta(seconds=10))
        except WorkflowAlreadyStartedError:
            description = await client.get_workflow_handle(ident).describe(rpc_timeout=timedelta(seconds=10))
            return description.status == WorkflowExecutionStatus.RUNNING
        return True


def build_structure_activities():
    from temporalio import activity

    @activity.defn(name="run_structure_build")
    async def run_structure_build(invocation_id: str):
        from ...bootstrap import get_application_container
        stop = asyncio.Event()

        async def heartbeat():
            while not stop.is_set():
                activity.heartbeat({"invocation_id": invocation_id})
                try:
                    await asyncio.wait_for(stop.wait(), 5)
                except asyncio.TimeoutError:
                    pass

        heartbeat_task = asyncio.create_task(heartbeat())
        try:
            try:
                return await get_application_container().structure_jobs.run(invocation_id)
            except Exception:
                from temporalio.exceptions import ApplicationError
                raise ApplicationError("Structural infrastructure unavailable; original pins and budget remain fixed.",
                    type="StructureInfrastructureFailure") from None
        finally:
            stop.set()
            await heartbeat_task

    @activity.defn(name="fail_structure_build")
    async def fail_structure_build(invocation_id: str):
        from ...bootstrap import get_application_container
        try:
            return await get_application_container().structure_jobs.fail(invocation_id)
        except Exception:
            from temporalio.exceptions import ApplicationError
            raise ApplicationError("Structural termination could not be recorded; reconciliation will retry.",
                type="StructureTerminationFailure") from None

    return [run_structure_build, fail_structure_build]


async def reconcile_structure_jobs_once(runtime, repository):
    after = ""
    while True:
        pending = await asyncio.to_thread(repository.pending, after_id=after)
        if not pending:
            return
        for invocation_id, _ in pending:
            try:
                if not await runtime.start(invocation_id):
                    await asyncio.to_thread(repository.finish, invocation_id, "failed")
            except Exception:
                logger.warning("Structural delivery deferred for invocation %s", invocation_id)
        after = pending[-1][0]


async def reconcile_structure_jobs(runtime):
    from ...bootstrap import get_application_container
    repository = get_application_container().structure_jobs.repository
    while True:
        try:
            await reconcile_structure_jobs_once(runtime, repository)
        except Exception:
            logger.warning("Structural workflow reconciliation deferred")
        await asyncio.sleep(5)
