from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import and_, func, literal, select, text, union_all

from ...application.platform.tool_models import EventPayload
from ...domain.system_image.source_access import (
    SourceAccessRule, SourceAccessSnapshot, SourceBindingAccess, StaleSourceAccessScope,
)
from .event_outbox_repository import EventOutboxRepository
from .db_models import ProjectRecord, ProjectRoleBindingRecord
from .source_access_models import (
    SourceAccessEpochRecord, SourceAccessPolicyHeadRecord, SourceAccessPolicyRevisionRecord,
)
from .source_snapshot_models import SourceBindingRecord, SourceRevisionRecord
from .unit_of_work import session_scope
from .source_access_read_session import current_source_access_read_session, live_source_access_read_session


class SourceAccessRepository:
    """Policy facts; no public mutation route until every read path is scoped."""

    @staticmethod
    def live_read_session():
        return live_source_access_read_session()

    def binding_for_revision(self, project_id: str, source_revision_id: str) -> str:
        with session_scope() as session:
            binding_id = session.scalar(select(SourceRevisionRecord.binding_id).where(
                SourceRevisionRecord.project_id == project_id,
                SourceRevisionRecord.source_revision_id == source_revision_id,
            ))
        if binding_id is None:
            raise KeyError("source revision not found")
        return binding_id

    @staticmethod
    def _snapshot_statement(project_id):
        # One statement gives the epoch, policy heads and inventory one MVCC view,
        # including an empty project. Never filter a mutable workspace for ACLs.
        project = select(literal(project_id).label("project_id")).subquery()
        epoch, head, policy, binding = (
            SourceAccessEpochRecord, SourceAccessPolicyHeadRecord,
            SourceAccessPolicyRevisionRecord, SourceBindingRecord,
        )
        return select(
            func.coalesce(epoch.acl_epoch, 0), binding.binding_id, binding.legacy_source_id,
            policy.visibility, policy.reader_user_ids,
        ).select_from(project).outerjoin(epoch, epoch.project_id == project.c.project_id).outerjoin(
            binding, binding.project_id == project.c.project_id,
        ).outerjoin(head, and_(head.project_id == binding.project_id, head.binding_id == binding.binding_id)).outerjoin(
            policy, and_(policy.project_id == head.project_id, policy.binding_id == head.binding_id,
                         policy.policy_revision_id == head.policy_revision_id),
        ).order_by(binding.binding_id)
    @staticmethod
    def _snapshot(project_id, rows):
        return SourceAccessSnapshot(project_id, rows[0][0], tuple(
            SourceBindingAccess(binding_id, source_id, SourceAccessRule(visibility or "project", tuple(readers or ())))
            for _, binding_id, source_id, visibility, readers in rows if binding_id is not None
        ))

    def load_snapshot(self, project_id: str) -> SourceAccessSnapshot:
        with session_scope() as session:
            rows = session.execute(self._snapshot_statement(project_id)).all()
        return self._snapshot(project_id, rows)

    @classmethod
    def _authorized_statement(cls, project_id, actor_id, *, platform_administrator):
        membership = select(ProjectRoleBindingRecord.role).where(
            ProjectRoleBindingRecord.project_id == project_id,
            ProjectRoleBindingRecord.user_id == actor_id,
            ProjectRoleBindingRecord.version_id.is_(None),
            ProjectRoleBindingRecord.session_id.is_(None),
            ProjectRoleBindingRecord.status == "active",
        ).scalar_subquery()
        role = literal("platform_admin") if platform_administrator else membership
        exists = select(ProjectRecord.id).where(ProjectRecord.id == project_id).exists()
        return cls._snapshot_statement(project_id).add_columns(role).where(exists)

    def load_authorized_snapshot(self, project_id, actor_id, *, platform_administrator):
        # Membership, existence, source inventory and policy share one MVCC
        # statement. Every check executes it again; no authorization is cached.
        statement = self._authorized_statement(project_id, actor_id, platform_administrator=platform_administrator)
        active = current_source_access_read_session()
        with nullcontext(active) if active is not None else session_scope() as session:
            rows = session.execute(statement).all()
        if not rows:
            raise KeyError(project_id)
        return self._snapshot(project_id, [row[:5] for row in rows]), rows[0][5]

    def load_authorized_snapshots(self, project_ids, actor_id, *, platform_administrator):
        if (type(project_ids) is not tuple or not 1 <= len(project_ids) <= 128
                or len(set(project_ids)) != len(project_ids)
                or any(type(ident) is not str or not ident for ident in project_ids)):
            raise ValueError("invalid source authorization cohort")
        statement = union_all(*(self._authorized_statement(ident, actor_id,
            platform_administrator=platform_administrator).order_by(None).add_columns(literal(ident))
            for ident in project_ids))
        active = current_source_access_read_session()
        with nullcontext(active) if active is not None else session_scope() as session:
            rows = session.execute(statement).all()
        grouped = {}
        for row in rows:
            grouped.setdefault(row[6], []).append(row)
        return {ident: (self._snapshot(ident, [row[:5] for row in values]), values[0][5])
            for ident, values in grouped.items()}

    def set_policy(
        self, project_id: str, binding_id: str, rule: SourceAccessRule, *,
        expected_epoch: int, changed_by: str, invocation_id: str,
    ) -> int:
        """Internal persistence port, to be called by a governed application command."""
        if type(expected_epoch) is not int or expected_epoch < 0 or not changed_by or not invocation_id:
            raise ValueError("policy update needs an epoch, actor and invocation")
        with session_scope() as session:
            session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {
                "key": f"nasus:source-access:{project_id}",
            })
            binding = session.scalar(select(SourceBindingRecord).where(
                SourceBindingRecord.project_id == project_id, SourceBindingRecord.binding_id == binding_id,
            ))
            if binding is None:
                raise KeyError("source binding not found")
            epoch = session.get(SourceAccessEpochRecord, project_id)
            current_epoch = epoch.acl_epoch if epoch else 0
            if expected_epoch != current_epoch:
                raise StaleSourceAccessScope("source access policy changed; reload before updating")
            head = session.get(SourceAccessPolicyHeadRecord, binding_id)
            current = session.get(SourceAccessPolicyRevisionRecord, head.policy_revision_id) if head else None
            existing = SourceAccessRule(current.visibility, tuple(current.reader_user_ids)) if current else SourceAccessRule()
            if existing == rule:
                return current_epoch
            next_epoch = current_epoch + 1
            if epoch is None:
                session.add(SourceAccessEpochRecord(project_id=project_id, acl_epoch=next_epoch))
            else:
                epoch.acl_epoch = next_epoch
            revision_id = str(uuid4())
            now = datetime.now(timezone.utc).isoformat()
            session.add(SourceAccessPolicyRevisionRecord(
                policy_revision_id=revision_id, project_id=project_id, binding_id=binding_id,
                acl_epoch=next_epoch, visibility=rule.visibility, reader_user_ids=list(rule.reader_user_ids),
                changed_by=changed_by, invocation_id=invocation_id, created_at=now,
            ))
            session.flush()
            if head is None:
                session.add(SourceAccessPolicyHeadRecord(
                    binding_id=binding_id, project_id=project_id, policy_revision_id=revision_id,
                ))
            else:
                head.policy_revision_id = revision_id
            EventOutboxRepository().append(EventPayload(
                event_id=str(uuid4()), event_type="system_image.source_access.changed", occurred_at=now,
                correlation_id=project_id, tool_invocation_id=invocation_id,
                entity_type="source_access", entity_id=project_id, entity_version=next_epoch,
                mutation_kind="invalidate", patch={"project_id": project_id, "acl_epoch": next_epoch},
                query_keys=[["system-image", project_id]],
            ), session=session)
            return next_epoch
