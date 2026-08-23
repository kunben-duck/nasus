from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .agent_models import ConversationMessage, MessageBlock
from .ports import AgentConversationEventPublisherPort, ConversationMessageStatePort


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationMessageWriterApplicationService:
    """Writes conversation messages and emits the canonical message event."""

    def __init__(
        self,
        state: ConversationMessageStatePort,
        events: AgentConversationEventPublisherPort,
    ) -> None:
        self._state = state
        self._events = events

    async def append_text_message(
        self,
        conversation_id: str,
        role: str,
        text: str,
        tone: str | None = None,
        metadata: dict[str, Any] | None = None,
        tool_refs: list[str] | None = None,
        object_refs: list[str] | None = None,
    ) -> ConversationMessage:
        conversation = self._state.get_conversation(conversation_id)
        message = ConversationMessage(
            id=f"msg_{uuid4().hex[:10]}",
            role=role,  # type: ignore[arg-type]
            created_at=_now_iso(),
            status="completed",
            content_type="text",
            blocks=[MessageBlock(type="text", text=text, tone=tone)],
            tool_refs=tool_refs or [],
            object_refs=object_refs or [],
            metadata=metadata or {},
        )
        conversation.messages.append(message)
        conversation.last_message_at = message.created_at
        if conversation.status in {"draft", "idle"}:
            conversation.status = "active"

        self._state.persist_message(conversation, message)
        await self._state.maybe_create_summary_checkpoint(conversation)
        await self._events.publish_message_created(conversation_id, message)
        return message
