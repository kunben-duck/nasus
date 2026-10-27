import asyncio
import logging
from datetime import timedelta

from .generation_runtime import TemporalGenerationRuntime
from .nasus_native_build_workflow import NasusNativeBuildWorkflow

logger = logging.getLogger(__name__)


class TemporalNativeBuildRuntime(TemporalGenerationRuntime):
    @property
    def task_queue(self):
        return self.config.task_queue + "-native-build"

    async def start(self, invocation_id):
        from temporalio.client import WorkflowExecutionStatus
        from temporalio.common import WorkflowIDReusePolicy
        from temporalio.exceptions import WorkflowAlreadyStartedError
        client = await self._client()
        ident = "nasus-native-build:" + invocation_id
        try:
            await client.start_workflow(NasusNativeBuildWorkflow.run, invocation_id, id=ident,
                task_queue=self.task_queue, id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                rpc_timeout=timedelta(seconds=10))
        except WorkflowAlreadyStartedError:
            status = await client.get_workflow_handle(ident).describe(rpc_timeout=timedelta(seconds=10))
            return status.status == WorkflowExecutionStatus.RUNNING
        return True

    async def cancel(self, invocation_id):
        from temporalio.service import RPCError, RPCStatusCode
        client = await self._client()
        try:
            await client.get_workflow_handle("nasus-native-build:" + invocation_id).cancel(rpc_timeout=timedelta(seconds=10))
        except RPCError as exc:
            if exc.status != RPCStatusCode.NOT_FOUND:
                raise


def build_native_build_activities():
    from temporalio import activity
    from temporalio.exceptions import ApplicationError

    @activity.defn(name="run_native_build")
    async def run_native_build(invocation_id: str):
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
                return await get_application_container().native_build_jobs.run(invocation_id)
            except Exception:
                raise ApplicationError("Native build infrastructure unavailable; existing reservations are never rebuilt.",
                    type="NativeBuildInfrastructureFailure") from None
        finally:
            stop.set()
            await task

    @activity.defn(name="fail_native_build")
    async def fail_native_build(invocation_id: str):
        from ...bootstrap import get_application_container
        try:
            return await get_application_container().native_build_jobs.fail(invocation_id)
        except Exception:
            raise ApplicationError("Native build termination deferred until the current owner is fenced.",
                type="NativeBuildTerminationFailure") from None

    return [run_native_build, fail_native_build]


async def reconcile_native_builds_once(runtime, repository):
    for cancelling in (True, False):
        after_id = None
        query = repository.pending_cancellations if cancelling else repository.pending
        while True:
            page = await asyncio.to_thread(query, after_id=after_id)
            if not page:
                break
            for invocation_id, project_id in page:
                try:
                    if cancelling:
                        await runtime.cancel(invocation_id)
                        await asyncio.to_thread(repository.cancellation_delivered, project_id, invocation_id)
                    elif not await runtime.start(invocation_id):
                        await asyncio.to_thread(repository.finish, project_id, invocation_id, "failed")
                except Exception:
                    logger.warning("Native build workflow delivery deferred for %s", invocation_id)
            after_id = page[-1][0]


async def reconcile_native_builds(runtime):
    from ...bootstrap import get_application_container
    repository = get_application_container().native_build_jobs.repository
    while True:
        try:
            await reconcile_native_builds_once(runtime, repository)
        except Exception:
            logger.warning("Native build reconciliation deferred")
        await asyncio.sleep(5)
