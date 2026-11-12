"""Durable dispatch intent and compare-and-swap checkpoint publication."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError

from .db_models import ConversationMemoryJobRecord, ConversationRecord, ConversationSummaryCheckpointRecord
from .conversation_repository import ConversationRepository
from .event_outbox_repository import EventOutboxRepository
from .unit_of_work import session_scope
from ...application.platform.tool_models import EventPayload


def now():
    return datetime.now(timezone.utc).isoformat()


class ConversationMemoryRepository:
    @staticmethod
    def _value(row):
        return {**row.payload, "id": row.id, "status": row.status, "attempts": row.attempts,
                "reason": row.reason, "checkpoint_id": row.checkpoint_id}

    def enqueue(self, job):
        try:
            with session_scope() as session:
                row = session.get(ConversationMemoryJobRecord, job["id"])
                if row is None:
                    row = ConversationMemoryJobRecord(id=job["id"], conversation_id=job["conversation_id"],
                        payload=job, status="pending", attempts=0, lease_until="", reason="",
                        created_at=now(), updated_at=now())
                    session.add(row)
                return self._value(row)
        except IntegrityError:
            return self.get(job["id"])

    def get(self, job_id):
        with session_scope() as session:
            row = session.get(ConversationMemoryJobRecord, job_id)
            if row is None:
                raise KeyError(job_id)
            return self._value(row)

    def latest(self, conversation_id):
        with session_scope() as session:
            row = session.scalar(select(ConversationMemoryJobRecord).where(
                ConversationMemoryJobRecord.conversation_id == conversation_id).order_by(
                ConversationMemoryJobRecord.created_at.desc()).limit(1))
            return self._value(row) if row else None

    def pending(self):
        with session_scope() as session:
            return list(session.scalars(select(ConversationMemoryJobRecord.id).where(
                or_(ConversationMemoryJobRecord.status == "pending",
                    (ConversationMemoryJobRecord.status == "running") & (ConversationMemoryJobRecord.lease_until < now()))
            ).order_by(ConversationMemoryJobRecord.created_at).limit(100)))

    def claim(self, job_id):
        with session_scope() as session:
            row = session.scalar(select(ConversationMemoryJobRecord).where(
                ConversationMemoryJobRecord.id == job_id).with_for_update())
            if row is None or row.status in {"completed", "failed", "superseded"}:
                return None
            if row.status == "running" and row.lease_until > now():
                return None
            if row.attempts >= 2:
                row.status, row.reason = "failed", "retry_limit"
                return None
            row.status, row.attempts = "running", row.attempts + 1
            row.lease_until = (datetime.now(timezone.utc) + timedelta(seconds=90)).isoformat()
            row.updated_at = now()
            return self._value(row)

    def fail(self, job_id, reason, attempt):
        with session_scope() as session:
            row = session.scalar(select(ConversationMemoryJobRecord).where(
                ConversationMemoryJobRecord.id == job_id).with_for_update())
            if row is not None and row.status == "running" and row.attempts == attempt:
                retryable = {"summary_model_unavailable", "summary_invalid_reference", "summary_invalid_origin",
                             "summary_empty", "summary_dropped_constraints", "summary_output_exceeds_budget"}
                row.status = "pending" if row.attempts < 2 and reason in retryable else "failed"
                row.reason, row.updated_at = reason, now()

    def commit(self, job, checkpoint):
        with session_scope() as session:
            conversation = session.scalar(select(ConversationRecord).where(
                ConversationRecord.id == job["conversation_id"]).with_for_update())
            row = session.scalar(select(ConversationMemoryJobRecord).where(
                ConversationMemoryJobRecord.id == job["id"]).with_for_update())
            if not conversation or not row or row.status != "running" or row.attempts != job["attempts"]:
                return False
            latest = session.scalar(select(ConversationSummaryCheckpointRecord).where(
                ConversationSummaryCheckpointRecord.conversation_id == job["conversation_id"])
                .order_by(ConversationSummaryCheckpointRecord.created_at.desc()).limit(1))
            if (latest.id if latest else None) != job["parent_id"]:
                row.status, row.reason = "superseded", "checkpoint_changed"
                return False
            session.add(ConversationSummaryCheckpointRecord(**checkpoint.model_dump()))
            conversation.latest_summary_checkpoint_id = checkpoint.id
            row.status, row.checkpoint_id, row.updated_at = "completed", checkpoint.id, now()
            row.reason = ""
            EventOutboxRepository().append(EventPayload(event_id="event_" + checkpoint.id,
                event_type="conversation.summary.updated", occurred_at=now(), correlation_id=job["id"],
                conversation_id=conversation.id, entity_type="conversation", entity_id=conversation.id,
                entity_version=0, mutation_kind="patch", patch={"latest_summary_checkpoint_id": checkpoint.id},
                query_keys=[["conversation", conversation.id], ["agent-memory"]]), session=session)
            return True

    def checkpoint(self, checkpoint_id):
        with session_scope() as session:
            row = session.get(ConversationSummaryCheckpointRecord, checkpoint_id)
            return ConversationRepository._to_summary_checkpoint(row) if row else None
