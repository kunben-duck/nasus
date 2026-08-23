from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


UNASSIGNED_OWNER = "Unassigned"


class USParticipantItemLike(Protocol):
    """Minimal US work-item shape required by participant assignment policy."""

    id: str
    owner: str


@dataclass(frozen=True)
class USParticipantDecision:
    us_id: str
    owner: str


@dataclass(frozen=True)
class VersionParticipantDecision:
    item_decisions: list[USParticipantDecision]
    assigned_count: int


def owner_assignments_from_payload(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        return {str(key): str(value) for key, value in raw.items()}
    if isinstance(raw, list):
        owners: dict[str, str] = {}
        for item in raw:
            if isinstance(item, dict):
                us_id = str(item.get("us_id") or item.get("id") or "")
                owner = str(item.get("owner") or item.get("assignee") or "")
                if us_id and owner:
                    owners[us_id] = owner
        return owners
    return {}


def decide_us_participant(
    item: USParticipantItemLike,
    *,
    owner_by_us: dict[str, str],
    default_owner: str,
) -> USParticipantDecision:
    owner = owner_by_us.get(item.id) or default_owner or item.owner
    return USParticipantDecision(us_id=item.id, owner=owner or UNASSIGNED_OWNER)


def decide_version_participants(
    items: list[USParticipantItemLike],
    *,
    owner_by_us: dict[str, str],
    default_owner: str,
) -> VersionParticipantDecision:
    item_decisions = [
        decide_us_participant(item, owner_by_us=owner_by_us, default_owner=default_owner)
        for item in items
    ]
    return VersionParticipantDecision(
        item_decisions=item_decisions,
        assigned_count=len(item_decisions),
    )
