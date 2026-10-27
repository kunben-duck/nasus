"""Pre-batch workflow compatibility fixture; never a production workflow."""
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, is_cancelled_exception


@workflow.defn(name="NasusTestDesignGenerationWorkflow")
class LegacyGenerationWorkflow:
    @workflow.run
    async def run(self, invocation_id: str) -> str:
        try:
            return await workflow.execute_activity("run_test_design_generation", invocation_id,
                start_to_close_timeout=timedelta(minutes=10), schedule_to_close_timeout=timedelta(minutes=30),
                heartbeat_timeout=timedelta(seconds=15), retry_policy=RetryPolicy(maximum_attempts=3),
                cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED)
        except ActivityError as exc:
            if is_cancelled_exception(exc):
                raise
            return await workflow.execute_activity("fail_test_design_generation", invocation_id,
                start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=3))
