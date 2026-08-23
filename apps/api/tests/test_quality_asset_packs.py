from __future__ import annotations

from dataclasses import dataclass, field

from apps.api.app.application.platform.project_models import VersionSummary
from apps.api.app.application.quality_loop.asset_packs import (
    QualityAssetPackApplicationService,
)
from apps.api.app.application.quality_loop.quality_models import QualityAssetPack
from apps.api.app.application.system_image.system_image_models import TaskContext


@dataclass
class InMemoryQualityAssetPackWorkspace:
    packs: dict[str, QualityAssetPack] = field(default_factory=dict)
    writes: list[str] = field(default_factory=list)

    def get_quality_asset_pack(
        self,
        project_id: str,
        us_id: str,
    ) -> QualityAssetPack | None:
        pack = self.packs.get(f"qap_{project_id}_{us_id}")
        return pack.model_copy(deep=True) if pack is not None else None

    def save_quality_asset_pack(self, pack: QualityAssetPack) -> None:
        self.packs[pack.id] = pack.model_copy(deep=True)
        self.writes.append(pack.id)


@dataclass
class StubContextQueries:
    contexts: dict[tuple[str, str], TaskContext] = field(default_factory=dict)

    def current_task_context(
        self,
        project_id: str,
        us_id: str,
    ) -> TaskContext | None:
        return self.contexts.get((project_id, us_id))


def version_provider(project_id: str) -> VersionSummary:
    return VersionSummary(
        id=f"ver_{project_id}",
        name="2026.08",
        status="active",
        branch_name="version/2026.08",
        us_total=1,
        us_closed=0,
        pending_runs=0,
        pending_approvals=0,
    )


def context(project_id: str, us_id: str) -> TaskContext:
    return TaskContext(
        id=f"ctx_{project_id}_{us_id}",
        project_id=project_id,
        baseline_id=f"baseline_{project_id}",
        us_id=us_id,
        retrieval_run_id=f"retrieval_{us_id}",
        source_refs=["source:git", "source:us"],
        summary="Version-scoped system image context.",
        readiness="ready",
        freshness_at="2026-07-30T00:00:00+00:00",
        context_hash="context-hash",
    )


def test_asset_pack_upsert_persists_aggregate_and_revision_chain() -> None:
    workspace = InMemoryQualityAssetPackWorkspace()
    contexts = StubContextQueries(
        contexts={
            ("proj_a", "US-A1"): context("proj_a", "US-A1"),
        }
    )
    service = QualityAssetPackApplicationService(
        workspace,
        contexts,  # type: ignore[arg-type]
        version_provider,
    )

    first_refs = service.upsert_part(
        "proj_a",
        "US-A1",
        part_type="scenario_set",
        status="ready_for_review",
        title="Checkout scenarios",
        summary="Risk-based checkout scenarios.",
        object_refs=["us:US-A1"],
        evidence_refs=["evidence:scenario-1"],
    )
    second_refs = service.upsert_part(
        "proj_a",
        "US-A1",
        part_type="scenario_set",
        status="approved",
        title="Checkout scenarios",
        summary="Reviewed checkout scenarios.",
        object_refs=["us:US-A1"],
        evidence_refs=["evidence:scenario-2"],
    )

    pack = workspace.packs["qap_proj_a_US-A1"]
    assert pack.version_id == "ver_proj_a"
    assert pack.source_refs == ["source:git", "source:us"]
    assert pack.current_revision == 2
    assert len(pack.parts) == 1
    assert pack.parts[0].revision == 2
    assert pack.parts[0].status == "approved"
    assert pack.evidence_refs == ["evidence:scenario-2"]
    assert first_refs == [
        "quality_asset_pack:qap_proj_a_US-A1",
        "quality_asset_part:qap_proj_a_US-A1_scenario_set",
    ]
    assert second_refs == first_refs
    assert workspace.writes == [
        "qap_proj_a_US-A1",
        "qap_proj_a_US-A1",
    ]


def test_asset_pack_refresh_initializes_or_advances_existing_pack() -> None:
    workspace = InMemoryQualityAssetPackWorkspace()
    service = QualityAssetPackApplicationService(
        workspace,
        StubContextQueries(),  # type: ignore[arg-type]
        version_provider,
    )

    initialized, initialized_refs = service.refresh_pack("proj_b", "US-B1")
    refreshed, refreshed_refs = service.refresh_pack("proj_b", "US-B1")

    assert initialized is not None
    assert initialized.parts[0].part_type == "scope_pack"
    assert initialized_refs == [
        "quality_asset_pack:qap_proj_b_US-B1",
        "quality_asset_part:qap_proj_b_US-B1_scope_pack",
    ]
    assert refreshed is not None
    assert refreshed.current_revision == 2
    assert refreshed_refs == ["quality_asset_pack:qap_proj_b_US-B1"]
