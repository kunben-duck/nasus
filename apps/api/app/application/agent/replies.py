from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .reply_ports import (
    AgentReplyGenerationPort,
    AgentReplyMemoryPort,
    AgentReplyMessageWriterPort,
    AgentReplyModelSettingsPort,
)
from ..platform.prompts import PromptRegistryPort
from ...domain.platform.llm_call import LLMCallContext
from ...domain.platform.prompt_registry import builtin_prompt


@dataclass(frozen=True)
class AgentReply:
    content: str
    metadata: dict[str, Any]


class AgentReplyApplicationService:
    """Agent-facing LLM reply generation and message persistence use cases."""

    def __init__(
        self,
        memory: AgentReplyMemoryPort,
        generation: AgentReplyGenerationPort,
        model_settings: AgentReplyModelSettingsPort,
        messages: AgentReplyMessageWriterPort,
        prompt_registry: PromptRegistryPort | None = None,
    ) -> None:
        self._memory = memory
        self._generation = generation
        self._model_settings = model_settings
        self._messages = messages
        self._prompt_registry = prompt_registry

    async def generate_reply(
        self,
        *,
        conversation: Any,
        user_message: str,
        fallback_text: str,
        system_prompt: str | None = None,
        prompt_id: str = "agent_conversation_reply",
        purpose: str = "agent.conversation_reply",
        tool_invocation_id: str | None = None,
    ) -> AgentReply:
        memory_context = await self._memory.build_context(
            conversation,
            trace_retrieval=True,
        )
        settings = self._model_settings.get_settings()
        prompt = (
            self._prompt_registry.get_active(prompt_id)
            if self._prompt_registry is not None
            else builtin_prompt(prompt_id)
        )
        effective_system_prompt = system_prompt or (
            f"{memory_context.system_prompt}\n\n{prompt.system_template}"
        )
        reply = await self._generation.generate_reply(
            settings=settings,
            system_prompt=effective_system_prompt,
            user_message=user_message,
            context_snapshot=memory_context.context_snapshot,
            history_snapshot=memory_context.history_snapshot,
            fallback_text=fallback_text,
            custom_api_key=self._model_settings.get_custom_model_api_key("chat"),
            call_context=LLMCallContext(
                purpose=purpose,
                prompt_id=prompt.prompt_id,
                prompt_version=prompt.version,
                project_id=conversation.project_id,
                version_id=conversation.version_id,
                task_id=conversation.task_id or conversation.us_id,
                conversation_id=conversation.id,
                tool_invocation_id=tool_invocation_id,
            ),
        )
        metadata = {
            "llm_provider": reply.provider,
            "llm_model": reply.model_name,
            "llm_mode": reply.mode,
            "llm_reason": reply.reason,
            "settings_preset": settings.model_preset,
            "memory_recent_turns": memory_context.recent_turn_count,
            "memory_checkpoint_count": memory_context.checkpoint_count,
        }
        llm_call_id = getattr(reply, "llm_call_id", None)
        if llm_call_id:
            metadata["llm_call_id"] = llm_call_id
        return AgentReply(content=reply.content, metadata=metadata)

    async def append_assistant_message(
        self,
        *,
        conversation_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        return await self._messages.append_text_message(
            conversation_id,
            "assistant",
            content,
            metadata=metadata,
        )
