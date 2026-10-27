"""Actual isolated PG/canonical writes; source/model content is explicit fixture data."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select, delete, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.mapping_part_inputs import MappingPartStageInput, STAGE_PART_TOOL
from apps.api.app.domain.quality_loop.test_design_mapping import TestDesignMappingChanged, TestDesignMappingIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.mapping_part_models import MappingPartRevisionRecord as PartRecord
from apps.api.app.infrastructure.persistence.test_design_mapping_models import TestDesignMappingRecord
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, SSEEventOutboxRecord, ToolInvocationRecord, LLMCallRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_test_design_mapping_api import (
    mapping, generation_result, design_scope, publication, documents, evidence_api,
    count, invoke, completed, submit as final_v1_review, grant_member,
)
from apps.api.tests.test_test_design_results_api import read_result


@pytest.fixture
def staging(mapping):
    v = mapping
    prefix = v["mapping_url"].removesuffix("/mapping-review")
    params = {"artifact_hash": v["generation_metadata"]["artifact_hash"]}
    plan_response = v["client"].get(prefix + "/mapping-plan", headers=v["headers"], params=params)
    assert plan_response.status_code == 200, plan_response.text
    plan = plan_response.json()["plan"]
    page_response = v["client"].get(prefix + "/mapping-parts/0", headers=v["headers"],
        params={**params, "plan_digest": plan["plan_digest"]})
    assert page_response.status_code == 200, page_response.text
    part = page_response.json()["part"]
    by_pair = {(value["case_id"], value["row_id"]): value for value in v["mapping_request"]["mappings"]}
    request = {**{key: v["mapping_request"][key] for key in ("project_id", "generation_id", "generation_artifact_hash")},
        "plan_digest": plan["plan_digest"], "expected_previous_revision_id": plan["expected_previous_revision_id"],
        "sequence": 0, "part_digest": part["part_digest"], "expected_previous_part_revision_id": None,
        "decisions": [deepcopy(by_pair[(pair["case_id"], pair["row_id"])]) for pair in part["assertions"]]}
    v.update(stage_request=request, stage_service=app.state.container.test_design_mapping_parts)
    return v


def submit(v, request=None, headers=None):
    pending = invoke(v, STAGE_PART_TOOL, request or v["stage_request"], headers=headers, key=uuid4().hex)
    if pending.status_code != 200 or pending.json()["status"] != "waiting_confirmation":
        return pending
    return v["client"].post(f"/v1/tool-invocations/{pending.json()['id']}/confirm", headers=headers or v["headers"])


def read(v, ident, headers=None):
    return v["client"].get(f"/v1/projects/{v['project_id']}/quality/test-design-mapping-parts/{ident}",
        headers=headers or v["headers"])


def seed(v, request=None, **changes):
    request = MappingPartStageInput.model_validate(request or v["stage_request"])
    ident = uuid4().hex
    with session_scope() as session:
        session.add(ToolInvocationRecord(id=ident, tool_id=STAGE_PART_TOOL, status="running", summary="Explicit internal staging race fixture",
            conversation_id=v["conversation"].json()["id"], input_payload={**request.model_dump(mode="json"),
                "confirmed_by_user": True, "confirmed_actor_id": v["owner"]["id"],
                "confirmed_at": datetime.now(timezone.utc).isoformat(), **changes}))
    return request, ident


def stage(v, request, ident):
    with actor_scope(UserProfile.model_validate(v["owner"])):
        return v["stage_service"].stage(request, invocation_id=ident, recorded_at=datetime.now(timezone.utc).isoformat())


def test_canonical_part_staging_is_private_append_only_and_never_approves_coverage(staging):
    v = staging
    calls_before = count(v, LLMCallRecord)
    pending = invoke(v, STAGE_PART_TOOL, {**v["stage_request"], "confirmed_by_user": True}, key=uuid4().hex)
    assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
    assert count(v, PartRecord) == count(v, TestDesignMappingRecord) == 0
    command = completed(v["client"].post(f"/v1/tool-invocations/{pending.json()['id']}/confirm", headers=v["headers"]))
    ident = command["result"]["object_refs"][0].split(":", 1)[1]
    response = read(v, ident)
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store", response.text
    first = response.json()
    assert first["request"]["decisions"] == v["stage_request"]["decisions"] and first["current_use"]["part_current"]
    assert not first["current_use"]["assertion_mapped"] and not first["current_use"]["execution_authorized"]
    assert "artifact_ref" not in response.text and "native-test-design-fixture-key" not in response.text
    assert count(v, PartRecord) == 1 and count(v, TestDesignMappingRecord) == 0 and count(v, LLMCallRecord) == calls_before
    assert read_result(v, v["generation_metadata"]).json() == v["original_result"]
    staged_url = v["mapping_url"].removesuffix("/mapping-review") + "/mapping-parts/0/staged"
    staged_params = {"artifact_hash": v["generation_metadata"]["artifact_hash"], "plan_digest": v["stage_request"]["plan_digest"]}
    recovered_head = v["client"].get(staged_url, headers=v["headers"], params=staged_params)
    assert recovered_head.status_code == 200 and recovered_head.headers["cache-control"] == "private, no-store"
    assert recovered_head.json()["head"]["part_revision_id"] == ident and "decisions" not in recovered_head.text
    edited = deepcopy(v["stage_request"])
    edited["expected_previous_part_revision_id"] = ident
    edited["decisions"][0].update(decision="reject", reason="Independent corrected fixture decision")
    second_command = completed(submit(v, edited))
    second_id = second_command["result"]["object_refs"][0].split(":", 1)[1]
    second = read(v, second_id).json()
    assert second["revision"]["revision_sequence"] == 2 and second["request"] == MappingPartStageInput.model_validate(edited).model_dump(mode="json")
    old = read(v, ident).json()
    assert old["request"] == first["request"] and not old["current_use"]["part_current"]
    stale = submit(v)
    assert stale.json()["status"] == "failed" and stale.json()["result"]["requires_followup"]
    assert count(v, PartRecord) == 2 and count(v, TestDesignMappingRecord) == 0
    with session_scope() as session:
        audits = session.scalars(select(AuditEventRecord).where(AuditEventRecord.tool_invocation_id == command["id"],
            AuditEventRecord.action == "quality.test_design_mapping.part_staged")).all()
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == ident)).all()
        assert len(audits) == len(events) == 1
        assert "decisions" not in str(events[0].event_payload) and "reason" not in str(events[0].event_payload)
    for statement in (delete(PartRecord), update(PartRecord).values(revision_sequence=5)):
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as session:
                session.execute(statement.where(PartRecord.project_id == v["project_id"]))


def test_same_staging_command_race_recovers_original_and_different_command_cannot_overwrite(staging):
    v = staging
    request, ident = seed(v)
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(lambda _: stage(v, request, ident), range(2)))
    assert values[0] == values[1] and count(v, PartRecord) == 1
    edited = deepcopy(v["stage_request"])
    edited["expected_previous_part_revision_id"] = values[0]["part_revision_id"]
    changed = deepcopy(edited)
    changed["decisions"][0].update(decision="defer", reason="Conflicting independent edit fixture")
    first, second = seed(v, edited), seed(v, changed)

    def attempt(item):
        try:
            return stage(v, *item)
        except TestDesignMappingChanged:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [first, second]))
    assert sum(value is not None for value in results) == 1 and count(v, PartRecord) == 2
    completed(final_v1_review(v))
    assert stage(v, request, ident) == values[0]
    assert not read(v, values[0]["part_revision_id"]).json()["current_use"]["part_current"]
    assert count(v, TestDesignMappingRecord) == 1


def test_staging_outbox_failure_rolls_back_every_pg_fact_and_retry_is_exact(staging, monkeypatch):
    v = staging
    request, ident = seed(v)
    original = EventOutboxRepository.append

    def fail(*args, **kwargs):
        raise RuntimeError("explicit staging outbox failure")

    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    with pytest.raises(RuntimeError, match="outbox failure"):
        stage(v, request, ident)
    assert count(v, PartRecord) == count(v, TestDesignMappingRecord) == 0
    with session_scope() as session:
        assert not session.scalars(select(AuditEventRecord).where(AuditEventRecord.tool_invocation_id == ident)).all()
    monkeypatch.setattr(EventOutboxRepository, "append", original)
    committed = stage(v, request, ident)
    assert stage(v, request, ident) == committed and count(v, PartRecord) == 1


def test_committed_part_survives_lost_terminal_ack_without_reopening_failed_command(staging, monkeypatch):
    v = staging
    request, ident = seed(v)
    saved = stage(v, request, ident)
    with session_scope() as session:
        command = session.get(ToolInvocationRecord, ident)
        command.status = "failed"
        command.input_payload = {**command.input_payload,
            "confirmed_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()}

    def no_put(*args):
        raise AssertionError("committed part recovery must not rewrite its archive")

    monkeypatch.setattr(v["stage_service"].artifacts, "put", no_put)
    assert stage(v, request, ident) == saved and count(v, PartRecord) == 1
    assert read(v, saved["part_revision_id"]).status_code == 200
    with session_scope() as session:
        assert session.get(ToolInvocationRecord, ident).status == "failed"
    other_request, other_id = seed(v)
    with session_scope() as session:
        session.get(ToolInvocationRecord, other_id).status = "failed"
    with pytest.raises(TestDesignMappingIntegrityError):
        stage(v, other_request, other_id)
    assert count(v, PartRecord) == 1


def test_staging_confirmation_scope_or_original_source_cannot_be_forged(staging):
    v = staging
    for changes in ({"confirmed_by_user": False}, {"confirmed_actor_id": "foreign"},
            {"confirmed_at": (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()},
            {"confirmed_at": datetime.now().isoformat()},
            {"confirmed_at": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()},
            {"agent_goal_id": "foreign"}):
        request, ident = seed(v, **changes)
        with pytest.raises((TestDesignMappingIntegrityError, ValueError)):
            stage(v, request, ident)
    grant_member(v)
    role_url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(role_url, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    member_command = completed(submit(v, headers=v["member_headers"]))
    part_id = member_command["result"]["object_refs"][0].split(":", 1)[1]
    assert read(v, part_id, v["member_headers"]).status_code == 200
    repo = SourceAccessRepository()
    snapshot = repo.load_snapshot(v["project_id"])
    repo.set_policy(v["project_id"], v["evidence"]["binding_id"], SourceAccessRule("restricted"),
        expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id=uuid4().hex)
    denied = read(v, part_id, v["member_headers"])
    assert denied.status_code == 403 and "decisions" not in denied.text and "plan_digest" not in denied.text
    assert read(v, part_id).status_code == 200
    assert count(v, PartRecord) == 1 and count(v, TestDesignMappingRecord) == 0


def test_staging_corrupt_archive_or_canonical_actor_fails_closed(staging, monkeypatch):
    v = staging
    command = completed(submit(v))
    ident = command["result"]["object_refs"][0].split(":", 1)[1]
    original = v["stage_service"].artifacts.read

    def corrupt(*args):
        payload = deepcopy(original(*args))
        payload["request"]["decisions"][0]["decision"] = "reject"
        return payload

    monkeypatch.setattr(v["stage_service"].artifacts, "read", corrupt)
    response = read(v, ident)
    assert response.status_code == 502 and "decisions" not in response.text
    monkeypatch.setattr(v["stage_service"].artifacts, "read", original)
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, command["id"])
        row.input_payload = {**row.input_payload, "confirmed_actor_id": "forged"}
    response = read(v, ident)
    assert response.status_code == 502 and "decisions" not in response.text
    assert count(v, PartRecord) == 1 and count(v, TestDesignMappingRecord) == 0


def test_staging_write_then_source_revocation_commits_no_part_or_audit(staging, monkeypatch):
    v = staging
    grant_member(v)
    role_url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(role_url, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    original = v["stage_service"].artifacts.put

    def revoke(project_id, payload):
        value = original(project_id, payload)
        repository = SourceAccessRepository()
        current = repository.load_snapshot(project_id)
        repository.set_policy(project_id, v["evidence"]["binding_id"], SourceAccessRule("restricted"),
            expected_epoch=current.acl_epoch, changed_by=v["owner"]["id"], invocation_id=uuid4().hex)
        return value

    monkeypatch.setattr(v["stage_service"].artifacts, "put", revoke)
    response = submit(v, headers=v["member_headers"])
    assert response.status_code == 200 and response.json()["status"] == "failed", response.text
    assert count(v, PartRecord) == count(v, TestDesignMappingRecord) == 0
    with session_scope() as session:
        assert not session.scalars(select(AuditEventRecord).where(
            AuditEventRecord.tool_invocation_id == response.json()["id"],
            AuditEventRecord.action == "quality.test_design_mapping.part_staged")).all()


def test_staging_downgrade_refuses_to_delete_saved_decisions(staging):
    import importlib
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from apps.api.app.infrastructure.persistence.database import engine

    v = staging
    completed(submit(v))
    migration = importlib.import_module("apps.api.migrations.versions.0066_mapping_part_staging")
    with engine.begin() as connection:
        original = migration.op
        try:
            migration.op = Operations(MigrationContext.configure(connection))
            with pytest.raises(RuntimeError, match="cannot downgrade"):
                migration.downgrade()
        finally:
            migration.op = original
    assert count(v, PartRecord) == 1


def test_staging_minio_roundtrip_is_private_and_only_cleans_its_own_keys(staging, tmp_path, monkeypatch):
    import os
    import boto3
    from apps.api.app.infrastructure.storage.mapping_part_artifacts import MappingPartArtifacts
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
    storage = RecordingStorage(config)
    v = staging
    monkeypatch.setattr(v["stage_service"], "artifacts", MappingPartArtifacts(storage))
    try:
        command = completed(submit(v))
        ident = command["result"]["object_refs"][0].split(":", 1)[1]
        response = read(v, ident)
        assert response.status_code == 200 and not response.json()["current_use"]["assertion_mapped"], response.text
        metadata, ref = v["stage_service"].repository.get(v["project_id"], ident)
        assert ref.startswith("s3://")
        archived = v["stage_service"].artifacts.read(v["project_id"], ref, metadata["artifact_hash"])
        assert archived["request"] == response.json()["request"]
        assert archived["plan"] == response.json()["plan"] and len(written) == 1
        assert read_result(v, v["generation_metadata"]).json() == v["original_result"]
        assert count(v, TestDesignMappingRecord) == 0
    finally:
        client = boto3.client("s3", endpoint_url=config.endpoint, aws_access_key_id=config.access_key, aws_secret_access_key=config.secret_key)
        if written:
            cleanup = client.delete_objects(Bucket=config.bucket, Delete={"Objects": [{"Key": key} for key in written]})
            assert not cleanup.get("Errors")
