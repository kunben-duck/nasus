from __future__ import annotations

from typing import Callable

from ...application.platform.project_models import ProjectCard
from ...application.system_image.read_model_port import SystemImageReadView
from ...application.system_image.source_access import SourceScopeAuthorizationPort
from ...application.system_image.system_image_models import (
    SystemImageBuildState, SystemImageChunkView, SystemImageResponse, SystemImageRestrictedProject, SystemImageVisibility,
)
from ...domain.system_image.source_access import SourceAccessScope
from ..persistence.system_image_repository import SystemImageRepository
from .source_read_projection import SQLAlchemySourceReadProjection
from ...application.system_image.published_reads import PublishedImageReadApplicationService
from ...application.system_image.publication_read_models import ImageReadState


class SQLAlchemySystemImageSnapshotReader:
    def __init__(self, repository: SystemImageRepository, access: SourceScopeAuthorizationPort,
                 project_reader: Callable[[str], ProjectCard], legacy_snapshot: Callable[[str], SystemImageResponse],
                 published: PublishedImageReadApplicationService | None = None) -> None:
        self.repository = repository
        self.access = access
        self.project_reader = project_reader
        self.legacy_snapshot = legacy_snapshot
        self.projection = SQLAlchemySourceReadProjection()
        self.published = published

    def require_current(self, scope: SourceAccessScope) -> None:
        self.access.require_current(scope)

    def read(self, project_id: str, *, working: bool = False) -> SystemImageReadView:
        scope = self.access.scope(project_id)
        if self.published and not working:
            published = self.published.read(project_id)
            if published is not None:
                project = self.project_reader(project_id)
                if project is None:
                    raise KeyError(project_id)
                response = SystemImageResponse(read_state=published.state, source_manifest=published.manifest,
                    project=SystemImageRestrictedProject(id=project.id, name=project.name, code=project.code),
                    visibility=SystemImageVisibility(withheld_sections=["project_status", "build_progress", "chunks",
                        "overlays", "metric_snapshots", "embedding_records", "retrieval_runs", "rerank_records", "task_contexts", "quality_profiles"]),
                    summary="Published knowledge snapshot only; not business acceptance, test coverage or release approval."
                        if published.state.pin else "This target has no published image. Working drafts are not a published baseline.",
                    build_state=SystemImageBuildState(status="ready" if published.state.pin else "materialized", stage_index=None,
                        label="Published knowledge snapshot" if published.state.pin else "No published image for this target"),
                    sources=list(published.sources), objects=list(published.objects), baselines=list(published.baselines),
                    relationships=list(published.relationships), overlays=[], metric_snapshots=[])
                self.require_current(scope)
                return SystemImageReadView(scope, response, lambda: self.published.require_current(published))
        if not scope.requires_provenance:
            response = self.legacy_snapshot(project_id).model_copy(deep=True)
        else:
            snapshot = self.projection.project(self.repository.load_project_snapshot(project_id), scope).snapshot
            project = self.project_reader(project_id)
            if project is None:
                raise KeyError(project_id)
            # Internal archives, invocation links and unknown derived facts are
            # not part of this public view. Evidence is read through its own API.
            sources = [source.model_copy(deep=True, update={
                "content_ref": None, "credential_ref": None, "registered_from_invocation_id": None,
                "failure_reason": None, "evidence_refs": [],
            }) for source in snapshot.raw_assets]
            chunks = [SystemImageChunkView(**{**chunk.model_dump(), "content_ref": None,
                                             "embedding_record_id": None, "metadata": {}})
                      for chunk in snapshot.raw_asset_chunks]
            response = SystemImageResponse(
                visibility=SystemImageVisibility(mode="source_filtered", withheld_sections=[
                    "project_status", "build_progress", "source_manifest", "baselines", "relationships",
                    "overlays", "metric_snapshots", "embedding_records", "retrieval_runs", "rerank_records",
                    "task_contexts", "quality_profiles",
                ]),
                project=SystemImageRestrictedProject(id=project.id, name=project.name, code=project.code),
                summary="Only authorized source-local facts are shown. Build progress, relationships and derived metrics are unavailable until their complete provenance is verified.",
                build_state=SystemImageBuildState(status="visibility_limited", stage_index=None,
                                                  label="Source-filtered view; overall build progress is unavailable."),
                sources=sources, chunks=chunks, objects=snapshot.knowledge_objects,
                baselines=[], relationships=[], overlays=[], metric_snapshots=[],
            )
        if working:
            response.read_state = ImageReadState(mode="working_draft")
        self.require_current(scope)
        verify = (lambda: self.published.require_legacy(project_id)) if self.published and not working else None
        return SystemImageReadView(scope, response, verify)
