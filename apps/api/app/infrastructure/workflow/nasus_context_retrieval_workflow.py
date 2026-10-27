from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn(name="NasusContextRetrievalWorkflow")
class NasusContextRetrievalWorkflow:
    @workflow.run
    async def run(self, invocation_id: str) -> str:
        return await workflow.execute_activity("run_context_retrieval", invocation_id,
            start_to_close_timeout=timedelta(minutes=30), schedule_to_close_timeout=timedelta(hours=1),
            heartbeat_timeout=timedelta(seconds=15), retry_policy=RetryPolicy(maximum_attempts=3),
            cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED)
