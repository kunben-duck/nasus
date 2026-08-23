from __future__ import annotations

from datetime import datetime, timezone
from ...domain.system_image.us_work_items import (
    default_asset_lanes_for_us,
    derive_us_work_items_from_context,
)
from ..quality_loop.quality_models import AssetLane, USItem
from .ports import SystemImageWorkspacePort


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SystemImageUSWorkItemApplicationService:
    """Synchronize US work items and default quality lanes from system-image context."""

    def __init__(self, workspace: SystemImageWorkspacePort) -> None:
        self._workspace = workspace

    def sync_from_context(self, project_id: str, *, version_id: str | None) -> None:
        if self._workspace.list_us_items(project_id):
            return

        us_item_decisions = derive_us_work_items_from_context(
            self._workspace.list_knowledge_objects(project_id),
            project_id=project_id,
        )
        if not us_item_decisions:
            return

        us_items = [USItem(**decision.__dict__) for decision in us_item_decisions]
        self._workspace.replace_us_items(project_id, version_id, us_items)

        for us_item in us_items:
            lanes = [
                AssetLane(
                    **decision.__dict__,
                    updated_at=_now_iso(),
                )
                for decision in default_asset_lanes_for_us(us_item.id)
            ]
            self._workspace.replace_asset_lanes(project_id, us_item.id, lanes)


__all__ = ["SystemImageUSWorkItemApplicationService"]
