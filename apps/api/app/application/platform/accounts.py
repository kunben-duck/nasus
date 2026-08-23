from __future__ import annotations

from typing import Any, Optional

from .account_models import AuthLoginRequest, AuthRegisterRequest, AuthSessionResponse, UserAvatarUpdateRequest
from .account_ports import AccountIdentityPort, CurrentUserProviderPort
from .auth_service import AuthServiceError
from .errors import PlatformApplicationError


class AccountApplicationService:
    """Account and profile use cases for the platform bounded context."""

    def __init__(
        self,
        current_user: CurrentUserProviderPort,
        identities: AccountIdentityPort,
    ) -> None:
        self._current_user = current_user
        self._identities = identities

    def current_user(self) -> Any:
        return self._current_user.current_user()

    def authenticate_token(self, token: str) -> Any:
        return self._identities.authenticate_token(token)

    def register_user(self, payload: AuthRegisterRequest, *, user_agent: Optional[str] = None) -> AuthSessionResponse:
        try:
            result = self._identities.register(
                email=payload.email,
                password=payload.password,
                display_name=payload.name,
                user_agent=user_agent,
            )
        except AuthServiceError as exc:
            raise PlatformApplicationError(exc.code, exc.message, exc.status_code) from exc
        return AuthSessionResponse(
            access_token=result.access_token,
            token_type="Bearer",
            expires_at=result.expires_at,
            user=result.user,
        )

    def login_user(self, payload: AuthLoginRequest, *, user_agent: Optional[str] = None) -> AuthSessionResponse:
        try:
            result = self._identities.login(
                email=payload.email,
                password=payload.password,
                user_agent=user_agent,
            )
        except AuthServiceError as exc:
            raise PlatformApplicationError(exc.code, exc.message, exc.status_code) from exc
        return AuthSessionResponse(
            access_token=result.access_token,
            token_type="Bearer",
            expires_at=result.expires_at,
            user=result.user,
        )

    def logout_user(self, token: str) -> dict[str, bool]:
        self._identities.logout(token)
        return {"ok": True}

    def update_user_avatar(self, *, user: Any, payload: UserAvatarUpdateRequest) -> Any:
        if user is None:
            raise PlatformApplicationError("missing_token", "Bearer token is required.", 401)
        try:
            return self._identities.update_avatar(
                user_id=user.id,
                avatar_url=payload.avatar_url,
                avatar_preset=payload.avatar_preset,
            )
        except AuthServiceError as exc:
            raise PlatformApplicationError(exc.code, exc.message, exc.status_code) from exc

    def get_user_avatar_content(self, *, user: Any) -> Any:
        if user is None:
            raise PlatformApplicationError("missing_token", "Bearer token is required.", 401)
        try:
            return self._identities.get_avatar_content(user_id=user.id)
        except AuthServiceError as exc:
            raise PlatformApplicationError(exc.code, exc.message, exc.status_code) from exc
