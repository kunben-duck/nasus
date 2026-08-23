from __future__ import annotations

from sqlalchemy import select

from ...application.platform.project_access import (
    ConversationAccessScope,
    InvocationAccessScope,
)
from ..persistence.db_models import (
    AuditEventRecord,
    ConversationRecord,
    ProjectRecord,
    ToolInvocationRecord,
    USWorkItemRecord,
    VersionRecord,
)
from ..persistence.unit_of_work import session_scope


class SQLAlchemyProjectAccessReadModel:
    """Durable authorization facts for project-scoped resources."""

    def project_exists(self, project_id: str) -> bool:
        with session_scope() as session:
            return session.get(ProjectRecord, project_id) is not None

    def list_project_ids(self) -> set[str]:
        with session_scope() as session:
            return set(session.scalars(select(ProjectRecord.id)).all())

    def conversation_scope(self, conversation_id: str) -> ConversationAccessScope | None:
        if not conversation_id:
            return None
        with session_scope() as session:
            row = session.get(ConversationRecord, conversation_id)
            if row is None:
                return None
            return ConversationAccessScope(
                id=row.id,
                project_id=row.project_id,
                initiator_id=row.initiator_id,
            )

    def invocation_scope(self, invocation_id: str) -> InvocationAccessScope | None:
        with session_scope() as session:
            row = session.get(ToolInvocationRecord, invocation_id)
            if row is None:
                return None
            result_payload = row.result_payload or {}
            object_refs = result_payload.get("object_refs", [])
            return InvocationAccessScope(
                id=row.id,
                conversation_id=row.conversation_id,
                input_payload=row.input_payload or {},
                object_refs=tuple(object_refs) if isinstance(object_refs, list) else (),
            )

    def project_id_for_version(self, version_id: str) -> str | None:
        with session_scope() as session:
            return session.scalar(
                select(VersionRecord.project_id).where(VersionRecord.id == version_id)
            )

    def project_id_for_us(self, us_id: str) -> str | None:
        with session_scope() as session:
            return session.scalar(
                select(USWorkItemRecord.project_id).where(USWorkItemRecord.id == us_id)
            )

    def invocation_created_by(self, invocation_id: str, user_id: str) -> bool:
        with session_scope() as session:
            event_id = session.scalar(
                select(AuditEventRecord.id)
                .where(
                    AuditEventRecord.tool_invocation_id == invocation_id,
                    AuditEventRecord.action == "tool.invocation.created",
                    AuditEventRecord.actor == user_id,
                )
                .limit(1)
            )
            return event_id is not None


__all__ = ["SQLAlchemyProjectAccessReadModel"]
