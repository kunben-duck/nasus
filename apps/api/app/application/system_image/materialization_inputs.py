from __future__ import annotations

from dataclasses import dataclass

from ...domain.system_image.image_revision import (
    ImageRevisionConflict, ImageRevisionIntegrityError, require_frozen_inputs,
)
from ...domain.system_image.source_access import SourceAccessDenied, SourceAccessScope, StaleSourceAccessScope
from ...domain.system_image.source_snapshots import CapturedSourceManifest
from ...domain.system_image.materialization_command import (
    MaterializationCommandInput, MaterializationCommandConflict, MaterializationOriginalInputUnavailable,
)
from ..platform.errors import PlatformApplicationError
from .source_access import SourceScopeAuthorizationPort
from .source_snapshot_ports import SourceSnapshotRepositoryPort
from .materialization_command_port import MaterializationCommandInputPort


@dataclass(frozen=True)
class MaterializationInput:
    manifest: CapturedSourceManifest
    access: SourceAccessScope
    command: MaterializationCommandInput | None = None


class MaterializationInputApplicationService:
    """Admit an existing immutable input; never acquire or repair source history."""

    def __init__(self, snapshots: SourceSnapshotRepositoryPort | None,
                 authorization: SourceScopeAuthorizationPort | None,
                 commands: MaterializationCommandInputPort | None = None):
        self.snapshots, self.authorization = snapshots, authorization
        self.commands = commands

    def admit(self, project_id: str, *, invocation_id: str | None = None) -> MaterializationInput:
        if self.commands is not None and invocation_id is None:
            raise PlatformApplicationError("materialization_canonical_command_required", "Materialization requires a canonical tool invocation.", 409)
        access = self._authorize(project_id)
        if not access.binding_ids:
            raise PlatformApplicationError("missing_source_binding", "A real code source binding is required before materialization.", 409)
        if self.snapshots is None:
            raise PlatformApplicationError("materialization_inputs_unavailable", "Frozen source inputs are unavailable.", 503)
        original = self._command_read(lambda: self.commands.get(invocation_id, access)) if invocation_id is not None else None
        manifest = self._read(lambda: self.snapshots.get_manifest(project_id, original.manifest_id)
            if original is not None else self.snapshots.latest_manifest(project_id))
        if manifest is None:
            raise PlatformApplicationError("materialization_source_manifest_required",
                "Capture the registered sources before materializing context.", 409)
        if manifest.project_id != project_id:
            raise PlatformApplicationError("materialization_sources_changed", "Frozen source scope could not be verified.", 409)
        try:
            require_frozen_inputs(manifest)
        except ImageRevisionConflict as exc:
            raise PlatformApplicationError("materialization_source_capture_required",
                "Every selected code source requires a verified capture before materialization.", 409) from exc
        except ImageRevisionIntegrityError as exc:
            raise PlatformApplicationError("materialization_source_integrity_failed",
                "Frozen source integrity could not be verified.", 409) from exc
        if original is not None and (original.project_id != project_id or original.manifest_hash != manifest.content_hash):
            raise PlatformApplicationError("materialization_input_integrity_failed", "Original materialization inputs could not be verified.", 409)
        admitted = MaterializationInput(manifest, access, original)
        self.require_current(admitted)
        if invocation_id is not None:
            original = self._command_read(lambda: self.commands.admit(invocation_id, access, manifest))
            admitted = MaterializationInput(manifest, access, original)
            self.require_current(admitted)
        return admitted

    def require_current(self, admitted: MaterializationInput) -> None:
        self._authorize(admitted.manifest.project_id, admitted.access)
        if admitted.command is not None:
            self._command_read(lambda: self.commands.require_current(admitted.command, admitted.access))
        if (self.snapshots is None or not self._read(lambda: self.snapshots.is_current_materialization_input(admitted.manifest))
                or self._read(lambda: self.snapshots.latest_manifest(admitted.manifest.project_id)) != admitted.manifest):
            raise PlatformApplicationError("materialization_sources_changed",
                "Source inputs changed; explicitly capture sources before a new materialization.", 409)

    def _command_read(self, operation):
        if self.commands is None:
            raise PlatformApplicationError("materialization_inputs_unavailable", "Durable materialization inputs are unavailable.", 503)
        try:
            return operation()
        except MaterializationOriginalInputUnavailable as exc:
            raise PlatformApplicationError("materialization_original_input_required", "Original inputs are unavailable; submit a new materialization command.", 409) from exc
        except MaterializationCommandConflict as exc:
            raise PlatformApplicationError("materialization_sources_changed", "Original materialization source inputs changed; submit a new command.", 409) from exc
        except SourceAccessDenied as exc:
            raise PlatformApplicationError("source_access_denied", "Source materialization is not authorized.", 403) from exc
        except (ValueError, ImageRevisionIntegrityError, KeyError) as exc:
            raise PlatformApplicationError("materialization_input_integrity_failed", "Original materialization inputs could not be verified.", 409) from exc
        except Exception as exc:
            raise PlatformApplicationError("materialization_inputs_unavailable", "Durable materialization inputs are unavailable.", 503) from exc

    @staticmethod
    def _read(operation):
        try:
            return operation()
        except (ValueError, ImageRevisionIntegrityError) as exc:
            raise PlatformApplicationError("materialization_source_integrity_failed",
                "Frozen source integrity could not be verified.", 409) from exc
        except Exception as exc:
            raise PlatformApplicationError("materialization_inputs_unavailable", "Frozen source inputs are unavailable.", 503) from exc

    def _authorize(self, project_id: str, access: SourceAccessScope | None = None) -> SourceAccessScope:
        if self.authorization is None:
            raise PlatformApplicationError("source_access_unavailable", "Source authorization is unavailable.", 503)
        try:
            if access is None:
                access = self.authorization.require_all_sources_access(project_id)
            if access.project_id != project_id:
                raise SourceAccessDenied("materialization source project mismatch")
            self.authorization.require_current(access)
            return access
        except (SourceAccessDenied, StaleSourceAccessScope, PlatformApplicationError, KeyError) as exc:
            raise PlatformApplicationError("source_access_denied", "Source materialization is not authorized.", 403) from exc
        except Exception as exc:
            raise PlatformApplicationError("source_access_unavailable", "Source authorization is unavailable.", 503) from exc
