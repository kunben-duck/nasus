from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

from temporalio import workflow


AGENT_GOAL_WORKFLOW_TYPE = "NasusAgentGoalWorkflow"
CURRENT_GOAL_QUERY = "current_goal"
RESUME_GOAL_SIGNAL = "resume_goal"
WAITING_AGENT_GOAL_STATUSES = frozenset({"paused", "blocked"})


@workflow.defn(name=AGENT_GOAL_WORKFLOW_TYPE)
class NasusAgentGoalWorkflow:
    """Durable Temporal lifecycle for one AgentGoal."""

    def __init__(self) -> None:
        self._current_goal: dict[str, Any] | None = None
        self._resume_requested = False
        self._resume_payload: dict[str, Any] = {}

    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._current_goal = await workflow.execute_activity(
            "start_agent_goal",
            payload,
            start_to_close_timeout=timedelta(minutes=30),
        )
        while self._is_waiting_for_resume(self._current_goal):
            await workflow.wait_condition(lambda: self._resume_requested)
            self._resume_requested = False
            resume_payload: dict[str, Any] = {
                "goal_id": self._current_goal["id"],
            }
            actor = self._resume_payload.get("actor")
            if actor is not None:
                resume_payload["actor"] = actor
            self._resume_payload = {}
            self._current_goal = await workflow.execute_activity(
                "resume_agent_goal",
                resume_payload,
                start_to_close_timeout=timedelta(minutes=30),
            )
        return self._current_goal

    @workflow.query(name=CURRENT_GOAL_QUERY)
    def current_goal(self) -> dict[str, Any]:
        return self._current_goal or {}

    @workflow.signal(name=RESUME_GOAL_SIGNAL)
    async def resume_goal(self, payload: Optional[dict[str, Any]] = None) -> None:
        self._resume_payload = dict(payload or {})
        self._resume_requested = True

    @staticmethod
    def _is_waiting_for_resume(goal: dict[str, Any] | None) -> bool:
        return bool(goal and goal.get("status") in WAITING_AGENT_GOAL_STATUSES)


__all__ = [
    "AGENT_GOAL_WORKFLOW_TYPE",
    "CURRENT_GOAL_QUERY",
    "NasusAgentGoalWorkflow",
    "RESUME_GOAL_SIGNAL",
]
