from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, or_, select

from ...application.platform.identity_administration_models import (
    AccessSessionView,
    UserAdministrationPage,
    UserAdministrationRecord,
)
from ..persistence.db_models import AccessSessionRecord, UserIdentityRecord
from ..persistence.unit_of_work import session_scope


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class SQLAlchemyIdentityAdministrationAdapter:
    """PostgreSQL adapter for governed identity administration queries and commands."""

    def list_users(
        self,
        *,
        query: str | None,
        limit: int,
        offset: int,
    ) -> UserAdministrationPage:
        with session_scope() as session:
            predicates = []
            if query:
                pattern = f"%{query}%"
                predicates.append(
                    or_(
                        UserIdentityRecord.email.ilike(pattern),
                        UserIdentityRecord.display_name.ilike(pattern),
                    )
                )
            total = int(
                session.scalar(
                    select(func.count())
                    .select_from(UserIdentityRecord)
                    .where(*predicates)
                )
                or 0
            )
            rows = session.scalars(
                select(UserIdentityRecord)
                .where(*predicates)
                .order_by(UserIdentityRecord.created_at.desc(), UserIdentityRecord.user_id)
                .offset(offset)
                .limit(limit)
            ).all()
            counts = self._active_session_counts(session, [row.user_id for row in rows])
            return UserAdministrationPage(
                items=[self._to_user(row, counts.get(row.user_id, 0)) for row in rows],
                total=total,
                limit=limit,
                offset=offset,
            )

    def get_user(self, user_id: str) -> UserAdministrationRecord | None:
        with session_scope() as session:
            row = session.get(UserIdentityRecord, user_id)
            if row is None:
                return None
            count = self._active_session_counts(session, [user_id]).get(user_id, 0)
            return self._to_user(row, count)

    def update_user(
        self,
        *,
        user_id: str,
        display_name: str | None,
        role: str | None,
        status: str | None,
    ) -> UserAdministrationRecord:
        with session_scope() as session:
            row = session.get(UserIdentityRecord, user_id)
            if row is None:
                raise KeyError(user_id)
            now = _now_iso()
            if display_name is not None:
                row.display_name = display_name.strip()
            if role is not None:
                row.role = role
            if status is not None:
                row.status = status
                if status == "suspended":
                    sessions = session.scalars(
                        select(AccessSessionRecord).where(
                            AccessSessionRecord.user_id == user_id,
                            AccessSessionRecord.status == "active",
                        )
                    ).all()
                    for access_session in sessions:
                        access_session.status = "revoked"
                        access_session.revoked_at = now
                        access_session.last_seen_at = now
            row.updated_at = now
            session.flush()
            count = self._active_session_counts(session, [user_id]).get(user_id, 0)
            return self._to_user(row, count)

    def list_sessions(self, user_id: str) -> list[AccessSessionView]:
        with session_scope() as session:
            rows = session.scalars(
                select(AccessSessionRecord)
                .where(AccessSessionRecord.user_id == user_id)
                .order_by(AccessSessionRecord.created_at.desc())
            ).all()
            now = _now_iso()
            for row in rows:
                if row.status == "active" and row.expires_at <= now:
                    row.status = "expired"
            session.flush()
            return [self._to_session(row) for row in rows]

    def revoke_session(
        self,
        session_id: str,
        *,
        expected_user_id: str | None = None,
    ) -> AccessSessionView:
        with session_scope() as session:
            row = session.get(AccessSessionRecord, session_id)
            if row is None or (expected_user_id is not None and row.user_id != expected_user_id):
                raise KeyError(session_id)
            now = _now_iso()
            if row.status == "active" and row.expires_at <= now:
                row.status = "expired"
            elif row.status == "active":
                row.status = "revoked"
                row.revoked_at = now
                row.last_seen_at = now
            session.flush()
            return self._to_session(row)

    @staticmethod
    def _active_session_counts(session, user_ids: list[str]) -> dict[str, int]:
        if not user_ids:
            return {}
        rows = session.execute(
            select(AccessSessionRecord.user_id, func.count())
            .where(
                AccessSessionRecord.user_id.in_(user_ids),
                AccessSessionRecord.status == "active",
                AccessSessionRecord.expires_at > _now_iso(),
            )
            .group_by(AccessSessionRecord.user_id)
        ).all()
        return {user_id: int(count) for user_id, count in rows}

    @staticmethod
    def _to_user(row: UserIdentityRecord, active_session_count: int) -> UserAdministrationRecord:
        return UserAdministrationRecord(
            id=row.user_id,
            email=row.email,
            display_name=row.display_name,
            role=row.role,
            status=row.status,
            avatar_preset=row.avatar_preset,
            avatar_image=bool(row.avatar_object_ref or row.avatar_url),
            created_at=row.created_at,
            updated_at=row.updated_at,
            last_login_at=row.last_login_at,
            active_session_count=active_session_count,
        )

    @staticmethod
    def _to_session(row: AccessSessionRecord) -> AccessSessionView:
        return AccessSessionView(
            session_id=row.session_id,
            user_id=row.user_id,
            status=row.status,
            created_at=row.created_at,
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
            last_seen_at=row.last_seen_at,
            user_agent=row.user_agent,
        )


__all__ = ["SQLAlchemyIdentityAdministrationAdapter"]
