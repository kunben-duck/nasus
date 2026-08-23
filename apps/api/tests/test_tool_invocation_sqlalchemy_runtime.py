from __future__ import annotations

from uuid import uuid4

from sqlalchemy import delete

from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.infrastructure.persistence.conversation_repository import (
    ConversationRepository,
)
from apps.api.app.infrastructure.persistence.database import init_database
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.platform.tool_runtime import (
    SQLAlchemyToolInvocationRuntimeState,
)


def _cleanup(*invocation_ids: str) -> None:
    with session_scope() as session:
        session.execute(
            delete(ToolInvocationRecord).where(
                ToolInvocationRecord.id.in_(invocation_ids)
            )
        )


def test_sql_runtime_state_is_durable_idempotent_and_claims_once() -> None:
    init_database()
    suffix = uuid4().hex[:10]
    first_id = f"tool_sql_runtime_{suffix}"
    duplicate_id = f"tool_sql_runtime_duplicate_{suffix}"
    scope = f"conversation:conversation_sql_runtime_{suffix}"
    repository = ConversationRepository()
    mirrored: list[ToolInvocation] = []
    state = SQLAlchemyToolInvocationRuntimeState(
        repository=repository,
        mirror_invocation=mirrored.append,
    )
    _cleanup(first_id, duplicate_id)

    first = ToolInvocation(
        id=first_id,
        conversation_id=f"conversation_sql_runtime_{suffix}",
        tool_id="run.progress.get",
        status="pending",
        summary="Pending",
        idempotency_scope=scope,
        idempotency_key="same-request",
        idempotency_fingerprint="fingerprint-one",
    )
    duplicate = first.model_copy(update={"id": duplicate_id})

    try:
        created = state.create_invocation(first)
        reused = state.create_invocation(duplicate)

        assert created.id == first_id
        assert reused.id == first_id
        assert len(repository.load_tool_invocations()) >= 1

        restored_state = SQLAlchemyToolInvocationRuntimeState(
            repository=ConversationRepository()
        )
        assert restored_state.get_invocation(first_id).status == "pending"

        claimed = state.claim_for_execution(
            first_id,
            expected_statuses=("pending",),
        )
        duplicate_claim = restored_state.claim_for_execution(
            first_id,
            expected_statuses=("pending",),
        )

        assert claimed is not None
        assert claimed.status == "running"
        assert claimed.revision == 1
        assert duplicate_claim is None

        claimed.status = "completed"
        claimed.summary = "Completed"
        claimed.result = ToolResult(
            invocation_id=first_id,
            status="completed",
            summary="Completed",
        )
        state.persist_invocation(claimed)
        restored = restored_state.get_invocation(first_id)
        assert restored.status == "completed"
        assert restored.result is not None
        assert restored.result.status == "completed"
        assert mirrored[-1].status == "completed"
    finally:
        _cleanup(first_id, duplicate_id)
