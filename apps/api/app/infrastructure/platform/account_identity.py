from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select

from ..persistence.database import SessionLocal
from ..persistence.db_models import AccessSessionRecord, UserIdentityRecord
from ..storage.object_storage import ObjectStorage
from ...application.platform.account_models import UserProfile
from ...application.platform.auth_service import (
    AuthServiceError,
    AuthSessionResult,
    AvatarImageContent,
)


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
AVATAR_DATA_URL_PATTERN = re.compile(r"^data:(image/(?:png|jpeg|webp|gif));base64,([A-Za-z0-9+/=\s]+)$")
DEFAULT_ROLE = "qa_lead"
MAX_AVATAR_BYTES = 512 * 1024
AVATAR_PRESET_IDS = {
    "yellow_duck",
    "city_fox",
    "officer_bunny",
    "zen_sloth",
    "jungle_lion",
    "panda_tester",
    "koala_builder",
    "capybara_lead",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


class SQLAlchemyAccountIdentityService:
    """Email/password auth for the first production baseline.

    Self-registered users may create projects as QA leads. Creating a project
    grants a project-scoped administrator binding without granting global
    platform administration.
    """

    def register(
        self,
        *,
        email: str,
        password: str,
        display_name: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> AuthSessionResult:
        normalized_email = self._normalize_email(email)
        self._validate_password(password)
        name = self._display_name(display_name, normalized_email)
        now = iso_now()

        with SessionLocal() as session:
            existing = session.scalar(select(UserIdentityRecord).where(UserIdentityRecord.email == normalized_email))
            if existing is not None:
                raise AuthServiceError("email_already_registered", "This email is already registered.", 409)

            user = UserIdentityRecord(
                user_id=f"user_{secrets.token_hex(12)}",
                email=normalized_email,
                display_name=name,
                role=DEFAULT_ROLE,
                password_hash=self._hash_password(password),
                status="active",
                created_at=now,
                updated_at=now,
                last_login_at=now,
            )
            session.add(user)
            result = self._create_session(session, user, user_agent=user_agent)
            session.commit()
            return result

    def login(self, *, email: str, password: str, user_agent: Optional[str] = None) -> AuthSessionResult:
        normalized_email = self._normalize_email(email)
        with SessionLocal() as session:
            user = session.scalar(select(UserIdentityRecord).where(UserIdentityRecord.email == normalized_email))
            if user is None or user.status != "active" or not self._verify_password(password, user.password_hash):
                raise AuthServiceError("invalid_credentials", "Email or password is incorrect.", 401)

            user.last_login_at = iso_now()
            user.updated_at = user.last_login_at
            result = self._create_session(session, user, user_agent=user_agent)
            session.commit()
            return result

    def authenticate_token(self, token: str) -> Optional[UserProfile]:
        token = token.strip()
        if not token:
            return None

        token_hash = self._hash_token(token)
        now = iso_now()
        with SessionLocal() as session:
            access_session = session.scalar(
                select(AccessSessionRecord).where(
                    AccessSessionRecord.token_hash == token_hash,
                    AccessSessionRecord.status == "active",
                )
            )
            if access_session is None or access_session.expires_at <= now:
                return None

            user = session.get(UserIdentityRecord, access_session.user_id)
            if user is None or user.status != "active":
                return None

            access_session.last_seen_at = now
            session.commit()
            return self._profile(user)

    def logout(self, token: str) -> bool:
        token = token.strip()
        if not token:
            return False

        token_hash = self._hash_token(token)
        with SessionLocal() as session:
            access_session = session.scalar(select(AccessSessionRecord).where(AccessSessionRecord.token_hash == token_hash))
            if access_session is None:
                return False
            now = iso_now()
            access_session.status = "revoked"
            access_session.revoked_at = now
            access_session.last_seen_at = now
            session.commit()
            return True

    def update_avatar(
        self,
        *,
        user_id: str,
        avatar_url: Optional[str] = None,
        avatar_preset: Optional[str] = None,
    ) -> UserProfile:
        with SessionLocal() as session:
            user = session.get(UserIdentityRecord, user_id)
            if user is None or user.status != "active":
                raise AuthServiceError("user_not_found", "Signed-in user was not found.", 404)

            normalized_preset = self._normalize_avatar_preset(avatar_preset)
            avatar_payload = self._parse_avatar_data_url(avatar_url) if normalized_preset is None else None
            if avatar_payload is not None:
                mime_type, raw = avatar_payload
                storage = ObjectStorage().put_bytes(
                    self._avatar_storage_key(user.user_id, raw, mime_type),
                    raw,
                    content_type=mime_type,
                )
                user.avatar_object_ref = storage.storage_ref
                user.avatar_mime_type = mime_type
            else:
                user.avatar_object_ref = None
                user.avatar_mime_type = None
            user.avatar_url = None
            user.avatar_preset = normalized_preset
            user.updated_at = iso_now()
            session.commit()
            return self._profile(user)

    def get_avatar_content(self, *, user_id: str) -> AvatarImageContent:
        with SessionLocal() as session:
            user = session.get(UserIdentityRecord, user_id)
            if user is None or user.status != "active":
                raise AuthServiceError("user_not_found", "Signed-in user was not found.", 404)
            if user.avatar_object_ref:
                return AvatarImageContent(
                    body=ObjectStorage().get_bytes(user.avatar_object_ref),
                    mime_type=user.avatar_mime_type or "application/octet-stream",
                )
            if user.avatar_url:
                mime_type, raw = self._parse_avatar_data_url(user.avatar_url)
                return AvatarImageContent(body=raw, mime_type=mime_type)
            raise AuthServiceError("avatar_not_found", "No uploaded avatar is available.", 404)

    def _create_session(
        self,
        session,
        user: UserIdentityRecord,
        *,
        user_agent: Optional[str] = None,
    ) -> AuthSessionResult:
        access_token = secrets.token_urlsafe(48)
        now = utc_now()
        expires_at = now + timedelta(days=int(os.getenv("NASUS_ACCESS_SESSION_DAYS", "14")))
        record = AccessSessionRecord(
            session_id=f"session_{secrets.token_hex(12)}",
            user_id=user.user_id,
            token_hash=self._hash_token(access_token),
            status="active",
            created_at=now.isoformat().replace("+00:00", "Z"),
            expires_at=expires_at.isoformat().replace("+00:00", "Z"),
            revoked_at=None,
            last_seen_at=now.isoformat().replace("+00:00", "Z"),
            user_agent=(user_agent or "")[:500] or None,
        )
        session.add(record)
        return AuthSessionResult(
            access_token=access_token,
            token_type="Bearer",
            expires_at=record.expires_at,
            user=self._profile(user),
        )

    @staticmethod
    def _profile(user: UserIdentityRecord) -> UserProfile:
        return UserProfile(
            id=user.user_id,
            name=user.display_name,
            email=user.email,
            role=user.role,
            avatar_url=user.avatar_url if not user.avatar_object_ref else None,
            avatar_preset=user.avatar_preset,
            avatar_image=bool(user.avatar_object_ref or user.avatar_url),
            avatar_updated_at=user.updated_at,
        )

    @staticmethod
    def _normalize_avatar_preset(avatar_preset: Optional[str]) -> Optional[str]:
        candidate = (avatar_preset or "").strip()
        if not candidate:
            return None
        if candidate not in AVATAR_PRESET_IDS:
            raise AuthServiceError("invalid_avatar_preset", "Avatar preset is not available.", 422)
        return candidate

    @staticmethod
    def _parse_avatar_data_url(avatar_url: Optional[str]) -> Optional[tuple[str, bytes]]:
        candidate = (avatar_url or "").strip()
        if not candidate:
            return None

        match = AVATAR_DATA_URL_PATTERN.match(candidate)
        if not match:
            raise AuthServiceError(
                "invalid_avatar",
                "Avatar must be a PNG, JPEG, WebP, or GIF data URL.",
                422,
            )

        mime_type, encoded = match.groups()
        compact_encoded = "".join(encoded.split())
        try:
            raw = base64.b64decode(compact_encoded.encode("ascii"), validate=True)
        except Exception as exc:
            raise AuthServiceError("invalid_avatar", "Avatar image data is not valid base64.", 422) from exc

        if len(raw) > MAX_AVATAR_BYTES:
            raise AuthServiceError("avatar_too_large", "Avatar image must be 512KB or smaller.", 413)

        return mime_type, raw

    @staticmethod
    def _avatar_storage_key(user_id: str, body: bytes, mime_type: str) -> str:
        extension_by_mime = {
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/webp": "webp",
            "image/gif": "gif",
        }
        digest = hashlib.sha256(body).hexdigest()
        extension = extension_by_mime.get(mime_type, "bin")
        return f"avatars/{user_id}/{digest}.{extension}"

    @staticmethod
    def _normalize_email(email: str) -> str:
        normalized = (email or "").strip().lower()
        if not EMAIL_PATTERN.match(normalized):
            raise AuthServiceError("invalid_email", "Register and sign in with a valid email address.", 422)
        return normalized

    @staticmethod
    def _display_name(display_name: Optional[str], email: str) -> str:
        candidate = (display_name or "").strip()
        if candidate:
            return candidate[:80]
        return email.split("@", 1)[0][:80] or "Nasus User"

    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password or "") < 8:
            raise AuthServiceError("weak_password", "Password must be at least 8 characters.", 422)

    @staticmethod
    def _hash_password(password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
        return "pbkdf2_sha256$200000$" + base64.b64encode(salt).decode("ascii") + "$" + base64.b64encode(digest).decode("ascii")

    @staticmethod
    def _verify_password(password: str, encoded: str) -> bool:
        try:
            algorithm, iterations, salt_b64, digest_b64 = encoded.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            salt = base64.b64decode(salt_b64.encode("ascii"))
            expected = base64.b64decode(digest_b64.encode("ascii"))
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
            return hmac.compare_digest(actual, expected)
        except Exception:
            return False

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()


__all__ = ["SQLAlchemyAccountIdentityService"]
