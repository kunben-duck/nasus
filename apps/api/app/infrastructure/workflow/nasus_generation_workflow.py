from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, is_cancelled_exception


@workflow.defn(name="NasusTestDesignGenerationWorkflow")
class NasusTestDesignGenerationWorkflow:
    @workflow.run
    async def run(self, invocation_id: str) -> str:
        # Preserve old workflow history while allowing every confirmed batch its
        # existing 120-second native deadline plus bounded validation overhead.
        complete_batches = workflow.patched("test-design-complete-batch-timeout-v1")
        activity_window = timedelta(seconds=64 * 120 + 10 * 60) if complete_batches else timedelta(minutes=10)
        retry_window = activity_window * 3 + timedelta(minutes=30) if complete_batches else timedelta(minutes=30)
        try:
            return await workflow.execute_activity("run_test_design_generation", invocation_id,
                start_to_close_timeout=activity_window, schedule_to_close_timeout=retry_window,
                heartbeat_timeout=timedelta(seconds=15), retry_policy=RetryPolicy(maximum_attempts=3),
                cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED)
        except ActivityError as exc:
            # Cancellation must not be reclassified as an ordinary failed job.
            if is_cancelled_exception(exc):
                raise
            return await workflow.execute_activity("fail_test_design_generation", invocation_id,
                start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=3))
