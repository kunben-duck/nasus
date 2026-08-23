from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable, Protocol

from .agent_models import AgentGoal, ConversationSession
from .orchestrator import ConversationOrchestrator, QualityStateResolver
from .replanning import AgentReplanDecision, AgentReplanRequest
from .reply_ports import AgentReplyGenerationPort
from ...domain.agent.memory import AgentMemoryContext
from ...domain.agent.plan_policy import (
    AgentPlanPolicy,
    AgentPlanPolicyViolation,
    AgentPlanScope,
    AgentToolContract,
)
from ...domain.agent.runtime_models import (
    AgentGoalProposal,
    ClarificationRequest,
    DirectAnswer,
    ModelUsage,
    OrchestratorDecision,
    ToolInvocationPlan,
    ToolPlanStep,
)
from ...domain.platform.llm_call import LLMCallContext
from ...domain.platform.prompt_registry import PromptDefinition, builtin_prompt
from ...application.platform.model_settings import StudioSettings
from ...application.platform.prompts import PromptRegistryPort
from ..platform.tool_models import ToolDefinition


SummaryBuilder = Callable[[ConversationSession], str]
NameExtractor = Callable[[str], str]
SettingsProvider = Callable[[], StudioSettings]
SecretProvider = Callable[[], str]
MemoryContextBuilder = Callable[[ConversationSession], Awaitable[AgentMemoryContext]]


class AgentPlanner(Protocol):
    async def plan(
        self,
        conversation: ConversationSession,
        user_message: str,
        *,
        canonical_action_id: str | None = None,
    ) -> OrchestratorDecision:
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
        quality_state_resolver: QualityStateResolver | None = None,
    ) -> "DeterministicAgentPlanner":
        return cls(
            orchestrator=ConversationOrchestrator(
                tools=tools,
                project_name_extractor=project_name_extractor,
                version_name_extractor=version_name_extractor,
                summary_builder=summary_builder,
                **({"quality_state_resolver": quality_state_resolver} if quality_state_resolver else {}),
            )
        )

    async def plan(
        self,
        conversation: ConversationSession,
        user_message: str,
        *,
        canonical_action_id: str | None = None,
    ) -> OrchestratorDecision:
        return self.orchestrator.plan(conversation, user_message)


