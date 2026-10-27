from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Protocol

from ...domain.system_image.source_access import SourceAccessScope
from .system_image_models import SystemImageResponse


@dataclass(frozen=True)
class SystemImageReadView:
    scope: SourceAccessScope
    response: SystemImageResponse
    verify_publication: Optional[Callable[[], None]] = None


class SystemImageReadPort(Protocol):
    """Source-authorized read model, separate from the materialization workspace."""

    def read(self, project_id: str, *, working: bool = False) -> SystemImageReadView: ...

    def require_current(self, scope: SourceAccessScope) -> None: ...
