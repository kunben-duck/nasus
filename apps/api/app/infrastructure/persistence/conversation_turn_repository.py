from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ...application.agent.agent_models import ConversationTurn
from ...application.agent.turns import ConversationTurnConflict
from .db_models import ConversationTurnRecord
from .unit_of_work import session_scope


class ConversationTurnRepository:
    """PostgreSQL/SQLite persistence for asynchronous conversation turns."""

    def create(self, turn: ConversationTurn) -> tuple[ConversationTurn, bool]:
        try:
            with session_scope() as session:
                session.add(self._to_record(turn))
        except IntegrityError:
            existing = self.find_idempotent(
                turn.conversation_id,
                turn.idempotency_key,
            )
            if existing is None:
                active = self.active_for_conversation(turn.conversation_id)
                if active is not None:
                    raise ConversationTurnConflict(
                        f"Conversation {turn.conversation_id} already has active turn {active.id}."
                    )
                raise
            return existing, False
        return turn, True

    def get(self, turn_id: str) -> ConversationTurn | None:
        with session_scope() as session:
            row = session.get(ConversationTurnRecord, turn_id)
            return self._to_model(row) if row is not None else None

    def find_idempotent(
        self,
        conversation_id: str,
        idempotency_key: str,
    ) -> ConversationTurn | None:
        with session_scope() as session:
            row = session.scalar(
                select(ConversationTurnRecord).where(
                    ConversationTurnRecord.conversation_id == conversation_id,
                    ConversationTurnRecord.idempotency_key == idempotency_key,
                )
            )
            return self._to_model(row) if row is not None else None

    def active_for_conversation(self, conversation_id: str) -> ConversationTurn | None:
        with session_scope() as session:
            row = session.scalar(
                select(ConversationTurnRecord)
                .where(
                    ConversationTurnRecord.conversation_id == conversation_id,
                    ConversationTurnRecord.status.in_(
                        ("accepted", "planning", "streaming", "delegated")
                    ),
                )
                .order_by(ConversationTurnRecord.created_at.desc())
                .limit(1)
            )
            return self._to_model(row) if row is not None else None

    def upsert(self, turn: ConversationTurn) -> None:
        with session_scope() as session:
            row = session.get(ConversationTurnRecord, turn.id)
            if row is None:
                row = self._to_record(turn)
                session.add(row)
                return
            row.assistant_message_id = turn.assistant_message_id
            row.workflow_id = turn.workflow_id
            row.status = turn.status
            row.result = turn.result
            row.error = turn.error
            row.updated_at = turn.updated_at
            row.completed_at = turn.completed_at

    @staticmethod
    def _to_record(turn: ConversationTurn) -> ConversationTurnRecord:
        return ConversationTurnRecord(
            id=turn.id,
            conversation_id=turn.conversation_id,
            user_message_id=turn.user_message_id,
            assistant_message_id=turn.assistant_message_id,
            workflow_id=turn.workflow_id,
            idempotency_key=turn.idempotency_key,
            status=turn.status,
            result=turn.result,
            error=turn.error,
            created_at=turn.created_at,
            updated_at=turn.updated_at,
            completed_at=turn.completed_at,
        )

    @staticmethod
    def _to_model(row: ConversationTurnRecord) -> ConversationTurn:
        return ConversationTurn(
            id=row.id,
            conversation_id=row.conversation_id,
            user_message_id=row.user_message_id,
            assistant_message_id=row.assistant_message_id,
            workflow_id=row.workflow_id,
            idempotency_key=row.idempotency_key,
            status=row.status,
            result=row.result or {},
            error=row.error,
            created_at=row.created_at,
            updated_at=row.updated_at,
            completed_at=row.completed_at,
        )


__all__ = ["ConversationTurnRepository"]
