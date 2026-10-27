"""Actual isolated PostgreSQL/MinIO admission; protocol cases are not business gold."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.case_approvals import CaseApprovalReviewInput
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.case_approval import CASE_APPROVAL_TOOL, CASE_APPROVAL_EVENT, CaseApprovalChanged
from apps.api.app.application.platform.tool_models import EventPayload
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.case_approval_models import CaseApprovalRevisionRecord as Record, CaseApprovalMemberRecord as Member
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, SSEEventOutboxRecord, ToolInvocationRecord, LLMCallRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_automation_input_api import mapping, generation_result, design_scope, publication, documents, evidence_api, base_evidence_api
from apps.api.tests.test_automation_input_api import accepted
from apps.api.tests.test_automation_input_api import verify_fixed_exweb_archive
from apps.api.tests.test_test_design_mapping_api import submit as mapping_submit, read_result
from apps.api.tests.test_semantic_evaluations_api import invoke, completed, count
from apps.api.tests.test_source_access_api import grant_member
from apps.api.tests.test_test_design_mapping_read_postgres import read_only_session


@pytest.fixture
def admission(mapping):
    v = mapping
    head = accepted(v)
    v["admission_selection"] = {"project_id": v["project_id"], "mapping_revision_id": head["revision"]["revision_id"],
        "mapping_artifact_hash": head["revision"]["artifact_hash"], "case_ids": head["assessment"]["accepted_case_ids"]}
    v["admission_mapping"] = head
    v["admission_url"] = f"/v1/projects/{v['project_id']}/quality/test-design-case-approvals"
    v["admission_service"] = app.state.container.case_approvals
    preview = inspect(v)
    assert preview.status_code == 200, preview.text
    v["admission_preview"] = preview.json()
    v["admission_request"] = {**v["admission_selection"], "expected_input_digest": preview.json()["basis"]["input_digest"],
        "expected_previous_revision_id": None, "decision": "approve", "reason": "Explicit independent admission, no execution or business pass"}
    return v


def inspect(v, headers=None):
    selected = v["admission_selection"]
    return v["client"].get(v["admission_url"] + "/preview", headers=headers or v["headers"],
        params=[(key, selected[key]) for key in ("mapping_revision_id", "mapping_artifact_hash")]
            + [("case_ids", item) for item in selected["case_ids"]])


def submit(v, request=None, headers=None):
    pending = invoke(v, CASE_APPROVAL_TOOL, request or v["admission_request"], headers=headers, key=uuid4().hex)
    if pending.status_code != 200 or pending.json()["status"] != "waiting_confirmation":
        return pending
    return v["client"].post(f"/v1/tool-invocations/{pending.json()['id']}/confirm", headers=headers or v["headers"])


def read(v, command, headers=None):
    ident = command["result"]["object_refs"][0].split(":", 1)[1]
    return v["client"].get(v["admission_url"] + "/" + ident, headers=headers or v["headers"])


def seed(v, **changes):
    request = CaseApprovalReviewInput.model_validate(v["admission_request"])
    ident = uuid4().hex
    with session_scope() as session:
        session.add(ToolInvocationRecord(id=ident, tool_id=CASE_APPROVAL_TOOL, status="running", summary="Internal canonical race specimen",
            conversation_id=v["conversation"].json()["id"], input_payload={**request.model_dump(mode="json"),
                "confirmed_by_user": True, "confirmed_actor_id": v["owner"]["id"],
                "confirmed_at": datetime.now(timezone.utc).isoformat(), **changes}))
    return request, ident


def review(v, request, ident):
    with actor_scope(UserProfile.model_validate(v["owner"])):
        return v["admission_service"].review(request, invocation_id=ident, recorded_at=datetime.now(timezone.utc).isoformat())


def test_canonical_admission_is_private_atomic_and_keeps_original_draft_oracles(admission):
    v = admission
    original = deepcopy(v["original_result"])
    calls = count(v, LLMCallRecord)
    pending = invoke(v, CASE_APPROVAL_TOOL, {**v["admission_request"], "confirmed_by_user": True}, key=uuid4().hex)
    assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
    assert count(v, Record) == count(v, Member) == 0
    command = completed(v["client"].post(f"/v1/tool-invocations/{pending.json()['id']}/confirm", headers=v["headers"]))
    response = read(v, command)
    assert response.status_code == 200, response.text
    result = response.json()
    assert response.headers["cache-control"] == "private, no-store"
    assert result["current_use"] == {"case_admission_current": True, "generation_authorized": False,
        "execution_authorized": False, "business_coverage_verified": False}
    assert result["basis"] == v["admission_preview"]["basis"]
    assert count(v, Record) == 1 and count(v, Member) == len(v["admission_selection"]["case_ids"])
    assert count(v, LLMCallRecord) == calls
    assert read_result(v, v["generation_metadata"]).json() == original
    assert "Explicit independent" not in json.dumps(command["result"])
    assert "artifact_ref" not in response.text and "s3://" not in response.text
    with session_scope() as session:
        events = list(session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == result["revision"]["revision_id"])))
        audits = list(session.scalars(select(AuditEventRecord).where(AuditEventRecord.tool_invocation_id == command["id"], AuditEventRecord.action == CASE_APPROVAL_EVENT)))
        assert len(events) == len(audits) == 1
        assert set(events[0].event_payload["patch"]) == {"project_id", "revision_id", "status"}
        assert "Explicit independent" not in json.dumps(events[0].event_payload)
        assert session.bind.dialect.name == "postgresql"
    preview = inspect(v).json()
    assert preview["history_count"] == 1 and preview["head"]["revision_id"] == result["revision"]["revision_id"]


def test_withdrawn_admission_does_not_rewrite_cases_or_allow_current_consumer(admission):
    v = admission
    command = completed(submit(v))
    original = read(v, command).json()
    withdrawn = completed(submit(v, {**v["admission_request"], "decision": "withdraw",
        "expected_previous_revision_id": original["revision"]["revision_id"]}))
    assert read(v, withdrawn).json()["revision"]["status"] == "withdrawn"
    historical = read(v, command).json()
    assert historical["basis"] == original["basis"] and historical["revision"] == original["revision"]
    assert not historical["current_use"]["case_admission_current"] and count(v, Record) == 2
    assert read_result(v, v["generation_metadata"]).json() == v["original_result"]
    with actor_scope(UserProfile.model_validate(v["owner"])):
        prepared = app.state.container.automation_inputs.replay(CaseApprovalReviewInput.model_validate(v["admission_request"]).selection())
        with pytest.raises(CaseApprovalChanged):
            v["admission_service"].resolve(v["project_id"], original["revision"]["revision_id"], original["revision"]["artifact_hash"], prepared)


def test_mapping_withdrawal_allows_exact_recovery_but_not_new_approval(admission, monkeypatch):
    v = admission
    request, ident = seed(v)
    original = review(v, request, ident)
    completed(mapping_submit(v, {**v["mapping_request"], "decision": "withdraw", "mappings": None,
        "expected_previous_revision_id": v["admission_selection"]["mapping_revision_id"]}))
    def no_write(*_):
        raise AssertionError("committed admission cannot rewrite its archive")
    monkeypatch.setattr(v["admission_service"].artifacts, "put", no_write)
    with session_scope() as session:
        command = session.get(ToolInvocationRecord, ident)
        command.input_payload = {**command.input_payload, "confirmed_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()}
    assert review(v, request, ident) == original and count(v, Record) == 1
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert not v["admission_service"].read(v["project_id"], original["revision_id"])["current_use"]["case_admission_current"]
    preview = inspect(v)
    assert preview.status_code == 200 and not preview.json()["input_current"], preview.text


def test_concurrent_approvals_use_cohort_head_cas(admission):
    v = admission
    commands = [seed(v), seed(v)]
    def attempt(command):
        try:
            return review(v, *command)
        except CaseApprovalChanged:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(attempt, commands))
    assert sum(value is not None for value in values) == 1 and count(v, Record) == 1


@pytest.mark.parametrize("fault", ["unconfirmed", "actor", "expired", "future"])
def test_admission_cannot_forge_canonical_confirmation(admission, fault):
    changes = {"unconfirmed": {"confirmed_by_user": False}, "actor": {"confirmed_actor_id": "other"},
        "expired": {"confirmed_at": (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()},
        "future": {"confirmed_at": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()}}
    request, ident = seed(admission, **changes[fault])
    with pytest.raises(ValueError):
        review(admission, request, ident)
    assert count(admission, Record) == count(admission, Member) == 0


@pytest.mark.parametrize("race", ["outbox", "mapping"])
def test_final_parent_recheck_or_outbox_failure_rolls_back_admission(admission, monkeypatch, race):
    v = admission
    request, ident = seed(v)
    if race == "outbox":
        def fail(*_, **__):
            raise RuntimeError("synthetic transaction rollback")
        monkeypatch.setattr(EventOutboxRepository, "append", fail)
    else:
        put = v["admission_service"].artifacts.put
        def withdraw(project, payload):
            value = put(project, payload)
            completed(mapping_submit(v, {**v["mapping_request"], "decision": "withdraw", "mappings": None,
                "expected_previous_revision_id": v["admission_selection"]["mapping_revision_id"]}))
            return value
        monkeypatch.setattr(v["admission_service"].artifacts, "put", withdraw)
    with pytest.raises(Exception):
        review(v, request, ident)
    assert count(v, Record) == count(v, Member) == 0
    with session_scope() as session:
        assert not list(session.scalars(select(AuditEventRecord).where(AuditEventRecord.tool_invocation_id == ident)))


def test_current_reviewer_and_source_access_are_not_implied_by_project_membership(admission):
    v = admission
    grant_member(v)
    assert inspect(v, v["member_headers"]).json()["can_review"] is False
    own = v["client"].post("/v1/conversations", headers=v["member_headers"], json={"space_type": "project", "space_id": v["project_id"]})
    old, v["conversation"] = v["conversation"], own
    try:
        denied = submit(v, headers=v["member_headers"])
        assert denied.status_code == 200 and denied.json()["status"] == "failed", denied.text
        assert count(v, Record) == 0
        assert v["client"].put(f"/v1/projects/{v['project_id']}/members/{v['member']['id']}", headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
        command = completed(submit(v, headers=v["member_headers"]))
        assert read(v, command, v["member_headers"]).json()["revision"]["authority_actor"] == v["member"]["id"]
        with session_scope() as session:
            persisted = session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_type == CASE_APPROVAL_EVENT,
                SSEEventOutboxRecord.conversation_id == own.json()["id"]))
            event = EventPayload.model_validate(persisted.event_payload)
        member = UserProfile.model_validate(v["member"])
        with actor_scope(member):
            assert app.state.container.case_approval_events.can_access(event)
        repo = SourceAccessRepository()
        epoch = repo.load_snapshot(v["project_id"]).acl_epoch
        repo.set_policy(v["project_id"], v["evidence"]["binding_id"], SourceAccessRule("restricted"),
            expected_epoch=epoch, changed_by=v["owner"]["id"], invocation_id=uuid4().hex)
        assert read(v, command, v["member_headers"]).status_code == 403
        receipt = v["client"].get("/v1/tool-invocations/" + command["id"], headers=v["member_headers"])
        assert receipt.status_code == 403 and "case_count" not in receipt.text
        with actor_scope(member):
            assert not app.state.container.case_approval_events.can_access(event)
        assert read(v, command).status_code == 200
    finally:
        v["conversation"] = old


def test_case_approval_rows_are_append_only_and_historical_reads_are_read_only(admission, monkeypatch):
    v = admission
    command = completed(submit(v))
    row = read(v, command).json()["revision"]
    import apps.api.app.infrastructure.persistence.case_approval_repository as module
    monkeypatch.setattr(module, "session_scope", read_only_session)
    metadata, ref = v["admission_service"].repository.get(v["project_id"], row["revision_id"])
    assert metadata == row and ref.startswith("s3://")
    assert v["admission_service"].repository.history(v["project_id"], row["cohort_id"]) == [row]
    with pytest.raises(DBAPIError):
        with session_scope() as session:
            session.execute(update(Record).where(Record.revision_id == row["revision_id"]).values(status="withdrawn"))
    with pytest.raises(DBAPIError):
        with session_scope() as session:
            session.execute(text("DELETE FROM quality_case_approval_members WHERE revision_id = :revision"), {"revision": row["revision_id"]})
    assert read(v, command).json()["revision"] == row


def test_fixed_exweb_case_admission_preserves_all_source_pins(admission):
    v = admission
    prepared = v["admission_preview"]["prepared"]
    original = deepcopy(prepared)
    source_pin, members = verify_fixed_exweb_archive(v, prepared)
    command = completed(submit(v))
    response = read(v, command)
    assert response.status_code == 200, response.text
    basis = response.json()["basis"]
    assert basis == v["admission_preview"]["basis"]
    assert prepared == original and source_pin["file_count"] == 126 and members == 725
    assert len(basis["case_pins"]) == 4 and basis["constraint_denominator"] == 1 and basis["obligation_denominator"] == 4
    assert basis["case_pins"] == [{"case_id": case["case_id"], "case_digest": acceptance_digest(case)} for case in original["cases"]]
    assert basis["obligation_pins"] == [{key: row[key] for key in ("row_id", "oracle_digest", "selected_case_ids")} for row in original["obligations"]]
    assert response.json()["current_use"] == {"case_admission_current": True, "generation_authorized": False,
        "execution_authorized": False, "business_coverage_verified": False}
    with actor_scope(UserProfile.model_validate(v["owner"])):
        value, historical, current = v["admission_service"].read_with_inputs(v["project_id"], response.json()["revision"]["revision_id"])
    assert value == response.json() and historical == current == original
    assert read_result(v, v["generation_metadata"]).json() == v["original_result"]
    if os.getenv("CASE_APPROVAL_VERIFY_PORTAL") == "1":
        root = Path(__file__).resolve().parents[3]
        probe = subprocess.run(["node", str(root / "scripts/verify-case-admission-contract.cjs")], cwd=root,
            input=json.dumps({"preview": inspect(v).json(), "draft": v["original_result"], "mapping": v["admission_mapping"]}),
            text=True, capture_output=True, timeout=30)
        assert probe.returncode == 0, probe.stderr
        assert json.loads(probe.stdout) == {"verified": True, "cases": 4, "obligations": 4, "target_execution_verified": False}
