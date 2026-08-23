from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os

from sqlalchemy import func, select

from .db_models import SSEEventOutboxRecord
from .unit_of_work import session_scope
from ...application.platform.event_ports import EventStreamKind
from ...application.platform.tool_models import EventPayload


class EventOutboxRepository:
    """Durable SSE event log used for replay and multi-instance polling."""

    def __init__(self) -> None:
        self._retention_days = max(1, int(os.getenv("NASUS_SSE_RETENTION_DAYS", "7")))

    def append(self, event: EventPayload) -> EventPayload:
        retention_until = (
            datetime.now(timezone.utc) + timedelta(days=self._retention_days)
        ).isoformat()
        with session_scope() as session:
            record = SSEEventOutboxRecord(
                event_id=event.event_id,
                event_type=event.event_type,
                occurred_at=event.occurred_at,
                conversation_id=event.conversation_id,
                agent_goal_id=event.agent_goal_id,
                swarm_run_id=event.swarm_run_id,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                entity_version=0,
                event_payload={},
                retention_until=retention_until,
            )
            session.add(record)
            session.flush()
            event.entity_version = record.sequence
            record.entity_version = record.sequence
            record.event_payload = event.model_dump()
        return event

    def list_after(
        self,
        *,
        stream_kind: EventStreamKind,
        stream_id: str,
        after_event_id: str | None,
        limit: int = 500,
        initial_replay_limit: int = 500,
    ) -> list[EventPayload]:
        stream_column = self._stream_column(stream_kind)
        with session_scope() as session:
            if after_event_id:
                cursor = session.scalar(
                    select(SSEEventOutboxRecord.sequence).where(
                        SSEEventOutboxRecord.event_id == after_event_id
                    )
                )
                cursor_sequence = int(cursor or 0)
            else:
                latest = session.scalar(
                    select(func.max(SSEEventOutboxRecord.sequence)).where(
                        stream_column == stream_id
                    )
                )
                cursor_sequence = max(0, int(latest or 0) - initial_replay_limit)

            rows = session.scalars(
                select(SSEEventOutboxRecord)
                .where(
                    stream_column == stream_id,
                    SSEEventOutboxRecord.sequence > cursor_sequence,
                )
                .order_by(SSEEventOutboxRecord.sequence)
                .limit(limit)
            ).all()
        return [EventPayload(**row.event_payload) for row in rows]

    def latest_entity_version(self, *, entity_type: str, entity_id: str) -> int:
        with session_scope() as session:
            version = session.scalar(
                select(func.max(SSEEventOutboxRecord.entity_version)).where(
                    SSEEventOutboxRecord.entity_type == entity_type,
                    SSEEventOutboxRecord.entity_id == entity_id,
                )
            )
        return int(version or 0)

    @staticmethod
    def _stream_column(stream_kind: EventStreamKind):
        if stream_kind == "conversation":
            return SSEEventOutboxRecord.conversation_id
        if stream_kind == "goal":
            return SSEEventOutboxRecord.agent_goal_id
        if stream_kind == "swarm":
            return SSEEventOutboxRecord.swarm_run_id
        raise ValueError(f"Unsupported event stream kind: {stream_kind}")


__all__ = ["EventOutboxRepository", "EventStreamKind"]
