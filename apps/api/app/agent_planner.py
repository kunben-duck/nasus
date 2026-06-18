from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .agent_memory import AgentMemoryContext
from .agent_runtime_models import (
    AgentGoalProposal,
    ClarificationRequest,
    DirectAnswer,
    OrchestratorDecision,
    ToolInvocationPlan,
    ToolPlanStep,
)
from .conversation_orchestrator import ConversationOrchestrator
from .llm import LLMGateway
from .models import ConversationSession, StudioSettings, ToolDefinition


SummaryBuilder = Callable[[ConversationSession], str]
NameExtractor = Callable[[str], str]
SettingsProvider = Callable[[], StudioSettings]
SecretProvider = Callable[[], str]
MemoryContextBuilder = Callable[[ConversationSession], AgentMemoryContext]


class AgentPlanner(Protocol):
    async def plan(self, conversation: ConversationSession, user_message: str) -> OrchestratorDecision:
        ...


@dataclass
class DeterministicAgentPlanner:
    orchestrator: ConversationOrchestrator

    @classmethod
    def build(
        cls,
        *,
        tools: list[ToolDefinition],
        project_name_extractor: NameExtractor,
        version_name_extractor: NameExtractor,
        summary_builder: SummaryBuilder,
    ) -> "DeterministicAgentPlanner":
        return cls(
            orchestrator=ConversationOrchestrator(
                tools=tools,
                project_name_extractor=project_name_extractor,
                version_name_extractor=version_name_extractor,
                summary_builder=summary_builder,
            )
        )

    async def plan(self, conversation: ConversationSession, user_message: str) -> OrchestratorDecision:
        return self.orchestrator.plan(conversation, user_message)


