from __future__ import annotations

from collections.abc import Callable

from ...application.platform.account_models import UserProfile
from ...application.platform.account_ports import CurrentUserProviderPort


class CallableCurrentUserProvider(CurrentUserProviderPort):
    def __init__(self, current_user: Callable[[], UserProfile]) -> None:
        self._current_user = current_user

    def current_user(self) -> UserProfile:
        return self._current_user()


__all__ = ["CallableCurrentUserProvider"]
