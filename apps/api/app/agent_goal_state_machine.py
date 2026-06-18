from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .models import AgentGoal, AgentStep


AgentGoalPhase = Literal["pending", "thinking", "acting", "observing", "deciding", "completed", "failed", "paused"]


@dataclass(frozen=True)
class AgentGoalRuntimeCheckpoint:
    goal_id: str
    workflow_id: str | None
    status: str
    phase: AgentGoalPhase
    current_step_index: int | None
    current_step_id: str | None
    current_step_title: str | None
    blocked_step_index: int | None
    blocked_tool_invocation_id: str | None
    resume_step_index: int | None
    steps_completed: int


class AgentGoalStateMachine:
    """Centralizes AgentGoal/AgentStep transitions and derives durable resume checkpoints."""

    terminal_statuses = {"completed", "failed", "cancelled"}

    def checkpoint(self, goal: AgentGoal) -> AgentGoalRuntimeCheckpoint:
        blocked_index = self.blocked_act_step_index(goal)
        current_index = self.current_step_index(goal)
        current_step = goal.steps[current_index] if current_index is not None else None
        blocked_step = goal.steps[blocked_index] if blocked_index is not None else None
        return AgentGoalRuntimeCheckpoint(
            goal_id=goal.id,
            workflow_id=goal.workflow_id,
            status=goal.status,
            phase=self.phase(goal, current_step),
            current_step_index=current_index,
            current_step_id=current_step.id if current_step else None,
            current_step_title=current_step.title if current_step else None,
            blocked_step_index=blocked_index,
            blocked_tool_invocation_id=blocked_step.tool_invocation_id if blocked_step else None,
            resume_step_index=blocked_index,
            steps_completed=goal.steps_completed,
        )

    def start_goal(self, goal: AgentGoal) -> dict[str, str]:
        if goal.status in self.terminal_statuses:
            return {"status": goal.status}
        previous_status = goal.status
        goal.status = "running"
        goal.pause_reason = None
        lifecycle_transition = "resumed" if previous_status in {"paused", "blocked"} else "started"
        return {"status": goal.status, "lifecycle_transition": lifecycle_transition}

    def start_step(self, goal: AgentGoal, step_index: int, phase: AgentGoalPhase) -> dict[str, str]:
        step = goal.steps[step_index]
        step.status = "running"
        step.phase = phase  # type: ignore[assignment]
        return {"current_step": step.title, "phase": phase}

    def complete_step(
        self,
        goal: AgentGoal,
        step_index: int,
        *,
        decision: str | None = "continue",
        decision_rationale: str | None = None,
        observation_summary: str | None = None,
        next_plan_hint: str | None = None,
    ) -> dict[str, str]:
        step = goal.steps[step_index]
        step.status = "completed"
        if decision is not None:
            step.decision = decision  # type: ignore[assignment]
        if decision_rationale is not None:
            step.decision_rationale = decision_rationale
        if observation_summary is not None:
            step.observation_summary = observation_summary
        if next_plan_hint is not None:
            step.next_plan_hint = next_plan_hint
        goal.steps_completed = max(goal.steps_completed, step_index + 1)
        return {"current_step": step.title, "status": goal.status}

    def pause_on_gate(self, goal: AgentGoal, step_index: int, pause_reason: str) -> dict[str, str]:
        step = goal.steps[step_index]
        goal.status = "paused"
        goal.pause_reason = pause_reason
        step.status = "blocked"
        step.decision = "pause"
        step.decision_rationale = "The selected tool reached a governance gate and needs an external resume signal."
        return {"status": goal.status, "pause_reason": pause_reason, "lifecycle_transition": "paused"}

    def pause_on_budget(self, goal: AgentGoal, step_index: int) -> dict[str, str]:
        step = goal.steps[step_index]
        goal.status = "paused"
        goal.pause_reason = "budget_exhausted"
        step.status = "blocked"
        step.decision = "pause"
        step.decision_rationale = "The AgentGoal reached max_steps and needs a user decision before continuing."
        return {"status": goal.status, "pause_reason": goal.pause_reason, "lifecycle_transition": "budget_exhausted"}

    def pause_on_followup(self, goal: AgentGoal, step_index: int, pause_reason: str, summary: str) -> dict[str, str]:
        step = goal.steps[step_index]
        goal.status = "paused"
        goal.pause_reason = pause_reason
        step.status = "blocked"
        step.decision = "pause"
        step.decision_rationale = summary
        return {"status": goal.status, "pause_reason": pause_reason, "lifecycle_transition": "paused"}

    def fail_on_step(self, goal: AgentGoal, step_index: int, summary: str) -> dict[str, str]:
        step = goal.steps[step_index]
        goal.status = "failed"
        step.status = "blocked"
        step.decision = "fail"
        step.decision_rationale = summary
        return {"status": goal.status, "current_step": step.title, "lifecycle_transition": "failed"}

    def complete_goal(self, goal: AgentGoal, step_index: int | None = None) -> dict[str, str]:
        if step_index is not None and 0 <= step_index < len(goal.steps):
            step = goal.steps[step_index]
            step.status = "completed"
            step.decision = step.decision or "complete"
            goal.steps_completed = max(goal.steps_completed, step_index + 1)
            current_step = step.title
        else:
            current_step = ""
        goal.status = "completed"
        goal.pause_reason = None
        goal.steps_completed = len(goal.steps)
        return {"status": goal.status, "current_step": current_step, "lifecycle_transition": "completed"}

    @staticmethod
    def current_step_index(goal: AgentGoal) -> int | None:
        for index, step in enumerate(goal.steps):
            if step.status == "running":
                return index
        for index, step in enumerate(goal.steps):
            if step.status == "blocked":
                return index
        for index, step in enumerate(goal.steps):
            if step.status == "pending":
                return index
        if goal.steps:
            return len(goal.steps) - 1
        return None

    @staticmethod
    def blocked_act_step_index(goal: AgentGoal) -> int | None:
        for index, step in enumerate(goal.steps):
            if step.phase == "acting" and step.status == "blocked":
                return index
        return None

    @staticmethod
    def phase(goal: AgentGoal, step: AgentStep | None) -> AgentGoalPhase:
        if goal.status == "completed":
            return "completed"
        if goal.status == "failed":
            return "failed"
        if goal.status == "paused":
            return "paused"
        if step and step.phase:
            return step.phase
        return "pending"
