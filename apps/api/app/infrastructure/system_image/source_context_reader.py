from __future__ import annotations

from typing import Callable, Optional

from ...application.system_image.memory_context import SystemImageContextFacts
from ...application.system_image.source_access import SourceScopeAuthorizationPort
from ...domain.system_image.source_access import SourceAccessScope
from ..persistence.system_image_repository import SystemImageRepository
from .source_read_projection import SQLAlchemySourceReadProjection
from ...application.system_image.published_reads import PublishedImageReadApplicationService


class SQLAlchemySystemImageContextReader:
    """Authenticated read model; it cannot mutate the materialization workspace."""

    def __init__(self, repository: SystemImageRepository, access: SourceScopeAuthorizationPort,
                 project_status: Callable[[str], Optional[str]], published: PublishedImageReadApplicationService | None = None) -> None:
        self.repository = repository
        self.access = access
        self.project_status = project_status
        self.projection = SQLAlchemySourceReadProjection()
        self.published = published

    def scope(self, project_id: str) -> SourceAccessScope:
        return self.access.scope(project_id)

    def require_current(self, scope: SourceAccessScope) -> None:
        self.access.require_current(scope)

    def read(self, project_id: str, *, version_id: Optional[str] = None) -> SystemImageContextFacts:
        scope = self.scope(project_id)
        if self.published:
            published = self.published.read(project_id, version_id=version_id)
            if published is not None:
                self.require_current(scope)
                return SystemImageContextFacts(scope=scope, sources=published.sources, objects=published.objects,
                    baselines=published.baselines, relationships=published.relationships, read_state=published.state,
                    system_image_status=published.state.mode,
                    verify_publication=lambda: self.published.require_current(published))
        view = self.projection.project(self.repository.load_project_snapshot(project_id), scope).snapshot
        facts = SystemImageContextFacts(
            scope=scope, sources=tuple(view.raw_assets), objects=tuple(view.knowledge_objects),
            baselines=() if scope.requires_provenance else tuple(view.baselines),
            relationships=tuple(view.relationships), metrics=tuple(view.metric_snapshots),
            system_image_status=None if scope.requires_provenance else self.project_status(project_id),
            verify_publication=(lambda: self.published.require_legacy(project_id, version_id=version_id)) if self.published else None,
        )
        self.require_current(scope)
        return facts
