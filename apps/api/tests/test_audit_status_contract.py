"""Audit states describe recorded facts; they do not grant execution authority."""
import pytest
from pydantic import ValidationError

from apps.api.app.application.platform.tool_models import AuditEvent


FACT_STATES = ("reviewed", "prepared", "build_attested", "recorded", "issued", "reserved",
    "passed", "error", "timed_out")


@pytest.mark.parametrize("status", FACT_STATES)
def test_domain_fact_audit_status_round_trips_without_rewriting_history(status):
    payload = dict(id="audit:contract", occurred_at="2026-10-12T00:00:00+00:00",
        actor="user:contract", actor_kind="user", action="quality.original_fact.recorded",
        entity_type="quality_fact", entity_id="fact:contract", status=status,
        summary="Recorded original fact, not an execution grant.",
        metadata={"execution_authorized": False, "business_coverage_verified": False})
    event = AuditEvent.model_validate(payload)
    assert event.model_dump(mode="json")["status"] == status
    assert AuditEvent.model_validate(event.model_dump(mode="json")) == event
    assert event.metadata == payload["metadata"]


@pytest.mark.parametrize("status", ["executed_and_approved", "unknown", True, 1, None])
def test_unknown_or_untyped_audit_status_is_not_silently_coerced(status):
    with pytest.raises(ValidationError):
        AuditEvent(id="audit:contract", occurred_at="2026-10-12T00:00:00+00:00",
            actor="user:contract", action="quality.original_fact.recorded",
            entity_type="quality_fact", entity_id="fact:contract", status=status, summary="Invalid")
