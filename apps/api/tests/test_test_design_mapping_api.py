from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.test_design_mapping_inputs import MappingReviewInput, MappingQueryInput
from apps.api.app.application.quality_loop.test_design_mapping_pins import mapping_review_query_keys
from apps.api.app.domain.quality_loop.test_design_mapping import MAPPING_TOOL, MAPPING_QUERY_TOOL, TestDesignMappingChanged, TestDesignMappingIntegrityError, TestDesignMappingInvalid
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.test_design_mapping_models import TestDesignMappingRecord as Record
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, SSEEventOutboxRecord, ToolInvocationRecord, LLMCallRecord, UserIdentityRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_test_design_results_api import generation_result, commit, read_result
from apps.api.tests.test_test_design_scope_api import design_scope, submit as scope_submit
from apps.api.tests.test_image_publications_api import publication
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_semantic_evaluations_api import invoke, completed, count
from apps.api.tests.test_source_access_api import grant_member
from apps.api.tests.test_test_design_mapping import reviews


@pytest.fixture
def mapping(generation_result):
    v = generation_result
    metadata = commit(v)
    value = read_result(v, metadata).json()
    request = dict(project_id=v["project_id"], generation_id=metadata["generation_id"], generation_artifact_hash=metadata["artifact_hash"],
        expected_previous_revision_id=None, decision="review", mappings=reviews(value["result"]["proposal"]), reason="Independent fixture review, not target pass")
    v.update(mapping_request=request, mapping_service=app.state.container.test_design_mappings, generation_metadata=metadata,
        original_result=value, mapping_url=f"/v1/projects/{v['project_id']}/quality/test-design-results/{metadata['generation_id']}/mapping-review")
    return v


def inspect(v, headers=None, **params):
    return v["client"].get(v["mapping_url"], headers=headers or v["headers"],
        params={"artifact_hash": v["generation_metadata"]["artifact_hash"], **params})


def submit(v, request=None, headers=None):
    pending = invoke(v, MAPPING_TOOL, request or v["mapping_request"], headers=headers, key=uuid4().hex)
    if pending.status_code != 200 or pending.json()["status"] != "waiting_confirmation":
        return pending
    return v["client"].post(f"/v1/tool-invocations/{pending.json()['id']}/confirm", headers=headers or v["headers"])


def seed(v, request=None, **changes):
    request = MappingReviewInput.model_validate(request or v["mapping_request"])
    ident = uuid4().hex
    with session_scope() as session:
        session.add(ToolInvocationRecord(id=ident, tool_id=MAPPING_TOOL, status="running", summary="Internal canonical review race fixture",
            conversation_id=v["conversation"].json()["id"], input_payload={**request.model_dump(mode="json"),
                "confirmed_by_user": True, "confirmed_actor_id": v["owner"]["id"],
                "confirmed_at": datetime.now(timezone.utc).isoformat(), **changes}))
    return request, ident


def review(v, request, ident):
    with actor_scope(UserProfile.model_validate(v["owner"])):
        return v["mapping_service"].review(request, invocation_id=ident, recorded_at=datetime.now(timezone.utc).isoformat())


def test_canonical_mapping_review_preserves_draft_and_records_private_atomic_authority(mapping):
    v = mapping
    calls_before = count(v, LLMCallRecord)
    assert inspect(v).json()["head"] is None
    pending = invoke(v, MAPPING_TOOL, {**v["mapping_request"], "confirmed_by_user": True}, key=uuid4().hex)
    assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation"
    assert count(v, Record) == 0
    command = completed(v["client"].post(f"/v1/tool-invocations/{pending.json()['id']}/confirm", headers=v["headers"]))
    response = inspect(v)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    head = response.json()["head"]
    assert head["current_use"]["mapping_current"] and head["current_use"]["mapping_complete"]
    assert not head["current_use"]["execution_authorized"]
    coverage = head["assessment"]["coverage"]
    assert coverage["assertion_mapped_count"] == coverage["obligation_denominator"]
    assert coverage["automated_count"] == coverage["executed_on_target_count"] == coverage["passed_count"] == 0
    assert read_result(v, v["generation_metadata"]).json() == v["original_result"]
    assert count(v, Record) == 1 and count(v, LLMCallRecord) == calls_before
    assert command["result"]["object_refs"] == ["test_design_mapping:" + head["revision"]["revision_id"]]
    assert "Independently inspected" not in json.dumps(command["result"]) and "artifact_ref" not in response.text
    with session_scope() as session:
        audits = session.scalars(select(AuditEventRecord).where(AuditEventRecord.tool_invocation_id == command["id"],
            AuditEventRecord.entity_id == head["revision"]["revision_id"], AuditEventRecord.action == "quality.test_design_mapping.reviewed")).all()
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == head["revision"]["revision_id"])).all()
        assert len(audits) == len(events) == 1 and audits[0].status == "completed"
        assert events[0].event_payload["query_keys"] == mapping_review_query_keys(v["project_id"])
        assert events[0].event_payload["snapshot_hint"] is True
        assert "Independently inspected" not in json.dumps(events[0].event_payload)
    assert v["client"].get("/v1/audit-events", headers=v["headers"]).status_code == 200


