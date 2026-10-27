from dataclasses import replace

import pytest

from apps.api.app.domain.system_image.build_plan import BuildPlanIntegrityError
from apps.api.app.domain.system_image.gap_ownership import (GapResponsibility, ownership_digest,
    ownership_view, report_gaps, validate_responsibilities)


def report():
    gap = {"code": "missing_requirement", "blocks": "business_acceptance", "reason": "No requirement source.",
        "required_action": "Add a reviewed requirement.", "owner_actor_id": None, "ownership_status": "unassigned"}
    return {"gaps": [gap, dict(gap), {**gap, "code": "gap_ownership_unassigned"}]}


def test_gap_inventory_uses_fixed_definitions_not_order_or_owner():
    first = report_gaps(report())
    assert len(first) == 1 and first[0]["gap_id"].startswith("gap_")
    changed = report()
    changed["gaps"].reverse()
    changed["gaps"][1]["owner_actor_id"] = "not-an-authority"
    assert report_gaps(changed) == first
    changed["gaps"][1]["reason"] = "Different actual missing evidence."
    assert len(report_gaps(changed)) == 2


@pytest.mark.parametrize("field,value", [("gap_id", "gap_fake"), ("owner_actor_id", ""),
    ("owner_actor_id", "bad\nowner"), ("reason", " "), ("reason", "x" * 1001)])
def test_responsibility_requires_exact_identity_and_justification(field, value):
    body = {"gap_id": report_gaps(report())[0]["gap_id"], "owner_actor_id": "owner", "reason": "Will investigate."}
    with pytest.raises(BuildPlanIntegrityError):
        GapResponsibility(**{**body, field: value})


@pytest.mark.parametrize("failure", ["missing", "duplicate", "extra"])
def test_full_responsibility_revision_cannot_omit_or_invent_gaps(failure):
    gaps = report_gaps(report())
    assignment = GapResponsibility(gaps[0]["gap_id"], "owner", "Will investigate.")
    values = () if failure == "missing" else (assignment, assignment) if failure == "duplicate" else (
        assignment, replace(assignment, gap_id="gap_" + "0" * 64))
    with pytest.raises(BuildPlanIntegrityError):
        validate_responsibilities(gaps, values)


def test_owner_availability_is_not_gap_resolution():
    gaps = report_gaps(report())
    assignment = GapResponsibility(gaps[0]["gap_id"], "owner", "Will investigate.")
    assert ownership_view(gaps, (), set())[0]["ownership_status"] == "unassigned"
    current = ownership_view(gaps, (assignment,), {"owner"})[0]
    assert current["ownership_status"] == "confirmed" and current["resolution_status"] == "unresolved"
    suspended = ownership_view(gaps, (assignment,), set())[0]
    assert suspended["owner_actor_id"] == "owner" and suspended["ownership_status"] == "owner_unavailable"


def test_revision_hash_fixes_actor_time_and_complete_request():
    original = ownership_digest({"assignments": []}, 1, "actor", "time")
    assert original != ownership_digest({"assignments": []}, 2, "actor", "time")
    assert original != ownership_digest({"assignments": []}, 1, "other", "time")
    assert original != ownership_digest({"assignments": ["changed"]}, 1, "actor", "time")
