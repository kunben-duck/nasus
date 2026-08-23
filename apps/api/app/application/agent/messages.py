from __future__ import annotations

import re
from typing import Any, Dict

from .ports import ConversationMessageRuntimePort
from ..platform.tool_models import ToolInvocation, ToolInvocationRequest


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
        conversation = self._runtime.get_conversation(conversation_id)
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
        source_binding_result = await self.handle_source_binding_message_if_any(conversation_id, content)
        if source_binding_result is not None:
            return source_binding_result
        confirmation_result = await self.handle_confirmation_message_if_any(conversation_id, content)
        if confirmation_result is not None:
            return confirmation_result

        if canonical_action_id:
            decision = await self._runtime.plan_message(
                conversation,
                content,
                canonical_action_id=canonical_action_id,
            )
        else:
            decision = await self._runtime.plan_message(conversation, content)

        if decision.kind == "clarification" and decision.clarification:
            await self._runtime.append_message(
                conversation_id,
                "assistant",
                decision.clarification.question,
                metadata={
                    "planner_kind": "clarification",
                    "clarification_kind": decision.clarification.reason,
                    "missing_context": decision.clarification.missing_context,
                },
            )
            return {"clarification": decision.clarification.__dict__}

        if decision.kind == "tool_plan" and decision.tool_plan:
            tool_invocations = []
            for step in decision.tool_plan.steps:
                invocation = await self._runtime.create_tool_invocation(
                    ToolInvocationRequest(
                        conversation_id=conversation_id,
                        tool_id=step.tool_id,
                        input=step.input_payload,
                        initiator_surface="chat",
                        initiator_actor="user",
                        target_scope=step.target_scope,
                    )
                )
                tool_invocations.append(invocation)
            return {"tool_invocations": tool_invocations}

        if decision.kind == "agent_goal" and decision.agent_goal:
            goal = await self._runtime.start_goal_from_proposal(
                conversation_id,
                decision.agent_goal,
            )
            return {"agent_goal": goal}

        direct_answer = decision.direct_answer
        fallback_text = (
            direct_answer.fallback_text
            if direct_answer
            else self._runtime.fallback_text(conversation)
        )
        query_keys = direct_answer.query_keys if direct_answer else [["conversation", conversation_id]]
        tool_invocation = await self._runtime.create_tool_invocation(
            ToolInvocationRequest(
                conversation_id=conversation_id,
                tool_id="query.answer",
                input={
                    "user_message": content,
                    "fallback_text": fallback_text,
                    "query_keys": query_keys,
                },
                initiator_surface="chat",
                initiator_actor="user",
                target_scope="central",
            )
        )
        return {"tool_invocation": tool_invocation}

    async def handle_confirmation_message_if_any(self, conversation_id: str, content: str) -> Dict[str, Any] | None:
        if not self._runtime.is_confirmation_message(content):
            return None

        invocation = self.pending_confirmation_invocation(conversation_id, content)
        if invocation is None:
            return None

        goal_id = invocation.input_payload.get("agent_goal_id")
        if isinstance(goal_id, str) and self._runtime.is_paused_goal(goal_id):
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
