from __future__ import annotations

from typing import Protocol

from .identity_administration_models import (
    AccessSessionView,
    UserAdministrationPage,
    UserAdministrationRecord,
)


class IdentityAdministrationPort(Protocol):
    def list_users(
        self,
        *,
        query: str | None,
        limit: int,
        offset: int,
    ) -> UserAdministrationPage: ...

    def get_user(self, user_id: str) -> UserAdministrationRecord | None: ...

    def update_user(
        self,
        *,
        user_id: str,
        display_name: str | None,
        role: str | None,
        status: str | None,
    ) -> UserAdministrationRecord: ...

    def list_sessions(self, user_id: str) -> list[AccessSessionView]: ...

    def revoke_session(
        self,
        session_id: str,
        *,
        expected_user_id: str | None = None,
    ) -> AccessSessionView: ...


__all__ = ["IdentityAdministrationPort"]
