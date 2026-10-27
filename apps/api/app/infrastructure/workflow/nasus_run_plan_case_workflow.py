from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, is_cancelled_exception


@workflow.defn
class NasusRunPlanCaseWorkflow:
    @workflow.run
    async def run(self, invocation_id: str) -> str:
        try:
            return await workflow.execute_activity("run_original_run_plan_cases", invocation_id,
                start_to_close_timeout=timedelta(minutes=12), schedule_to_close_timeout=timedelta(minutes=30),
                heartbeat_timeout=timedelta(seconds=15),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=15), maximum_interval=timedelta(seconds=60), maximum_attempts=6),
                cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED)
        except ActivityError as exc:
            if is_cancelled_exception(exc):
                raise
            return await workflow.execute_activity("fail_original_run_plan_cases", invocation_id,
                start_to_close_timeout=timedelta(minutes=3),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=15), maximum_interval=timedelta(seconds=60), maximum_attempts=6))
