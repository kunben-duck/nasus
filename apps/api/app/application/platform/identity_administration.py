from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from .account_models import UserProfile
from .account_ports import CurrentUserProviderPort
from .audit_events import PlatformAuditApplicationService
from .errors import PlatformApplicationError
from .identity_administration_models import (
    AccessSessionView,
    ProjectMemberUpsertRequest,
    ProjectMemberCandidate,
    ProjectMemberView,
    UserAdministrationPage,
    UserAdministrationPatch,
    UserAdministrationRecord,
)
from .identity_administration_ports import IdentityAdministrationPort
from .project_access import ProjectAccessApplicationService
from .tool_models import AuditEvent
from ...domain.platform.rbac import ToolRBAC


class IdentityAdministrationApplicationService:
    """Governed global identity, session, and project membership use cases."""

    def __init__(
        self,
        *,
        current_user: CurrentUserProviderPort,
        identities: IdentityAdministrationPort,
        project_access: ProjectAccessApplicationService,
        audit: PlatformAuditApplicationService,
    ) -> None:
        self._current_user = current_user
        self._identities = identities
        self._project_access = project_access
        self._audit = audit

    def list_users(
        self,
        *,
        actor: UserProfile | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> UserAdministrationPage:
        self._require_platform_admin(actor)
        return self._identities.list_users(
            query=(query or "").strip() or None,
            limit=max(1, min(limit, 200)),
            offset=max(0, offset),
        )

    def update_user(
        self,
        user_id: str,
        payload: UserAdministrationPatch,
        *,
        actor: UserProfile | None = None,
    ) -> UserAdministrationRecord:
        administrator = self._require_platform_admin(actor)
        existing = self._require_user(user_id)
        if administrator.id == user_id and (
            (payload.role is not None and payload.role != "platform_admin")
            or (payload.status is not None and payload.status != "active")
        ):
            raise PlatformApplicationError(
                "cannot_remove_own_platform_access",
                "A platform administrator cannot demote or suspend the active account used for this request.",
                409,
            )
        removes_platform_access = existing.role == "platform_admin" and (
            (payload.role is not None and payload.role != "platform_admin")
            or payload.status == "suspended"
        )
        if removes_platform_access:
            remaining_administrators = [
                user
                for user in self._identities.list_users(
                    query=None,
                    limit=200,
                    offset=0,
                ).items
                if user.id != user_id
                and user.role == "platform_admin"
                and user.status == "active"
            ]
            if not remaining_administrators:
                raise PlatformApplicationError(
                    "last_platform_admin_required",
                    "Create another active platform administrator before removing the last one.",
                    409,
                )
        try:
            updated = self._identities.update_user(
                user_id=user_id,
                display_name=payload.display_name,
                role=payload.role,
                status=payload.status,
            )
        except KeyError as exc:
            raise PlatformApplicationError(
                "user_not_found",
                f"User {user_id} was not found.",
                404,
            ) from exc
        self._record(
            actor=administrator,
            action="identity.user.updated",
            entity_type="user_identity",
            entity_id=user_id,
            summary=f"Updated account {updated.email}.",
            object_refs=[f"user:{user_id}"],
            metadata={
                "previous_role": existing.role,
                "role": updated.role,
                "previous_status": existing.status,
                "status": updated.status,
            },
        )
        return updated

    def list_my_sessions(self, *, actor: UserProfile | None = None) -> list[AccessSessionView]:
        user = self._actor(actor)
        return self._identities.list_sessions(user.id)

    def list_user_sessions(
        self,
        user_id: str,
        *,
        actor: UserProfile | None = None,
    ) -> list[AccessSessionView]:
        self._require_platform_admin(actor)
        self._require_user(user_id)
        return self._identities.list_sessions(user_id)

    def revoke_session(
        self,
        session_id: str,
        *,
        target_user_id: str | None = None,
        actor: UserProfile | None = None,
    ) -> AccessSessionView:
        administrator = self._actor(actor)
        if target_user_id is None:
            expected_user_id = administrator.id
        else:
            self._require_platform_admin(administrator)
            self._require_user(target_user_id)
            expected_user_id = target_user_id
        try:
            session = self._identities.revoke_session(
                session_id,
                expected_user_id=expected_user_id,
            )
        except KeyError as exc:
            raise PlatformApplicationError(
                "access_session_not_found",
                "The access session was not found in the permitted account scope.",
                404,
            ) from exc
        self._record(
            actor=administrator,
            action="identity.session.revoked",
            entity_type="access_session",
            entity_id=session_id,
            summary=f"Revoked access session {session_id}.",
            object_refs=[f"user:{session.user_id}", f"access_session:{session_id}"],
        )
        return session

    def list_project_members(
        self,
        project_id: str,
        *,
        actor: UserProfile | None = None,
    ) -> list[ProjectMemberView]:
        administrator = self._actor(actor)
        bindings = self._project_access.list_project_members(project_id, administrator)
        members = []
        for binding in bindings:
            user = self._identities.get_user(binding.user_id)
            if user is not None:
                members.append(ProjectMemberView(user=user, binding=binding))
        return members

    def search_project_member_candidates(
        self,
        project_id: str,
        *,
        query: str,
        actor: UserProfile | None = None,
        limit: int = 20,
    ) -> list[ProjectMemberCandidate]:
        administrator = self._actor(actor)
        existing_bindings = self._project_access.list_project_members(
            project_id,
            administrator,
        )
        normalized_query = query.strip()
        if len(normalized_query) < 2:
            return []
        page = self._identities.list_users(
            query=normalized_query,
            limit=max(1, min(limit, 50)),
            offset=0,
        )
        existing_user_ids = {binding.user_id for binding in existing_bindings}
        return [
            ProjectMemberCandidate(
                id=user.id,
                email=user.email,
                display_name=user.display_name,
                avatar_preset=user.avatar_preset,
                avatar_image=user.avatar_image,
            )
            for user in page.items
            if user.status == "active" and user.id not in existing_user_ids
        ]

    def upsert_project_member(
        self,
        project_id: str,
        user_id: str,
        payload: ProjectMemberUpsertRequest,
        *,
        actor: UserProfile | None = None,
    ) -> ProjectMemberView:
        administrator = self._actor(actor)
        user = self._require_user(user_id)
        if user.status != "active":
            raise PlatformApplicationError(
                "inactive_project_member",
                "Only active accounts can receive a project role.",
                409,
            )
        binding = self._project_access.assign_project_member(
            project_id=project_id,
            user_id=user_id,
            role=payload.role,
            actor=administrator,
        )
        self._record(
            actor=administrator,
            action="project.role.assigned",
            entity_type="role_binding",
            entity_id=binding.binding_id,
            summary=f"Assigned {payload.role} to {user.email} in project {project_id}.",
            object_refs=[f"project:{project_id}", f"user:{user_id}"],
            metadata={"role": payload.role},
        )
        return ProjectMemberView(user=user, binding=binding)

    def revoke_project_member(
        self,
        project_id: str,
        user_id: str,
        *,
        actor: UserProfile | None = None,
    ) -> dict[str, bool]:
        administrator = self._actor(actor)
        user = self._require_user(user_id)
        binding = self._project_access.revoke_project_member(
            project_id=project_id,
            user_id=user_id,
            actor=administrator,
        )
        self._record(
            actor=administrator,
            action="project.role.revoked",
            entity_type="role_binding",
            entity_id=binding.binding_id,
            summary=f"Revoked project access for {user.email} in project {project_id}.",
            object_refs=[f"project:{project_id}", f"user:{user_id}"],
            metadata={"previous_role": binding.role},
        )
        return {"ok": True}

    def _require_user(self, user_id: str) -> UserAdministrationRecord:
        user = self._identities.get_user(user_id)
        if user is None:
            raise PlatformApplicationError("user_not_found", f"User {user_id} was not found.", 404)
        return user

    def _require_platform_admin(self, actor: UserProfile | None = None) -> UserProfile:
        user = self._actor(actor)
        if ToolRBAC.normalize_role(user.role) != "platform_admin":
            raise PlatformApplicationError(
                "platform_admin_required",
                "Platform administrator permission is required.",
                403,
            )
        return user

    def _actor(self, actor: UserProfile | None) -> UserProfile:
        return actor or self._current_user.current_user()

    def _record(
        self,
        *,
        actor: UserProfile,
        action: str,
        entity_type: str,
        entity_id: str,
        summary: str,
        object_refs: list[str],
        metadata: dict | None = None,
    ) -> None:
        self._audit.record_audit_event(
            AuditEvent(
                id=f"audit_{uuid4().hex[:12]}",
                occurred_at=datetime.now(timezone.utc).isoformat(),
                actor=actor.id,
                actor_kind="user",
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                status="completed",
                summary=summary,
                object_refs=object_refs,
                metadata=metadata or {},
            )
        )


__all__ = ["IdentityAdministrationApplicationService"]
