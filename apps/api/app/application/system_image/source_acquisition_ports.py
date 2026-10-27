from __future__ import annotations

from typing import Protocol

from ...domain.system_image.source_acquisition import SourceAcquisitionIntent
from ...domain.system_image.source_acquisition_results import SourceAcquisitionResult
from ...domain.system_image.source_access import SourceAccessScope
from ...domain.system_image.source_refresh import SourceRefreshSelection
from ...domain.system_image.source_inventory import SourceInventoryArtifact
from ...domain.system_image.source_snapshots import CapturedSourceManifest
from .source_ports import IngestedSource
from .system_image_models import RawAssetRecord


class SourceAcquisitionIntentPort(Protocol):
    def admit(self, invocation_id: str, scope: SourceAccessScope, source_ids: tuple[str, ...],
              selection: SourceRefreshSelection | None) -> SourceAcquisitionIntent: ...

    def results(self, intent: SourceAcquisitionIntent, scope: SourceAccessScope) -> tuple[SourceAcquisitionResult, ...]: ...

    def record_success(self, intent: SourceAcquisitionIntent, scope: SourceAccessScope,
                       source: RawAssetRecord, ingested: IngestedSource) -> SourceAcquisitionResult: ...

    def record_failure(self, intent: SourceAcquisitionIntent, scope: SourceAccessScope,
                       source: RawAssetRecord, *, inventory: SourceInventoryArtifact | None = None,
                       denied: bool = False) -> SourceAcquisitionResult: ...

    def commit_manifest(self, intent: SourceAcquisitionIntent, scope: SourceAccessScope) -> CapturedSourceManifest: ...
