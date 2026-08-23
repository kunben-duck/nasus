from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from .agent_models import (
    AgentGoal,
    AgentGoalBudgetUpdateRequest,
    AgentGoalCreateRequest,
    AgentStep,
)
from .ports import AgentGoalLifecycleStatePort
from ...domain.agent.runtime_models import AgentGoalProposal, ModelUsage, ToolPlanStep
from ...domain.agent.budget_policy import evaluate_agent_budget

if TYPE_CHECKING:
    from .workflow import AgentWorkflowRuntime


TERMINAL_GOAL_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_GOAL_STATUSES = {"pending", "running", "paused", "blocked"}


class AgentGoalLifecycleApplicationService:
    """Coordinates AgentGoal lifecycle above the concrete loop runtime."""

    def __init__(
        self,
        state: AgentGoalLifecycleStatePort,
        runtime: "AgentWorkflowRuntime",
    ) -> None:
        self._state = state
        self.runtime = runtime

    async def start_from_proposal(self, conversation_id: str, proposal: AgentGoalProposal) -> AgentGoal:
        existing = self.active_goal_for_conversation(conversation_id)
        if existing is not None:
            self._state.record_goal_audit(
                existing,
                action="agent.goal.active_goal_guard",
                status=existing.status,
                summary=f"Existing active goal kept as controller: {existing.title}",
                actor="system",
                actor_kind="system",
            )
            await self._state.append_assistant_message(
                conversation_id,
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

    async def create_manual_goal(self, payload: AgentGoalCreateRequest) -> AgentGoal:
        existing = self.active_goal_for_conversation(payload.conversation_id)
        if existing is not None:
            self._state.record_goal_audit(
                existing,
                action="agent.goal.active_goal_guard",
                status=existing.status,
                summary=f"Manual goal creation reused active goal: {existing.title}",
                actor="system",
                actor_kind="system",
            )
            return existing
        planned_tools = [
            ToolPlanStep(
                tool_id=step.selected_tool_id,
                input_payload=dict(step.tool_input_payload),
                target_scope=step.tool_target_scope,
                reason=step.reasoning or step.title,
            )
            for step in payload.steps or []
            if step.phase == "acting" and step.selected_tool_id
        ]
        proposal = AgentGoalProposal(
            goal_template=payload.goal_template or "manual_goal",
            title=payload.title,
            summary=payload.summary,
            goal_description=payload.goal_description or payload.summary,
            planner_kind=payload.planner_kind or "manual",
            suggested_autonomy_level=payload.autonomy_level,
            estimated_steps=max(1, len(planned_tools)),
            target_refs=list(payload.target_refs),
            planned_tools=planned_tools,
            query_keys=list(payload.query_keys),
            planning_usage=ModelUsage(
                model_calls=payload.model_calls_used,
                input_tokens=payload.thinking_input_tokens_used,
                output_tokens=payload.thinking_output_tokens_used,
                usage_source="none",
            ),
            max_steps=payload.max_steps,
            max_model_calls=payload.max_model_calls,
            max_thinking_tokens=payload.max_thinking_tokens,
            max_runtime_seconds=payload.max_runtime_seconds,
            max_no_progress_observations=payload.max_no_progress_observations,
        )
        return await self.runtime.start_goal(payload.conversation_id, proposal)

    def create_goal_record(self, payload: AgentGoalCreateRequest) -> AgentGoal:
        goal = AgentGoal(
            id=f"goal_{uuid4().hex[:10]}",
            conversation_id=payload.conversation_id,
            project_id=payload.project_id,
            us_id=payload.us_id,
            goal_template=payload.goal_template,
            goal_description=payload.goal_description,
            target_refs=payload.target_refs,
            query_keys=payload.query_keys,
            planner_kind=payload.planner_kind or "manual",
            planning_summary=payload.planning_summary,
            title=payload.title,
            status="pending",
            summary=payload.summary,
            autonomy_level=payload.autonomy_level,
            max_steps=payload.max_steps,
            max_model_calls=payload.max_model_calls,
            max_thinking_tokens=payload.max_thinking_tokens,
            max_runtime_seconds=payload.max_runtime_seconds,
            max_no_progress_observations=payload.max_no_progress_observations,
            model_calls_used=payload.model_calls_used,
            thinking_input_tokens_used=payload.thinking_input_tokens_used,
            thinking_output_tokens_used=payload.thinking_output_tokens_used,
            thinking_tokens_used=(
                payload.thinking_input_tokens_used + payload.thinking_output_tokens_used
            ),
            workflow_id=f"wf_{uuid4().hex[:8]}",
            steps=payload.steps
            or [
                AgentStep(id="step_context", title="Assemble context", status="pending"),
                AgentStep(id="step_impact", title="Review impact", status="pending"),
                AgentStep(id="step_output", title="Materialize output", status="pending"),
            ],
        )
        self._state.create_goal(goal)
        self._state.record_goal_audit(
            goal,
            action="agent.goal.created",
            status="pending",
            summary=f"Agent goal created: {goal.title}",
            actor="system",
            actor_kind="system",
        )
        return goal

    def has_goal(self, goal_id: str) -> bool:
        return self._state.has_goal(goal_id)

    def get_goal(self, goal_id: str) -> AgentGoal:
        return self._state.get_goal(goal_id)

    def get_checkpoint(self, goal_id: str):
        return self.runtime.checkpoint(goal_id)

    def is_paused_goal(self, goal_id: str) -> bool:
        return self.has_goal(goal_id) and self.get_goal(goal_id).status == "paused"

    async def resume_goal(self, goal_id: str) -> AgentGoal:
        goal = self._state.get_goal(goal_id)
        self._state.record_goal_audit(
            goal,
            action="agent.goal.resume_requested",
            status=goal.status,
            summary=f"Resume requested for AgentGoal: {goal.title}",
            actor="user",
            actor_kind="user",
        )
        return await self.runtime.resume_goal(goal_id)

    async def interrupt_goal(self, goal_id: str) -> AgentGoal:
        goal = self._state.get_goal(goal_id)
        if goal.status in TERMINAL_GOAL_STATUSES:
            return goal
        goal.status = "paused"
        goal.pause_reason = "user_interrupt"
        self._state.persist_goal(goal)
        self._state.record_goal_audit(
            goal,
            action="agent.goal.interrupted",
            status=goal.status,
            summary=f"User interrupted AgentGoal: {goal.title}",
            actor="user",
            actor_kind="user",
        )
        await self._state.publish_interrupted(goal)
        return goal

    async def add_feedback(self, goal_id: str, feedback: str) -> AgentGoal:
        goal = self._state.get_goal(goal_id)
        goal.summary = f"{goal.summary} Feedback: {feedback}"
        self._state.persist_goal(goal)
        self._state.record_goal_audit(
            goal,
            action="agent.goal.feedback",
            status=goal.status,
            summary=f"User feedback added to AgentGoal: {goal.title}",
            actor="user",
            actor_kind="user",
            metadata={"feedback": feedback},
        )
        await self._state.publish_feedback(goal, feedback)
        if goal.conversation_id:
            await self._state.append_assistant_message(
                goal.conversation_id,
                f"Feedback acknowledged for goal **{goal.title}**: {feedback}",
            )
        return goal

    def update_budget(
        self,
        goal_id: str,
        payload: AgentGoalBudgetUpdateRequest,
    ) -> AgentGoal:
        goal = self._state.get_goal(goal_id)
        if goal.status == "running":
            raise ValueError("Pause the AgentGoal before changing its runtime budget.")
        changed: dict[str, int] = {}
        for field_name in (
            "max_steps",
            "max_model_calls",
            "max_thinking_tokens",
            "max_runtime_seconds",
            "max_no_progress_observations",
        ):
            value = getattr(payload, field_name)
            if value is None:
                continue
            setattr(goal, field_name, value)
            changed[field_name] = value
        if not changed:
            raise ValueError("At least one AgentGoal runtime budget must be provided.")
        if not evaluate_agent_budget(goal).exhausted:
            goal.budget_exhausted_reason = None
        self._state.persist_goal(goal)
        self._state.record_goal_audit(
            goal,
            action="agent.goal.budget_updated",
            status=goal.status,
            summary=f"Agent goal runtime budget updated: {goal.title}",
            actor="user",
            actor_kind="user",
            metadata={"changed_budgets": changed},
        )
        return goal

    def active_goal_for_conversation(self, conversation_id: str) -> AgentGoal | None:
        goals = tuple(self._state.list_goals_for_conversation(conversation_id))
        for goal in reversed(goals):
            if goal.status in ACTIVE_GOAL_STATUSES:
                return goal
        return None


AgentService = AgentGoalLifecycleApplicationService

__all__ = [
    "ACTIVE_GOAL_STATUSES",
    "TERMINAL_GOAL_STATUSES",
    "AgentGoalLifecycleApplicationService",
    "AgentService",
]
