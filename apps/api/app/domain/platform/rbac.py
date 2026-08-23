from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


ROLE_ORDER = {
    "viewer": 0,
    "tester": 10,
    "qa_lead": 20,
    "project_admin": 30,
    "platform_admin": 40,
}

ROLE_ALIASES = {
    "admin": "platform_admin",
    "owner": "project_admin",
    "qa": "qa_lead",
    "developer": "tester",
    "member": "tester",
    "read_only": "viewer",
    "readonly": "viewer",
}


class UserRoleSubject(Protocol):
    role: str


class ToolAuthorizationSubject(Protocol):
    tool_id: str
    tool_kind: str
    risk_level: str
    confirmation_mode: str


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    summary: str
    required_roles: tuple[str, ...]
    user_role: str


class ToolRBAC:
    """Role gate for the canonical ToolInvocation surface.

    This domain policy is deliberately deterministic and adapter-free. It
    accepts protocol-shaped subjects so API DTOs, ORM records, or future
    project-scoped role bindings can call it without making the domain layer
    depend on those concrete types.
    """

    @staticmethod
    def normalize_role(role: str | None) -> str:
        normalized = (role or "viewer").strip().lower().replace("-", "_")
        return ROLE_ALIASES.get(normalized, normalized if normalized in ROLE_ORDER else "viewer")

    def authorize(
        self,
        user: UserRoleSubject,
        tool: ToolAuthorizationSubject | None,
    ) -> AuthorizationDecision:
        role = self.normalize_role(user.role)
        if tool is None:
            return AuthorizationDecision(
                allowed=False,
                summary="Unknown tools cannot be authorized.",
                required_roles=("platform_admin",),
                user_role=role,
            )

        required_roles = self.required_roles(tool)
        allowed = role in required_roles
        if allowed:
            return AuthorizationDecision(
                allowed=True,
                summary=f"{role} is authorized to invoke {tool.tool_id}.",
                required_roles=required_roles,
                user_role=role,
            )
        return AuthorizationDecision(
            allowed=False,
            summary=(
                f"Role {role} is not authorized to invoke {tool.tool_id}; "
                f"required role: {', '.join(required_roles)}."
            ),
            required_roles=required_roles,
            user_role=role,
        )

    def required_roles(self, tool: ToolAuthorizationSubject) -> tuple[str, ...]:
        if tool.tool_kind == "query":
            return self._roles_at_least("viewer")

        if tool.tool_id in {"release.decision.submit", "baseline.promote"} or tool.risk_level == "critical":
            return self._roles_at_least("project_admin")

        if tool.tool_kind == "governance" or tool.risk_level == "high" or tool.confirmation_mode != "none":
            return self._roles_at_least("qa_lead")

        if tool.tool_kind in {"analysis", "execution", "us", "sync"}:
            return self._roles_at_least("tester")

        if tool.tool_kind in {"project", "version"}:
            return self._roles_at_least("qa_lead")

        return self._roles_at_least("project_admin")

    @staticmethod
    def _roles_at_least(minimum_role: str) -> tuple[str, ...]:
        minimum_rank = ROLE_ORDER[minimum_role]
        return tuple(role for role, rank in ROLE_ORDER.items() if rank >= minimum_rank)
