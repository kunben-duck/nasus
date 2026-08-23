from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol, Sequence
from uuid import uuid4

from .account_models import UserProfile
from .errors import PlatformApplicationError
from .project_models import ProjectRoleBinding
from ...domain.platform.rbac import ROLE_ORDER, ToolRBAC


class ProjectAccessRepositoryPort(Protocol):
    def upsert(self, binding: ProjectRoleBinding) -> ProjectRoleBinding:
        ...

    def get_project_binding(self, *, project_id: str, user_id: str) -> ProjectRoleBinding | None:
        ...

    def list_for_user(self, user_id: str) -> list[ProjectRoleBinding]:
        ...

    def list_for_project(self, project_id: str) -> list[ProjectRoleBinding]:
        ...


@dataclass(frozen=True)
class ConversationAccessScope:
    id: str
    project_id: str | None
    initiator_id: str | None


@dataclass(frozen=True)
class InvocationAccessScope:
    id: str
    conversation_id: str | None
    input_payload: Mapping[str, Any]
    object_refs: Sequence[str]


class ProjectAccessReadPort(Protocol):
    def project_exists(self, project_id: str) -> bool:
        ...

    def list_project_ids(self) -> set[str]:
        ...

    def conversation_scope(self, conversation_id: str) -> ConversationAccessScope | None:
        ...

    def invocation_scope(self, invocation_id: str) -> InvocationAccessScope | None:
        ...

    def project_id_for_version(self, version_id: str) -> str | None:
        ...

    def project_id_for_us(self, us_id: str) -> str | None:
        ...

    def invocation_created_by(self, invocation_id: str, user_id: str) -> bool:
        ...


