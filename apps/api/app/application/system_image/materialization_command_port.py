from __future__ import annotations

from typing import Protocol

from ...domain.system_image.materialization_command import MaterializationCommandInput
from ...domain.system_image.source_access import SourceAccessScope
from ...domain.system_image.source_snapshots import CapturedSourceManifest


class MaterializationCommandInputPort(Protocol):
    def get(self, invocation_id: str, scope: SourceAccessScope) -> MaterializationCommandInput | None: ...

    def admit(self, invocation_id: str, scope: SourceAccessScope,
              manifest: CapturedSourceManifest) -> MaterializationCommandInput: ...

    def require_current(self, original: MaterializationCommandInput, scope: SourceAccessScope) -> None: ...
