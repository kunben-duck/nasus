"""Startup registration for an explicitly configured local/static principal."""
from __future__ import annotations

from sqlalchemy import func, select, text

from ...application.platform.account_models import UserProfile
from ..persistence.db_models import UserIdentityRecord
from ..persistence.unit_of_work import session_scope
from .account_identity import SQLAlchemyAccountIdentityService


OPERATOR_PASSWORD_MARKER = "!nasus-configured-operator-only-v1!"


class SQLAlchemyOperatorIdentityBootstrap:
    def ensure(self, profile: UserProfile) -> None:
        for value in (profile.id, profile.name, profile.email, profile.role):
            if not value.strip() or len(value) > 256 or any(ord(char) < 32 for char in value):
                raise ValueError("Configured operator identity is invalid.")
        with session_scope() as session:
            for key in sorted((f"id:{profile.id}", f"email:{profile.email.lower()}")):
                session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": f"nasus:operator-identity:{key}"})
            existing = session.get(UserIdentityRecord, profile.id)
            if existing is not None:
                if existing.email != profile.email or existing.password_hash != OPERATOR_PASSWORD_MARKER:
                    raise ValueError("Configured operator identity conflicts with an existing account.")
                # Restarting cannot undo deactivation, role changes, or profile edits.
                return
            if session.scalar(select(UserIdentityRecord.user_id).where(
                    func.lower(UserIdentityRecord.email) == profile.email.lower())) is not None:
                raise ValueError("Configured operator email belongs to another account.")
            now = session.scalar(select(func.clock_timestamp())).isoformat()
            session.add(UserIdentityRecord(user_id=profile.id, display_name=profile.name, email=profile.email,
                role=profile.role, password_hash=OPERATOR_PASSWORD_MARKER, status="active",
                created_at=now, updated_at=now))


class SQLAlchemyConfiguredIdentityReader:
    def authenticate(self, configured: UserProfile) -> UserProfile | None:
        with session_scope() as session:
            row = session.get(UserIdentityRecord, configured.id)
            if (row is None or row.status != "active" or row.email != configured.email
                    or row.password_hash != OPERATOR_PASSWORD_MARKER):
                return None
            return SQLAlchemyAccountIdentityService._profile(row)
