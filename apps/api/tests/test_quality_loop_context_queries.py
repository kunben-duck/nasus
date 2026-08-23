from __future__ import annotations

from dataclasses import dataclass, field

from apps.api.app.application.quality_loop.context_queries import (
    QualityLoopContextQueryApplicationService,
)
from apps.api.app.application.quality_loop.quality_models import (
    AssetLane,
    QualityAssetPack,
    USItem,
)
from apps.api.app.application.system_image.system_image_models import (
    QualityProfile,
    TaskContext,
)


@dataclass
class InMemoryQualityLoopContextWorkspace:
    contexts: dict[str, list[TaskContext]] = field(default_factory=dict)
    profiles: dict[str, list[QualityProfile]] = field(default_factory=dict)
    packs: dict[str, QualityAssetPack] = field(default_factory=dict)
    us_items: dict[str, list[USItem]] = field(default_factory=dict)
    lanes: dict[str, list[AssetLane]] = field(default_factory=dict)

    def list_task_contexts(self, project_id: str) -> list[TaskContext]:
        return list(self.contexts.get(project_id, []))

    def list_quality_profiles(self, project_id: str) -> list[QualityProfile]:
        return list(self.profiles.get(project_id, []))

    def get_quality_asset_pack(
        self,
        project_id: str,
        us_id: str,
    ) -> QualityAssetPack | None:
        return self.packs.get(f"qap_{project_id}_{us_id}")

    def list_quality_asset_packs(self, project_id: str) -> list[QualityAssetPack]:
        return [
            pack
            for pack in self.packs.values()
            if pack.project_id == project_id
        ]

    def list_us_items(self, project_id: str) -> list[USItem]:
        return list(self.us_items.get(project_id, []))

    def project_id_for_us(self, us_id: str) -> str | None:
        for project_id, items in self.us_items.items():
            if any(item.id == us_id for item in items):
                return project_id
        return None

    def list_asset_lanes(self, us_id: str) -> list[AssetLane]:
        return list(self.lanes.get(us_id, []))


def test_context_queries_resolve_current_facts_and_planner_state() -> None:
    workspace = InMemoryQualityLoopContextWorkspace()
    project_id = "proj_context"
    us_id = "US-301"
    workspace.contexts[project_id] = [
        TaskContext(
            id="ctx_301",
            project_id=project_id,
            baseline_id="baseline_1",
            us_id=us_id,
            retrieval_run_id="retrieval_1",
            summary="Checkout context",
            readiness="ready",
            freshness_at="2026-07-30T00:00:00+00:00",
            context_hash="context-hash",
        )
    ]
    workspace.profiles[project_id] = [
        QualityProfile(
            id="profile_301",
            project_id=project_id,
            baseline_id="baseline_1",
            us_id=us_id,
            task_context_id="ctx_301",
            risk_score=70,
            coverage_score=60,
            release_score=55,
            automation_feasibility=80,
            freshness_at="2026-07-30T00:00:00+00:00",
        )
    ]
    workspace.packs[f"qap_{project_id}_{us_id}"] = QualityAssetPack(
        id=f"qap_{project_id}_{us_id}",
        project_id=project_id,
        us_id=us_id,
        updated_at="2026-07-30T00:00:00+00:00",
    )
    workspace.us_items[project_id] = [
        USItem(
            id=us_id,
            title="Confirm checkout",
            owner="QA",
            status="analysis",
            risk="high",
            progress=35,
            next_action="Generate scenarios",
        )
    ]
    workspace.lanes[us_id] = [
        AssetLane(
            id="lane_scenario",
            label="Scenario Set",
            status="ready_for_review",
            summary="Scenarios generated",
            updated_at="2026-07-30T00:00:00+00:00",
        ),
        AssetLane(
            id="lane_case",
            label="Case Set",
            status="draft",
            summary="Cases pending",
            updated_at="2026-07-30T00:00:00+00:00",
        ),
    ]
    service = QualityLoopContextQueryApplicationService(workspace)

    assert service.current_task_context(project_id, us_id).id == "ctx_301"
    assert service.current_quality_profile(project_id, us_id).id == "profile_301"
    assert service.current_quality_asset_pack(project_id, us_id).id == (
        f"qap_{project_id}_{us_id}"
    )
    assert service.planner_quality_state(None, us_id) == {
        "project_id": project_id,
        "us_id": us_id,
        "scenarios": "ready_for_review",
        "cases": "draft",
    }


def test_planner_state_selects_first_us_when_only_project_is_known() -> None:
    workspace = InMemoryQualityLoopContextWorkspace(
        us_items={
            "proj_first": [
                USItem(
                    id="US-FIRST",
                    title="First",
                    owner="QA",
                    status="draft",
                    risk="low",
                    progress=0,
                    next_action="Start",
                )
            ]
        }
    )

    state = QualityLoopContextQueryApplicationService(
        workspace
    ).planner_quality_state("proj_first", None)

    assert state == {
        "project_id": "proj_first",
        "us_id": "US-FIRST",
    }
