from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import func, select

from ...application.platform.tool_models import EventPayload
from ...domain.system_image.image_revision import require_frozen_inputs
from ...domain.system_image.materialization_command import (
    MaterializationCommandInput, MaterializationCommandConflict, MaterializationOriginalInputUnavailable,
)
from ...domain.system_image.source_access import SourceAccessDenied
from ...domain.system_image.source_snapshots import snapshot_digest
from .db_models import ToolInvocationRecord, UserIdentityRecord
from .event_outbox_repository import EventOutboxRepository
from .materialization_command_models import MaterializationCommandInputRecord as Input, MaterializationLegacyCommandRecord as Legacy
from .source_access_repository import SourceAccessRepository
from .source_snapshot_models import SourceBindingRecord, SourceManifestHeadRecord, SourceManifestRecord
from .source_snapshot_repository import SourceSnapshotRepository
from .unit_of_work import session_scope


class MaterializationCommandInputRepository:
    @staticmethod
    def _from_row(row):
        result = MaterializationCommandInput(**{key: getattr(row, key)
            for key in MaterializationCommandInput.__dataclass_fields__})
        if result.content_hash != row.content_hash:
            raise ValueError("Original materialization input integrity check failed.")
        return result

    @staticmethod
    def _command(session, invocation_id, scope):
        if session.get(Legacy, invocation_id) is not None:
            raise MaterializationOriginalInputUnavailable("Legacy materialization has no verified original input.")
        command = session.scalar(select(ToolInvocationRecord).where(
            ToolInvocationRecord.id == invocation_id).with_for_update())
        if (command is None or command.status != "running"
                or command.tool_id not in {"system_image.context.materialize", "system_image.baseline.initialize"}
                or command.input_payload.get("project_id") != scope.project_id):
            raise ValueError("Materialization requires its original running canonical command.")
        actor = session.get(UserIdentityRecord, scope.actor_id)
        if actor is None or actor.status != "active":
            raise SourceAccessDenied("Materialization account is unavailable.")
        rows = session.execute(SourceAccessRepository._authorized_statement(scope.project_id, scope.actor_id,
            platform_administrator=actor.role == "platform_admin")).all()
        if not rows or rows[0][5] is None:
            raise SourceAccessDenied("Materialization project membership is unavailable.")
        current = SourceAccessRepository._snapshot(scope.project_id, [row[:5] for row in rows]).for_actor(scope.actor_id, rows[0][5])
        roles = {"qa_lead", "project_admin", "platform_admin"}
        if command.tool_id == "system_image.context.materialize":
            roles.add("tester")
        if current.fingerprint != scope.fingerprint or current.effective_project_role not in roles:
            raise SourceAccessDenied("Materialization authorization changed.")
        command_hash = snapshot_digest({key: getattr(command, key) for key in (
            "tool_id", "input_payload", "conversation_id", "initiator_surface", "initiator_actor", "target_scope",
            "idempotency_scope", "idempotency_key", "idempotency_fingerprint")})
        return command, command_hash

    @staticmethod
    def _manifest(session, project_id, manifest_id):
        row = session.get(SourceManifestRecord, manifest_id)
        if row is None or row.project_id != project_id:
            raise ValueError("Original materialization source manifest is unavailable.")
        manifest = SourceSnapshotRepository._manifest(session, row)
        require_frozen_inputs(manifest)
        return manifest

    @classmethod
    def _validate(cls, session, original, scope, command_hash):
        if ((original.project_id, original.actor_id, original.command_hash)
                != (scope.project_id, scope.actor_id, command_hash)):
            raise ValueError("Original materialization command scope changed.")
        manifest = cls._manifest(session, original.project_id, original.manifest_id)
        if manifest.content_hash != original.manifest_hash:
            raise ValueError("Original materialization source manifest changed.")
        return manifest

    @staticmethod
    def _require_head(session, manifest, scope):
        head = session.get(SourceManifestHeadRecord, manifest.project_id)
        kinds = dict(session.execute(select(SourceBindingRecord.binding_id, SourceBindingRecord.kind).where(
            SourceBindingRecord.project_id == manifest.project_id)).all())
        if (head is None or head.manifest_id != manifest.manifest_id
                or set(kinds) != {item.binding_id for item in manifest.members}
                or any(kinds[item.binding_id] != item.source_type for item in manifest.members)):
            raise MaterializationCommandConflict("Original materialization source head or roster changed.")
        if set(kinds) != scope.binding_ids:
            raise SourceAccessDenied("Materialization requires access to the complete source selection.")

    @classmethod
    def _original(cls, session, command):
        row = session.get(Input, command.id)
        if row is None:
            if command.materialization_input_hash is not None:
                raise ValueError("Original materialization input history is unavailable.")
            return None
        original = cls._from_row(row)
        if command.materialization_input_hash != original.content_hash:
            raise ValueError("Materialization input consumption pin differs from its history.")
        return original

    def get(self, invocation_id, scope):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, scope.project_id)
            command, command_hash = self._command(session, invocation_id, scope)
            original = self._original(session, command)
            if original is None:
                return None
            self._validate(session, original, scope, command_hash)
            return original

    def admit(self, invocation_id, scope, manifest):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, scope.project_id)
            command, command_hash = self._command(session, invocation_id, scope)
            stored_manifest = self._manifest(session, scope.project_id, manifest.manifest_id)
            if stored_manifest != manifest:
                raise ValueError("Materialization source input changed before admission.")
            self._require_head(session, manifest, scope)
            proposed = MaterializationCommandInput(invocation_id, scope.project_id, scope.actor_id, command_hash,
                manifest.manifest_id, manifest.content_hash)
            original = self._original(session, command)
            if original is not None:
                self._validate(session, original, scope, command_hash)
                original.require_same(proposed)
                return original
            now = session.scalar(select(func.clock_timestamp()))
            session.add(Input(**asdict(proposed), content_hash=proposed.content_hash, created_at=now))
            command.materialization_input_hash = proposed.content_hash
            session.flush()
            EventOutboxRepository().append(EventPayload(event_id=f"materialization-source-input:{invocation_id}",
                event_type="system_image.materialization.admitted", occurred_at=now.isoformat(),
                correlation_id=command.conversation_id or scope.project_id, conversation_id=command.conversation_id,
                tool_invocation_id=invocation_id, entity_type="materialization_source_input", entity_id=invocation_id,
                entity_version=1, mutation_kind="invalidate", patch={"project_id": scope.project_id},
                query_keys=[["system-image", scope.project_id]]), session=session)
            return proposed

    def require_current(self, original, scope):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, scope.project_id)
            command, command_hash = self._command(session, original.invocation_id, scope)
            stored = self._original(session, command)
            if stored is None:
                raise ValueError("Original materialization input is unavailable.")
            original.require_same(stored)
            manifest = self._validate(session, stored, scope, command_hash)
            self._require_head(session, manifest, scope)