@dataclass
class LLMStructuredAgentPlanner:
    fallback: AgentPlanner
    llm: AgentReplyGenerationPort
    tools: list[ToolDefinition]
    settings_provider: SettingsProvider
    custom_api_key_provider: SecretProvider
    memory_context_builder: MemoryContextBuilder
    plan_policy: AgentPlanPolicy = field(default_factory=AgentPlanPolicy)
    allow_deterministic_write_fallback: bool = True
    prompt_registry: PromptRegistryPort | None = None

    async def plan(
        self,
        conversation: ConversationSession,
        user_message: str,
        *,
        canonical_action_id: str | None = None,
    ) -> OrchestratorDecision:
        fallback_decision = await self.fallback.plan(conversation, user_message)
        if self._is_canonical_ui_agent_action(canonical_action_id, user_message):
            return fallback_decision
        settings = self.settings_provider()
        if settings.runtime_mode != "live":
            return self._safe_deterministic_fallback(
                fallback_decision,
                reason="route_not_live",
            )

        memory_context = await self.memory_context_builder(conversation)
        prompt = self._active_prompt("agent_loop_planner")
        reply = await self.llm.generate_reply(
            settings=settings,
            system_prompt=self._planner_system_prompt(
                memory_context,
                prompt.system_template,
            ),
            user_message=user_message,
            context_snapshot=memory_context.context_snapshot,
            history_snapshot=memory_context.history_snapshot,
            fallback_text="{}",
            custom_api_key=self.custom_api_key_provider(),
            call_context=LLMCallContext(
                purpose="agent.initial_plan",
                prompt_id=prompt.prompt_id,
                prompt_version=prompt.version,
                project_id=conversation.project_id,
                version_id=conversation.version_id,
                task_id=conversation.task_id or conversation.us_id,
                conversation_id=conversation.id,
            ),
        )
        model_usage = self._model_usage(reply)
        if reply.mode != "live":
            safe_fallback = self._safe_deterministic_fallback(
                fallback_decision,
                reason="provider_fallback",
            )
            return self._decision_with_usage(safe_fallback, model_usage)

        try:
            payload = self._extract_json(reply.content)
            decision = self._decision_from_payload(payload)
            if decision is not None:
                decision = self._govern_decision(decision, conversation)
        except AgentPlanPolicyViolation as exc:
            return self._clarification_for_policy_violation(exc)
        except (TypeError, ValueError, KeyError):
            safe_fallback = self._safe_deterministic_fallback(
                fallback_decision,
                reason="invalid_structured_output",
            )
            return self._decision_with_usage(safe_fallback, model_usage)

        if decision is None:
            decision = self._safe_deterministic_fallback(
                fallback_decision,
                reason="invalid_structured_output",
            )
        return self._decision_with_usage(decision, model_usage)

    async def replan(self, request: AgentReplanRequest) -> AgentReplanDecision:
        settings = self.settings_provider()
        if settings.runtime_mode != "live" or request.goal.planner_kind != "llm_structured":
            return AgentReplanDecision.keep(
                "The goal is using its validated initial plan.",
                planner_kind="initial_plan",
            )
        if not request.remaining_steps:
            return AgentReplanDecision.keep(
                "No pending tool action remains to replan.",
                planner_kind="initial_plan",
            )

        memory_context = await self.memory_context_builder(request.conversation)
        prompt = self._active_prompt("agent_loop_replanner")
        reply = await self.llm.generate_reply(
            settings=settings,
            system_prompt=self._replanner_system_prompt(
                memory_context,
                prompt.system_template,
            ),
            user_message=self._replanner_user_message(request),
            context_snapshot=memory_context.context_snapshot,
            history_snapshot=memory_context.history_snapshot,
            fallback_text="{}",
            custom_api_key=self.custom_api_key_provider(),
            call_context=LLMCallContext(
                purpose="agent.replan",
                prompt_id=prompt.prompt_id,
                prompt_version=prompt.version,
                project_id=request.goal.project_id or request.conversation.project_id,
                version_id=request.conversation.version_id,
                task_id=request.goal.us_id or request.conversation.task_id,
                conversation_id=request.conversation.id,
                agent_goal_id=request.goal.id,
            ),
        )
        model_usage = self._model_usage(reply)
        if reply.mode != "live":
            return AgentReplanDecision.keep(
                "The live replanner was unavailable, so the validated initial plan was retained.",
                planner_kind="provider_fallback",
                model_usage=model_usage,
            )

        try:
            payload = self._extract_json(reply.content)
            action = str(payload.get("action") or "")
            rationale = str(
                payload.get("rationale")
                or "The latest tool observation does not require a plan change."
            )
            confidence = min(1.0, max(0.0, float(payload.get("confidence") or 0.0)))
            if action == "keep":
                return AgentReplanDecision.keep(
                    rationale,
                    confidence=confidence,
                    planner_kind="llm_structured",
                    model_usage=model_usage,
                )
            if action == "complete":
                self._validate_replan_completion(request.goal, request.completed_steps)
                return AgentReplanDecision(
                    action="complete",
                    rationale=rationale,
                    confidence=confidence,
                    planner_kind="llm_structured",
                    model_usage=model_usage,
                )
            if action != "replace_remaining":
                return AgentReplanDecision.keep(
                    "The replanner returned an unsupported action, so the validated plan was retained.",
                    planner_kind="invalid_replan_output",
                    model_usage=model_usage,
                )

            replacement_steps = self._tool_steps(payload.get("steps", []))
            if not replacement_steps:
                return AgentReplanDecision.keep(
                    "The replanner did not provide a valid replacement tool sequence.",
                    planner_kind="invalid_replan_output",
                    model_usage=model_usage,
                )
            all_steps = [*request.completed_steps, *replacement_steps]
            bound_steps = self.plan_policy.bind_and_validate(
                all_steps,
                contracts=self._tool_contracts(),
                scope=self._plan_scope(request.conversation),
            )
            self.plan_policy.validate_goal_completion_contract(
                request.goal.goal_template or "",
                bound_steps,
            )
            replacement_count = len(replacement_steps)
            return AgentReplanDecision(
                action="replace_remaining",
                rationale=rationale,
                planned_tools=bound_steps[-replacement_count:],
                confidence=confidence,
                planner_kind="llm_structured",
                model_usage=model_usage,
            )
        except AgentPlanPolicyViolation as exc:
            return AgentReplanDecision.keep(
                f"The proposed replan was rejected by policy: {exc.code}.",
                planner_kind=f"replan_policy:{exc.code}",
                model_usage=model_usage,
            )
        except (TypeError, ValueError, KeyError):
            return AgentReplanDecision.keep(
                "The replanner response was invalid, so the validated plan was retained.",
                planner_kind="invalid_replan_output",
                model_usage=model_usage,
            )

    @staticmethod
    def _model_usage(reply: Any) -> ModelUsage:
        return ModelUsage(
            model_calls=max(0, int(getattr(reply, "model_calls", 0) or 0)),
            input_tokens=max(0, int(getattr(reply, "input_tokens", 0) or 0)),
            output_tokens=max(0, int(getattr(reply, "output_tokens", 0) or 0)),
            usage_source=getattr(reply, "usage_source", "none"),
        )

    @staticmethod
    def _decision_with_usage(
        decision: OrchestratorDecision,
        usage: ModelUsage,
    ) -> OrchestratorDecision:
        if decision.kind != "agent_goal" or decision.agent_goal is None:
            return decision
        return replace(
            decision,
            agent_goal=replace(decision.agent_goal, planning_usage=usage),
        )

    def _safe_deterministic_fallback(
        self,
        decision: OrchestratorDecision,
        *,
        reason: str,
    ) -> OrchestratorDecision:
        if self.allow_deterministic_write_fallback or not self._has_write_effect(decision):
            return decision
        return OrchestratorDecision(
            kind="clarification",
            clarification=ClarificationRequest(
                question=(
                    "The live planning model is unavailable, so I did not start the requested "
                    "write action. Restore the chat model connection and try again."
                ),
                reason=f"planner_provider_unavailable:{reason}",
                missing_context=["live_chat_model"],
            ),
        )

    def _has_write_effect(self, decision: OrchestratorDecision) -> bool:
        if decision.kind == "agent_goal":
            return True
        if decision.kind != "tool_plan" or decision.tool_plan is None:
            return False
        definitions_by_id = {tool.tool_id: tool for tool in self.tools}
        return any(
            definitions_by_id.get(step.tool_id) is None
            or definitions_by_id[step.tool_id].tool_kind != "query"
            for step in decision.tool_plan.steps
        )

    @staticmethod
    def _is_canonical_ui_agent_action(
        canonical_action_id: str | None,
        user_message: str,
    ) -> bool:
        """Accept only explicit UI actions whose fixed command still matches the contract."""
        normalized = " ".join(user_message.strip().lower().split())
        expected_commands = {
            "system-image.build-goal": (
                "build the official system image from code, historical us documents, "
                "and historical test assets."
            ),
            "quality-loop.continue-goal": (
                "complete the end-to-end quality loop for the riskiest open us through "
                "scope, scenarios, verification planning, cases, automation evidence, "
                "a change document, and release readiness."
            ),
        }
        return expected_commands.get(canonical_action_id) == normalized

    def _govern_decision(
        self,
        decision: OrchestratorDecision,
        conversation: ConversationSession,
    ) -> OrchestratorDecision:
        scope = self._plan_scope(conversation)
        contracts = self._tool_contracts()
        if decision.kind == "tool_plan" and decision.tool_plan is not None:
            bound_steps = self.plan_policy.bind_and_validate(
                decision.tool_plan.steps,
                contracts=contracts,
                scope=scope,
            )
            definitions_by_id = {tool.tool_id: tool for tool in self.tools}
            if any(
                definitions_by_id[step.tool_id].tool_kind != "query"
                for step in bound_steps
            ):
                title = self._write_goal_title(decision.tool_plan.intent_kind, bound_steps)
                proposal = AgentGoalProposal(
                    goal_template=decision.tool_plan.intent_kind or "llm_planned_goal",
                    title=title,
                    summary=f"Execute {len(bound_steps)} governed tool action(s) for {title}.",
                    goal_description=title,
                    planner_kind="llm_structured",
                    suggested_autonomy_level="semi_auto",
                    estimated_steps=min(50, len(bound_steps) * 2 + 2),
                    planned_tools=bound_steps,
                    initial_tool_id=bound_steps[0].tool_id,
                    initial_tool_input=bound_steps[0].input_payload,
                    target_refs=self._scope_target_refs(conversation),
                    query_keys=[["conversation", conversation.id]],
                    kickoff_message=(
                        "I converted the requested write plan into a governed AgentGoal "
                        "so every action remains interruptible and auditable."
                    ),
                )
                return OrchestratorDecision(kind="agent_goal", agent_goal=proposal)
            return replace(
                decision,
                tool_plan=replace(decision.tool_plan, steps=bound_steps),
            )
        if decision.kind == "agent_goal" and decision.agent_goal is not None:
            bound_steps = self.plan_policy.bind_and_validate(
                decision.agent_goal.planned_tools,
                contracts=contracts,
                scope=scope,
            )
            self.plan_policy.validate_goal_completion_contract(
                decision.agent_goal.goal_template,
                bound_steps,
            )
            initial_tool = bound_steps[0]
            target_refs = list(decision.agent_goal.target_refs)
            for ref in self._scope_target_refs(conversation):
                if ref and ref not in target_refs:
                    target_refs.append(ref)
            return replace(
                decision,
                agent_goal=replace(
                    decision.agent_goal,
                    planned_tools=bound_steps,
                    initial_tool_id=initial_tool.tool_id,
                    initial_tool_input=initial_tool.input_payload,
                    target_refs=target_refs,
                    estimated_steps=min(
                        50,
                        max(
                            decision.agent_goal.estimated_steps,
                            len(bound_steps) * 2 + 2,
                        ),
                    ),
                ),
            )
        return decision

    @staticmethod
    def _plan_scope(conversation: ConversationSession) -> AgentPlanScope:
        return AgentPlanScope(
            conversation_id=conversation.id,
            project_id=conversation.project_id,
            version_id=conversation.version_id,
            us_id=conversation.us_id,
            task_id=conversation.task_id,
        )

    def _tool_contracts(self) -> list[AgentToolContract]:
        return [
            AgentToolContract(
                tool_id=tool.tool_id,
                scope=tool.scope,
                required_context=tuple(tool.required_context),
            )
            for tool in self.tools
        ]

    def _validate_replan_completion(
        self,
        goal: AgentGoal,
        completed_steps: list[ToolPlanStep],
    ) -> None:
        if goal.goal_template not in {"quality_loop", "us.quality.complete"}:
            return
        if not completed_steps or completed_steps[-1].tool_id != "release.assess":
            raise AgentPlanPolicyViolation(
                "incomplete_goal_plan",
                "A quality goal cannot complete before release.assess has succeeded.",
                missing_context=("complete_quality_plan",),
            )

    @staticmethod
    def _scope_target_refs(conversation: ConversationSession) -> list[str]:
        return [
            ref
            for ref in (
                f"project:{conversation.project_id}" if conversation.project_id else None,
                f"version:{conversation.version_id}" if conversation.version_id else None,
                f"us:{conversation.us_id}" if conversation.us_id else None,
                f"task:{conversation.task_id}" if conversation.task_id else None,
            )
            if ref is not None
        ]

    @staticmethod
    def _write_goal_title(intent_kind: str, steps: list[ToolPlanStep]) -> str:
        normalized_intent = " ".join(
            part for part in intent_kind.replace("_", " ").replace(".", " ").split() if part
        )
        if normalized_intent:
            return normalized_intent[:96].capitalize()
        return f"Execute {steps[0].tool_id}"

    @staticmethod
    def _clarification_for_policy_violation(
        violation: AgentPlanPolicyViolation,
    ) -> OrchestratorDecision:
        if violation.code == "missing_context":
            question = (
                f"I need {', '.join(violation.missing_context)} before I can execute this plan."
            )
        elif violation.code == "scope_conflict":
            question = (
                "The proposed action targets a different workspace scope. "
                "Open the intended project, version, or US workspace and try again."
            )
        elif violation.code == "step_budget_exceeded":
            question = (
                "This request produced too many tool actions for one governed goal. "
                "Please narrow the objective or split it into stages."
            )
        elif violation.code == "incomplete_goal_plan":
            question = (
                "The proposed quality goal did not include a complete path to release assessment. "
                "Please provide any missing execution target or narrow the request to a specific quality stage."
            )
        else:
            question = "I could not produce a safe executable plan. Please clarify the intended outcome."
        return OrchestratorDecision(
            kind="clarification",
            clarification=ClarificationRequest(
                question=question,
                reason=f"planner_policy:{violation.code}",
                missing_context=list(violation.missing_context),
            ),
        )

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
                    fallback_text=str(
                        payload.get("fallback_text")
                        or payload.get("text")
                        or "I can help plan the next tool action."
                    ),
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
                    planner_kind="llm_structured",
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
    def _planner_system_prompt(
        memory_context: AgentMemoryContext,
        system_template: str,
    ) -> str:
        return f"{memory_context.system_prompt}\n\n{system_template}"

    @staticmethod
    def _replanner_system_prompt(
        memory_context: AgentMemoryContext,
        system_template: str,
    ) -> str:
        return f"{memory_context.system_prompt}\n\n{system_template}"

    def _active_prompt(self, prompt_id: str) -> PromptDefinition:
        if self.prompt_registry is not None:
            return self.prompt_registry.get_active(prompt_id)
        return builtin_prompt(prompt_id)

    @staticmethod
    def _replanner_user_message(request: AgentReplanRequest) -> str:
        completed = [
            {"tool_id": step.tool_id, "input": step.input_payload}
            for step in request.completed_steps
        ]
        remaining = [
            {"tool_id": step.tool_id, "input": step.input_payload}
            for step in request.remaining_steps
        ]
        return json.dumps(
            {
                "goal_id": request.goal.id,
                "goal_template": request.goal.goal_template,
                "goal_description": request.goal.goal_description or request.goal.summary,
                "latest_observation": request.observation_summary,
                "completed_steps": completed,
                "validated_remaining_steps": remaining,
            },
            ensure_ascii=False,
            sort_keys=True,
        )


__all__ = [
    "AgentPlanner",
    "DeterministicAgentPlanner",
    "LLMStructuredAgentPlanner",
]
