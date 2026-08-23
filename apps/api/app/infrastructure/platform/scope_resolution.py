from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from ..persistence.db_models import USWorkItemRecord, VersionRecord
from ..persistence.unit_of_work import session_scope


class SQLAlchemyProjectScopeReadModel:
    """Resolve conversation scope from durable project hierarchy facts."""

    def project_id_for_version(self, version_id: str) -> str | None:
        with session_scope() as session:
            return session.scalar(
                select(VersionRecord.project_id).where(
                    VersionRecord.id == version_id
                )
            )

    def project_id_for_us(self, us_id: str) -> str | None:
        with session_scope() as session:
            return session.scalar(
                select(USWorkItemRecord.project_id).where(
                    USWorkItemRecord.id == us_id
                )
            )

    def first_version_id(self, project_id: str) -> str | None:
        with session_scope() as session:
            return session.scalar(
                select(VersionRecord.id)
                .where(VersionRecord.project_id == project_id)
                .order_by(VersionRecord.sort_order, VersionRecord.id)
                .limit(1)
            )


@dataclass(frozen=True)
class CompatibilityProjectScopeProjection:
    """Translate compatibility project projections to the scope read port."""

    versions: Mapping[str, Sequence[Any]]
    us_items: Mapping[str, Sequence[Any]]

    def project_id_for_version(self, version_id: str) -> str | None:
        for project_id, versions in self.versions.items():
            if any(version.id == version_id for version in versions):
                return project_id
        return None

    def project_id_for_us(self, us_id: str) -> str | None:
        for project_id, items in self.us_items.items():
            if any(item.id == us_id for item in items):
                return project_id
        return None

    def first_version_id(self, project_id: str) -> str | None:
        versions = self.versions.get(project_id, ())
        return versions[0].id if versions else None


__all__ = [
    "CompatibilityProjectScopeProjection",
    "SQLAlchemyProjectScopeReadModel",
]
