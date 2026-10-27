"""Pin canonical acquisition before mutable workspace markers or connector IO."""
from __future__ import annotations

from dataclasses import asdict
from contextlib import nullcontext

from sqlalchemy import func, select

from ...application.platform.tool_models import EventPayload
from ...application.system_image.source_refresh_inputs import source_refresh_selection
from ...domain.system_image.source_acquisition import AcquisitionSourcePin, SourceAcquisitionIntent, SourceAcquisitionIntentConflict
from ...domain.system_image.source_acquisition_results import SourceAcquisitionResult, acquisition_results_hash
from ...domain.system_image.source_access import SourceAccessDenied
from ...domain.system_image.source_snapshots import SourceManifestMember, SourceSnapshotArtifact, snapshot_digest
from ...domain.system_image.source_inventory import SourceInventoryArtifact
from ...domain.system_image.source_refresh import SourceRefreshConflict
from ...domain.system_image.source_tracking import require_tracked_ref
from .db_models import RawAssetRecord as RawAssetRow, ToolInvocationRecord, UserIdentityRecord
from .event_outbox_repository import EventOutboxRepository
from .source_access_repository import SourceAccessRepository
from .source_acquisition_models import SourceAcquisitionIntentRecord as Intent
from .source_acquisition_result_models import SourceAcquisitionProgressRecord as Progress, SourceAcquisitionResultRecord as Result, SourceAcquisitionManifestRecord as Receipt
from .source_snapshot_models import SourceBindingRecord, SourceRevisionRecord, SourceManifestHeadRecord, SourceManifestRecord
from .source_inventory_models import SourceInventoryRecord
from .source_snapshot_repository import SourceSnapshotRepository
from .unit_of_work import session_scope


