from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol


class QualityAssetPartLike(Protocol):
    part_type: str
    status: str
    revision: int
    evidence_refs: list[str]


@dataclass(frozen=True)
class AssetLaneTemplate:
    lane_key: str
    label: str
    summary: str
    status: str = "not_started"

    def lane_id(self, us_id: str) -> str:
        return f"{us_id}_lane_{self.lane_key}"


DEFAULT_ASSET_LANE_TEMPLATES: tuple[AssetLaneTemplate, ...] = (
    AssetLaneTemplate(
        lane_key="scenarios",
        label="Scenarios",
        summary="Waiting for scenario generation from system image, US, and test evidence.",
    ),
    AssetLaneTemplate(
        lane_key="verification",
        label="Verification Plan",
        summary="Waiting for approved scenario coverage and execution planning.",
    ),
    AssetLaneTemplate(
        lane_key="cases",
        label="Cases",
        summary="Waiting for an approved verification plan.",
    ),
    AssetLaneTemplate(
        lane_key="automation",
        label="Automation",
        summary="Waiting for reviewed cases before script generation.",
    ),
    AssetLaneTemplate(
        lane_key="change_document",
        label="Change Document",
        summary="Waiting for quality assets and execution evidence to summarize the change.",
    ),
    AssetLaneTemplate(
        lane_key="release",
        label="Release Assessment",
        summary="Waiting for execution evidence, the change document, and quality scoring.",
    ),
)

QUALITY_ASSET_REVIEW_STATUSES = frozenset({"ready_for_review", "approved", "completed"})


def default_asset_lane_templates() -> tuple[AssetLaneTemplate, ...]:
    return DEFAULT_ASSET_LANE_TEMPLATES


def asset_lane_id(us_id: str, lane_key: str) -> str:
    return f"{us_id}_lane_{lane_key}"


def asset_lane_label_key(lane_key: str) -> str:
    return {
        "scenarios": "scenarios",
        "cases": "cases",
        "verification": "verification plan",
        "automation": "automation",
        "release": "release assessment",
        "change_document": "change document",
    }[lane_key]


def matches_asset_lane(*, lane_id: str, label: str, lane_key: str) -> bool:
    expected_suffix = f"lane_{lane_key}"
    return (
        lane_id == expected_suffix
        or lane_id.endswith(f"_{expected_suffix}")
        or label.strip().lower() == asset_lane_label_key(lane_key)
    )


def next_quality_asset_part_revision(parts: Iterable[QualityAssetPartLike], part_type: str) -> int:
    previous = next((part for part in parts if part.part_type == part_type), None)
    return (previous.revision + 1) if previous else 1


def quality_asset_pack_status(parts: Iterable[QualityAssetPartLike]) -> str:
    part_list = list(parts)
    part_statuses = {item.part_type: item.status for item in part_list}
    if part_statuses.get("release_assessment") == "completed":
        return "completed"
    if any(item.status in QUALITY_ASSET_REVIEW_STATUSES for item in part_list):
        return "in_review"
    return "draft"


def quality_asset_pack_current_revision(parts: Iterable[QualityAssetPartLike]) -> int:
    revisions = [part.revision for part in parts]
    return max(revisions) if revisions else 1


def quality_asset_pack_evidence_refs(parts: Iterable[QualityAssetPartLike]) -> list[str]:
    return sorted({ref for part in parts for ref in part.evidence_refs})
