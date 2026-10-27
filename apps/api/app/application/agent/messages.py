from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from typing import Any, Dict

from .ports import ConversationMessageRuntimePort
from ..platform.tool_models import ToolInvocation, ToolInvocationRequest
from ...domain.agent.image_plan_policy import is_pinned_image_plan
from ...domain.agent.resume_checkpoint import AgentResumeCheckpoint, AgentResumeCheckpointChanged
from ...domain.agent.image_plan_phases import active_phase_start
from ...domain.agent.runtime_models import ToolPlanStep


class ConversationMessageApplicationService:
    """Main conversation message orchestration use cases."""

    def __init__(self, runtime: ConversationMessageRuntimePort) -> None:
        self._runtime = runtime

    async def post_message(
        self,
        conversation_id: str,
        content: str,
        *,
        canonical_action_id: str | None = None,
    ) -> Dict[str, Any]:
        self._runtime.get_conversation(conversation_id)
        await self._runtime.append_message(
            conversation_id,
            "user",
            content,
            metadata=(
                {
                    "initiator_surface": "ui",
                    "canonical_action_id": canonical_action_id,
                }
                if canonical_action_id
                else None
            ),
        )
        return await self.process_message(
            conversation_id,
            content,
            canonical_action_id=canonical_action_id,
        )

    async def prepare_message(
        self,
        conversation_id: str,
        content: str,
        *,
        canonical_action_id: str | None = None,
    ) -> dict[str, Any]:
        conversation = self._runtime.get_conversation(conversation_id)
        source_binding_result = await self.handle_source_binding_message_if_any(conversation_id, content)
        if source_binding_result is not None:
            return {"route": "finalize", "result": source_binding_result}
        confirmation_result = await self.handle_confirmation_message_if_any(conversation_id, content)
        if confirmation_result is not None:
            return {"route": "finalize", "result": confirmation_result}

        if canonical_action_id:
            decision = await self._runtime.plan_message(
                conversation,
                content,
                canonical_action_id=canonical_action_id,
            )
        else:
            decision = await self._runtime.plan_message(conversation, content)

        return {
            "route": decision.kind,
            "decision": self._to_plain_data(decision),
        }

    async def process_message(
        self,
        conversation_id: str,
        content: str,
        *,
        canonical_action_id: str | None = None,
        turn_id: str | None = None,
    ) -> Dict[str, Any]:
        prepared = await self.prepare_message(
            conversation_id,
            content,
            canonical_action_id=canonical_action_id,
        )
        return await self.execute_prepared(
            conversation_id,
            content,
            prepared,
            turn_id=turn_id,
        )

    async def execute_prepared(
        self,
        conversation_id: str,
        content: str,
        prepared: dict[str, Any],
        *,
        turn_id: str | None = None,
    ) -> Dict[str, Any]:
        conversation = self._runtime.get_conversation(conversation_id)
        route = str(prepared.get("route") or "finalize")
        if route == "finalize":
            return dict(prepared.get("result") or {})
        decision = dict(prepared.get("decision") or {})

        clarification = decision.get("clarification")
        if route == "clarification" and isinstance(clarification, dict):
            await self._runtime.append_message(
                conversation_id,
                "assistant",
                str(clarification.get("question") or "Please provide more context."),
                metadata={
                    "planner_kind": "clarification",
                    "clarification_kind": clarification.get("reason"),
                    "missing_context": list(clarification.get("missing_context") or []),
                },
            )
            return {"clarification": clarification}

        tool_plan = decision.get("tool_plan")
        if route == "tool_plan" and isinstance(tool_plan, dict):
            tool_invocations = []
            for step in tool_plan.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                invocation = await self._runtime.create_tool_invocation(
                    ToolInvocationRequest(
                        conversation_id=conversation_id,
                        tool_id=str(step["tool_id"]),
                        input=dict(step.get("input_payload") or {}),
                        initiator_surface="chat",
                        initiator_actor="user",
                        target_scope=step.get("target_scope", "central"),
                    )
                )
                tool_invocations.append(invocation)
            return {"tool_invocations": tool_invocations}

        agent_goal = decision.get("agent_goal")
        if route == "agent_goal" and isinstance(agent_goal, dict):
            from ...domain.agent.runtime_models import agent_goal_proposal_from_payload

            goal = await self._runtime.start_goal_from_proposal(
                conversation_id,
                agent_goal_proposal_from_payload(agent_goal),
            )
            return {"agent_goal": goal}

        direct_answer = decision.get("direct_answer")
        fallback_text = (
            str(direct_answer.get("fallback_text"))
            if isinstance(direct_answer, dict) and direct_answer.get("fallback_text")
            else self._runtime.fallback_text(conversation)
        )
        query_keys = (
            list(direct_answer.get("query_keys") or [])
            if isinstance(direct_answer, dict)
            else [["conversation", conversation_id]]
        )
        tool_input: dict[str, Any] = {
            "user_message": content,
            "fallback_text": fallback_text,
            "query_keys": query_keys,
        }
        if turn_id:
            tool_input.update({"_stream_reply": True, "_conversation_turn_id": turn_id})
        tool_invocation = await self._runtime.create_tool_invocation(
            ToolInvocationRequest(
                conversation_id=conversation_id,
                tool_id="query.answer",
                input=tool_input,
                initiator_surface="chat",
                initiator_actor="user",
                target_scope="central",
            )
        )
        return {"tool_invocation": tool_invocation}

    @classmethod
    def _to_plain_data(cls, value: Any) -> Any:
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, dict):
            return {key: cls._to_plain_data(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._to_plain_data(item) for item in value]
        if hasattr(value, "__dict__"):
            return {
                key: cls._to_plain_data(item)
                for key, item in vars(value).items()
            }
        return value

    async def handle_confirmation_message_if_any(self, conversation_id: str, content: str) -> Dict[str, Any] | None:
        if not self._runtime.is_confirmation_message(content):
            return None

        invocation = self.pending_confirmation_invocation(conversation_id, content)
        if invocation is None:
            return None

        goal_id = invocation.input_payload.get("agent_goal_id")
        if isinstance(goal_id, str):
            current = self._runtime.get_goal(goal_id)
            conversation = self._runtime.get_conversation(conversation_id)
            blocked = [step for step in current.steps[active_phase_start(current):] if step.phase == "acting" and step.status == "blocked"]
            if (current.id != goal_id or current.conversation_id != conversation_id
                    or current.project_id != conversation.project_id or invocation.conversation_id != conversation_id
                    or current.status != "paused" or current.pause_reason != "waiting_confirmation"
                    or len(blocked) != 1 or blocked[0].tool_invocation_id != invocation.id
                    or blocked[0].selected_tool_id != invocation.tool_id):
                raise AgentResumeCheckpointChanged()
            if is_pinned_image_plan([ToolPlanStep(step.selected_tool_id, step.tool_input_payload)
                    for step in current.steps if step.selected_tool_id], current.target_refs):
                if invocation.input_payload.get("project_id") != current.project_id:
                    raise AgentResumeCheckpointChanged()
                # Chat consent is scoped to this exact pending command, never a
                # generic structural continuation or a newer confirmation gate.
                checkpoint = AgentResumeCheckpoint.capture(current.model_dump(mode="json"))
                goal = await self._runtime.resume_goal(goal_id, expected_resume=checkpoint)
            else:
                goal = await self._runtime.resume_goal(goal_id)
            return {
                "agent_goal": goal,
                "tool_invocation": self._runtime.get_tool_invocation(invocation.id),
            }

        confirmed = await self._runtime.confirm_tool_invocation(invocation.id)
        return {"tool_invocation": confirmed}

    async def handle_source_binding_message_if_any(self, conversation_id: str, content: str) -> Dict[str, Any] | None:
        active_goal = self._runtime.active_goal_for_conversation(conversation_id)
        if active_goal is None or active_goal.status != "paused" or active_goal.pause_reason != "missing_source_binding":
            return None

        from .orchestrator import ConversationOrchestrator

        source_specs = ConversationOrchestrator._extract_system_image_source_specs(content)
        if not source_specs:
            return None

        blocked_step = next(
            (
                step
                for step in active_goal.steps
                if step.status == "blocked" and step.selected_tool_id == "system_image.sources.register"
            ),
            None,
        )
        if blocked_step is None:
            return None

        existing_specs = blocked_step.tool_input_payload.get("source_specs")
        specs_by_type: Dict[str, Dict[str, str]] = {}
        if isinstance(existing_specs, list):
            for item in existing_specs:
                if isinstance(item, dict) and isinstance(item.get("source_type"), str):
                    specs_by_type[item["source_type"]] = {str(key): str(value) for key, value in item.items()}
        for spec in source_specs:
            specs_by_type[spec["source_type"]] = spec
        blocked_step.tool_input_payload["source_specs"] = [
            specs_by_type[source_type]
            for source_type in ("code", "us_doc", "test_asset")
            if source_type in specs_by_type
        ]

        source_types = [spec["source_type"] for spec in source_specs]
        self._runtime.project_goal(active_goal)
        self._runtime.record_source_binding_received(
            active_goal,
            source_types=source_types,
        )
        await self._runtime.append_message(
            conversation_id,
            "assistant",
            "I received the source bindings and will continue the system image build.",
            metadata={
                "planner_kind": "source_binding_received",
                "agent_goal_id": active_goal.id,
                "source_types": source_types,
            },
        )
        goal = await self._runtime.resume_goal(active_goal.id)
        return {"agent_goal": goal}

    def pending_confirmation_invocation(self, conversation_id: str, content: str) -> ToolInvocation | None:
        explicit_match = re.search(r"tool_[a-f0-9]+", content)
        explicit_invocation_id = explicit_match.group(0) if explicit_match else None
        candidates = self._runtime.list_tool_invocations(
            conversation_id=conversation_id,
            status="waiting_confirmation",
        )
        if explicit_invocation_id:
            return next((invocation for invocation in candidates if invocation.id == explicit_invocation_id), None)
        return candidates[-1] if candidates else None

    def validate_conversation(self, conversation_id: str) -> None:
        self._runtime.get_conversation(conversation_id)
