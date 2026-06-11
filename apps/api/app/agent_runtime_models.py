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
    initial_tool_id: str | None = None
    initial_tool_input: dict[str, Any] = field(default_factory=dict)
    query_keys: list[list[str]] = field(default_factory=list)
    kickoff_message: str | None = None


@dataclass
class OrchestratorDecision:
    kind: DecisionKind
    clarification: ClarificationRequest | None = None
    direct_answer: DirectAnswer | None = None
    tool_plan: ToolInvocationPlan | None = None
    agent_goal: AgentGoalProposal | None = None