class ProjectAccessApplicationService:
    """Project membership and effective-role application policy."""

    def __init__(
        self,
        repository: ProjectAccessRepositoryPort,
        read_model: ProjectAccessReadPort,
        actor_provider: Callable[[], UserProfile],
    ) -> None:
        self._repository = repository
        self._read_model = read_model
        self._actor_provider = actor_provider

    def grant_creator(self, project_id: str, user: UserProfile | None = None) -> ProjectRoleBinding:
        actor = self._actor(user)
        return self.grant_role(
            project_id=project_id,
            user_id=actor.id,
            role="project_admin",
            created_by=actor.id,
        )

    def grant_role(
        self,
        *,
        project_id: str,
        user_id: str,
        role: str,
        created_by: str,
    ) -> ProjectRoleBinding:
        normalized_role = ToolRBAC.normalize_role(role)
        if normalized_role not in ROLE_ORDER:
            raise PlatformApplicationError("invalid_project_role", f"Unknown project role: {role}", 400)
        now = datetime.now(timezone.utc).isoformat()
        existing = self._repository.get_project_binding(project_id=project_id, user_id=user_id)
        binding = ProjectRoleBinding(
            binding_id=existing.binding_id if existing else f"role_{uuid4().hex[:16]}",
            project_id=project_id,
            user_id=user_id,
            role=normalized_role,  # type: ignore[arg-type]
            scope_ref=f"project:{project_id}",
            effective_policy_ref="policy:project-default-v1",
            status="active",
            created_at=existing.created_at if existing else now,
            updated_at=now,
            created_by=created_by,
        )
        return self._repository.upsert(binding)

    def list_project_members(
        self,
        project_id: str,
        user: UserProfile | None = None,
    ) -> list[ProjectRoleBinding]:
        self._require_project_administrator(project_id, user)
        return self._repository.list_for_project(project_id)

    def assign_project_member(
        self,
        *,
        project_id: str,
        user_id: str,
        role: str,
        actor: UserProfile | None = None,
    ) -> ProjectRoleBinding:
        administrator = self._require_project_administrator(project_id, actor)
        normalized_role = ToolRBAC.normalize_role(role)
        if normalized_role not in {"viewer", "tester", "qa_lead", "project_admin"}:
            raise PlatformApplicationError(
                "invalid_project_role",
                f"Role {role} cannot be assigned within a project.",
                400,
            )
        existing = self._repository.get_project_binding(
            project_id=project_id,
            user_id=user_id,
        )
        if (
            existing is not None
            and existing.role == "project_admin"
            and normalized_role != "project_admin"
            and ToolRBAC.normalize_role(administrator.role) != "platform_admin"
        ):
            self._require_another_project_administrator(project_id, user_id)
        return self.grant_role(
            project_id=project_id,
            user_id=user_id,
            role=normalized_role,
            created_by=administrator.id,
        )

    def revoke_project_member(
        self,
        *,
        project_id: str,
        user_id: str,
        actor: UserProfile | None = None,
    ) -> ProjectRoleBinding:
        administrator = self._require_project_administrator(project_id, actor)
        binding = self._repository.get_project_binding(
            project_id=project_id,
            user_id=user_id,
        )
        if binding is None:
            raise PlatformApplicationError(
                "project_member_not_found",
                f"User {user_id} is not an active member of project {project_id}.",
                404,
            )

        if binding.role == "project_admin" and ToolRBAC.normalize_role(administrator.role) != "platform_admin":
            self._require_another_project_administrator(project_id, user_id)

        revoked = binding.model_copy(
            update={
                "status": "revoked",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return self._repository.upsert(revoked)

    def visible_project_ids(self, user: UserProfile | None = None) -> set[str]:
        actor = self._actor(user)
        if ToolRBAC.normalize_role(actor.role) == "platform_admin":
            return self._read_model.list_project_ids()
        return {
            binding.project_id
            for binding in self._repository.list_for_user(actor.id)
            if binding.status == "active"
        }

    def can_access_project(self, project_id: str, user: UserProfile | None = None) -> bool:
        actor = self._actor(user)
        if not self._read_model.project_exists(project_id):
            return False
        if ToolRBAC.normalize_role(actor.role) == "platform_admin":
            return True
        return self._repository.get_project_binding(project_id=project_id, user_id=actor.id) is not None

    def require_project_access(self, project_id: str, user: UserProfile | None = None) -> ProjectRoleBinding | None:
        actor = self._actor(user)
        if not self._read_model.project_exists(project_id):
            raise KeyError(project_id)
        if ToolRBAC.normalize_role(actor.role) == "platform_admin":
            return None
        binding = self._repository.get_project_binding(project_id=project_id, user_id=actor.id)
        if binding is None:
            raise PlatformApplicationError(
                "project_access_denied",
                f"User {actor.id} is not a member of project {project_id}.",
                403,
            )
        return binding

    def effective_user_for_project(
        self,
        project_id: str,
        user: UserProfile | None = None,
        *,
        require_existing_project: bool = False,
    ) -> UserProfile:
        actor = self._actor(user)
        if ToolRBAC.normalize_role(actor.role) == "platform_admin":
            return actor
        if require_existing_project and not self._read_model.project_exists(project_id):
            raise KeyError(project_id)
        binding = self._repository.get_project_binding(project_id=project_id, user_id=actor.id)
        if binding is None:
            raise PlatformApplicationError(
                "project_access_denied",
                f"User {actor.id} is not a member of project {project_id}.",
                403,
            )
        return actor.model_copy(update={"role": binding.role})

    def require_conversation_access(self, conversation: Any, user: UserProfile | None = None) -> None:
        actor = self._actor(user)
        if ToolRBAC.normalize_role(actor.role) == "platform_admin":
            return
        if conversation.project_id:
            self.require_project_access(conversation.project_id, actor)
            return
        if conversation.initiator_id != actor.id:
            raise PlatformApplicationError(
                "conversation_access_denied",
                f"User {actor.id} cannot access conversation {conversation.id}.",
                403,
            )

    def can_access_conversation(self, conversation: Any, user: UserProfile | None = None) -> bool:
        try:
            self.require_conversation_access(conversation, user)
        except PlatformApplicationError:
            return False
        return True

    def project_id_for_invocation(self, invocation: Any) -> str | None:
        explicit = invocation.input_payload.get("project_id")
        if isinstance(explicit, str) and explicit:
            return explicit
        conversation = self._read_model.conversation_scope(invocation.conversation_id or "")
        if conversation is not None and conversation.project_id:
            return conversation.project_id
        for object_ref in self._invocation_object_refs(invocation):
            if object_ref.startswith("project:"):
                return object_ref.split(":", 1)[1]
        version_id = invocation.input_payload.get("version_id")
        if isinstance(version_id, str) and version_id:
            project_id = self._read_model.project_id_for_version(version_id)
            if project_id:
                return project_id
        us_id = invocation.input_payload.get("us_id")
        if isinstance(us_id, str) and us_id:
            project_id = self._read_model.project_id_for_us(us_id)
            if project_id:
                return project_id
        return None

    def can_access_invocation(self, invocation: Any, user: UserProfile | None = None) -> bool:
        actor = self._actor(user)
        if ToolRBAC.normalize_role(actor.role) == "platform_admin":
            return True
        project_id = self.project_id_for_invocation(invocation)
        if project_id:
            if self.can_access_project(project_id, actor):
                return True
            return bool(
                invocation.input_payload.get("authorization_denied")
                and self._invocation_created_by(invocation.id, actor.id)
            )
        conversation = self._read_model.conversation_scope(invocation.conversation_id or "")
        if conversation is not None:
            return self.can_access_conversation(conversation, actor)
        return self._invocation_created_by(invocation.id, actor.id)

    def require_invocation_access(self, invocation: Any, user: UserProfile | None = None) -> None:
        if not self.can_access_invocation(invocation, user):
            actor = self._actor(user)
            raise PlatformApplicationError(
                "tool_invocation_access_denied",
                f"User {actor.id} cannot access tool invocation {invocation.id}.",
                403,
            )

    def can_access_audit_event(self, event: Any, user: UserProfile | None = None) -> bool:
        actor = self._actor(user)
        if ToolRBAC.normalize_role(actor.role) == "platform_admin":
            return True
        if event.tool_invocation_id:
            invocation = self._read_model.invocation_scope(event.tool_invocation_id)
            if invocation is not None:
                return self.can_access_invocation(invocation, actor)
        if event.conversation_id:
            conversation = self._read_model.conversation_scope(event.conversation_id)
            if conversation is not None:
                return self.can_access_conversation(conversation, actor)
        for object_ref in event.object_refs:
            if object_ref.startswith("project:"):
                return self.can_access_project(object_ref.split(":", 1)[1], actor)
        return event.actor == actor.id

    def _invocation_created_by(self, invocation_id: str, user_id: str) -> bool:
        return self._read_model.invocation_created_by(invocation_id, user_id)

    def _actor(self, user: UserProfile | None) -> UserProfile:
        return user or self._actor_provider()

    def _require_project_administrator(
        self,
        project_id: str,
        user: UserProfile | None = None,
    ) -> UserProfile:
        actor = self._actor(user)
        if not self._read_model.project_exists(project_id):
            raise KeyError(project_id)
        if ToolRBAC.normalize_role(actor.role) == "platform_admin":
            return actor
        binding = self._repository.get_project_binding(
            project_id=project_id,
            user_id=actor.id,
        )
        if binding is None or ROLE_ORDER.get(binding.role, -1) < ROLE_ORDER["project_admin"]:
            raise PlatformApplicationError(
                "project_admin_required",
                f"Project administrator permission is required for project {project_id}.",
                403,
            )
        return actor.model_copy(update={"role": binding.role})

    def _require_another_project_administrator(
        self,
        project_id: str,
        excluded_user_id: str,
    ) -> None:
        remaining_administrators = [
            candidate
            for candidate in self._repository.list_for_project(project_id)
            if candidate.user_id != excluded_user_id and candidate.role == "project_admin"
        ]
        if not remaining_administrators:
            raise PlatformApplicationError(
                "last_project_admin_required",
                "Assign another project administrator before changing the last project administrator.",
                409,
            )

    @staticmethod
    def _invocation_object_refs(invocation: Any) -> Sequence[str]:
        object_refs = getattr(invocation, "object_refs", None)
        if object_refs is not None:
            return object_refs
        result = getattr(invocation, "result", None)
        return result.object_refs if result is not None else ()


__all__ = [
    "ConversationAccessScope",
    "InvocationAccessScope",
    "ProjectAccessApplicationService",
    "ProjectAccessReadPort",
    "ProjectAccessRepositoryPort",
]
