from __future__ import annotations

import asyncio
from typing import Any, Literal

from ...application.agent.agent_models import ConversationMessage
from ...application.agent.message_writer import ConversationStreamCommitPort
from ...application.platform.events import PlatformEventApplicationService
from ...application.platform.event_streams import PlatformEventStreamApplicationService
from ..persistence.conversation_repository import ConversationRepository
from ..persistence.event_outbox_repository import EventOutboxRepository


class SQLAlchemyConversationStreamCommitter(ConversationStreamCommitPort):
    """Atomic message/outbox writer followed by process-local SSE fan-out."""

    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        outbox: EventOutboxRepository,
        events: PlatformEventApplicationService,
        streams: PlatformEventStreamApplicationService,
    ) -> None:
        self._conversations = conversations
        self._outbox = outbox
        self._events = events
        self._streams = streams

    async def commit_message_event(
        self,
        *,
        operation: Literal["append", "update"],
        conversation_id: str,
        message: ConversationMessage,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        event = self._events.build_conversation_event(
            conversation_id=conversation_id,
            event_type=event_type,
            entity_type="conversation_message",
            entity_id=message.id,
            mutation_kind="patch",
            patch={
                "status": message.status,
                "stream_id": message.stream_id,
                "sequence_max": message.sequence_max,
            },
            query_keys=[["conversation", conversation_id]],
            payload={"message_id": message.id, **payload},
        )
        await asyncio.to_thread(
            self._conversations.commit_stream_message_event,
            operation=operation,
            conversation_id=conversation_id,
            message=message,
            event=event,
            outbox=self._outbox,
        )
        await self._streams.fan_out_persisted_conversation_event(
            conversation_id,
            event,
        )


__all__ = ["SQLAlchemyConversationStreamCommitter"]
