from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Protocol

from .source_binding import slugify_project_name


PRIMARY_US_OBJECT_TYPE = "USWorkItem"
FALLBACK_US_OBJECT_TYPES = {"Feature", "RequirementSection", "RequirementDocument"}
DEFAULT_US_OWNER = "Nasus Agent"
DEFAULT_US_STATUS = "analysis"
DEFAULT_US_RISK = "medium"
DEFAULT_US_PROGRESS = 18
DEFAULT_US_NEXT_ACTION = "Generate scenarios"


class KnowledgeObjectLike(Protocol):
    name: str
    type: str


@dataclass(frozen=True)
class USWorkItemDecision:
    id: str
    title: str
    owner: str = DEFAULT_US_OWNER
    status: str = DEFAULT_US_STATUS
    risk: str = DEFAULT_US_RISK
    progress: int = DEFAULT_US_PROGRESS
    next_action: str = DEFAULT_US_NEXT_ACTION


@dataclass(frozen=True)
class AssetLaneDecision:
    id: str
    label: str
    status: str
    summary: str


def derive_us_work_items_from_context(
    objects: Iterable[KnowledgeObjectLike],
    *,
    project_id: str,
    limit: int = 8,
) -> list[USWorkItemDecision]:
    object_list = list(objects)
    us_objects = [item for item in object_list if item.type == PRIMARY_US_OBJECT_TYPE]
    if not us_objects:
        us_objects = [item for item in object_list if item.type in FALLBACK_US_OBJECT_TYPES]

    decisions: list[USWorkItemDecision] = []
    for index, item in enumerate(us_objects[:limit], start=1):
        us_code = _us_code_from_name(item.name, index)
        decisions.append(
            USWorkItemDecision(
                id=f"us_{slugify_project_name(us_code)}_{project_id[-6:]}",
                title=item.name[:96],
            )
        )
    return decisions


def default_asset_lanes_for_us(us_id: str) -> list[AssetLaneDecision]:
    return [
        AssetLaneDecision(
            id=f"{us_id}_lane_scenarios",
            label="Scenarios",
            status="not_started",
            summary="Waiting for scenario generation from system image, US, and test evidence.",
        ),
        AssetLaneDecision(
            id=f"{us_id}_lane_cases",
            label="Cases",
            status="not_started",
            summary="Waiting for approved scenario structure.",
        ),
        AssetLaneDecision(
            id=f"{us_id}_lane_automation",
            label="Automation",
            status="not_started",
            summary="Waiting for reviewed cases before script generation.",
        ),
        AssetLaneDecision(
            id=f"{us_id}_lane_release",
            label="Release Assessment",
            status="not_started",
            summary="Waiting for execution evidence and quality scoring.",
        ),
    ]


def _us_code_from_name(name: str, index: int) -> str:
    us_id_match = re.search(r"\bUS[-_ ]?(\d+)\b", name, re.IGNORECASE)
    return f"US-{us_id_match.group(1)}" if us_id_match else f"US-{index:03d}"
