"""PG owns projection pins and fencing; native cache files are never authority."""
from dataclasses import asdict
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select, text

from ...application.platform.tool_models import EventPayload
from ...application.system_image.system_image_models import RawAssetRecord
from ...application.system_image.code_index_lifecycle import CODE_INDEX_CANCEL_TOOL, CodeIndexListPage
from ...domain.system_image.code_index import CodeIndexCancelled
from ...domain.system_image.code_index_generation import (
    CodeIndexBusy, CodeIndexGenerationPin, CodeIndexGenerationStatus, CodeIndexLease, CodeIndexLeaseLost,
)
from ...domain.system_image.code_provider_protocol import CODE_PROVIDER_CONTRACT_TYPES, read_code_provider_contract
from ...domain.system_image.image_revision import require_digest
from ...domain.system_image.source_snapshots import snapshot_digest
from .code_index_generation_models import CodeIndexGenerationRecord, CodeIndexWorkerLeaseRecord, CodeIndexWorkerAttemptRecord, CodeIndexProjectionRecord, CodeIndexProtocolRecord
from .db_models import ToolInvocationRecord
from .event_outbox_repository import EventOutboxRepository
from .source_snapshot_models import SourceBindingRecord, SourceRevisionRecord
from .source_snapshot_repository import SourceSnapshotRepository
from .structure_build_models import StructureBuildArtifactRecord
from .unit_of_work import session_scope


