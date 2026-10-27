from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow


CONVERSATION_TURN_WORKFLOW_TYPE = "NasusConversationTurnWorkflow"


@workflow.defn(name=CONVERSATION_TURN_WORKFLOW_TYPE)
class NasusConversationTurnWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await workflow.execute_activity(
            "run_conversation_turn",
            payload,
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=timedelta(seconds=15),
        )


__all__ = ["CONVERSATION_TURN_WORKFLOW_TYPE", "NasusConversationTurnWorkflow"]
