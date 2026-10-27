"""Confirmed responsibilities for fixed gaps, never gap resolution or authority."""
from dataclasses import dataclass

from .build_plan import BuildPlanIntegrityError
from .source_snapshots import snapshot_digest


OWNERSHIP_SCHEMA = "nasus.image-build-gap-ownership.v1"
GAP_FIELDS = ("code", "blocks", "reason", "required_action")


def report_gaps(report):
    gaps = {}
    for gap in report["gaps"]:
        # This is a derived governance notice, not another task to own.
        if gap["code"] == "gap_ownership_unassigned":
            continue
        value = {key: gap[key] for key in GAP_FIELDS}
        if any(type(item) is not str or not item.strip() for item in value.values()):
            raise BuildPlanIntegrityError("Gap responsibilities require complete fixed gap definitions.")
        ident = "gap_" + snapshot_digest(value)[7:]
        gaps[ident] = value
    if not 1 <= len(gaps) <= 96:
        raise BuildPlanIntegrityError("Gap responsibility inventory is empty or exceeds its complete bound.")
    return tuple({"gap_id": key, **gaps[key]} for key in sorted(gaps))


@dataclass(frozen=True)
class GapResponsibility:
    gap_id: str
    owner_actor_id: str
    reason: str

    def __post_init__(self):
        if (type(self.gap_id) is not str or len(self.gap_id) != 68 or not self.gap_id.startswith("gap_")
                or any(char not in "0123456789abcdef" for char in self.gap_id[4:])
                or type(self.owner_actor_id) is not str or not 1 <= len(self.owner_actor_id) <= 128
                or any(ord(char) < 32 for char in self.owner_actor_id)
                or type(self.reason) is not str or not self.reason.strip() or len(self.reason) > 1000):
            raise BuildPlanIntegrityError("Invalid gap responsibility identity or justification.")


def validate_responsibilities(gaps, responsibilities):
    ids = [item.gap_id for item in responsibilities]
    if len(ids) != len(set(ids)) or set(ids) != {item["gap_id"] for item in gaps}:
        raise BuildPlanIntegrityError("Responsibility revision must account for every fixed gap exactly once.")
    return tuple(sorted(responsibilities, key=lambda item: item.gap_id))


def ownership_digest(request, number, actor_id, created_at):
    return snapshot_digest({"schema": OWNERSHIP_SCHEMA, "request": request,
        "revision_number": number, "confirmed_by": actor_id, "created_at": created_at})


def ownership_view(gaps, assignments, eligible):
    by_id = {item.gap_id: item for item in assignments}
    return [{**gap, "owner_actor_id": by_id[gap["gap_id"]].owner_actor_id if gap["gap_id"] in by_id else None,
        "ownership_status": ("confirmed" if by_id[gap["gap_id"]].owner_actor_id in eligible else "owner_unavailable")
            if gap["gap_id"] in by_id else "unassigned",
        "resolution_status": "unresolved"} for gap in gaps]
