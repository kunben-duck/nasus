from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete

from apps.api.app.application.platform.tool_models import AuditEvent
from apps.api.app.infrastructure.persistence.conversation_repository import (
    ConversationRepository,
)
from apps.api.app.infrastructure.persistence.database import init_database
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.platform.audit_persistence import (
    SQLAlchemyAuditEventPersistence,
)


def _cleanup(event_id: str) -> None:
    with session_scope() as session:
        session.execute(delete(AuditEventRecord).where(AuditEventRecord.id == event_id))


def test_sql_audit_is_idempotent_for_identical_retries_and_immutable_after_commit() -> None:
    init_database()
    event_id = f"audit_sql_{uuid4().hex[:10]}"
    first_process = SQLAlchemyAuditEventPersistence(ConversationRepository())
    second_process = SQLAlchemyAuditEventPersistence(ConversationRepository())
    event = AuditEvent(
        id=event_id,
        occurred_at="2026-08-09T00:00:00+00:00",
        actor="user:test",
        actor_kind="user",
        action="tool.invocation.completed",
        entity_type="tool_invocation",
        entity_id=f"tool_{event_id}",
        status="accepted",
        summary="Tool completed",
        tool_invocation_id=f"tool_{event_id}",
    )
    _cleanup(event_id)

    try:
        first_process.persist_audit_event(event)
        second_process.persist_audit_event(event.model_copy(deep=True))

        persisted = [
            item
            for item in ConversationRepository().load_audit_events()
            if item.id == event_id
        ]
        assert persisted == [event]

        with pytest.raises(ValueError, match="immutable"):
            second_process.persist_audit_event(
                event.model_copy(update={"summary": "Rewritten history"})
            )

        persisted_after_rejection = [
            item
            for item in ConversationRepository().load_audit_events()
            if item.id == event_id
        ]
        assert persisted_after_rejection == [event]
    finally:
        _cleanup(event_id)