def test_reject_defer_withdraw_and_history_do_not_grant_execution(mapping):
    v = mapping
    request = deepcopy(v["mapping_request"])
    request["mappings"][0]["decision"], request["mappings"][1]["decision"] = "reject", "defer"
    completed(submit(v, request))
    head = inspect(v).json()["head"]
    assert head["assessment"]["rejected_assertion_count"] == head["assessment"]["deferred_assertion_count"] == 1
    assert head["current_use"]["mapping_current"] and not head["current_use"]["mapping_complete"]
    revision = head["revision"]["revision_id"]
    withdrawal = {**request, "expected_previous_revision_id": revision, "decision": "withdraw", "mappings": None}
    completed(submit(v, withdrawal))
    current = inspect(v).json()
    assert current["head"]["revision"]["status"] == "withdrawn" and not current["head"]["current_use"]["mapping_current"]
    response = v["client"].get(f"/v1/projects/{v['project_id']}/quality/test-design-mapping-reviews/{revision}", headers=v["headers"])
    assert response.status_code == 200 and response.json()["assessment"] == head["assessment"]
    assert not response.json()["current_use"]["mapping_current"]
    assert len(current["history"]) == 2
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(TestDesignMappingChanged):
            v["mapping_service"].resolve(v["project_id"], revision, head["revision"]["artifact_hash"])
    stale = submit(v, request)
    assert stale.json()["status"] == "failed" and stale.json()["result"]["requires_followup"]


def test_same_command_recovery_is_idempotent_after_scope_withdrawal(mapping, monkeypatch):
    v = mapping
    request, ident = seed(v)
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(lambda _: review(v, request, ident), range(2)))
    assert values[0] == values[1] and count(v, Record) == 1
    def no_put(*args):
        raise AssertionError("committed review cannot rewrite its archive")
    monkeypatch.setattr(v["mapping_service"].artifacts, "put", no_put)
    completed(scope_submit(v, {**v["scope_request"], "expected_previous_revision_id": v["execution"]["request"].scope_revision_id,
        "decision": "withdraw", "contract": None}))
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, ident)
        row.input_payload = {**row.input_payload, "confirmed_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()}
    assert review(v, request, ident) == values[0]
    assert not inspect(v).json()["head"]["current_use"]["mapping_current"]


def test_concurrent_different_commands_cannot_overwrite_same_head(mapping):
    v = mapping
    first, a = seed(v)
    changed = deepcopy(v["mapping_request"])
    changed["mappings"][0]["decision"] = "reject"
    second, b = seed(v, changed)
    def attempt(item):
        try:
            return review(v, *item)
        except TestDesignMappingChanged:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(attempt, [(first, a), (second, b)]))
    assert sum(value is not None for value in values) == 1 and count(v, Record) == 1


@pytest.mark.parametrize("change", ["pin", "case", "row", "step", "oracle", "omit", "duplicate"])
def test_mapping_rejects_unpinned_or_incomplete_reviews(mapping, change):
    v = mapping
    request = deepcopy(v["mapping_request"])
    if change == "pin":
        request["generation_artifact_hash"] = "sha256:" + "0" * 64
    elif change == "omit":
        request["mappings"].pop()
    elif change == "duplicate":
        request["mappings"].append(deepcopy(request["mappings"][0]))
    else:
        key, value = {"case": ("case_id", "other"), "row": ("row_id", "other"),
            "step": ("step_index", 1), "oracle": ("oracle_digest", "sha256:" + "0" * 64)}[change]
        request["mappings"][0][key] = value
    assert submit(v, request).json()["status"] == "failed"
    assert count(v, Record) == 0


