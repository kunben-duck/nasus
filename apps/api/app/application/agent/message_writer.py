from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Protocol
from uuid import uuid4

from .agent_models import ConversationMessage, MessageBlock
from .ports import AgentConversationEventPublisherPort, ConversationMessageStatePort


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationStreamCommitPort(Protocol):
    async def commit_message_event(
        self,
        *,
        operation: Literal["append", "update"],
        conversation_id: str,
        message: ConversationMessage,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        ...


class ConversationMessageWriterApplicationService:
    """Writes conversation messages and emits the canonical message event."""

    def __init__(
        self,
        state: ConversationMessageStatePort,
        events: AgentConversationEventPublisherPort,
        stream_committer: ConversationStreamCommitPort | None = None,
    ) -> None:
        self._state = state
        self._events = events
        self._stream_committer = stream_committer

    def bind_stream_committer(
        self,
        committer: ConversationStreamCommitPort,
    ) -> None:
        self._stream_committer = committer

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

    async def start_streaming_message(
        self,
        conversation_id: str,
        *,
        turn_id: str,
        stream_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationMessage:
        conversation = self._state.get_conversation(conversation_id)
        message = ConversationMessage(
            id=f"msg_{uuid4().hex[:10]}",
            role="assistant",
            created_at=_now_iso(),
            status="streaming",
            content_type="markdown",
            blocks=[MessageBlock(type="text", text="")],
            metadata={"turn_id": turn_id, **(metadata or {})},
            stream_id=stream_id,
            sequence_max=0,
        )
        conversation.messages.append(message)
        conversation.last_message_at = message.created_at
        if conversation.status in {"draft", "idle"}:
            conversation.status = "active"
        await self._commit_stream_event(
            operation="append",
            conversation_id=conversation_id,
            conversation=conversation,
            message=message,
            event_type="conversation.message.started",
            payload={"message": message.model_dump(), "stream_id": stream_id},
        )
        return message

    async def append_stream_delta(
        self,
        conversation_id: str,
        message_id: str,
        *,
        stream_id: str,
        sequence: int,
        delta: str,
    ) -> ConversationMessage:
        conversation, message = self._streaming_message(
            conversation_id,
            message_id,
            stream_id,
        )
        if sequence <= (message.sequence_max or 0):
            return message
        if not message.blocks:
            message.blocks.append(MessageBlock(type="text", text=""))
        message.blocks[0].text += delta
        message.sequence_max = sequence
        await self._commit_stream_event(
            operation="update",
            conversation_id=conversation_id,
            conversation=conversation,
            message=message,
            event_type="conversation.message.delta",
            payload={
                "stream_id": stream_id,
                "sequence": sequence,
                "delta": delta,
                "turn_id": message.metadata.get("turn_id"),
            },
        )
        return message

    async def finish_streaming_message(
        self,
        conversation_id: str,
        message_id: str,
        *,
        stream_id: str,
        status: str,
        metadata: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> ConversationMessage:
        conversation, message = self._streaming_message(
            conversation_id,
            message_id,
            stream_id,
        )
        message.status = status  # type: ignore[assignment]
        message.metadata.update(metadata or {})
        if error:
            message.metadata["stream_error"] = error
        event_type = {
            "completed": "conversation.message.completed",
            "interrupted": "conversation.message.interrupted",
            "failed": "conversation.message.failed",
        }[status]
        await self._commit_stream_event(
            operation="update",
            conversation_id=conversation_id,
            conversation=conversation,
            message=message,
            event_type=event_type,
            payload={
                "message": message.model_dump(),
                "stream_id": stream_id,
                "sequence": message.sequence_max or 0,
                "turn_id": message.metadata.get("turn_id"),
                "error": error,
            },
        )
        if status == "completed":
            await self._state.maybe_create_summary_checkpoint(conversation)
        return message

    def _streaming_message(
        self,
        conversation_id: str,
        message_id: str,
        stream_id: str,
    ) -> tuple[Any, ConversationMessage]:
        conversation = self._state.get_conversation(conversation_id)
        message = next(
            (item for item in conversation.messages if item.id == message_id),
            None,
        )
        if message is None:
            raise KeyError(message_id)
        if message.stream_id != stream_id:
            raise ValueError("stream_id does not match the conversation message")
        return conversation, message

    def get_message(
        self,
        conversation_id: str,
        message_id: str,
    ) -> ConversationMessage | None:
        conversation = self._state.get_conversation(conversation_id)
        return next(
            (message for message in conversation.messages if message.id == message_id),
            None,
        )

    async def _commit_stream_event(
        self,
        *,
        operation: Literal["append", "update"],
        conversation_id: str,
        conversation: Any,
        message: ConversationMessage,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        if self._stream_committer is not None:
            await self._stream_committer.commit_message_event(
                operation=operation,
                conversation_id=conversation_id,
                message=message,
                event_type=event_type,
                payload=payload,
            )
            return
        if operation == "append":
            self._state.persist_message(conversation, message)
        else:
            self._state.update_message(conversation, message)
        await self._events.publish_message_event(
            conversation_id,
            message,
            event_type,
            payload,
        )
