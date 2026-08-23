from __future__ import annotations

from dataclasses import dataclass, field

from apps.api.app.application.quality_loop.asset_progress import (
    QualityAssetProgressApplicationService,
)
from apps.api.app.application.quality_loop.quality_models import AssetLane, USItem
from apps.api.app.domain.quality_loop.quality_assets import matches_asset_lane


@dataclass
class InMemoryQualityAssetProgressWorkspace:
    lanes: dict[str, list[AssetLane]] = field(default_factory=dict)
    us_items: dict[str, list[USItem]] = field(default_factory=dict)
    lane_writes: list[tuple[str, str]] = field(default_factory=list)
    us_writes: list[tuple[str, str]] = field(default_factory=list)

    def list_asset_lanes(self, us_id: str) -> list[AssetLane]:
        return [
            lane.model_copy(deep=True)
            for lane in self.lanes.get(us_id, [])
        ]

    def ensure_asset_lanes(
        self,
        project_id: str,
        us_id: str,
        lanes: list[AssetLane],
    ) -> None:
        existing = self.lanes.setdefault(us_id, [])
        known_ids = {lane.id for lane in existing}
        existing.extend(
            lane.model_copy(deep=True)
            for lane in lanes
            if lane.id not in known_ids
        )
        self.lane_writes.append((project_id, us_id))

    def save_asset_lane(
        self,
        project_id: str,
        us_id: str,
        lane: AssetLane,
    ) -> None:
        lanes = self.lanes.setdefault(us_id, [])
        self.lanes[us_id] = [
            lane.model_copy(deep=True) if item.id == lane.id else item
            for item in lanes
        ]
        if all(item.id != lane.id for item in lanes):
            self.lanes[us_id].append(lane.model_copy(deep=True))
        self.lane_writes.append((project_id, us_id))

    def get_us_item(self, project_id: str, us_id: str) -> USItem | None:
        item = next(
            (
                candidate
                for candidate in self.us_items.get(project_id, [])
                if candidate.id == us_id
            ),
            None,
        )
        return item.model_copy(deep=True) if item is not None else None

    def save_us_item(
        self,
        project_id: str,
        item: USItem,
    ) -> None:
        items = self.us_items.setdefault(project_id, [])
        self.us_items[project_id] = [
            item.model_copy(deep=True) if candidate.id == item.id else candidate
            for candidate in items
        ]
        self.us_writes.append((project_id, item.id))


def us_item(us_id: str) -> USItem:
    return USItem(
        id=us_id,
        title="Checkout confirmation",
        owner="QA",
        status="analysis",
        risk="high",
        progress=20,
        next_action="Generate scope",
    )


def test_asset_progress_materializes_default_lanes_idempotently() -> None:
    workspace = InMemoryQualityAssetProgressWorkspace()
    service = QualityAssetProgressApplicationService(workspace)

    service.ensure_asset_lanes("proj_a", "US-A1")
    initial_lanes = workspace.lanes["US-A1"]
    service.ensure_asset_lanes("proj_a", "US-A1")

    assert initial_lanes
    assert len(workspace.lanes["US-A1"]) == len(initial_lanes)
    assert workspace.lane_writes == [("proj_a", "US-A1")]


def test_asset_progress_updates_named_lane_through_workspace_port() -> None:
    workspace = InMemoryQualityAssetProgressWorkspace()
    service = QualityAssetProgressApplicationService(workspace)

    service.update_lane(
        "proj_a",
        "US-A1",
        "scenarios",
        status="ready_for_review",
        summary="Generated risk-based scenarios.",
    )

    scenario_lane = next(
        lane
        for lane in workspace.lanes["US-A1"]
        if matches_asset_lane(
            lane_id=lane.id,
            label=lane.label,
            lane_key="scenarios",
        )
    )
    assert scenario_lane.status == "ready_for_review"
    assert scenario_lane.summary == "Generated risk-based scenarios."
    assert workspace.lane_writes == [
        ("proj_a", "US-A1"),
        ("proj_a", "US-A1"),
    ]


def test_asset_progress_updates_only_target_us_and_preserves_version_scope() -> None:
    workspace = InMemoryQualityAssetProgressWorkspace(
        us_items={
            "proj_a": [
                us_item("US-A1"),
                us_item("US-A2"),
            ]
        },
    )
    service = QualityAssetProgressApplicationService(workspace)

    service.touch_us(
        "proj_a",
        "US-A2",
        progress=65,
        status="case_generation",
        next_action="Review generated cases",
    )

    first, second = workspace.us_items["proj_a"]
    assert first.progress == 20
    assert second.progress == 65
    assert second.status == "case_generation"
    assert second.next_action == "Review generated cases"
    assert workspace.us_writes == [("proj_a", "US-A2")]
