from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


DecisionKind = Literal["clarification", "direct_answer", "tool_plan", "agent_goal"]


@dataclass
class ClarificationRequest:
    question: str
    reason: str
    missing_context: list[str] = field(default_factory=list)


@dataclass
class DirectAnswer:
    fallback_text: str
    query_keys: list[list[str]] = field(default_factory=list)


@dataclass
class ToolPlanStep:
    tool_id: str
    input_payload: dict[str, Any]
    target_scope: Literal["central", "edge"] = "central"
    reason: str = ""


@dataclass
class ToolInvocationPlan:
    intent_kind: str
    confidence: float
    steps: list[ToolPlanStep]
    recommended_next_tools: list[str] = field(default_factory=list)


@dataclass
class AgentGoalProposal:
    goal_template: str
    title: str
    summary: str
    goal_description: str
    suggested_autonomy_level: Literal["full_auto", "semi_auto", "step_by_step"] = "semi_auto"
    estimated_steps: int = 3
    target_refs: list[str] = field(default_factory=list)
    requires_user_confirmation: bool = False
    planned_tools: list[ToolPlanStep] = field(default_factory=list)
    initial_tool_id: str | None = None
    initial_tool_input: dict[str, Any] = field(default_factory=dict)
    query_keys: list[list[str]] = field(default_factory=list)
    kickoff_message: str | None = None


def tool_plan_step_from_payload(payload: dict[str, Any]) -> ToolPlanStep:
    return ToolPlanStep(
        tool_id=str(payload["tool_id"]),
        input_payload=dict(payload.get("input_payload") or payload.get("input") or {}),
        target_scope=payload.get("target_scope", "central"),
        reason=str(payload.get("reason") or ""),
    )


def agent_goal_proposal_from_payload(payload: dict[str, Any]) -> AgentGoalProposal:
    return AgentGoalProposal(
        goal_template=str(payload["goal_template"]),
        title=str(payload["title"]),
        summary=str(payload["summary"]),
        goal_description=str(payload["goal_description"]),
        suggested_autonomy_level=payload.get("suggested_autonomy_level", "semi_auto"),
        estimated_steps=int(payload.get("estimated_steps", 3)),
        target_refs=list(payload.get("target_refs") or []),
        requires_user_confirmation=bool(payload.get("requires_user_confirmation", False)),
        planned_tools=[tool_plan_step_from_payload(item) for item in payload.get("planned_tools", [])],
        initial_tool_id=payload.get("initial_tool_id"),
        initial_tool_input=dict(payload.get("initial_tool_input") or {}),
        query_keys=list(payload.get("query_keys") or []),
        kickoff_message=payload.get("kickoff_message"),
    )


@dataclass
class OrchestratorDecision:
    kind: DecisionKind
    clarification: ClarificationRequest | None = None
    direct_answer: DirectAnswer | None = None
    tool_plan: ToolInvocationPlan | None = None
    agent_goal: AgentGoalProposal | None = None
