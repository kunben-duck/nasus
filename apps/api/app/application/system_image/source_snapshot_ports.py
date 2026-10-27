from __future__ import annotations

from typing import Protocol, Sequence

from ...domain.system_image.source_snapshots import (
    CapturedSourceManifest,
    SourceSnapshotArtifact,
)
from .system_image_models import RawAssetRecord
from ...domain.system_image.source_inventory import SourceInventoryArtifact


class SourceSnapshotRepositoryPort(Protocol):
    def register_bindings(self, project_id: str, sources: Sequence[RawAssetRecord]) -> None: ...

    def record_capture(
        self, source: RawAssetRecord, artifact: SourceSnapshotArtifact, *, captured_at: str,
    ) -> str: ...

    def record_inventory(
        self, source: RawAssetRecord, artifact: SourceInventoryArtifact, *, recorded_at: str,
    ) -> str: ...

    def freeze_manifest(
        self, project_id: str, sources: Sequence[RawAssetRecord], *, captured_at: str,
    ) -> CapturedSourceManifest: ...

    def latest_manifest(self, project_id: str) -> CapturedSourceManifest | None: ...

    def get_manifest(self, project_id: str, manifest_id: str) -> CapturedSourceManifest: ...

    def materialization_sources(self, manifest: CapturedSourceManifest) -> list[RawAssetRecord]: ...

    def build_source_revision(self, project_id: str, binding_id: str, source_revision_id: str) -> dict: ...

    def is_current_materialization_input(self, manifest: CapturedSourceManifest) -> bool: ...
