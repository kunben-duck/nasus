"""Actual isolated PG/canonical final authority; all model/source content is fixture data."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.mapping_finalization_inputs import MappingFinalizeInput
from apps.api.app.domain.quality_loop.mapping_part_sets import FINALIZE_TOOL
from apps.api.app.domain.quality_loop.test_design_mapping import MAPPING_QUERY_TOOL, TestDesignMappingChanged, TestDesignMappingIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessRule, SourceAccessDenied
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, AuditEventRecord, SSEEventOutboxRecord, LLMCallRecord
from apps.api.app.infrastructure.persistence.test_design_mapping_models import TestDesignMappingRecord as Record
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_mapping_part_staging_api import staging, mapping, generation_result, design_scope, publication, documents, evidence_api
from apps.api.tests.test_mapping_part_staging_api import submit as stage_submit, read as read_part
from apps.api.tests.test_test_design_mapping_api import invoke, completed, count, inspect, submit as v1_submit, grant_member
from apps.api.tests.test_test_design_results_api import read_result


def preview(v, headers=None):
    return v["client"].get(v["mapping_url"].removesuffix("/mapping-review") + "/mapping-finalization",
        headers=headers or v["headers"], params={"artifact_hash": v["generation_metadata"]["artifact_hash"],
            "plan_digest": v["stage_request"]["plan_digest"]})


def request(v):
    response = preview(v)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["ready_for_confirmation"] and not value["review_authorized"] and not value["execution_authorized"]
    return {**{key: value[key] for key in ("project_id", "generation_id", "generation_artifact_hash", "plan_digest", "expected_previous_revision_id")},
        "part_set_digest": value["part_set"]["part_set_digest"], "reason": "Independent final fixture confirmation"}


def submit(v, payload):
    pending = invoke(v, FINALIZE_TOOL, payload, key=uuid4().hex)
    if pending.status_code != 200 or pending.json()["status"] != "waiting_confirmation":
        return pending
    return v["client"].post(f"/v1/tool-invocations/{pending.json()['id']}/confirm", headers=v["headers"])


def seed(v, payload, **changes):
    parsed, ident = MappingFinalizeInput.model_validate(payload), uuid4().hex
    with session_scope() as session:
        session.add(ToolInvocationRecord(id=ident, tool_id=FINALIZE_TOOL, status="running", summary="Explicit final-authority race fixture",
            conversation_id=v["conversation"].json()["id"], input_payload={**parsed.model_dump(mode="json"),
                "confirmed_by_user": True, "confirmed_actor_id": v["owner"]["id"],
                "confirmed_at": datetime.now(timezone.utc).isoformat(), **changes}))
    return parsed, ident


def finalize(v, parsed, ident):
    with actor_scope(UserProfile.model_validate(v["owner"])):
        return v["mapping_service"].finalize(parsed, invocation_id=ident, recorded_at=datetime.now(timezone.utc).isoformat())


def test_complete_set_requires_separate_canonical_confirmation_and_v1_withdrawal_remains_compatible(staging):
    v = staging
    initial = preview(v)
    assert initial.status_code == 200 and initial.headers["cache-control"] == "private, no-store", initial.text
    assert initial.json()["saved_part_count"] == 0 and not initial.json()["ready_for_confirmation"]
    calls = count(v, LLMCallRecord)
    staged = completed(stage_submit(v))
    part_id = staged["result"]["object_refs"][0].split(":", 1)[1]
    payload = request(v)
    assert "mappings" not in payload and "members" not in payload
    pending = invoke(v, FINALIZE_TOOL, {**payload, "confirmed_by_user": True}, key=uuid4().hex)
    assert pending.json()["status"] == "waiting_confirmation" and count(v, Record) == 0
    command = completed(v["client"].post(f"/v1/tool-invocations/{pending.json()['id']}/confirm", headers=v["headers"]))
    value = inspect(v)
    assert value.status_code == 200, value.text
    head = value.json()["head"]
    assert head["revision"]["mapping_schema"] == "nasus.test-design-mapping-review.v2" and head["part_set"]["part_count"] == 1
    assert head["current_use"]["mapping_current"] and head["current_use"]["mapping_complete"]
    assert head["assessment"]["coverage"]["executed_on_target_count"] == head["assessment"]["coverage"]["passed_count"] == 0
    assert not head["current_use"]["execution_authorized"]
    assert head["part_set"]["members"][0]["part_revision_id"] == part_id
    assert set(head["part_set"]["members"][0]) == {"sequence", "part_revision_id", "artifact_hash", "request_hash", "part_digest"}
    assert read_result(v, v["generation_metadata"]).json() == v["original_result"] and count(v, LLMCallRecord) == calls
    assert not read_part(v, part_id).json()["current_use"]["part_current"]
    receipt = completed(invoke(v, MAPPING_QUERY_TOOL, {key: payload[key] for key in (
        "project_id", "generation_id", "generation_artifact_hash")}, key=uuid4().hex))["result"]["test_design_mapping"]
    assert receipt["schema_version"] == "nasus.test-design-mapping-receipt.v2" and receipt["mapping_current"]
    with session_scope() as session:
        audits = session.scalars(select(AuditEventRecord).where(AuditEventRecord.tool_invocation_id == command["id"],
            AuditEventRecord.action == "quality.test_design_mapping.reviewed")).all()
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == head["revision"]["revision_id"])).all()
        assert len(audits) == len(events) == 1 and "decisions" not in str(events[0].event_payload)
    grant_member(v)
    promoted = v["client"].put(f"/v1/projects/{v['project_id']}/members/{v['member']['id']}", headers=v["headers"], json={"role": "qa_lead"})
    assert promoted.status_code == 200, promoted.text
    public = inspect(v, headers=v["member_headers"])
    assert public.status_code == 200 and public.json()["head"]["assessment"] == head["assessment"], public.text
    assert read_part(v, part_id, headers=v["member_headers"]).status_code == 403
    withdrawn = completed(v1_submit(v, {**v["mapping_request"], "expected_previous_revision_id": head["revision"]["revision_id"],
        "decision": "withdraw", "mappings": None}))
    assert withdrawn["result"]["object_refs"]
    history = inspect(v).json()
    assert len(history["history"]) == 2 and history["head"]["revision"]["status"] == "withdrawn"
    old = v["client"].get(f"/v1/projects/{v['project_id']}/quality/test-design-mapping-reviews/{head['revision']['revision_id']}", headers=v["headers"])
    assert old.status_code == 200 and old.json()["assessment"] == head["assessment"] and not old.json()["current_use"]["mapping_current"]


def test_edit_after_preview_or_in_confirmation_window_cannot_approve_a_different_part_set(staging, monkeypatch):
    v = staging
    first = completed(stage_submit(v))
    first_id = first["result"]["object_refs"][0].split(":", 1)[1]
    payload = request(v)
    edited = deepcopy(v["stage_request"])
    edited["expected_previous_part_revision_id"] = first_id
    edited["decisions"][0].update(decision="reject", reason="Independent changed fixture decision")
    completed(stage_submit(v, edited))
    rejected = submit(v, payload)
    assert rejected.json()["status"] == "failed" and rejected.json()["result"]["requires_followup"]
    assert count(v, Record) == 0
    payload = request(v)
    parsed, ident = seed(v, payload)
    original = v["mapping_service"].artifacts.put

    def mutate(project_id, body):
        saved = original(project_id, body)
        head_id = v["client"].get(v["mapping_url"].removesuffix("/mapping-review") + "/mapping-parts/0/staged", headers=v["headers"],
            params={"artifact_hash": payload["generation_artifact_hash"], "plan_digest": payload["plan_digest"]}).json()["head"]["part_revision_id"]
        next_part = deepcopy(edited)
        next_part["expected_previous_part_revision_id"] = head_id
        next_part["decisions"][-1].update(decision="defer", reason="Changed after final artifact write fixture")
        completed(stage_submit(v, next_part))
        return saved

    monkeypatch.setattr(v["mapping_service"].artifacts, "put", mutate)
    with pytest.raises(TestDesignMappingChanged):
        finalize(v, parsed, ident)
    assert count(v, Record) == 0


def test_atomic_finalization_rolls_back_on_outbox_failure_then_recovers_exact_original(staging, monkeypatch):
    v = staging
    completed(stage_submit(v))
    parsed, ident = seed(v, request(v))
    original = EventOutboxRepository.append

    def fail(*args, **kwargs):
        raise RuntimeError("Explicit final mapping outbox fault fixture")

    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    with pytest.raises(RuntimeError):
        finalize(v, parsed, ident)
    assert count(v, Record) == 0
    with session_scope() as session:
        assert not session.scalars(select(AuditEventRecord).where(AuditEventRecord.tool_invocation_id == ident)).all()
    monkeypatch.setattr(EventOutboxRepository, "append", original)
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(lambda _: finalize(v, parsed, ident), range(2)))
    assert values[0] == values[1] and count(v, Record) == 1
    with session_scope() as session:
        command = session.get(ToolInvocationRecord, ident)
        command.status = "failed"
        command.input_payload = {**command.input_payload, "confirmed_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}
    assert finalize(v, parsed, ident) == values[0]
    with session_scope() as session:
        assert session.get(ToolInvocationRecord, ident).status == "failed"


def test_finalization_rechecks_source_acl_after_artifact_write_and_before_approval(staging, monkeypatch):
    v = staging
    grant_member(v)
    promoted = v["client"].put(f"/v1/projects/{v['project_id']}/members/{v['member']['id']}",
        headers=v["headers"], json={"role": "qa_lead"})
    assert promoted.status_code == 200, promoted.text
    conversation = v["client"].post("/v1/conversations", headers=v["member_headers"],
        json={"space_type": "project", "space_id": v["project_id"]})
    assert conversation.status_code == 200, conversation.text
    reviewer = {**v, "headers": v["member_headers"], "owner": v["member"], "conversation": conversation}
    completed(stage_submit(reviewer))
    parsed, ident = seed(reviewer, request(reviewer))
    original = v["mapping_service"].artifacts.put

    def revoke(project_id, body):
        saved = original(project_id, body)
        repository = SourceAccessRepository()
        snapshot = repository.load_snapshot(project_id)
        repository.set_policy(project_id, v["evidence"]["binding_id"], SourceAccessRule("restricted"),
            expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id=uuid4().hex)
        return saved

    monkeypatch.setattr(v["mapping_service"].artifacts, "put", revoke)
    with pytest.raises(SourceAccessDenied, match="candidate inputs"):
        finalize(reviewer, parsed, ident)
    assert count(v, Record) == 0 and inspect(reviewer).status_code == 403
    assert inspect(v).status_code == 200
    with session_scope() as session:
        assert not session.scalars(select(AuditEventRecord).where(AuditEventRecord.tool_invocation_id == ident)).all()


@pytest.mark.parametrize("fault", ["actor", "expired", "cancelled"])
def test_final_set_rejects_invalid_confirmation_or_cancelled_command(staging, fault):
    v = staging
    completed(stage_submit(v))
    changes = {"actor": {"confirmed_actor_id": "forged-final-reviewer"},
        "expired": {"confirmed_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}, "cancelled": {}}[fault]
    parsed, ident = seed(v, request(v), **changes)
    if fault == "cancelled":
        with session_scope() as session:
            session.get(ToolInvocationRecord, ident).status = "cancelled"
    with pytest.raises(TestDesignMappingIntegrityError):
        finalize(v, parsed, ident)
    assert count(v, Record) == 0


def test_final_mapping_and_every_original_part_roundtrip_through_private_minio(staging, monkeypatch, tmp_path):
    import os
    import boto3
    from apps.api.app.infrastructure.storage.mapping_part_artifacts import MappingPartArtifacts
    from apps.api.app.infrastructure.storage.test_design_mapping_artifacts import TestDesignMappingArtifacts
    from apps.api.app.infrastructure.storage.object_storage import ObjectStorage, ObjectStorageConfig

    if not os.getenv("EXWEB_MINIO_ENDPOINT"):
        pytest.skip("explicit MinIO opt-in required")
    written = set()

    class RecordingStorage(ObjectStorage):
        def put_bytes(self, *args, **kwargs):
            value = super().put_bytes(*args, **kwargs)
            written.add(value.key)
            return value

    config = ObjectStorageConfig(os.environ["EXWEB_MINIO_ENDPOINT"], os.environ["EXWEB_MINIO_BUCKET"],
        os.environ["EXWEB_MINIO_ACCESS_KEY"], os.environ["EXWEB_MINIO_SECRET_KEY"], "us-east-1", tmp_path)
    storage, v = RecordingStorage(config), staging
    final_artifacts = TestDesignMappingArtifacts(storage)
    monkeypatch.setattr(v["stage_service"], "artifacts", MappingPartArtifacts(storage))
    monkeypatch.setattr(v["mapping_service"], "artifacts", final_artifacts)
    monkeypatch.setattr(v["mapping_service"].partitioned, "artifacts", final_artifacts)
    try:
        completed(stage_submit(v))
        command = completed(submit(v, request(v)))
        revision_id = command["result"]["object_refs"][0].split(":", 1)[1]
        metadata, ref = v["mapping_service"].repository.get(v["project_id"], revision_id)
        assert ref.startswith("s3://")
        body = final_artifacts.read(v["project_id"], ref, metadata["artifact_hash"])
        assert body["schema"] == "nasus.test-design-mapping-review.v2" and len(body["part_set"]["members"]) == 1
        archived = inspect(v)
        assert archived.status_code == 200 and archived.json()["head"]["assessment"] == body["assessment"], archived.text
        assert archived.json()["head"]["current_use"]["mapping_complete"] and len(written) == 2
        assert read_result(v, v["generation_metadata"]).json() == v["original_result"]
    finally:
        client = boto3.client("s3", endpoint_url=config.endpoint, aws_access_key_id=config.access_key, aws_secret_access_key=config.secret_key)
        if written:
            cleanup = client.delete_objects(Bucket=config.bucket, Delete={"Objects": [{"Key": key} for key in written]})
            assert not cleanup.get("Errors")
