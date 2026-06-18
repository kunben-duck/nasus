from __future__ import annotations

from typing import TYPE_CHECKING

from .agent_runtime_models import AgentGoalProposal
from .models import AgentGoal, AgentGoalCreateRequest

if TYPE_CHECKING:
    from .agent_workflow_runtime import AgentWorkflowRuntime
    from .store import ApplicationStore


TERMINAL_GOAL_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_GOAL_STATUSES = {"pending", "running", "paused", "blocked"}


class AgentService:
    """Coordinates AgentGoal lifecycle above the concrete loop runtime."""

    def __init__(self, store: "ApplicationStore", runtime: "AgentWorkflowRuntime") -> None:
        self.store = store
        self.runtime = runtime

    async def start_from_proposal(self, conversation_id: str, proposal: AgentGoalProposal) -> AgentGoal:
        existing = self.active_goal_for_conversation(conversation_id)
        if existing is not None:
            self.store.record_agent_goal_audit_event(
                existing,
                action="agent.goal.active_goal_guard",
                status=existing.status,
                summary=f"Existing active goal kept as controller: {existing.title}",
                actor="system",
                actor_kind="system",
            )
            await self.store.append_message(
                conversation_id,
                "assistant",
                (
                    f"I already have an active goal **{existing.title}** in this conversation. "
                    "I will keep that goal as the controlling work item until it completes, is cancelled, or is explicitly resumed."
                ),
                metadata={
                    "agent_runtime": "active_goal_guard",
                    "agent_goal_id": existing.id,
                    "status": existing.status,
                },
            )
            return existing
        return await self.runtime.start_goal(conversation_id, proposal)

    def create_manual_goal(self, payload: AgentGoalCreateRequest) -> AgentGoal:
        existing = self.active_goal_for_conversation(payload.conversation_id)
        if existing is not None:
            self.store.record_agent_goal_audit_event(
                existing,
                action="agent.goal.active_goal_guard",
                status=existing.status,
                summary=f"Manual goal creation reused active goal: {existing.title}",
                actor="system",
                actor_kind="system",
            )
            return existing
        return self.store.create_agent_goal(payload)

    async def resume_goal(self, goal_id: str) -> AgentGoal:
        goal = self.store.agent_goals[goal_id]
        self.store.record_agent_goal_audit_event(
            goal,
            action="agent.goal.resume_requested",
            status=goal.status,
            summary=f"Resume requested for AgentGoal: {goal.title}",
            actor="user",
            actor_kind="user",
        )
        return await self.runtime.resume_goal(goal_id)

    async def interrupt_goal(self, goal_id: str) -> AgentGoal:
        goal = self.store.agent_goals[goal_id]
        if goal.status in TERMINAL_GOAL_STATUSES:
            return goal
        goal.status = "paused"
        goal.pause_reason = "user_interrupt"
        self.store.conversation_repository.upsert_goal(goal)
        self.store._upsert_goal_in_conversation(goal)
        self.store.record_agent_goal_audit_event(
            goal,
            action="agent.goal.interrupted",
            status=goal.status,
            summary=f"User interrupted AgentGoal: {goal.title}",
            actor="user",
            actor_kind="user",
        )
        await self.store._push_goal_event(
            goal_id,
            "agent.goal.updated",
            "patch",
            {"status": "paused", "pause_reason": "user_interrupt"},
            [["agent-goal", goal_id]],
        )
        if goal.conversation_id:
            await self.store._push_event(
                goal.conversation_id,
                "agent.goal.updated",
                "agent_goal",
                goal_id,
                "patch",
                {"status": "paused", "pause_reason": "user_interrupt"},
                [["conversation", goal.conversation_id]],
            )
        return goal

    async def add_feedback(self, goal_id: str, feedback: str) -> AgentGoal:
        goal = self.store.agent_goals[goal_id]
        goal.summary = f"{goal.summary} Feedback: {feedback}"
        self.store.conversation_repository.upsert_goal(goal)
        self.store._upsert_goal_in_conversation(goal)
        self.store.record_agent_goal_audit_event(
            goal,
            action="agent.goal.feedback",
            status=goal.status,
            summary=f"User feedback added to AgentGoal: {goal.title}",
            actor="user",
            actor_kind="user",
            metadata={"feedback": feedback},
        )
        await self.store._push_goal_event(
            goal_id,
            "agent.goal.feedback",
            "patch",
            {"feedback": feedback},
            [["agent-goal", goal_id]],
        )
        if goal.conversation_id:
            await self.store.append_message(
                goal.conversation_id,
                "assistant",
                f"Feedback acknowledged for goal **{goal.title}**: {feedback}",
            )
        return goal

    def active_goal_for_conversation(self, conversation_id: str) -> AgentGoal | None:
        conversation = self.store.conversations[conversation_id]
        for goal in reversed(conversation.agent_goals):
            if goal.status in ACTIVE_GOAL_STATUSES:
                return goal
        return None
