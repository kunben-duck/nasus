from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn(name="NasusConversationMemoryWorkflow")
class NasusConversationMemoryWorkflow:
    @workflow.run
    async def run(self, job_id: str):
        return await workflow.execute_activity("compact_conversation_memory", job_id,
            start_to_close_timeout=timedelta(minutes=5), heartbeat_timeout=timedelta(seconds=20),
            retry_policy=RetryPolicy(maximum_attempts=2))
