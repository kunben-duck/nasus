from __future__ import annotations

import re
from typing import Any

from .agent_models import AgentGoal, AgentStep
from .ports import AgentGoalExplanationQueryPort
from ..platform.tool_models import ToolInvocation


class AgentGoalExplanationApplicationService:
    """Builds the AgentGoal explanation read model for UI and API consumers."""

    def __init__(self, queries: AgentGoalExplanationQueryPort) -> None:
        self._queries = queries

    def get_explanation(self, goal_id: str) -> dict[str, Any]:
        goal = self._queries.get_goal(goal_id)
        checkpoint = self._queries.get_checkpoint(goal_id)
        current_step = goal.steps[checkpoint.current_step_index] if checkpoint.current_step_index is not None else None
        blocked_step = goal.steps[checkpoint.blocked_step_index] if checkpoint.blocked_step_index is not None else None
        blocked_invocation = (
            self._tool_invocation_or_none(blocked_step.tool_invocation_id)
            if blocked_step is not None and blocked_step.tool_invocation_id
            else None
        )
        invocations = self._queries.list_tool_invocations(agent_goal_id=goal_id)
        memory_items = self._queries.list_agent_memory_items(source_ref=f"agent_goal:{goal_id}")
        audit_events = self._queries.list_audit_events(agent_goal_id=goal_id)
        latest_think_step = next((step for step in reversed(goal.steps) if step.phase == "thinking"), None)

        return {
            "goal_id": goal.id,
            "conversation_id": goal.conversation_id,
            "project_id": goal.project_id,
            "goal_template": goal.goal_template,
            "goal_description": goal.goal_description,
            "target_refs": goal.target_refs,
            "query_keys": goal.query_keys,
            "planner_kind": goal.planner_kind,
            "planning_summary": goal.planning_summary,
            "title": goal.title,
            "status": goal.status,
            "phase": checkpoint.phase,
            "pause_reason": goal.pause_reason,
            "budget": {
                "max_steps": goal.max_steps,
                "max_model_calls": goal.max_model_calls,
                "max_thinking_tokens": goal.max_thinking_tokens,
                "max_runtime_seconds": goal.max_runtime_seconds,
                "max_no_progress_observations": goal.max_no_progress_observations,
                "steps_completed": goal.steps_completed,
                "model_calls_used": goal.model_calls_used,
                "thinking_input_tokens_used": goal.thinking_input_tokens_used,
                "thinking_output_tokens_used": goal.thinking_output_tokens_used,
                "thinking_tokens_used": goal.thinking_tokens_used,
                "no_progress_observations": goal.no_progress_observations,
                "started_at": goal.started_at,
                "last_progress_at": goal.last_progress_at,
                "exhausted_reason": goal.budget_exhausted_reason,
            },
            "steps_completed": goal.steps_completed,
            "current_step": self._step_explanation(current_step),
            "blocked_step": self._step_explanation(blocked_step),
            "plan": [self._step_explanation(step) for step in goal.steps],
            "waiting_on": self._waiting_on(goal, blocked_invocation),
            "next_action": self._next_action(goal, blocked_invocation),
            "reasoning_summary": self._reasoning_summary(goal),
            "memory_context": {
                "context_hash": latest_think_step.memory_context_hash if latest_think_step else None,
                "summary": latest_think_step.memory_context_summary if latest_think_step else None,
                "retrieval_query": latest_think_step.memory_retrieval_query if latest_think_step else None,
                "retrieval_run_refs": latest_think_step.memory_retrieval_run_refs if latest_think_step else [],
                "retrieved_context_refs": latest_think_step.retrieved_context_refs if latest_think_step else [],
                "retrieved_context_summary": latest_think_step.retrieved_context_summary if latest_think_step else None,
            },
            "tool_invocation_refs": [f"tool_invocation:{invocation.id}" for invocation in invocations],
            "executed_tool_ids": [invocation.tool_id for invocation in invocations],
            "memory_refs": [f"agent_memory:{item.id}" for item in sorted(memory_items, key=lambda item: item.created_at)],
            "audit_event_refs": [f"audit:{event.id}" for event in audit_events],
        }

    def _tool_invocation_or_none(self, invocation_id: str) -> ToolInvocation | None:
        try:
            return self._queries.get_tool_invocation(invocation_id)
        except KeyError:
            return None

    @staticmethod
    def _step_explanation(step: AgentStep | None) -> dict[str, Any] | None:
        if step is None:
            return None
        return {
            "step_id": step.id,
            "title": step.title,
            "status": step.status,
            "phase": step.phase,
            "selected_tool_id": step.selected_tool_id,
            "tool_invocation_id": step.tool_invocation_id,
            "reasoning": step.reasoning,
            "observation_summary": step.observation_summary,
            "decision": step.decision,
            "decision_rationale": step.decision_rationale,
            "next_plan_hint": step.next_plan_hint,
        }

    @staticmethod
    def _waiting_on(goal: AgentGoal, blocked_invocation: ToolInvocation | None) -> str:
        if goal.status == "completed":
            return "none"
        if goal.status == "failed":
            return "human_review"
        if goal.pause_reason == "missing_source_binding":
            return "source_binding"
        if goal.pause_reason == "budget_exhausted":
            return "user_decision"
        if goal.pause_reason == "user_interrupt":
            return "user_resume"
        if blocked_invocation is not None and blocked_invocation.status == "waiting_confirmation":
            return "user_confirmation"
        if blocked_invocation is not None and blocked_invocation.status == "waiting_approval":
            return "approval"
        if goal.status in {"pending", "running"}:
            return "agent_runtime"
        return goal.pause_reason or "none"

    @staticmethod
    def _next_action(goal: AgentGoal, blocked_invocation: ToolInvocation | None) -> str:
        if goal.status == "completed":
            return "The AgentGoal is complete. Use the resulting memory, tool trace, or system image status for follow-up work."
        if goal.status == "failed":
            return "Review the blocked step and failure summary before resuming or creating a new goal."
        if goal.pause_reason == "missing_source_binding":
            return (
                "Provide code path or Git URL so the Agent can continue source ingestion. You may also upload "
                "historical US documents and test assets as optional enrichment sources."
            )
        if goal.pause_reason == "budget_exhausted":
            return "Increase the AgentGoal budget or ask the Agent to continue with a narrower scope."
        if goal.pause_reason == "user_interrupt":
            return "Resume the AgentGoal when you want the Agent to continue."
        if blocked_invocation is not None and blocked_invocation.status == "waiting_confirmation":
            return f"Confirm tool invocation {blocked_invocation.id} to let the Agent continue."
        if blocked_invocation is not None and blocked_invocation.status == "waiting_approval":
            return f"Approve tool invocation {blocked_invocation.id} through governance."
        running_step = next((step for step in goal.steps if step.status == "running"), None)
        if running_step is not None:
            return f"The Agent is currently working on: {running_step.title}."
        pending_step = next((step for step in goal.steps if step.status == "pending"), None)
        if pending_step is not None:
            return f"The next planned step is: {pending_step.title}."
        return "No next action is required."

    @staticmethod
    def _reasoning_summary(goal: AgentGoal) -> str:
        thinking_steps = [step for step in goal.steps if step.phase == "thinking" and step.reasoning]
        reasoning_steps = thinking_steps or [step for step in goal.steps if step.reasoning]
        if not reasoning_steps:
            return "No explicit thinking step has been recorded yet."
        latest = reasoning_steps[-1]
        reasoning = re.sub(r"\s+", " ", latest.reasoning or "").strip()
        return f"{latest.title}: {reasoning}"


__all__ = ["AgentGoalExplanationApplicationService"]
