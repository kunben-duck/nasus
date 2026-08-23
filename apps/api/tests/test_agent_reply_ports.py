from __future__ import annotations

import asyncio
from dataclasses import dataclass

from apps.api.app.application.agent.agent_models import ConversationMessage, ConversationSession
from apps.api.app.application.agent.replies import AgentReplyApplicationService
from apps.api.app.application.platform.model_settings import StudioSettings
from apps.api.app.domain.agent.memory import AgentMemoryContext


class ReplyMemory:
    async def build_context(
        self,
        conversation: ConversationSession,
        *,
        trace_retrieval: bool = False,
    ) -> AgentMemoryContext:
        assert trace_retrieval is True
        return AgentMemoryContext(
            system_prompt=f"memory:{conversation.id}",
            context_snapshot="project context",
            history_snapshot="recent history",
            recent_turn_count=3,
            checkpoint_count=2,
        )


@dataclass
class GeneratedReply:
    content: str = "Live model answer"
    provider: str = "openai_compatible"
    model_name: str = "production-chat"
    mode: str = "live"
    reason: str = "provider_success"


class ReplyGenerator:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def generate_reply(self, **kwargs):
        self.calls.append(kwargs)
        return GeneratedReply()


class ReplyModelSettings:
    def __init__(self) -> None:
        self.settings = StudioSettings(model_preset="custom")

    def get_settings(self) -> StudioSettings:
        return self.settings

    def get_custom_model_api_key(self, model_route: str = "chat") -> str:
        assert model_route == "chat"
        return "secret-key"


class ReplyMessages:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def append_text_message(
        self,
        conversation_id: str,
        role: str,
        text: str,
        tone: str | None = None,
        metadata: dict[str, object] | None = None,
        tool_refs: list[str] | None = None,
        object_refs: list[str] | None = None,
    ) -> ConversationMessage:
        self.calls.append(
            {
                "conversation_id": conversation_id,
                "role": role,
                "text": text,
                "metadata": metadata,
            }
        )
        return ConversationMessage(
            id="msg_reply",
            role="assistant",
            created_at="2026-08-08T00:00:00+00:00",
            content_type="text",
            blocks=[],
            metadata=metadata or {},
        )


def test_agent_reply_uses_explicit_memory_model_and_message_ports() -> None:
    asyncio.run(_exercise_agent_reply_ports())


async def _exercise_agent_reply_ports() -> None:
    generator = ReplyGenerator()
    messages = ReplyMessages()
    service = AgentReplyApplicationService(
        memory=ReplyMemory(),
        generation=generator,
        model_settings=ReplyModelSettings(),
        messages=messages,
    )
    conversation = ConversationSession(
        id="conv_reply",
        session_id="session_reply",
        space_type="project",
        space_id="proj_reply",
        title="Reply test",
        created_at="2026-08-08T00:00:00+00:00",
        last_message_at="2026-08-08T00:00:00+00:00",
    )

    reply = await service.generate_reply(
        conversation=conversation,
        user_message="What changed?",
        fallback_text="Fallback answer",
    )
    persisted = await service.append_assistant_message(
        conversation_id=conversation.id,
        content=reply.content,
        metadata=reply.metadata,
    )

    assert reply.content == "Live model answer"
    assert reply.metadata == {
        "llm_provider": "openai_compatible",
        "llm_model": "production-chat",
        "llm_mode": "live",
        "llm_reason": "provider_success",
        "settings_preset": "custom",
        "memory_recent_turns": 3,
        "memory_checkpoint_count": 2,
    }
    assert generator.calls[0]["system_prompt"].startswith("memory:conv_reply\n\n")
    assert "Do not claim that a write action completed" in generator.calls[0]["system_prompt"]
    call_context = generator.calls[0]["call_context"]
    assert call_context.prompt_id == "agent_conversation_reply"
    assert call_context.prompt_version == "1.0.0"
    assert generator.calls[0]["custom_api_key"] == "secret-key"
    assert messages.calls[0]["role"] == "assistant"
    assert persisted.id == "msg_reply"
