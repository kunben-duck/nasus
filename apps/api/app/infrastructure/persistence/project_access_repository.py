from __future__ import annotations

from sqlalchemy import select

from .db_models import ProjectRoleBindingRecord
from .unit_of_work import session_scope
from ...application.platform.project_models import ProjectRoleBinding


class ProjectAccessRepository:
    """SQLAlchemy adapter for project-scoped role bindings."""

    def upsert(self, binding: ProjectRoleBinding) -> ProjectRoleBinding:
        with session_scope() as session:
            row = session.scalar(
                select(ProjectRoleBindingRecord).where(
                    ProjectRoleBindingRecord.user_id == binding.user_id,
                    ProjectRoleBindingRecord.scope_key == binding.scope_ref,
                )
            )
            if row is None:
                row = ProjectRoleBindingRecord(
                    binding_id=binding.binding_id,
                    user_id=binding.user_id,
                    scope_key=binding.scope_ref,
                )
                session.add(row)
            row.project_id = binding.project_id
            row.version_id = binding.version_id
            row.session_id = binding.session_id
            row.role = binding.role
            row.scope_ref = binding.scope_ref
            row.effective_policy_ref = binding.effective_policy_ref
            row.status = binding.status
            row.created_at = binding.created_at
            row.updated_at = binding.updated_at
            row.created_by = binding.created_by
            session.flush()
            return self._to_model(row)

    def get_project_binding(self, *, project_id: str, user_id: str) -> ProjectRoleBinding | None:
        with session_scope() as session:
            row = session.scalar(
                select(ProjectRoleBindingRecord).where(
                    ProjectRoleBindingRecord.project_id == project_id,
                    ProjectRoleBindingRecord.user_id == user_id,
                    ProjectRoleBindingRecord.version_id.is_(None),
                    ProjectRoleBindingRecord.session_id.is_(None),
                    ProjectRoleBindingRecord.status == "active",
                )
            )
            return self._to_model(row) if row is not None else None

    def list_for_user(self, user_id: str) -> list[ProjectRoleBinding]:
        with session_scope() as session:
            rows = session.scalars(
                select(ProjectRoleBindingRecord).where(
                    ProjectRoleBindingRecord.user_id == user_id,
                    ProjectRoleBindingRecord.status == "active",
                )
            ).all()
            return [self._to_model(row) for row in rows]

    def list_for_project(self, project_id: str) -> list[ProjectRoleBinding]:
        with session_scope() as session:
            rows = session.scalars(
                select(ProjectRoleBindingRecord).where(
                    ProjectRoleBindingRecord.project_id == project_id,
                    ProjectRoleBindingRecord.version_id.is_(None),
                    ProjectRoleBindingRecord.session_id.is_(None),
                    ProjectRoleBindingRecord.status == "active",
                ).order_by(
                    ProjectRoleBindingRecord.created_at,
                    ProjectRoleBindingRecord.user_id,
                )
            ).all()
            return [self._to_model(row) for row in rows]

    @staticmethod
    def _to_model(row: ProjectRoleBindingRecord) -> ProjectRoleBinding:
        return ProjectRoleBinding(
            binding_id=row.binding_id,
            project_id=row.project_id,
            version_id=row.version_id,
            session_id=row.session_id,
            user_id=row.user_id,
            role=row.role,
            scope_ref=row.scope_ref,
            effective_policy_ref=row.effective_policy_ref,
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
            created_by=row.created_by,
        )


__all__ = ["ProjectAccessRepository"]
