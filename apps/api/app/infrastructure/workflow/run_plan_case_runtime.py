import asyncio
import logging
from datetime import timedelta

from .generation_runtime import TemporalGenerationRuntime
from .execution_activity_errors import execution_activity_error
from .nasus_run_plan_case_workflow import NasusRunPlanCaseWorkflow

logger = logging.getLogger(__name__)


class TemporalRunPlanCaseRuntime(TemporalGenerationRuntime):
    @property
    def task_queue(self):
        return self.config.task_queue + "-run-plan-cases"

    async def start(self, invocation_id):
        from temporalio.client import WorkflowExecutionStatus
        from temporalio.common import WorkflowIDReusePolicy
        from temporalio.exceptions import WorkflowAlreadyStartedError
        client = await self._client()
        ident = "nasus-run-plan-cases:" + invocation_id
        try:
            await client.start_workflow(NasusRunPlanCaseWorkflow.run, invocation_id, id=ident, task_queue=self.task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE, rpc_timeout=timedelta(seconds=10))
        except WorkflowAlreadyStartedError:
            original = await client.get_workflow_handle(ident).describe(rpc_timeout=timedelta(seconds=10))
            return original.status == WorkflowExecutionStatus.RUNNING
        return True

    async def cancel(self, invocation_id):
        from temporalio.service import RPCError, RPCStatusCode
        client = await self._client()
        try:
            await client.get_workflow_handle("nasus-run-plan-cases:" + invocation_id).cancel(rpc_timeout=timedelta(seconds=10))
        except RPCError as exc:
            if exc.status != RPCStatusCode.NOT_FOUND:
                raise


def build_run_plan_case_activities():
    from temporalio import activity
    from temporalio.exceptions import ApplicationError
    @activity.defn(name="run_original_run_plan_cases")
    async def run_original_run_plan_cases(invocation_id: str):
        from ...bootstrap import get_application_container
        stopped = asyncio.Event()
        async def heartbeat():
            while not stopped.is_set():
                activity.heartbeat({"invocation_id": invocation_id})
                try:
                    await asyncio.wait_for(stopped.wait(), 5)
                except asyncio.TimeoutError:
                    pass
        task = asyncio.create_task(heartbeat())
        try:
            try:
                return await get_application_container().run_plan_case_jobs.run(invocation_id)
            except Exception as error:
                raise execution_activity_error(error, prefix="RunPlanCase") from None
        finally:
            stopped.set()
            await task

    @activity.defn(name="fail_original_run_plan_cases")
    async def fail_original_run_plan_cases(invocation_id: str):
        from ...bootstrap import get_application_container
        try:
            return await get_application_container().run_plan_case_jobs.fail(invocation_id)
        except Exception:
            raise ApplicationError("Original case finalization deferred until its worker is fenced.",
                type="RunPlanCaseTerminationFailure") from None
    return [run_original_run_plan_cases, fail_original_run_plan_cases]


async def reconcile_run_plan_cases_once(runtime, repository, *, jobs):
    for cancelling in (True, False):
        after_id = None
        query = repository.pending_cancellations if cancelling else repository.pending
        while True:
            page = await asyncio.to_thread(query, after_id=after_id)
            if not page:
                break
            for invocation_id in page:
                try:
                    if cancelling:
                        await runtime.cancel(invocation_id)
                        await asyncio.to_thread(repository.cancellation_delivered, invocation_id)
                    else:
                        await jobs.deliver(invocation_id)
                except Exception:
                    logger.warning("Original case workflow delivery deferred for %s", invocation_id)
            after_id = page[-1]


async def reconcile_run_plan_cases(runtime):
    from ...bootstrap import get_application_container
    jobs = get_application_container().run_plan_case_jobs
    while True:
        try:
            await reconcile_run_plan_cases_once(runtime, jobs.repository, jobs=jobs)
        except Exception:
            logger.warning("Original case workflow reconciliation deferred")
        await asyncio.sleep(5)
