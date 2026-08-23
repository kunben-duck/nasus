from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from ...domain.system_image.source_binding import (
    REQUIRED_SOURCE_TYPES,
    is_placeholder_source,
)
from .raw_asset_chunks import SystemImageRawAssetChunkApplicationService
from .source_ports import (
    SourceIngestionPort,
    SourceSpec,
    SystemImageIngestionProjectionPort,
)
from .system_image_models import RawAssetRecord


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SystemImageSourceIngestionApplicationService:
    """Own source registration and ingestion write-side updates."""

    def __init__(
        self,
        projection: SystemImageIngestionProjectionPort,
        source_ingestion: SourceIngestionPort,
        raw_asset_chunks: SystemImageRawAssetChunkApplicationService,
    ) -> None:
        self._projection = projection
        self._source_ingestion = source_ingestion
        self._raw_asset_chunks = raw_asset_chunks

    def register_sources(
        self,
        project_id: str,
        source_specs: list[SourceSpec] | None,
        *,
        registered_by_actor: str,
        registered_from_invocation_id: str | None,
        ensure_draft_state: Callable[[], None],
    ) -> None:
        with self._projection.mutation_guard(project_id):
            self._register_sources(
                project_id,
                source_specs,
                registered_by_actor=registered_by_actor,
                registered_from_invocation_id=registered_from_invocation_id,
                ensure_draft_state=ensure_draft_state,
            )

    def _register_sources(
        self,
        project_id: str,
        source_specs: list[SourceSpec] | None,
        *,
        registered_by_actor: str,
        registered_from_invocation_id: str | None,
        ensure_draft_state: Callable[[], None],
    ) -> None:
        ensure_draft_state()
        now = _now_iso()
        if source_specs:
            self._clear_derived_context(project_id)
            sources = self._projection.list_sources(project_id)
            existing_by_type = {source.source_type: source for source in sources}
            for spec in source_specs:
                current = existing_by_type.get(spec.source_type)
                if current is None:
                    sources.append(
                        RawAssetRecord(
                            id=f"raw_{project_id}_{spec.source_type}",
                            project_id=project_id,
                            source_type=spec.source_type,
                            source_uri=spec.source_uri,
                            source_label=spec.label,
                            registered_at=now,
                            registered_by_actor=self._registered_actor(registered_by_actor),
                            registered_from_invocation_id=registered_from_invocation_id,
                            credential_ref=spec.credential_ref,
                        )
                    )
                else:
                    current.source_uri = spec.source_uri
                    current.source_label = spec.label
                    current.ingestion_status = "pending"
                    current.content_hash = ""
                    current.content_ref = None
                    current.evidence_refs = []
                    current.registered_at = now
                    current.registered_by_actor = self._registered_actor(registered_by_actor)
                    current.registered_from_invocation_id = registered_from_invocation_id
                    current.credential_ref = spec.credential_ref
                    current.permission_status = "not_checked"
                    current.permission_checked_at = None
                    current.ingest_started_at = None
                    current.last_ingested_at = None
                    current.failure_reason = None
                    current.file_count = 0
                    current.byte_count = 0
            self._projection.replace_sources(project_id, sources)

        project = self._projection.get_project(project_id)
        project.system_image_status = "draft"
        project.progress = max(project.progress, 16)
        self._projection.save_project(project)
        self._projection.persist(project_id)
        self._projection.refresh(project_id)

    def ingest_sources(
        self,
        project_id: str,
        *,
        ensure_draft_state: Callable[[], None],
        source_binding_incomplete: Callable[[], bool],
        missing_source_types: Callable[[], list[str]],
    ) -> None:
        with self._projection.mutation_guard(project_id):
            self._ingest_sources(
                project_id,
                ensure_draft_state=ensure_draft_state,
                source_binding_incomplete=source_binding_incomplete,
                missing_source_types=missing_source_types,
            )

    def _ingest_sources(
        self,
        project_id: str,
        *,
        ensure_draft_state: Callable[[], None],
        source_binding_incomplete: Callable[[], bool],
        missing_source_types: Callable[[], list[str]],
    ) -> None:
        if not self._projection.list_sources(project_id):
            ensure_draft_state()
        if source_binding_incomplete():
            missing = ", ".join(missing_source_types())
            raise RuntimeError(
                "System image source bindings are required before ingestion. "
                f"Missing source types: {missing or 'unknown'}."
            )

        project = self._projection.get_project(project_id)
        sources = self._projection.list_sources(project_id)
        registered_sources = [
            source
            for source in sources
            if not is_placeholder_source(source, project.name)
        ]
        now = _now_iso()
        for source in registered_sources:
            source.ingestion_status = "ingesting"
            source.ingest_started_at = now
            source.failure_reason = None

        project.system_image_status = "ingesting"
        self._projection.save_project(project)
        self._projection.persist(project_id)

        for source in registered_sources:
            try:
                ingested = self._source_ingestion.ingest(source)
                self._validate_ingested_source(source, ingested)
            except (OSError, RuntimeError, ValueError) as exc:
                reason = self._ingestion_failure_reason(exc)
                source.ingestion_status = "failed"
                source.permission_status = "denied" if isinstance(exc, PermissionError) else "allowed"
                source.permission_checked_at = now
                source.evidence_refs = [f"ingest_error:{reason}"]
                source.last_ingested_at = now
                source.failure_reason = reason
                source.file_count = 0
                source.byte_count = 0
                continue
            source.ingestion_status = "indexed"
            source.content_hash = ingested.content_hash
            source.content_ref = ingested.content_ref
            source.evidence_refs = ingested.evidence_refs
            source.permission_status = "allowed"
            source.permission_checked_at = now
            source.last_ingested_at = now
            source.failure_reason = None
            source.file_count = ingested.file_count
            source.byte_count = ingested.byte_count

        # A durable workspace invalidates its request snapshot at each commit.
        # Re-attach the completed source facts explicitly instead of relying on
        # mutations to object references retained from the previous snapshot.
        self._projection.replace_sources(project_id, sources)

        if any(source.ingestion_status == "indexed" for source in sources):
            self._raw_asset_chunks.materialize(project_id, captured_at=now)
        else:
            self._projection.clear_chunks(project_id)

        failed_required_sources = [
            source
            for source in registered_sources
            if source.source_type in REQUIRED_SOURCE_TYPES and source.ingestion_status == "failed"
        ]
        required_sources_indexed = all(
            any(
                source.source_type == required_type and source.ingestion_status == "indexed"
                for source in registered_sources
            )
            for required_type in REQUIRED_SOURCE_TYPES
        )
        project = self._projection.get_project(project_id)
        project.system_image_status = (
            "indexed"
            if required_sources_indexed and not failed_required_sources
            else "draft"
        )
        project.progress = max(project.progress, 20)
        self._projection.save_project(project)
        self._projection.persist(project_id)
        self._projection.refresh(project_id)

    def _clear_derived_context(self, project_id: str) -> None:
        self._projection.clear_derived_context(project_id)

    @staticmethod
    def _registered_actor(actor: str) -> str:
        return actor if actor in {"user", "agent"} else "system"

    @staticmethod
    def _ingestion_failure_reason(exc: Exception) -> str:
        message = str(exc).strip() or type(exc).__name__
        return message[:500]

    @staticmethod
    def _validate_ingested_source(source: RawAssetRecord, ingested: Any) -> None:
        if not ingested.content_hash or not ingested.content_ref:
            raise ValueError(f"{source.source_type} source produced no durable content reference")
        if not ingested.evidence_refs:
            raise ValueError(f"{source.source_type} source produced no ingestion evidence")
        if ingested.file_count < 0 or ingested.byte_count < 0:
            raise ValueError(f"{source.source_type} source produced invalid ingestion counters")
        if source.source_type == "code" and ingested.file_count == 0:
            raise ValueError("code source produced no ingestible files")


__all__ = ["SystemImageSourceIngestionApplicationService"]