@dataclass
class LLMStructuredAgentPlanner:
    fallback: AgentPlanner
    llm: LLMGateway
    tools: list[ToolDefinition]
    settings_provider: SettingsProvider
    custom_api_key_provider: SecretProvider
    memory_context_builder: MemoryContextBuilder

    async def plan(self, conversation: ConversationSession, user_message: str) -> OrchestratorDecision:
        fallback_decision = await self.fallback.plan(conversation, user_message)
        settings = self.settings_provider()
        if settings.runtime_mode != "live":
            return fallback_decision

        memory_context = self.memory_context_builder(conversation)
        reply = await self.llm.generate_reply(
            settings=settings,
            system_prompt=self._planner_system_prompt(memory_context),
            user_message=user_message,
            context_snapshot=memory_context.context_snapshot,
            history_snapshot=memory_context.history_snapshot,
            fallback_text="{}",
            custom_api_key=self.custom_api_key_provider(),
        )
        if reply.mode != "live":
            return fallback_decision

        try:
            payload = self._extract_json(reply.content)
            decision = self._decision_from_payload(payload)
        except (TypeError, ValueError, KeyError):
            return fallback_decision

        return decision or fallback_decision

    def _decision_from_payload(self, payload: dict[str, Any]) -> OrchestratorDecision | None:
        kind = payload.get("kind")
        if kind == "clarification":
            return OrchestratorDecision(
                kind="clarification",
                clarification=ClarificationRequest(
                    question=str(payload.get("question") or "I need more context before I can continue."),
                    reason=str(payload.get("reason") or "planner_clarification"),
                    missing_context=[str(item) for item in payload.get("missing_context", [])],
                ),
            )

        if kind == "direct_answer":
            return OrchestratorDecision(
                kind="direct_answer",
                direct_answer=DirectAnswer(
                    fallback_text=str(payload.get("fallback_text") or "I can help plan the next tool action."),
                    query_keys=self._query_keys(payload),
                ),
            )

        if kind == "tool_plan":
            steps = self._tool_steps(payload.get("steps", []))
            if not steps:
                return None
            return OrchestratorDecision(
                kind="tool_plan",
                tool_plan=ToolInvocationPlan(
                    intent_kind=str(payload.get("intent_kind") or "llm_tool_plan"),
                    confidence=float(payload.get("confidence") or 0.75),
                    steps=steps,
                    recommended_next_tools=self._tool_ids(payload.get("recommended_next_tools", [])),
                ),
            )

        if kind == "agent_goal":
            steps = self._tool_steps(payload.get("steps", []))
            initial_tool = steps[0] if steps else None
            return OrchestratorDecision(
                kind="agent_goal",
                agent_goal=AgentGoalProposal(
                    goal_template=str(payload.get("goal_template") or "llm_planned_goal"),
                    title=str(payload.get("title") or "Agent planned goal"),
                    summary=str(payload.get("summary") or "Execute a structured agent goal."),
                    goal_description=str(payload.get("goal_description") or payload.get("summary") or ""),
                    suggested_autonomy_level=payload.get("suggested_autonomy_level") or "semi_auto",
                    estimated_steps=int(payload.get("estimated_steps") or max(3, len(steps) * 2 + 2)),
                    planned_tools=steps,
                    initial_tool_id=initial_tool.tool_id if initial_tool else None,
                    initial_tool_input=initial_tool.input_payload if initial_tool else {},
                    target_refs=[str(item) for item in payload.get("target_refs", [])],
                    query_keys=self._query_keys(payload),
                    kickoff_message=payload.get("kickoff_message"),
                ),
            )

        return None

    def _tool_steps(self, raw_steps: Any) -> list[ToolPlanStep]:
        if not isinstance(raw_steps, list):
            return []

        steps: list[ToolPlanStep] = []
        allowed_tools = {tool.tool_id for tool in self.tools}
        for item in raw_steps:
            if not isinstance(item, dict):
                continue
            tool_id = str(item.get("tool_id") or "")
            if tool_id not in allowed_tools:
                raise ValueError(f"planner selected unknown tool {tool_id}")
            input_payload = item.get("input") or item.get("input_payload") or {}
            if not isinstance(input_payload, dict):
                input_payload = {}
            target_scope = item.get("target_scope") or "central"
            if target_scope not in {"central", "edge"}:
                target_scope = "central"
            steps.append(
                ToolPlanStep(
                    tool_id=tool_id,
                    input_payload=input_payload,
                    target_scope=target_scope,
                    reason=str(item.get("reason") or "Selected by structured planner."),
                )
            )
        return steps

    def _tool_ids(self, raw_items: Any) -> list[str]:
        if not isinstance(raw_items, list):
            return []
        allowed_tools = {tool.tool_id for tool in self.tools}
        return [str(item) for item in raw_items if str(item) in allowed_tools]

    @staticmethod
    def _query_keys(payload: dict[str, Any]) -> list[list[str]]:
        raw_keys = payload.get("query_keys", [])
        if not isinstance(raw_keys, list):
            return []
        keys: list[list[str]] = []
        for key in raw_keys:
            if isinstance(key, list):
                keys.append([str(part) for part in key])
        return keys

    @staticmethod
    def _extract_json(content: str) -> dict[str, Any]:
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            if stripped.startswith("json"):
                stripped = stripped[4:].strip()
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end < start:
            raise ValueError("planner response did not contain a JSON object")
        parsed = json.loads(stripped[start:end + 1])
        if not isinstance(parsed, dict):
            raise ValueError("planner response must be a JSON object")
        return parsed

    @staticmethod
    def _planner_system_prompt(memory_context: AgentMemoryContext) -> str:
        return (
            f"{memory_context.system_prompt}\n\n"
            "You are the Nasus structured agent planner. Return exactly one JSON object and no prose. "
            "Choose only tools that exist in the provided Tool catalog. All write actions must be expressed as "
            "tool_plan or agent_goal steps; never claim that a write action has already happened. "
            "For high-risk tools, still include them in the plan; governance gates will pause execution. "
            "Valid top-level kind values: clarification, direct_answer, tool_plan, agent_goal. "
            "For tool_plan and agent_goal, include steps as an array of {tool_id,input,reason,target_scope}. "
            "For system image construction, prefer the chain system_image.sources.register, "
            "system_image.sources.ingest, system_image.context.materialize, system_image.baseline.initialize."
        )