class SourceAcquisitionIntentRepository:
    @staticmethod
    def _from_row(row):
        result = SourceAcquisitionIntent(row.invocation_id, row.project_id, row.actor_id, row.command_hash,
            row.selection_mode, tuple(AcquisitionSourcePin(**item) for item in row.sources),
            row.origin_manifest_id, row.origin_manifest_hash)
        if result.content_hash != row.content_hash:
            raise ValueError("Acquisition intent integrity check failed.")
        return result

    def get(self, invocation_id):
        with session_scope() as session:
            row = session.get(Intent, invocation_id)
            return self._from_row(row) if row is not None else None

    def admit(self, invocation_id, scope, source_ids, selection, *, session=None, require_existing=False):
        if (type(source_ids) is not tuple or not 1 <= len(source_ids) <= 1000
                or any(type(ident) is not str or not ident for ident in source_ids)
                or len(set(source_ids)) != len(source_ids) or not scope.permits_sources(source_ids)):
            raise ValueError("Invalid acquisition source scope.")
        with session_scope() if session is None else nullcontext(session) as session:
            SourceSnapshotRepository._lock(session, scope.project_id)
            command = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id).with_for_update())
            if (command is None or command.tool_id != "system_image.sources.ingest" or command.status != "running"
                    or command.input_payload.get("project_id") != scope.project_id
                    or source_refresh_selection(command.input_payload) != selection):
                raise ValueError("Acquisition requires its original running canonical command.")
            actor = session.get(UserIdentityRecord, scope.actor_id)
            if actor is None or actor.status != "active":
                raise SourceAccessDenied("Acquisition account is unavailable.")
            rows = session.execute(SourceAccessRepository._authorized_statement(scope.project_id, scope.actor_id,
                platform_administrator=actor.role == "platform_admin")).all()
            if not rows or rows[0][5] is None:
                raise SourceAccessDenied("Acquisition project membership is unavailable.")
            current_scope = SourceAccessRepository._snapshot(scope.project_id, [row[:5] for row in rows]).for_actor(
                scope.actor_id, rows[0][5])
            if current_scope.fingerprint != scope.fingerprint:
                raise SourceAccessDenied("Acquisition source authorization changed.")
            bindings = session.scalars(select(SourceBindingRecord).where(SourceBindingRecord.project_id == scope.project_id)).all()
            if selection is None and set(source_ids) != {item.legacy_source_id for item in bindings}:
                raise ValueError("Whole acquisition requires the complete registered source set.")
            if selection is not None and set(source_ids) != set(selection.source_ids):
                raise ValueError("Selected acquisition does not match its command.")
            selected = [item for item in bindings if item.legacy_source_id in source_ids]
            if len(selected) != len(source_ids):
                raise ValueError("Acquisition source binding is unavailable.")
            raw_sources = {row.id: row for row in session.scalars(select(RawAssetRow).where(
                RawAssetRow.project_id == scope.project_id, RawAssetRow.id.in_(source_ids)))}
            for binding in selected:
                raw = raw_sources.get(binding.legacy_source_id)
                tracked_ref = require_tracked_ref(binding.kind, binding.tracked_ref)
                identity_hash = snapshot_digest([binding.kind, binding.external_identity]
                    + ([tracked_ref] if tracked_ref is not None else []))
                if (raw is None or raw.project_id != scope.project_id or raw.source_type != binding.kind
                        or raw.source_uri != binding.external_identity or raw.tracked_ref != tracked_ref
                        or binding.identity_hash != identity_hash):
                    raise ValueError("Acquisition source identity differs from its registered binding.")
            previous = session.get(Intent, invocation_id)
            if require_existing and previous is None:
                raise ValueError("Original acquisition intent is unavailable.")
            original = self._from_row(previous) if previous is not None else None
            head = session.get(SourceManifestHeadRecord, scope.project_id)
            manifest = self._read_manifest(session, scope.project_id, head.manifest_id) if head is not None else None
            if original is None and selection is not None and (manifest is None
                    or manifest.manifest_id != selection.expected_manifest_id or manifest.content_hash != selection.expected_manifest_hash):
                raise SourceRefreshConflict("Selected source refresh no longer matches the current source manifest.")
            origin_id = original.origin_manifest_id if original else manifest.manifest_id if manifest else None
            origin_hash = original.origin_manifest_hash if original else manifest.content_hash if manifest else None
            intent = SourceAcquisitionIntent(invocation_id, scope.project_id, scope.actor_id, snapshot_digest({
                "tool_id": command.tool_id, "input_payload": command.input_payload,
                "conversation_id": command.conversation_id, "initiator_surface": command.initiator_surface,
                "initiator_actor": command.initiator_actor, "target_scope": command.target_scope,
                "idempotency_scope": command.idempotency_scope, "idempotency_key": command.idempotency_key,
                "idempotency_fingerprint": command.idempotency_fingerprint}),
                "selected" if selection is not None else "whole_project",
                tuple(sorted((AcquisitionSourcePin(item.legacy_source_id, item.binding_id, item.identity_hash)
                    for item in selected), key=lambda item: item.source_id)),
                origin_id, origin_hash)
            if original is not None:
                original.require_same(intent)
                origin = self._origin(session, original)
                progress = self._progress(session, original)
                self._load_results(session, original)
                receipt = session.get(Receipt, invocation_id)
                if (receipt is None) != (progress.manifest_receipt_hash is None):
                    raise ValueError("Original acquisition consumption history is unavailable.")
                consumed = self._validate_receipt(session, original, receipt) if receipt is not None else None
                if manifest != origin and (consumed is None or manifest != consumed):
                    raise SourceAcquisitionIntentConflict("Acquisition manifest head changed outside the original command.")
                return original
            now = session.scalar(select(func.clock_timestamp()))
            session.add(Intent(**{**asdict(intent), "sources": [asdict(item) for item in intent.sources]},
                content_hash=intent.content_hash, created_at=now))
            session.flush()
            progress = Progress(invocation_id=intent.invocation_id, project_id=intent.project_id,
                intent_hash=intent.content_hash, result_pins=[], manifest_receipt_hash=None)
            progress.content_hash = self._progress_hash(progress)
            session.add(progress)
            session.flush()
            EventOutboxRepository().append(EventPayload(event_id=f"source-acquisition-intent:{invocation_id}",
                event_type="system_image.source_acquisition.admitted", occurred_at=now.isoformat(),
                correlation_id=command.conversation_id or scope.project_id, conversation_id=command.conversation_id,
                tool_invocation_id=invocation_id, entity_type="source_acquisition", entity_id=invocation_id,
                entity_version=1, mutation_kind="invalidate", patch={"project_id": scope.project_id},
                query_keys=[["system-image", scope.project_id]]), session=session)
            return intent

    @staticmethod
    def _read_manifest(session, project_id, manifest_id):
        row = session.get(SourceManifestRecord, manifest_id)
        if row is None or row.project_id != project_id:
            raise ValueError("Acquisition source manifest is unavailable.")
        manifest = SourceSnapshotRepository._manifest(session, row)
        kinds = dict(session.execute(select(SourceBindingRecord.binding_id, SourceBindingRecord.kind).where(
            SourceBindingRecord.project_id == project_id)).all())
        if (snapshot_digest([asdict(item) for item in manifest.members]) != row.content_hash
                or any(kinds.get(item.binding_id) != item.source_type for item in manifest.members)):
            raise ValueError("Acquisition source manifest integrity check failed.")
        return manifest

    def _origin(self, session, intent):
        if intent.origin_manifest_id is None:
            return None
        origin = self._read_manifest(session, intent.project_id, intent.origin_manifest_id)
        if origin.content_hash != intent.origin_manifest_hash:
            raise ValueError("Original acquisition manifest hash changed.")
        return origin

    def _require_intent(self, session, intent, scope):
        command = session.get(ToolInvocationRecord, intent.invocation_id)
        if command is None:
            raise ValueError("Original acquisition command is unavailable.")
        current = self.admit(intent.invocation_id, scope, tuple(pin.source_id for pin in intent.sources),
            source_refresh_selection(command.input_payload), session=session, require_existing=True)
        intent.require_same(current)

    @staticmethod
    def _result(session, row, intent, *, revisions=None, inventories=None):
        result = SourceAcquisitionResult(**{**row.payload, "evidence_refs": tuple(row.payload["evidence_refs"])})
        result.require_intent(intent)
        if (result.result_hash != row.result_hash or any(getattr(result, key) != getattr(row, key) for key in (
                "invocation_id", "project_id", "source_id", "binding_id", "status", "source_revision_id", "inventory_id"))):
            raise ValueError("Original acquisition result integrity check failed.")
        if result.source_revision_id is not None:
            revision = (session.get(SourceRevisionRecord, result.source_revision_id) if revisions is None
                else revisions.get(result.source_revision_id))
            if revision is None or (revision.project_id, revision.binding_id) != (intent.project_id, result.binding_id):
                raise ValueError("Acquisition result source revision is unavailable.")
            artifact = SourceSnapshotArtifact(**{key: getattr(revision, key) for key in SourceSnapshotArtifact.__dataclass_fields__})
            if (snapshot_digest(asdict(artifact)) != result.snapshot_hash
                    or (artifact.content_hash, artifact.manifest_ref, artifact.file_count, artifact.byte_count)
                    != (result.content_hash, result.content_ref, result.file_count, result.byte_count)):
                raise ValueError("Acquisition result source revision changed.")
        if result.inventory_id is not None:
            inventory = (session.get(SourceInventoryRecord, result.inventory_id) if inventories is None
                else inventories.get(result.inventory_id))
            if inventory is None or (inventory.project_id, inventory.binding_id, inventory.source_id) != (
                    intent.project_id, result.binding_id, result.source_id):
                raise ValueError("Acquisition result inventory is unavailable.")
            artifact = SourceInventoryArtifact(**{key: getattr(inventory, key) for key in SourceInventoryArtifact.__dataclass_fields__})
            if snapshot_digest(asdict(artifact)) != result.inventory_hash:
                raise ValueError("Acquisition result inventory changed.")
            if result.status == "captured" and (artifact.status != "complete"
                    or (artifact.file_count, artifact.byte_count) != (result.file_count, result.byte_count)):
                raise ValueError("Acquisition result inventory does not prove the captured content.")
        return result

    def _load_results(self, session, intent):
        progress = self._progress(session, intent)
        rows = session.scalars(select(Result).where(Result.invocation_id == intent.invocation_id)
            .order_by(Result.source_id)).all()
        if len(rows) > len(intent.sources):
            raise ValueError("Acquisition result roster exceeds its original source selection.")
        revision_ids = {row.source_revision_id for row in rows if row.source_revision_id is not None}
        inventory_ids = {row.inventory_id for row in rows if row.inventory_id is not None}
        # Only transaction-local metadata is batched; each pin and current ACL
        # is still validated, and missing artifacts never fall back to a cache.
        revisions = {row.source_revision_id: row for row in session.scalars(select(SourceRevisionRecord).where(
            SourceRevisionRecord.source_revision_id.in_(revision_ids)).execution_options(populate_existing=True))} if revision_ids else {}
        inventories = {row.inventory_id: row for row in session.scalars(select(SourceInventoryRecord).where(
            SourceInventoryRecord.inventory_id.in_(inventory_ids)).execution_options(populate_existing=True))} if inventory_ids else {}
        results = tuple(self._result(session, row, intent, revisions=revisions, inventories=inventories) for row in rows)
        if progress.result_pins != [{"source_id": item.source_id, "result_hash": item.result_hash} for item in results]:
            raise ValueError("Original acquisition result ledger is incomplete.")
        return results

    @staticmethod
    def _progress_hash(progress):
        return snapshot_digest({"schema": "nasus.source-acquisition-progress.v1", **{key: getattr(progress, key)
            for key in ("invocation_id", "project_id", "intent_hash", "result_pins", "manifest_receipt_hash")}})

    def _progress(self, session, intent):
        progress = session.get(Progress, intent.invocation_id)
        if (progress is None or progress.project_id != intent.project_id or progress.intent_hash != intent.content_hash
                or progress.content_hash != self._progress_hash(progress)):
            raise ValueError("Original acquisition progress is unavailable or changed; a new command is required.")
        return progress

    def results(self, intent, scope):
        with session_scope() as session:
            self._require_intent(session, intent, scope)
            return self._load_results(session, intent)

    @staticmethod
    def _source_pin(intent, source):
        pin = next((pin for pin in intent.sources if pin.source_id == source.id), None)
        tracked_ref = require_tracked_ref(source.source_type, source.tracked_ref)
        identity_hash = snapshot_digest([source.source_type, source.source_uri] + ([tracked_ref] if tracked_ref else []))
        if pin is None or source.project_id != intent.project_id or identity_hash != pin.identity_hash:
            raise ValueError("Acquired source does not match its original binding.")
        return pin

    def record_success(self, intent, scope, source, ingested):
        with session_scope() as session:
            self._require_intent(session, intent, scope)
            pin = self._source_pin(intent, source)
            prior = session.get(Result, (intent.invocation_id, source.id))
            if prior is not None:
                result = self._result(session, prior, intent)
                if ((result.content_hash, result.content_ref, result.evidence_refs, result.file_count, result.byte_count)
                        != (ingested.content_hash, ingested.content_ref, tuple(ingested.evidence_refs), ingested.file_count, ingested.byte_count)
                        or result.snapshot_hash != (snapshot_digest(asdict(ingested.snapshot)) if ingested.snapshot else None)
                        or result.inventory_hash != (snapshot_digest(asdict(ingested.inventory)) if ingested.inventory else None)):
                    raise SourceAcquisitionIntentConflict("Original acquisition outcome cannot be replaced.")
                return result
            now = session.scalar(select(func.clock_timestamp()))
            snapshots = SourceSnapshotRepository()
            inventory_id = snapshots.record_inventory(source, ingested.inventory, recorded_at=now.isoformat(), session=session) if ingested.inventory else None
            revision_id = snapshots.record_capture(source, ingested.snapshot, captured_at=now.isoformat(), session=session) if ingested.snapshot else None
            result = SourceAcquisitionResult(intent.invocation_id, intent.project_id, source.id, pin.binding_id, intent.content_hash,
                "captured" if revision_id else "legacy_unverified", now.isoformat(), ingested.content_hash, ingested.content_ref,
                tuple(ingested.evidence_refs), ingested.file_count, ingested.byte_count, revision_id,
                snapshot_digest(asdict(ingested.snapshot)) if ingested.snapshot else None, inventory_id,
                snapshot_digest(asdict(ingested.inventory)) if ingested.inventory else None)
            self._save_result(session, intent, result, now)
            return self._result(session, session.get(Result, (intent.invocation_id, source.id)), intent)

    def record_failure(self, intent, scope, source, *, inventory=None, denied=False):
        with session_scope() as session:
            self._require_intent(session, intent, scope)
            pin = self._source_pin(intent, source)
            prior = session.get(Result, (intent.invocation_id, source.id))
            reason = "source_acquisition_denied" if denied else "source_acquisition_incomplete" if inventory else "source_connector_failed"
            if prior is not None:
                result = self._result(session, prior, intent)
                if (result.status != "failed" or result.failure_reason != reason
                        or result.inventory_hash != (snapshot_digest(asdict(inventory)) if inventory else None)):
                    raise SourceAcquisitionIntentConflict("Original acquisition outcome cannot be replaced.")
                return result
            now = session.scalar(select(func.clock_timestamp()))
            inventory_id = SourceSnapshotRepository().record_inventory(source, inventory, recorded_at=now.isoformat(), session=session) if inventory else None
            result = SourceAcquisitionResult(intent.invocation_id, intent.project_id, source.id, pin.binding_id, intent.content_hash,
                "failed", now.isoformat(), None, None, (), 0, 0, None, None, inventory_id,
                snapshot_digest(asdict(inventory)) if inventory else None, reason, "denied" if denied else "allowed")
            self._save_result(session, intent, result, now)
            return result

    def _save_result(self, session, intent, result, now):
        previous = self._load_results(session, intent)
        session.add(Result(invocation_id=result.invocation_id, project_id=result.project_id, source_id=result.source_id,
            binding_id=result.binding_id, status=result.status, source_revision_id=result.source_revision_id,
            inventory_id=result.inventory_id, payload=asdict(result), result_hash=result.result_hash, created_at=now))
        session.flush()
        progress = self._progress(session, intent)
        progress.result_pins = [{"source_id": item.source_id, "result_hash": item.result_hash}
            for item in sorted((*previous, result), key=lambda item: item.source_id)]
        progress.content_hash = self._progress_hash(progress)
        session.flush()
        EventOutboxRepository().append(EventPayload(event_id=f"source-acquisition-result:{result.invocation_id}:{result.source_id}",
            event_type="system_image.source_acquisition.result_recorded", occurred_at=now.isoformat(),
            correlation_id=result.project_id, tool_invocation_id=result.invocation_id, entity_type="source_acquisition",
            entity_id=result.invocation_id, entity_version=1, mutation_kind="invalidate", patch={"project_id": result.project_id},
            query_keys=[["system-image", result.project_id]]), session=session)

    def _members(self, session, intent, results):
        acquisition_results_hash(intent, results)
        origin = self._origin(session, intent)
        members = ({item.binding_id: item for item in origin.members} if origin and intent.selection_mode == "selected" else {})
        bindings = {row.binding_id: row for row in session.scalars(select(SourceBindingRecord).where(
            SourceBindingRecord.project_id == intent.project_id,
            SourceBindingRecord.binding_id.in_([result.binding_id for result in results])))}
        for result in results:
            binding = bindings.get(result.binding_id)
            if binding is None or binding.legacy_source_id != result.source_id:
                raise ValueError("Acquisition result binding is unavailable or changed.")
            members[result.binding_id] = SourceManifestMember(result.binding_id, binding.kind, result.source_revision_id, result.status)
        return tuple(sorted(members.values(), key=lambda item: item.binding_id))

    def _validate_receipt(self, session, intent, receipt):
        results = self._load_results(session, intent)
        manifest = self._read_manifest(session, intent.project_id, receipt.manifest_id)
        value = {key: getattr(receipt, key) for key in (
            "invocation_id", "project_id", "intent_hash", "results_hash", "manifest_id", "manifest_hash")}
        if (receipt.invocation_id != intent.invocation_id or receipt.project_id != intent.project_id
                or receipt.intent_hash != intent.content_hash or receipt.results_hash != acquisition_results_hash(intent, results)
                or receipt.manifest_hash != manifest.content_hash or manifest.members != self._members(session, intent, results)
                or receipt.content_hash != snapshot_digest({"schema": "nasus.source-acquisition-manifest-receipt.v1", **value})
                or self._progress(session, intent).manifest_receipt_hash != receipt.content_hash):
            raise ValueError("Original acquisition manifest receipt integrity check failed.")
        return manifest

    def commit_manifest(self, intent, scope):
        with session_scope() as session:
            self._require_intent(session, intent, scope)
            receipt = session.get(Receipt, intent.invocation_id)
            if receipt is not None:
                return self._validate_receipt(session, intent, receipt)
            results = self._load_results(session, intent)
            members = self._members(session, intent, results)
            now = session.scalar(select(func.clock_timestamp()))
            manifest = SourceSnapshotRepository().freeze_members(session, intent.project_id, members, captured_at=now.isoformat())
            value = {"invocation_id": intent.invocation_id, "project_id": intent.project_id, "intent_hash": intent.content_hash,
                "results_hash": acquisition_results_hash(intent, results), "manifest_id": manifest.manifest_id,
                "manifest_hash": manifest.content_hash}
            receipt_hash = snapshot_digest({"schema": "nasus.source-acquisition-manifest-receipt.v1", **value})
            session.add(Receipt(**value, content_hash=receipt_hash, created_at=now))
            progress = self._progress(session, intent)
            progress.manifest_receipt_hash = receipt_hash
            progress.content_hash = self._progress_hash(progress)
            session.flush()
            EventOutboxRepository().append(EventPayload(event_id=f"source-acquisition-manifest:{intent.invocation_id}",
                event_type="system_image.source_acquisition.manifest_committed", occurred_at=now.isoformat(),
                correlation_id=intent.project_id, tool_invocation_id=intent.invocation_id, entity_type="source_acquisition",
                entity_id=intent.invocation_id, entity_version=1, mutation_kind="invalidate", patch={"project_id": intent.project_id},
                query_keys=[["system-image", intent.project_id]]), session=session)
            return manifest
