from __future__ import annotations

from datetime import datetime, timezone

from .ports import QualityAssetProgressWorkspacePort
from .quality_models import AssetLane, USItem
from ...domain.quality_loop.quality_assets import default_asset_lane_templates, matches_asset_lane


class QualityAssetProgressApplicationService:
    """Maintains quality asset lane and US progress write-side state.

    Quality-loop orchestration decides *what* changed; this service owns the
    storage-facing mechanics for materializing default lanes, updating lane
    status, and touching the US board item.
    """

    def __init__(self, workspace: QualityAssetProgressWorkspacePort) -> None:
        self._workspace = workspace

    def ensure_asset_lanes(self, project_id: str, us_id: str) -> None:
        lanes = self._workspace.list_asset_lanes(us_id)
        missing: list[AssetLane] = []
        for template in default_asset_lane_templates():
            if self._find_lane(lanes, template.lane_key) is None:
                missing.append(
                    AssetLane(
                        id=template.lane_id(us_id),
                        label=template.label,
                        status=template.status,
                        summary=template.summary,
                        updated_at=self._now(),
                    )
                )
        if missing:
            self._workspace.ensure_asset_lanes(project_id, us_id, missing)

    def update_lane(self, project_id: str, us_id: str, key: str, *, status: str, summary: str) -> None:
        lanes = self._workspace.list_asset_lanes(us_id)
        lane = self._find_lane(lanes, key)
        if lane is None:
            self.ensure_asset_lanes(project_id, us_id)
            lanes = self._workspace.list_asset_lanes(us_id)
            lane = self._find_lane(lanes, key)
        if lane is None:
            return
        lane.status = status
        lane.summary = summary
        lane.updated_at = self._now()
        self._workspace.save_asset_lane(project_id, us_id, lane)

    def touch_us(self, project_id: str, us_id: str, *, progress: int, status: str, next_action: str) -> None:
        item = self._workspace.get_us_item(project_id, us_id)
        if item is None:
            return
        self._workspace.save_us_item(
            project_id,
            item.model_copy(
                update={
                    "progress": progress,
                    "status": status,
                    "next_action": next_action,
                }
            ),
        )

    @staticmethod
    def _find_lane(lanes: list[AssetLane], key: str) -> AssetLane | None:
        return next(
            (
                lane
                for lane in lanes
                if matches_asset_lane(lane_id=lane.id, label=lane.label, lane_key=key)
            ),
            None,
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


__all__ = ["QualityAssetProgressApplicationService"]
