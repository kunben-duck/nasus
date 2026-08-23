from __future__ import annotations

from typing import Callable

from ...domain.platform.rbac import AuthorizationDecision, ToolRBAC
from .account_models import UserProfile
from .errors import PlatformApplicationError
from .project_access import ProjectAccessApplicationService
from .tool_models import ToolDefinition, ToolInvocation


class ToolInvocationAuthorizationApplicationService:
    """Resolve request-local and project-scoped roles for tool execution."""

    def __init__(
        self,
        project_access: ProjectAccessApplicationService,
        actor_provider: Callable[[], UserProfile],
        rbac: ToolRBAC | None = None,
    ) -> None:
        self._project_access = project_access
        self._actor_provider = actor_provider
        self._rbac = rbac or ToolRBAC()

    def authorize(
        self,
        invocation: ToolInvocation,
        tool: ToolDefinition | None,
    ) -> AuthorizationDecision:
        actor = self._actor_provider()
        project_id = self._project_access.project_id_for_invocation(invocation)
        if not project_id:
            return self._rbac.authorize(actor, tool)
        try:
            effective_user = self._project_access.effective_user_for_project(project_id, actor)
        except (PlatformApplicationError, KeyError):
            required_roles = self._rbac.required_roles(tool) if tool is not None else ("platform_admin",)
            return AuthorizationDecision(
                allowed=False,
                summary=f"User {actor.id} is not authorized for project {project_id}.",
                required_roles=required_roles,
                user_role=self._rbac.normalize_role(actor.role),
            )
        return self._rbac.authorize(effective_user, tool)

    def current_actor_id(self) -> str:
        return self._actor_provider().id


__all__ = ["ToolInvocationAuthorizationApplicationService"]
