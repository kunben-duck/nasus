from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ...domain.system_image.source_binding import (
    REQUIRED_SOURCE_TYPES,
    is_placeholder_source,
)
from ...domain.system_image.source_refresh import SourceRefreshSelection, SourceRefreshConflict
from ...domain.system_image.source_access import SourceAccessDenied, SourceAccessScope, StaleSourceAccessScope
from ...domain.system_image.source_acquisition import SourceAcquisitionIntentConflict
from ..platform.errors import PlatformApplicationError
from .raw_asset_chunks import SystemImageRawAssetChunkApplicationService
from .source_access import SourceScopeAuthorizationPort
from .source_acquisition_ports import SourceAcquisitionIntentPort
from .source_ports import (
    SourceAcquisitionFailed,
    SourceIngestionPort,
    SourceSpec,
    SystemImageIngestionProjectionPort,
)
from .system_image_models import RawAssetRecord
from .source_snapshot_ports import SourceSnapshotRepositoryPort


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SystemImageSourceIngestionApplicationService:
    """Own source registration and ingestion write-side updates."""

    def __init__(
        self,
        projection: SystemImageIngestionProjectionPort,
        source_ingestion: SourceIngestionPort,
        raw_asset_chunks: SystemImageRawAssetChunkApplicationService,
        snapshots: SourceSnapshotRepositoryPort | None = None,
        *,
        source_authorization: SourceScopeAuthorizationPort | None = None,
        acquisition_intents: SourceAcquisitionIntentPort | None = None,
    ) -> None:
        self._projection = projection
        self._source_ingestion = source_ingestion
        self._raw_asset_chunks = raw_asset_chunks
        self._snapshots = snapshots
        self._authorization = source_authorization
        self._acquisition_intents = acquisition_intents

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
        if not self._projection.list_sources(project_id):
            ensure_draft_state()
        now = _now_iso()
        added_binding = False
        if source_specs:
            sources = self._projection.list_sources(project_id)
            project = self._projection.get_project(project_id)
            existing_by_identity = {
                (source.source_type, source.source_uri, source.tracked_ref): source
                for source in sources
                if not is_placeholder_source(source, project.name)
            }
            for spec in source_specs:
                identity = (spec.source_type, spec.source_uri, spec.tracked_ref)
                current = existing_by_identity.get(identity)
                if current is not None:
                    # Re-registering the same binding updates metadata, not the
                    # captured revision. Refresh is an explicit ingestion action.
                    current.source_label = spec.label or current.source_label
                    current.credential_ref = spec.credential_ref or current.credential_ref
                    continue
                current = next((
                    source for source in sources
                    if source.source_type == spec.source_type
                    and is_placeholder_source(source, project.name)
                ), None)
                if current is None:
                    current = RawAssetRecord(
                        id=str(uuid4()),
                        project_id=project_id,
                        source_type=spec.source_type,
                        source_uri=spec.source_uri,
                        tracked_ref=spec.tracked_ref,
                        source_label=spec.label,
                        registered_at=now,
                        registered_by_actor=self._registered_actor(registered_by_actor),
                        registered_from_invocation_id=registered_from_invocation_id,
                        credential_ref=spec.credential_ref,
                    )
                    sources.append(current)
                else:
                    current.source_uri = spec.source_uri
                    current.tracked_ref = spec.tracked_ref
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
                existing_by_identity[identity] = current
                added_binding = True
            self._projection.replace_sources(project_id, sources)
            if self._snapshots is not None:
                self._snapshots.register_bindings(project_id, [
                    source for source in sources
                    if not is_placeholder_source(source, project.name)
                ])

        project = self._projection.get_project(project_id)
        if added_binding:
            project.system_image_status = "draft"
        project.progress = max(project.progress, 16)
        self._projection.save_project(project)
        self._projection.persist(project_id)
        self._projection.refresh(project_id)

    def ingest_sources(
        self,
        project_id: str,
        *,
        selection: SourceRefreshSelection | None = None,
        invocation_id: str | None = None,
        ensure_draft_state: Callable[[], None],
        source_binding_incomplete: Callable[[], bool],
        missing_source_types: Callable[[], list[str]],
    ) -> None:
        with self._projection.mutation_guard(project_id):
            self._ingest_sources(
                project_id,
                selection=selection,
                invocation_id=invocation_id,
                ensure_draft_state=ensure_draft_state,
                source_binding_incomplete=source_binding_incomplete,
                missing_source_types=missing_source_types,
            )

    def _ingest_sources(
        self,
        project_id: str,
        *,
        selection: SourceRefreshSelection | None = None,
        invocation_id: str | None = None,
        ensure_draft_state: Callable[[], None],
        source_binding_incomplete: Callable[[], bool],
        missing_source_types: Callable[[], list[str]],
    ) -> None:
        if selection is not None and invocation_id is None:
            selection.require_manifest(project_id,
                self._snapshots.latest_manifest(project_id) if self._snapshots else None)
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
        by_id = {source.id: source for source in registered_sources}
        if (len(by_id) != len(registered_sources)
                or any(source.project_id != project_id for source in registered_sources)):
            raise ValueError("Registered source IDs must belong to this project's sources.")
        selected_sources = registered_sources
        if selection is not None:
            if not set(selection.source_ids).issubset(by_id):
                raise ValueError("Selected source IDs must belong to this project's registered sources.")
            selected_sources = [source for source in registered_sources if source.id in selection.source_ids]
        source_ids = tuple(source.id for source in selected_sources)
        scope = self._require_source_authorization(project_id, source_ids)
        intent = None
        saved_results = {}
        if invocation_id is not None:
            intent = self._admit_acquisition(invocation_id, scope, source_ids, selection)
            self._require_source_authorization(project_id, source_ids, scope=scope)
            saved_results = {result.source_id: result for result in self._acquisition_call(
                lambda: self._acquisition_intents.results(intent, scope))}
            self._require_source_authorization(project_id, source_ids, scope=scope)
        now = _now_iso()
        for source in selected_sources:
            source.ingestion_status = "ingesting"
            source.ingest_started_at = now
            source.failure_reason = None

        project.system_image_status = "ingesting"
        self._projection.save_project(project)
        self._projection.persist(project_id)

        for source in selected_sources:
            self._require_source_authorization(project_id, source_ids, scope=scope)
            if intent is not None:
                result = saved_results.get(source.id)
                if result is None:
                    # Connector failures are outcomes; persistence failures must
                    # abort instead of being recorded as a successful gap.
                    try:
                        ingested = self._source_ingestion.ingest(source)
                        self._validate_ingested_source(source, ingested)
                    except PlatformApplicationError:
                        raise
                    except (OSError, RuntimeError, ValueError) as exc:
                        self._require_source_authorization(project_id, source_ids, scope=scope)
                        result = self._acquisition_call(lambda: self._acquisition_intents.record_failure(
                            intent, scope, source, inventory=exc.inventory if isinstance(exc, SourceAcquisitionFailed) else None,
                            denied=isinstance(exc, PermissionError)))
                    else:
                        self._require_source_authorization(project_id, source_ids, scope=scope)
                        result = self._acquisition_call(lambda: self._acquisition_intents.record_success(intent, scope, source, ingested))
                self._apply_acquisition_result(source, result, checked_at=now)
                continue
            inventory_id = None
            try:
                ingested = self._source_ingestion.ingest(source)
                self._require_source_authorization(project_id, source_ids, scope=scope)
                if self._snapshots is not None and ingested.inventory is not None:
                    inventory_id = self._snapshots.record_inventory(source, ingested.inventory, recorded_at=now)
                self._validate_ingested_source(source, ingested)
                revision_id = None
                if self._snapshots is not None and ingested.snapshot is not None:
                    self._require_source_authorization(project_id, source_ids, scope=scope)
                    revision_id = self._snapshots.record_capture(source, ingested.snapshot, captured_at=now)
            except PlatformApplicationError:
                # Revocation is not a connector gap and must stop the full command.
                raise
            except (OSError, RuntimeError, ValueError) as exc:
                self._require_source_authorization(project_id, source_ids, scope=scope)
                if self._snapshots is not None and isinstance(exc, SourceAcquisitionFailed):
                    inventory_id = self._snapshots.record_inventory(source, exc.inventory, recorded_at=now)
                reason = self._ingestion_failure_reason(exc)
                source.ingestion_status = "failed"
                source.permission_status = "denied" if isinstance(exc, PermissionError) else "allowed"
                source.permission_checked_at = now
                source.evidence_refs = [f"ingest_error:{reason}"]
                if inventory_id is not None:
                    source.evidence_refs.append(f"source-inventory:{inventory_id}")
                source.last_ingested_at = now
                source.failure_reason = reason
                source.file_count = 0
                source.byte_count = 0
                continue
            source.ingestion_status = "indexed"
            source.content_hash = ingested.content_hash
            source.content_ref = ingested.content_ref
            source.evidence_refs = ingested.evidence_refs
            if inventory_id is not None:
                source.evidence_refs = [*source.evidence_refs, f"source-inventory:{inventory_id}"]
            if revision_id is not None:
                source.evidence_refs = [*source.evidence_refs, f"source-revision:{revision_id}"]
            source.permission_status = "allowed"
            source.permission_checked_at = now
            source.last_ingested_at = now
            source.failure_reason = None
            source.file_count = ingested.file_count
            source.byte_count = ingested.byte_count

        # A durable workspace invalidates its request snapshot at each commit.
        # Re-attach the completed source facts explicitly instead of relying on
        # mutations to object references retained from the previous snapshot.
        self._require_source_authorization(project_id, source_ids, scope=scope)
        self._projection.replace_sources(project_id, sources)

        if intent is not None:
            self._acquisition_call(lambda: self._acquisition_intents.commit_manifest(intent, scope))
        elif self._snapshots is not None:
            self._snapshots.freeze_manifest(project_id, registered_sources, captured_at=now)

        if any(source.ingestion_status == "indexed" for source in sources):
            self._require_source_authorization(project_id, source_ids, scope=scope)
            if selection is None:
                self._raw_asset_chunks.materialize(project_id, captured_at=now)
            else:
                self._raw_asset_chunks.materialize(project_id, captured_at=now, source_ids=selection.source_ids)
        else:
            self._projection.clear_chunks(project_id)

        self._require_source_authorization(project_id, source_ids, scope=scope)
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

    def _admit_acquisition(self, invocation_id, scope, source_ids, selection):
        if self._acquisition_intents is None:
            raise PlatformApplicationError("source_acquisition_unavailable", "Source acquisition admission is unavailable.", 503)
        return self._acquisition_call(lambda: self._acquisition_intents.admit(invocation_id, scope, source_ids, selection))

    @staticmethod
    def _acquisition_call(operation):
        try:
            return operation()
        except SourceRefreshConflict:
            raise
        except SourceAcquisitionIntentConflict as exc:
            raise PlatformApplicationError("source_acquisition_scope_changed", "Original source acquisition scope changed.", 409) from exc
        except SourceAccessDenied as exc:
            raise PlatformApplicationError("source_access_denied", "Source ingestion is not authorized.", 403) from exc
        except ValueError as exc:
            raise PlatformApplicationError("source_acquisition_scope_invalid", "Source acquisition scope could not be verified.", 409) from exc
        except Exception as exc:
            raise PlatformApplicationError("source_acquisition_unavailable", "Source acquisition persistence is unavailable.", 503) from exc

    @staticmethod
    def _apply_acquisition_result(source, result, *, checked_at):
        source.ingestion_status = "failed" if result.status == "failed" else "indexed"
        source.content_hash = result.content_hash or ""
        source.content_ref = result.content_ref
        source.evidence_refs = ([f"ingest_error:{result.failure_reason}"] if result.status == "failed" else list(result.evidence_refs))
        if result.inventory_id is not None:
            source.evidence_refs.append(f"source-inventory:{result.inventory_id}")
        if result.source_revision_id is not None:
            source.evidence_refs.append(f"source-revision:{result.source_revision_id}")
        source.permission_status = result.permission_status
        source.permission_checked_at = checked_at
        source.last_ingested_at = result.acquired_at
        source.failure_reason = result.failure_reason
        source.file_count = result.file_count
        source.byte_count = result.byte_count

    def _require_source_authorization(
        self, project_id: str, source_ids: tuple[str, ...], *, scope: SourceAccessScope | None = None,
    ) -> SourceAccessScope:
        if self._authorization is None:
            raise PlatformApplicationError("source_access_unavailable", "Source authorization is unavailable.", 503)
        try:
            current = self._authorization.scope(project_id) if scope is None else scope
            if current.project_id != project_id or not current.permits_sources(source_ids):
                raise SourceAccessDenied("source ingestion is outside the authorized scope")
            self._authorization.require_current(current)
        except (SourceAccessDenied, StaleSourceAccessScope, PlatformApplicationError, KeyError) as exc:
            raise PlatformApplicationError("source_access_denied", "Source ingestion is not authorized.", 403) from exc
        except Exception as exc:
            raise PlatformApplicationError("source_access_unavailable", "Source authorization is unavailable.", 503) from exc
        return current

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