class CodeIndexGenerationRepository:
    LEASE_SECONDS = 45

    @staticmethod
    def _pin(row):
        if row is None:
            raise KeyError("code index generation is not available")
        return CodeIndexGenerationPin(**{key: getattr(row, key) for key in CodeIndexGenerationPin.__dataclass_fields__})

    @staticmethod
    def _invocation(session, project_id, invocation_id):
        invocation = session.get(ToolInvocationRecord, invocation_id)
        if (invocation is None or invocation.input_payload.get("project_id") != project_id
                or invocation.tool_id not in {"system_image.build.structure", "system_image.context.materialize", "system_image.baseline.initialize"}
                or invocation.status != "running"):
            raise CodeIndexLeaseLost("code index requires its running canonical invocation")

    def register(self, source, *, invocation_id, snapshot_hash, provider_fingerprint):
        require_digest(snapshot_hash)
        require_digest(provider_fingerprint)
        with session_scope() as session:
            self._invocation(session, source.project_id, invocation_id)
            session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {
                "key": f"nasus:code-index:{source.project_id}:{invocation_id}",
            })
            revision = session.scalar(select(SourceRevisionRecord).join(SourceBindingRecord,
                (SourceBindingRecord.project_id == SourceRevisionRecord.project_id)
                & (SourceBindingRecord.binding_id == SourceRevisionRecord.binding_id)).where(
                    SourceBindingRecord.project_id == source.project_id, SourceBindingRecord.kind == "code",
                    SourceBindingRecord.legacy_source_id == source.id, SourceBindingRecord.external_identity == source.source_uri,
                    SourceRevisionRecord.manifest_ref == source.content_ref, SourceRevisionRecord.content_hash == source.content_hash))
            if revision is None or source.source_type != "code":
                raise ValueError("code index requires a matching immutable code source revision")
            rows = session.scalars(select(CodeIndexGenerationRecord).where(
                CodeIndexGenerationRecord.binding_id == revision.binding_id,
                CodeIndexGenerationRecord.invocation_id == invocation_id)).all()
            if len(rows) > 1:
                raise CodeIndexLeaseLost("canonical code index command has ambiguous historical generations")
            if rows:
                pin = self._pin(rows[0])
                if pin.provider_fingerprint != provider_fingerprint:
                    raise CodeIndexLeaseLost("code index provider build or policy changed during canonical command retry")
                if pin.source_revision_id != revision.source_revision_id:
                    raise CodeIndexLeaseLost("code index source revision changed during canonical command retry")
                if (pin.project_id != source.project_id or pin.binding_id != revision.binding_id
                        or pin.source_manifest_hash != revision.manifest_hash or pin.snapshot_hash != snapshot_hash):
                    raise ValueError("code index generation cannot change its frozen inputs")
                return pin
            metadata = dict(generation_id="cgen_" + uuid4().hex, project_id=source.project_id, binding_id=revision.binding_id,
                source_revision_id=revision.source_revision_id, source_manifest_hash=revision.manifest_hash,
                snapshot_hash=snapshot_hash, provider_fingerprint=provider_fingerprint, invocation_id=invocation_id)
            pin = CodeIndexGenerationPin(**metadata, content_hash=snapshot_digest(metadata))
            session.add(CodeIndexGenerationRecord(**asdict(pin)))
            session.flush()
            session.add(CodeIndexWorkerLeaseRecord(generation_id=pin.generation_id, project_id=pin.project_id,
                epoch=0, state="idle", owner_id=None, lease_until=None))
            self._event(session, pin, "registered", 0)
            return pin

    def get(self, project_id, generation_id):
        with session_scope() as session:
            return self._pin(session.scalar(select(CodeIndexGenerationRecord).where(
                CodeIndexGenerationRecord.project_id == project_id, CodeIndexGenerationRecord.generation_id == generation_id)))

    def list(self, request):
        with session_scope() as session:
            rows = session.scalars(select(CodeIndexGenerationRecord).where(
                CodeIndexGenerationRecord.project_id == request.project_id,
                CodeIndexGenerationRecord.binding_id == request.binding_id,
                CodeIndexGenerationRecord.generation_id > request.after_id).order_by(
                    CodeIndexGenerationRecord.generation_id).limit(request.limit + 1)).all()
            pins = tuple(self._pin(row) for row in rows[:request.limit])
            return CodeIndexListPage(request, pins, pins[-1].generation_id if len(rows) > request.limit else None)

    def status(self, pin):
        with session_scope() as session:
            return self._status(session, pin)

    def _status(self, session, pin):
        self._require_pin(session, pin)
        row = session.get(CodeIndexWorkerLeaseRecord, pin.generation_id)
        invocation = session.get(ToolInvocationRecord, pin.invocation_id)
        revision = session.get(SourceRevisionRecord, pin.source_revision_id)
        binding = session.get(SourceBindingRecord, pin.binding_id)
        if (row is None or row.project_id != pin.project_id or invocation is None
                or invocation.input_payload.get("project_id") != pin.project_id
                or invocation.tool_id not in {"system_image.build.structure", "system_image.context.materialize", "system_image.baseline.initialize"}
                or revision is None or binding is None or binding.kind != "code"
                or revision.project_id != pin.project_id or binding.project_id != pin.project_id
                or revision.binding_id != pin.binding_id or revision.manifest_hash != pin.source_manifest_hash):
            raise CodeIndexLeaseLost("code index lifecycle pins are not intact")
        now = session.scalar(select(func.clock_timestamp()))
        if (row.owner_id is None) != (row.lease_until is None):
            raise CodeIndexLeaseLost("code index lease metadata is not intact")
        worker = "none" if row.owner_id is None else "active" if row.lease_until > now else "expired"
        protocol = self._protocol(session, pin, required=row.state in {"ready", "degraded"})
        projection = session.get(CodeIndexProjectionRecord, pin.generation_id)
        if projection is not None and projection.project_id != pin.project_id:
            raise CodeIndexLeaseLost("code index projection belongs to a different project")
        return CodeIndexGenerationStatus(pin, row.state, row.epoch, worker, invocation.status, now.isoformat(), protocol,
            projection.projection_hash if projection else None, projection.provider_version if projection else None,
            projection.entity_count if projection else None, projection.relationship_count if projection else None)

    def cancel_confirmed(self, pin, *, invocation_id, require_current):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, pin.project_id)
            require_current()
            command = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id).with_for_update())
            if (command is None or command.tool_id != CODE_INDEX_CANCEL_TOOL or command.status != "running"
                    or command.input_payload.get("confirmed_by_user") is not True
                    or any(command.input_payload.get(key) != value for key, value in {
                        "project_id": pin.project_id, "generation_id": pin.generation_id,
                        "expected_generation_hash": pin.content_hash}.items())):
                raise CodeIndexLeaseLost("code index cancellation requires its independent confirmed command")
            self._require_pin(session, pin)
            original = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == pin.invocation_id).with_for_update())
            if original is None:
                raise CodeIndexLeaseLost("code index origin command is missing")
            # The original command lock is shared with structural candidate commit.
            # Completed facts win; a prior cancellation is rechecked before commit.
            if session.get(StructureBuildArtifactRecord, pin.invocation_id) is not None:
                outcome = "already_committed"
            elif original.status in {"completed", "failed", "cancelled"}:
                outcome = "already_terminal"
            elif original.status != "running":
                raise CodeIndexLeaseLost("code index origin is not running or terminal")
            else:
                row = self._row(session, pin)
                now = session.scalar(select(func.clock_timestamp()))
                if row.state not in {"cancel_requested", "cancelled"}:
                    if row.owner_id is not None and row.lease_until is not None and row.lease_until > now:
                        row.state = "cancel_requested"
                    else:
                        row.state, row.owner_id, row.lease_until = "cancelled", None, None
                    self._event(session, pin, row.state, row.epoch, caused_by=invocation_id)
                outcome = row.state
            status = self._status(session, pin)
            require_current()
            return outcome, status

    def source(self, pin):
        with session_scope() as session:
            self._require_pin(session, pin)
            revision = session.get(SourceRevisionRecord, pin.source_revision_id)
            binding = session.get(SourceBindingRecord, pin.binding_id)
            if (revision is None or binding is None or binding.kind != "code"
                    or revision.project_id != pin.project_id or binding.project_id != pin.project_id
                    or revision.binding_id != pin.binding_id or revision.manifest_hash != pin.source_manifest_hash):
                raise ValueError("code index source pin is not intact")
            return RawAssetRecord(id=binding.legacy_source_id, project_id=pin.project_id, source_type="code",
                source_uri=binding.external_identity, content_ref=revision.manifest_ref, content_hash=revision.content_hash,
                file_count=revision.file_count, byte_count=revision.byte_count, ingestion_status="indexed",
                registered_at=binding.registered_at, last_ingested_at=revision.acquired_at)

    def _require_pin(self, session, pin):
        stored = self._pin(session.get(CodeIndexGenerationRecord, pin.generation_id))
        if stored != pin:
            raise ValueError("code index durable pin does not match")

    @staticmethod
    def _row(session, pin):
        row = session.scalar(select(CodeIndexWorkerLeaseRecord).where(
            CodeIndexWorkerLeaseRecord.project_id == pin.project_id,
            CodeIndexWorkerLeaseRecord.generation_id == pin.generation_id).with_for_update())
        if row is None:
            raise CodeIndexLeaseLost("code index lease is missing")
        return row

    def claim(self, pin, *, owner_id):
        if type(owner_id) is not str or not owner_id or len(owner_id) > 128:
            raise ValueError("invalid index lease owner")
        with session_scope() as session:
            self._require_pin(session, pin)
            self._invocation(session, pin.project_id, pin.invocation_id)
            row = self._row(session, pin)
            now = session.scalar(select(func.clock_timestamp()))
            if row.state in {"cancel_requested", "cancelled"}:
                raise CodeIndexCancelled("durable code index was cancelled")
            if row.owner_id is not None and row.lease_until > now:
                raise CodeIndexBusy("code index is owned by a live worker")
            row.epoch += 1
            row.owner_id, row.lease_until, row.state = owner_id, now + timedelta(seconds=self.LEASE_SECONDS), "preparing"
            session.add(CodeIndexWorkerAttemptRecord(generation_id=pin.generation_id, project_id=pin.project_id,
                epoch=row.epoch, owner_id=owner_id, started_at=now))
            self._event(session, pin, "claimed", row.epoch)
            return CodeIndexLease(pin, row.epoch, owner_id)

    def _owned(self, session, lease):
        self._require_pin(session, lease.pin)
        row = self._row(session, lease.pin)
        now = session.scalar(select(func.clock_timestamp()))
        if row.owner_id != lease.owner_id or row.epoch != lease.epoch or row.lease_until is None or row.lease_until <= now:
            raise CodeIndexLeaseLost("code index worker no longer owns its lease")
        if row.state == "cancel_requested":
            raise CodeIndexCancelled("durable code index cancellation requested")
        self._invocation(session, lease.pin.project_id, lease.pin.invocation_id)
        self._protocol(session, lease.pin, required=row.state in {"ready", "degraded"})
        return row, now

    @staticmethod
    def _protocol(session, pin, *, required):
        stored = session.get(CodeIndexProtocolRecord, pin.generation_id)
        if stored is None:
            if required or session.get(CodeIndexProjectionRecord, pin.generation_id) is not None:
                raise CodeIndexLeaseLost("durable native contract pin is missing")
            return None
        try:
            receipt = read_code_provider_contract(stored.receipt)
            if (stored.project_id != pin.project_id or stored.content_hash != receipt.digest
                    or stored.receipt != receipt.payload()):
                raise ValueError("native receipt content differs")
        except (KeyError, TypeError, ValueError) as error:
            raise CodeIndexLeaseLost("durable native contract pin is not intact") from error
        return receipt

    def check(self, lease):
        with session_scope() as session:
            row, now = self._owned(session, lease)
            row.lease_until = now + timedelta(seconds=self.LEASE_SECONDS)

    def mark_prepared(self, lease, *, state):
        if state not in {"ready", "degraded"}:
            raise ValueError("invalid prepared index state")
        with session_scope() as session:
            row, now = self._owned(session, lease)
            self._protocol(session, lease.pin, required=True)
            if row.state == state:
                row.lease_until = now + timedelta(seconds=self.LEASE_SECONDS)
                return
            row.state, row.lease_until = state, now + timedelta(seconds=self.LEASE_SECONDS)
            self._event(session, lease.pin, state, lease.epoch)

    def release(self, lease, *, failed=False):
        # Revocation must not prevent resource cleanup; a stale owner cannot
        # clear the new owner's lease or publish a completion event.
        with session_scope() as session:
            row = self._row(session, lease.pin)
            now = session.scalar(select(func.clock_timestamp()))
            if (row.epoch != lease.epoch or row.owner_id != lease.owner_id
                    or row.lease_until is None or row.lease_until <= now):
                return False
            row.state = "cancelled" if row.state == "cancel_requested" else "failed" if failed else "idle"
            row.owner_id, row.lease_until = None, None
            self._event(session, lease.pin, row.state, lease.epoch)
            return True

    def record_projection(self, lease, *, projection_hash, provider_version, entity_count, relationship_count):
        require_digest(projection_hash)
        if (type(provider_version) is not str or not provider_version or len(provider_version) > 120
                or any(type(count) is not int or not 0 <= count <= 100000000 for count in (entity_count, relationship_count))):
            raise ValueError("invalid code projection pin metadata")
        with session_scope() as session:
            row, _ = self._owned(session, lease)
            if row.state not in {"ready", "degraded"}:
                raise CodeIndexLeaseLost("code projection requires a prepared lease")
            metadata = dict(generation_id=lease.pin.generation_id, project_id=lease.pin.project_id,
                projection_hash=projection_hash, provider_version=provider_version,
                entity_count=entity_count, relationship_count=relationship_count)
            existing = session.get(CodeIndexProjectionRecord, lease.pin.generation_id)
            if existing is not None:
                if any(getattr(existing, key) != value for key, value in metadata.items()):
                    raise CodeIndexLeaseLost("rebuilt code projection diverges from its durable generation")
                return
            session.add(CodeIndexProjectionRecord(**metadata))
            self._event(session, lease.pin, "projection_recorded", lease.epoch)

    def record_protocol(self, lease, receipt):
        if not isinstance(receipt, CODE_PROVIDER_CONTRACT_TYPES):
            raise ValueError("durable code index requires a verified native contract")
        with session_scope() as session:
            row, _ = self._owned(session, lease)
            if row.state not in {"preparing", "ready", "degraded"}:
                raise CodeIndexLeaseLost("native contract requires a preparing worker lease")
            existing = session.get(CodeIndexProtocolRecord, lease.pin.generation_id)
            if existing is not None:
                if (existing.project_id != lease.pin.project_id or existing.content_hash != receipt.digest
                        or existing.receipt != receipt.payload()):
                    raise CodeIndexLeaseLost("native contract diverges from its durable generation")
                return
            session.add(CodeIndexProtocolRecord(generation_id=lease.pin.generation_id, project_id=lease.pin.project_id,
                content_hash=receipt.digest, receipt=receipt.payload()))
            self._event(session, lease.pin, "protocol_recorded", lease.epoch)

    def request_cancel(self, pin):
        with session_scope() as session:
            self._require_pin(session, pin)
            row = self._row(session, pin)
            if row.state in {"cancel_requested", "cancelled"}:
                return
            row.state = "cancel_requested" if row.owner_id is not None else "cancelled"
            self._event(session, pin, row.state, row.epoch)

    @staticmethod
    def _event(session, pin, state, epoch, *, caused_by=None):
        now = session.scalar(select(func.clock_timestamp())).isoformat()
        EventOutboxRepository().append(EventPayload(event_id=str(uuid4()),
            event_type="system_image.code_index." + state, occurred_at=now, correlation_id=pin.invocation_id,
            tool_invocation_id=caused_by,
            entity_type="code_index_generation", entity_id=pin.generation_id, entity_version=epoch, mutation_kind="append",
            patch={"project_id": pin.project_id, "generation_id": pin.generation_id,
                   "source_revision_id": pin.source_revision_id, "epoch": epoch, "state": state},
            query_keys=[["system-image", pin.project_id]]), session=session)