def test_current_reviewer_role_is_required_and_qa_can_review_without_egress(mapping):
    v = mapping
    grant_member(v)
    assert inspect(v, v["member_headers"]).json()["can_review"] is False
    # This reviewer uses their own conversation; an owner's conversation is not delegated.
    conversation = v["client"].post("/v1/conversations", headers=v["member_headers"], json={"space_type": "project", "space_id": v["project_id"]})
    assert conversation.status_code == 200, conversation.text
    original = v["conversation"]
    v["conversation"] = conversation
    try:
        denied = submit(v, headers=v["member_headers"])
        assert denied.status_code == 200 and denied.json()["status"] == "failed", denied.text
        assert denied.json()["result"]["followup_reason"] == "authorization_denied"
        assert count(v, Record) == 0
        url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
        assert v["client"].put(url, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
        completed(submit(v, headers=v["member_headers"]))
    finally:
        v["conversation"] = original
    assert inspect(v).json()["head"]["revision"]["authority_actor"] == v["member"]["id"]


def test_source_access_revocation_hides_mapping_history_and_old_receipts(mapping):
    v = mapping
    completed(submit(v))
    grant_member(v)
    assert inspect(v, v["member_headers"]).status_code == 200
    repo = SourceAccessRepository()
    snapshot = repo.load_snapshot(v["project_id"])
    repo.set_policy(v["project_id"], v["evidence"]["binding_id"], SourceAccessRule("restricted"),
        expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id=uuid4().hex)
    assert inspect(v, v["member_headers"]).status_code == 403
    assert inspect(v).status_code == 200


@pytest.mark.parametrize("race", ["scope", "acl", "account", "outbox"])
def test_final_commit_revalidates_authority_and_rolls_back_on_outbox_failure(mapping, monkeypatch, race):
    v = mapping
    request, ident = seed(v)
    original = v["mapping_service"].artifacts.put
    def change(project_id, payload):
        result = original(project_id, payload)
        if race == "scope":
            completed(scope_submit(v, {**v["scope_request"], "expected_previous_revision_id": v["execution"]["request"].scope_revision_id,
                "decision": "withdraw", "contract": None}))
        elif race == "acl":
            repo = SourceAccessRepository()
            snapshot = repo.load_snapshot(project_id)
            repo.set_policy(project_id, v["evidence"]["binding_id"], SourceAccessRule("restricted"),
                expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id=uuid4().hex)
        elif race == "account":
            with session_scope() as session:
                session.get(UserIdentityRecord, v["owner"]["id"]).status = "disabled"
        return result
    monkeypatch.setattr(v["mapping_service"].artifacts, "put", change)
    if race == "outbox":
        def fail(*args, **kwargs):
            raise RuntimeError("synthetic outbox failure")
        monkeypatch.setattr(EventOutboxRepository, "append", fail)
    with pytest.raises(Exception):
        review(v, request, ident)
    assert count(v, Record) == 0
    with session_scope() as session:
        assert not session.scalars(select(AuditEventRecord).where(AuditEventRecord.tool_invocation_id == ident)).all()


@pytest.mark.parametrize("invalid", ["confirmation", "actor", "expired", "naive", "future", "goal", "conversation"])
def test_canonical_confirmation_actor_ttl_and_project_scope_cannot_be_forged(mapping, invalid):
    v = mapping
    changes = {"confirmation": {"confirmed_by_user": False}, "actor": {"confirmed_actor_id": "forged"},
        "expired": {"confirmed_at": (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()},
        "naive": {"confirmed_at": datetime.now().isoformat()},
        "future": {"confirmed_at": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()},
        "goal": {"agent_goal_id": "foreign"}, "conversation": {}}[invalid]
    request, ident = seed(v, **changes)
    if invalid == "conversation":
        with session_scope() as session:
            session.get(ToolInvocationRecord, ident).conversation_id = "foreign"
    with pytest.raises((TestDesignMappingIntegrityError, ValueError)):
        review(v, request, ident)
    assert count(v, Record) == 0


def test_append_only_and_downgrade_protection(mapping):
    v = mapping
    completed(submit(v))
    for statement in (delete(Record), update(Record).values(status="withdrawn")):
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as session:
                session.execute(statement.where(Record.project_id == v["project_id"]))
    import importlib
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from apps.api.app.infrastructure.persistence.database import engine
    migration = importlib.import_module("apps.api.migrations.versions.0061_test_design_mappings")
    with engine.begin() as connection:
        original = migration.op
        try:
            migration.op = Operations(MigrationContext.configure(connection))
            with pytest.raises(RuntimeError, match="cannot downgrade"):
                migration.downgrade()
        finally:
            migration.op = original


def test_agent_receipt_is_metadata_only_and_invalidated_by_new_mapping_head(mapping):
    v = mapping
    query = {key: v["mapping_request"][key] for key in MappingQueryInput.model_fields}
    command = completed(invoke(v, MAPPING_QUERY_TOOL, query))
    receipt = command["result"]["test_design_mapping"]
    assert receipt["status"] == "unreviewed" and not receipt["execution_authorized"]
    assert "mappings" not in receipt and "proposal" not in receipt
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(command["id"], v["project_id"]) == receipt
    completed(submit(v))
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(TestDesignMappingChanged):
            app.state.container.tool_evidence.describe(command["id"], v["project_id"])


def test_corrupt_artifact_or_canonical_history_fails_closed(mapping, monkeypatch):
    v = mapping
    completed(submit(v))
    original = v["mapping_service"].artifacts.read
    def corrupt(*args):
        value = deepcopy(original(*args))
        value["assessment"]["coverage"]["passed_count"] = 99
        return value
    monkeypatch.setattr(v["mapping_service"].artifacts, "read", corrupt)
    response = inspect(v)
    assert response.status_code == 502
    error = response.json()["detail"]["error"]
    assert error == {"code": "test_design_mapping_integrity_failed", "message": "Mapping could not be verified.",
                     "details": {}, "retry_after": None}
    assert "assessment" not in response.json()["detail"]
    monkeypatch.setattr(v["mapping_service"].artifacts, "read", original)
    command = inspect(v).json()["head"]["revision"]["invocation_id"]
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, command)
        row.input_payload = {**row.input_payload, "confirmed_actor_id": "forged"}
    assert inspect(v).status_code == 502
