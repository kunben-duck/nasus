"""Recovered native batches enter independent review, never target execution."""
import asyncio
from copy import deepcopy

import pytest
from sqlalchemy import select

from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, LLMCallRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.test_design_mapping_models import TestDesignMappingRecord as Mapping
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_generation_batch_recovery_jobs_api import failed_batches, formal_batches
from apps.api.tests.test_generation_batch_results_api import aggregate, ledger, execution, design_scope, publication, documents, evidence_api, read
from apps.api.tests.test_generation_execution_api import queued, job, command
from apps.api.tests.test_semantic_evaluations_api import completed, invoke, count
from apps.api.tests.test_source_access_api import grant_member
from apps.api.tests.test_test_design_mapping_api import reviews, submit, inspect
from apps.api.app.application.quality_loop.generation_job_ports import GENERATION_RECOVER_TOOL
from apps.api.app.domain.quality_loop.test_design_mapping import MAPPING_TOOL


@pytest.fixture
def recovered_review(failed_batches, monkeypatch):
    v = failed_batches
    ident = queued(v, GENERATION_RECOVER_TOOL, v["complete_recovery"])
    assert asyncio.run(v["jobs"].run(ident)) == "completed"
    value = read(v, {"generation_id": job(v, ident)["generation_id"]}).json()
    metadata = value["metadata"]
    assert metadata["schema"] == "nasus.test-design-result.v4"
    assert metadata["recovery_invocation_id"] == ident and len(metadata["call_ids"]) == 3
    v.update(recovery_invocation_id=ident, original_result=value, generation_metadata=metadata,
        mapping_url=f"/v1/projects/{v['project_id']}/quality/test-design-results/{metadata['generation_id']}/mapping-review",
        mapping_request=dict(project_id=v["project_id"], generation_id=metadata["generation_id"],
            generation_artifact_hash=metadata["artifact_hash"], expected_previous_revision_id=None, decision="review",
            mappings=reviews(value["result"]["proposal"]), reason="Independent recovered v4 review, not target pass"))
    grant_member(v)
    role_url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(role_url, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    conversation = v["client"].post("/v1/conversations", headers=v["member_headers"],
        json={"space_type": "project", "space_id": v["project_id"]})
    assert conversation.status_code == 200, conversation.text
    previous = v["conversation"]
    v["conversation"] = conversation

    def no_model(*args, **kwargs):
        raise AssertionError("Independent review must not resolve a model or resend a native request")
    monkeypatch.setattr(v["executor"].profiles, "resolve", no_model)
    monkeypatch.setattr(v["batch_executor"].provider, "generate", no_model)
    try:
        yield v
    finally:
        v["conversation"] = previous


def assert_preserved(v, original, calls_before):
    assert read(v, v["generation_metadata"], headers=v["member_headers"]).json() == original
    assert command(v, v["failed_source"]).json()["status"] == "failed"
    assert command(v, v["recovery_invocation_id"]).json()["status"] == "completed"
    assert count(v, LLMCallRecord) == calls_before
    assert len(v["batch_native_sent"]) == 3 and not v["native_calls"]


@pytest.mark.parametrize("documents", [3], indirect=True)
def test_three_batch_recovery_supports_independent_qa_mapping_without_new_egress(recovered_review):
    v = recovered_review
    original, calls_before = v["original_result"], count(v, LLMCallRecord)
    listing = v["client"].get(f"/v1/projects/{v['project_id']}/quality/test-design-review-drafts", headers=v["member_headers"])
    assert listing.status_code == 200 and listing.json()["items"][0]["metadata"] == v["generation_metadata"]
    pending = invoke(v, MAPPING_TOOL, v["mapping_request"], headers=v["member_headers"]).json()
    assert pending["status"] == "waiting_confirmation" and count(v, Mapping) == 0
    reviewed = completed(v["client"].post(f"/v1/tool-invocations/{pending['id']}/confirm", headers=v["member_headers"]))
    response = inspect(v, v["member_headers"])
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store", response.text
    head = response.json()["head"]
    assert head["revision"]["authority_actor"] == v["member"]["id"]
    assert head["revision"]["invocation_id"] == reviewed["id"] != v["recovery_invocation_id"]
    assert head["generation_pin"]["context_pin"] == original["result"]["context_pin"]
    assert head["generation_pin"]["scope_pin"] == original["result"]["scope_pin"]
    coverage = head["assessment"]["coverage"]
    assert coverage["assertion_mapped_count"] == original["result"]["proposal"]["coverage"]["obligation_denominator"]
    assert coverage["automated_count"] == coverage["executed_on_target_count"] == coverage["passed_count"] == 0
    assert head["current_use"]["mapping_complete"] and not head["current_use"]["execution_authorized"]
    assert "artifact_ref" not in response.text and "native-test-design-fixture-key" not in response.text
    with session_scope() as session:
        audit = session.scalars(select(AuditEventRecord).where(AuditEventRecord.tool_invocation_id == reviewed["id"],
            AuditEventRecord.entity_id == head["revision"]["revision_id"], AuditEventRecord.action == "quality.test_design_mapping.reviewed")).all()
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == head["revision"]["revision_id"])).all()
        assert len(audit) == len(events) == 1
    assert count(v, Mapping) == 1
    assert_preserved(v, original, calls_before)


@pytest.mark.parametrize("documents", [3], indirect=True)
def test_recovered_mapping_rejects_oracle_changes_and_outbox_failure_preserves_draft(recovered_review, monkeypatch):
    v = recovered_review
    original, calls_before = v["original_result"], count(v, LLMCallRecord)
    changed = deepcopy(v["mapping_request"])
    changed["mappings"][0]["oracle_digest"] = "sha256:" + "0" * 64
    assert submit(v, changed, headers=v["member_headers"]).json()["status"] == "failed"
    assert count(v, Mapping) == 0 and inspect(v, v["member_headers"]).json()["head"] is None
    original_append = EventOutboxRepository.append
    with monkeypatch.context() as fault:
        def fail(self, event, **kwargs):
            if event.event_type == "quality.test_design_mapping.reviewed":
                raise RuntimeError("explicit recovered mapping outbox fixture")
            return original_append(self, event, **kwargs)
        fault.setattr(EventOutboxRepository, "append", fail)
        response = submit(v, headers=v["member_headers"])
        assert response.status_code == 200 and response.json()["status"] == "failed", response.text
    assert count(v, Mapping) == 0
    with session_scope() as session:
        assert not session.scalars(select(AuditEventRecord).where(AuditEventRecord.tool_invocation_id == response.json()["id"],
            AuditEventRecord.action == "quality.test_design_mapping.reviewed")).all()
        assert not session.scalars(select(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.event_payload["correlation_id"].as_string() == v["project_id"],
            SSEEventOutboxRecord.event_type == "quality.test_design_mapping.reviewed")).all()
    completed(submit(v, headers=v["member_headers"]))
    assert count(v, Mapping) == 1 and inspect(v, v["member_headers"]).json()["head"]["current_use"]["mapping_complete"]
    assert_preserved(v, original, calls_before)
