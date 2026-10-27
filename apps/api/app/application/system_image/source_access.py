from __future__ import annotations

from contextlib import nullcontext
from typing import Optional, Protocol

from ...domain.system_image.source_access import (
    SourceAccessDenied, SourceAccessScope, SourceAccessSnapshot, StaleSourceAccessScope,
)
from ..platform.account_models import UserProfile
from ..platform.errors import PlatformApplicationError


class SourceAccessRepositoryPort(Protocol):
    def load_snapshot(self, project_id: str) -> SourceAccessSnapshot: ...

    def load_authorized_snapshot(self, project_id: str, actor_id: str, *,
                                 platform_administrator: bool) -> tuple[SourceAccessSnapshot, Optional[str]]: ...

    def load_authorized_snapshots(self, project_ids: tuple[str, ...], actor_id: str, *,
                                  platform_administrator: bool) -> dict[str, tuple[SourceAccessSnapshot, Optional[str]]]: ...

    def binding_for_revision(self, project_id: str, source_revision_id: str) -> str: ...


class SourceProjectAuthorizationPort(Protocol):
    def current_actor(self) -> UserProfile: ...

    def effective_user_for_project(self, project_id: str, *, require_existing_project: bool) -> UserProfile: ...


class SourceBindingAuthorizationPort(Protocol):
    """Check live project membership and source policy together, never either alone."""

    def require_binding_access(self, project_id: str, binding_id: str) -> None: ...

    def require_revision_access(self, project_id: str, source_revision_id: str) -> None: ...


class SourceScopeAuthorizationPort(Protocol):
    def scope(self, project_id: str) -> SourceAccessScope: ...

    def require_current(self, scope: SourceAccessScope) -> None: ...

    def require_all_sources_access(self, project_id: str) -> SourceAccessScope: ...

    def require_current_many(self, scopes: tuple[SourceAccessScope, ...]) -> None: ...


class SourceAccessApplicationService:
    """Fresh project membership AND source policy, independent of mutable projections."""

    def __init__(self, repository: SourceAccessRepositoryPort, authorization: SourceProjectAuthorizationPort) -> None:
        self.repository = repository
        self.authorization = authorization

    def live_read_session(self):
        session = getattr(self.repository, "live_read_session", None)
        return session() if session else nullcontext()

    def scope(self, project_id: str) -> SourceAccessScope:
        actor = self.authorization.current_actor()
        snapshot, role = self.repository.load_authorized_snapshot(project_id, actor.id,
            platform_administrator=actor.role == "platform_admin")
        if snapshot.project_id != project_id:
            raise SourceAccessDenied("source policy project mismatch")
        if role is None:
            raise PlatformApplicationError("project_access_denied", "Project membership is required.", 403)
        current = self.authorization.current_actor()
        if (actor.id, actor.role) != (current.id, current.role):
            raise StaleSourceAccessScope("actor changed during authorization")
        return snapshot.for_actor(actor.id, role)

    def require_current(self, scope: SourceAccessScope) -> None:
        if self.scope(scope.project_id).fingerprint != scope.fingerprint:
            raise StaleSourceAccessScope("source access changed; rebuild the context")

    def require_current_many(self, scopes: tuple[SourceAccessScope, ...]) -> None:
        if not scopes:
            return
        if len(scopes) > 128 or len({scope.project_id for scope in scopes}) != len(scopes):
            raise StaleSourceAccessScope("invalid source authorization batch")
        actor = self.authorization.current_actor()
        if any(scope.actor_id != actor.id for scope in scopes):
            raise StaleSourceAccessScope("actor changed during authorization")
        project_ids = tuple(sorted(scope.project_id for scope in scopes))
        # One fresh MVCC statement validates the entire cohort, not a sequence
        # of final checks that could revoke an earlier project while reading another.
        with self.live_read_session():
            snapshots = self.repository.load_authorized_snapshots(project_ids, actor.id,
                platform_administrator=actor.role == "platform_admin")
        current = self.authorization.current_actor()
        if (actor.id, actor.role) != (current.id, current.role) or set(snapshots) != set(project_ids):
            raise StaleSourceAccessScope("authorization cohort changed")
        for scope in scopes:
            snapshot, role = snapshots[scope.project_id]
            if (role is None or snapshot.project_id != scope.project_id
                    or snapshot.for_actor(actor.id, role).fingerprint != scope.fingerprint):
                raise StaleSourceAccessScope("source access changed; discard the response")

    def require_all_sources_access(self, project_id: str) -> SourceAccessScope:
        scope = self.scope(project_id)
        snapshot = self.repository.load_snapshot(project_id)
        if (snapshot.project_id != project_id or (snapshot.bindings
                and not scope.permits_sources(tuple(item.source_id for item in snapshot.bindings)))):
            raise SourceAccessDenied("whole-project source receipt is not available")
        self.require_current(scope)
        return scope

    def require_binding_access(self, project_id: str, binding_id: str) -> None:
        try:
            self.scope(project_id).require_binding(binding_id)
        except SourceAccessDenied as exc:
            raise PlatformApplicationError("source_access_denied", "Source is not available.", 403) from exc

    def require_revision_access(self, project_id: str, source_revision_id: str) -> None:
        self.authorization.effective_user_for_project(project_id, require_existing_project=True)
        binding_id = self.repository.binding_for_revision(project_id, source_revision_id)
        self.require_binding_access(project_id, binding_id)
