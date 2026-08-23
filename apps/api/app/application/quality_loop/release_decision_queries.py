from __future__ import annotations

from .ports import QualityLoopReleaseDecisionReadPort
from .quality_models import ReleaseDecision


class QualityLoopReleaseDecisionQueryApplicationService:
    """Read current release decisions for governance use cases."""

    def __init__(self, reader: QualityLoopReleaseDecisionReadPort) -> None:
        self._reader = reader

    def current_release_decision(
        self,
        project_id: str,
        us_id: str | None = None,
        version_id: str | None = None,
    ) -> ReleaseDecision | None:
        return self._reader.find_release_decision(
            project_id,
            us_id=us_id,
            version_id=version_id,
        )


__all__ = ["QualityLoopReleaseDecisionQueryApplicationService"]
