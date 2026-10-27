from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Sequence
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ...application.platform.tool_models import EventPayload
from ...application.system_image.system_image_models import RawAssetRecord
from ...domain.system_image.source_snapshots import (
    CapturedSourceManifest, SourceManifestMember, SourceSnapshotArtifact, snapshot_digest,
)
from .event_outbox_repository import EventOutboxRepository
from .source_snapshot_models import (
    SourceBindingRecord, SourceRevisionRecord, SourceManifestRecord, SourceManifestMemberRecord,
    SourceManifestHeadRecord,
)
from .unit_of_work import session_scope
from ...domain.system_image.source_inventory import SourceInventoryArtifact
from ...domain.system_image.source_tracking import require_tracked_ref
from ...domain.system_image.image_revision import require_frozen_inputs, ImageRevisionIntegrityError
from .source_inventory_models import SourceInventoryRecord


class SourceSnapshotRepository:
    """Append-only source facts, separate from replaceable V1 projections."""

    @staticmethod
    def _lock(session: Session, project_id: str) -> None:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {
                "key": f"nasus:source-snapshots:{project_id}",
            })

    def register_bindings(self, project_id: str, sources: Sequence[RawAssetRecord]) -> None:
        with session_scope() as session:
            self._lock(session, project_id)
            for source in sources:
                if source.project_id != project_id:
                    raise ValueError("source binding project mismatch")
                self._binding(session, source)

    @staticmethod
    def _binding(session: Session, source: RawAssetRecord) -> SourceBindingRecord:
        tracked_ref = require_tracked_ref(source.source_type, source.tracked_ref)
        # Preserve the exact identity hash of untracked historical bindings.
        identity = snapshot_digest([source.source_type, source.source_uri]
            + ([tracked_ref] if tracked_ref is not None else []))
        record = session.scalar(select(SourceBindingRecord).where(
            SourceBindingRecord.project_id == source.project_id,
            SourceBindingRecord.legacy_source_id == source.id,
        ))
        if record is not None:
            if record.identity_hash != identity or record.tracked_ref != tracked_ref:
                raise ValueError("a source binding identity cannot be overwritten")
            return record
        record = SourceBindingRecord(
            binding_id=str(uuid4()), project_id=source.project_id, legacy_source_id=source.id,
            kind=source.source_type, external_identity=source.source_uri, identity_hash=identity,
            tracked_ref=tracked_ref,
            registered_at=source.registered_at or datetime.now(timezone.utc).isoformat(),
        )
        session.add(record)
        session.flush()
        return record

    def record_capture(
        self, source: RawAssetRecord, artifact: SourceSnapshotArtifact, *, captured_at: str, session: Session | None = None,
    ) -> str:
        if session is None:
            with session_scope() as active:
                return self.record_capture(source, artifact, captured_at=captured_at, session=active)
        self._lock(session, source.project_id)
        binding = self._binding(session, source)
        existing = session.scalar(select(SourceRevisionRecord).where(
            SourceRevisionRecord.binding_id == binding.binding_id,
            SourceRevisionRecord.external_revision == artifact.external_revision,
            SourceRevisionRecord.manifest_hash == artifact.manifest_hash,
        ))
        if existing is not None:
            if any(getattr(existing, key) != value for key, value in asdict(artifact).items()):
                raise ValueError("source snapshot digest was reused for different content")
            return existing.source_revision_id
        revision_id = str(uuid4())
        session.add(SourceRevisionRecord(
            source_revision_id=revision_id, project_id=source.project_id,
            binding_id=binding.binding_id, acquired_at=captured_at, **asdict(artifact),
        ))
        session.flush()
        self._event(session, "source.captured", source.project_id, revision_id, captured_at, {
            "binding_id": binding.binding_id, "source_revision_id": revision_id,
            "external_revision": artifact.external_revision, "manifest_hash": artifact.manifest_hash,
        })
        return revision_id

    def record_inventory(
        self, source: RawAssetRecord, artifact: SourceInventoryArtifact, *, recorded_at: str, session: Session | None = None,
    ) -> str:
        if artifact.project_id != source.project_id or artifact.source_id != source.id:
            raise ValueError("source inventory scope mismatch")
        if session is None:
            with session_scope() as active:
                return self.record_inventory(source, artifact, recorded_at=recorded_at, session=active)
        self._lock(session, source.project_id)
        binding = self._binding(session, source)
        existing = session.scalar(select(SourceInventoryRecord).where(
            SourceInventoryRecord.binding_id == binding.binding_id,
            SourceInventoryRecord.report_hash == artifact.report_hash,
        ))
        if existing is not None:
            if any(getattr(existing, key) != value for key, value in asdict(artifact).items()):
                raise ValueError("source inventory digest was reused for different content")
            return existing.inventory_id
        inventory_id = str(uuid4())
        session.add(SourceInventoryRecord(
            inventory_id=inventory_id, binding_id=binding.binding_id,
            recorded_at=recorded_at, **asdict(artifact),
        ))
        session.flush()
        # Paths and archive URLs require a current source-authorized read.
        self._event(session, "source.inventory_recorded", source.project_id, inventory_id, recorded_at, {
            "binding_id": binding.binding_id, "inventory_id": inventory_id,
        })
        return inventory_id

    def freeze_manifest(
        self, project_id: str, sources: Sequence[RawAssetRecord], *, captured_at: str,
    ) -> CapturedSourceManifest:
        with session_scope() as session:
            self._lock(session, project_id)
            members: list[SourceManifestMember] = []
            for source in sources:
                if source.project_id != project_id:
                    raise ValueError("source manifest project mismatch")
                binding = self._binding(session, source)
                revision_id = None
                status = "failed" if source.ingestion_status == "failed" else "pending"
                if source.ingestion_status == "indexed":
                    revision = session.scalar(select(SourceRevisionRecord).where(
                        SourceRevisionRecord.project_id == project_id,
                        SourceRevisionRecord.binding_id == binding.binding_id,
                        SourceRevisionRecord.manifest_ref == source.content_ref,
                        SourceRevisionRecord.content_hash == source.content_hash,
                    ))
                    revision_id = revision.source_revision_id if revision else None
                    status = "captured" if revision else "legacy_unverified"
                members.append(SourceManifestMember(binding.binding_id, source.source_type, revision_id, status))
            return self.freeze_members(session, project_id, members, captured_at=captured_at)

    def freeze_members(self, session: Session, project_id: str, members: Sequence[SourceManifestMember], *,
                       captured_at: str) -> CapturedSourceManifest:
        self._lock(session, project_id)
        members = tuple(sorted(members, key=lambda item: item.binding_id))
        if not members or len({item.binding_id for item in members}) != len(members):
            raise ValueError("invalid binding selection in source manifest")
        digest = snapshot_digest([asdict(member) for member in members])
        existing = session.scalar(select(SourceManifestRecord).where(
            SourceManifestRecord.project_id == project_id, SourceManifestRecord.content_hash == digest,
        ))
        if existing is not None:
            frozen = self._manifest(session, existing)
            if frozen.members != members:
                raise ValueError("source manifest digest differs from its members")
            self._set_head(session, project_id, existing.manifest_id)
            return frozen
        row = SourceManifestRecord(
            manifest_id=str(uuid4()), project_id=project_id, content_hash=digest, captured_at=captured_at,
        )
        session.add(row)
        session.flush()
        for member in members:
            session.add(SourceManifestMemberRecord(manifest_id=row.manifest_id, project_id=project_id, **asdict(member)))
        session.flush()
        self._event(session, "manifest.captured", project_id, row.manifest_id, captured_at, {
            "manifest_id": row.manifest_id, "content_hash": digest,
        })
        self._set_head(session, project_id, row.manifest_id)
        return CapturedSourceManifest(row.manifest_id, project_id, digest, captured_at, members)

    def latest_manifest(self, project_id: str) -> CapturedSourceManifest | None:
        with session_scope() as session:
            head = session.get(SourceManifestHeadRecord, project_id)
            row = session.get(SourceManifestRecord, head.manifest_id) if head else None
            return self._manifest(session, row) if row else None

    def materialization_sources(self, manifest: CapturedSourceManifest) -> list[RawAssetRecord]:
        require_frozen_inputs(manifest)
        with session_scope() as session:
            row = session.get(SourceManifestRecord, manifest.manifest_id)
            if row is None or self._manifest(session, row) != manifest:
                raise ImageRevisionIntegrityError("Frozen source manifest does not match its stored record.")
            sources = []
            for member in manifest.members:
                binding = session.get(SourceBindingRecord, member.binding_id)
                if binding is None or binding.project_id != manifest.project_id or binding.kind != member.source_type:
                    raise ImageRevisionIntegrityError("Frozen source binding is outside its manifest.")
                if member.status != "captured":
                    # Failed optional inputs remain explicit in the immutable
                    # manifest; do not re-read or invent content for them.
                    continue
                revision = session.get(SourceRevisionRecord, member.source_revision_id)
                if (binding is None or revision is None or binding.project_id != manifest.project_id
                        or revision.project_id != manifest.project_id or revision.binding_id != member.binding_id
                        or binding.kind != member.source_type):
                    raise ImageRevisionIntegrityError("Frozen source revision is outside its manifest.")
                sources.append(RawAssetRecord(id=binding.legacy_source_id, project_id=manifest.project_id,
                    source_type=binding.kind, source_uri=binding.external_identity, ingestion_status="indexed",
                    tracked_ref=binding.tracked_ref,
                    content_ref=revision.manifest_ref, content_hash=revision.content_hash,
                    file_count=revision.file_count, byte_count=revision.byte_count,
                    last_ingested_at=revision.acquired_at, registered_at=binding.registered_at))
            return sources

    def is_current_materialization_input(self, manifest: CapturedSourceManifest) -> bool:
        # The compatibility materializer selects all registered bindings. A new
        # pending binding invalidates that selection even before it has a revision.
        with session_scope() as session:
            self._lock(session, manifest.project_id)
            head = session.get(SourceManifestHeadRecord, manifest.project_id)
            bindings = set(session.scalars(select(SourceBindingRecord.binding_id).where(
                SourceBindingRecord.project_id == manifest.project_id)))
            return (head is not None and head.manifest_id == manifest.manifest_id
                    and bindings == {member.binding_id for member in manifest.members})

    def build_source_revision(self, project_id, binding_id, source_revision_id):
        with session_scope() as session:
            binding = session.get(SourceBindingRecord, binding_id)
            revision = session.get(SourceRevisionRecord, source_revision_id)
            if (binding is None or revision is None or binding.project_id != project_id
                    or revision.project_id != project_id or revision.binding_id != binding_id
                    or binding.kind != "code"):
                raise KeyError("fixed build source revision not found")
            return {"source_id": binding.legacy_source_id, **{key: getattr(revision, key) for key in
                ("external_revision", "content_hash", "manifest_hash", "manifest_ref", "file_count", "byte_count")}}

    @staticmethod
    def _set_head(session: Session, project_id: str, manifest_id: str) -> None:
        head = session.get(SourceManifestHeadRecord, project_id)
        if head is None:
            session.add(SourceManifestHeadRecord(project_id=project_id, manifest_id=manifest_id))
        else:
            head.manifest_id = manifest_id

    def get_manifest(self, project_id: str, manifest_id: str) -> CapturedSourceManifest:
        with session_scope() as session:
            row = session.scalar(select(SourceManifestRecord).where(
                SourceManifestRecord.project_id == project_id, SourceManifestRecord.manifest_id == manifest_id,
            ))
            if row is None:
                raise KeyError("source manifest not found")
            return self._manifest(session, row)

    @staticmethod
    def _manifest(session: Session, row: SourceManifestRecord) -> CapturedSourceManifest:
        members = session.scalars(select(SourceManifestMemberRecord).where(
            SourceManifestMemberRecord.manifest_id == row.manifest_id,
            SourceManifestMemberRecord.project_id == row.project_id,
        ).order_by(SourceManifestMemberRecord.binding_id)).all()
        return CapturedSourceManifest(
            row.manifest_id, row.project_id, row.content_hash, row.captured_at,
            tuple(SourceManifestMember(item.binding_id, item.source_type, item.source_revision_id, item.status) for item in members),
        )

    @staticmethod
    def _event(session: Session, kind: str, project_id: str, entity_id: str, occurred_at: str, patch: dict) -> None:
        EventOutboxRepository().append(EventPayload(
            event_id=str(uuid4()), event_type=f"system_image.{kind}", occurred_at=occurred_at,
            correlation_id=project_id, entity_type="source_snapshot", entity_id=entity_id,
            entity_version=0, mutation_kind="append", patch={"project_id": project_id, **patch},
            query_keys=[["system-image", project_id]],
        ), session=session)
