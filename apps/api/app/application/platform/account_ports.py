from __future__ import annotations

from typing import Any, Optional, Protocol

from .account_models import UserProfile


class CurrentUserProviderPort(Protocol):
    """Returns the request-local actor projected by the delivery boundary."""

    def current_user(self) -> UserProfile:
        ...


class AccountIdentityPort(Protocol):
    """Durable identity, session, and avatar operations used by account cases."""

    def register(
        self,
        *,
        email: str,
        password: str,
        display_name: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Any:
        ...

    def login(
        self,
        *,
        email: str,
        password: str,
        user_agent: Optional[str] = None,
    ) -> Any:
        ...

    def authenticate_token(self, token: str) -> Optional[UserProfile]:
        ...

    def logout(self, token: str) -> bool:
        ...

    def update_avatar(
        self,
        *,
        user_id: str,
        avatar_url: Optional[str] = None,
        avatar_preset: Optional[str] = None,
    ) -> UserProfile:
        ...

    def get_avatar_content(self, *, user_id: str) -> Any:
        ...


__all__ = ["AccountIdentityPort", "CurrentUserProviderPort"]
