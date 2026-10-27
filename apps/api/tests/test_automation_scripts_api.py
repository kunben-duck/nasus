"""Native wire specimens through real canonical tools, PostgreSQL and MinIO.

The provider transport and business oracles are explicit protocol fixtures.
No external model, exweb target execution, or independently approved script
semantics are claimed by these persistence and provenance tests.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from threading import Barrier
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.quality_loop.automation_script_inputs import SCRIPT_TOOL, SCRIPT_PREVIEW_TOOL, SCRIPT_HISTORY_TOOL, ScriptExecutionSelection, ScriptExecutionRequest
from apps.api.app.application.quality_loop.generation_executor import GenerationOutcomeUnknown
from apps.api.app.application.quality_loop.test_design_results import TestDesignResultIntegrityError, response_digest
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.infrastructure.llm.test_design_model import HTTPTestDesignModel
from apps.api.app.infrastructure.persistence.automation_script_models import AutomationCallReservationRecord as Reservation, AutomationNativeReplyRecord as Reply, AutomationScriptRevisionRecord as Result
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, LLMCallRecord, SSEEventOutboxRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_automation_input_api import base_evidence_api, evidence_api, documents, publication, design_scope, generation_result, mapping, accepted, verify_fixed_exweb_archive
from apps.api.tests.test_automation_scripts import script_output
from apps.api.tests.test_generation_executor import budget, policy
from apps.api.tests.test_semantic_evaluations_api import completed, count, invoke, confirm
from apps.api.tests.test_semantic_link_model import saved_config, native_reply
from apps.api.tests.test_source_access_api import grant_member, policy as restrict_source
from apps.api.tests.test_test_design_mapping_api import submit as mapping_submit
from apps.api.tests.test_test_design_scope_api import submit as scope_submit
from apps.api.tests.test_automation_script_reviews import decisions
from apps.api.app.domain.quality_loop.automation_script_review import SCRIPT_REVIEW_TOOL, SCRIPT_REVIEW_QUERY_TOOL
from apps.api.app.infrastructure.persistence.automation_script_review_models import AutomationScriptReviewRecord as Review


@pytest.fixture
def native_scripts(mapping, monkeypatch):
    v = mapping
    head = accepted(v)
    service = app.state.container.automation_scripts
    config = saved_config(config_id=uuid4().hex)
    encrypted = service.profiles.secrets.encrypt_api_key("native-script-transport-fixture-key")
    service.profiles.repository.save_model_config(config, encrypted)
    monkeypatch.setattr(service.policies, "resolve", lambda binding: SimpleNamespace(policy=policy(binding), count=lambda *args: 32000))
    calls, sent = [], []
    transport = SimpleNamespace(fault=None, output=None)

    def handle(request):
        calls.append(request)
        wire = json.loads(request.content)
        prepared = json.loads(wire["messages"][-1]["content"])
        sent.append(prepared)
        assert request.url == httpx.URL(config.base_url + "/chat/completions")
        assert wire["model"] == config.model_name
        if transport.fault == "disconnect":
            raise httpx.ReadError("explicit native disconnect specimen", request=request)
        output = transport.output(prepared) if transport.output else script_output(prepared, kind="http")
        if transport.fault == "invalid_dsl":
            output["scripts"][0]["actions"][0]["action"] = "evaluate"
        reply = native_reply("openai_compatible", json.dumps(output))
        if transport.fault == "missing_usage":
            reply.pop("usage")
        elif transport.fault == "over_budget":
            reply["usage"]["completion_tokens"] = 8193
        return httpx.Response(200, json=reply)

    monkeypatch.setattr(service, "provider", HTTPTestDesignModel(transport=httpx.MockTransport(handle)))
    selection = ScriptExecutionSelection(project_id=v["project_id"], mapping_revision_id=head["revision"]["revision_id"],
        mapping_artifact_hash=head["revision"]["artifact_hash"], case_ids=tuple(head["assessment"]["accepted_case_ids"]),
        model_config_id=config.config_id, budget=budget())
    admission_selection = selection.selection()
    with actor_scope(UserProfile.model_validate(v["owner"])):
        admission_preview = app.state.container.case_approvals.preview(admission_selection)
    from apps.api.app.domain.quality_loop.case_approval import CASE_APPROVAL_TOOL
    pending_admission = invoke(v, CASE_APPROVAL_TOOL, {**admission_selection.model_dump(mode="json"),
        "expected_input_digest": admission_preview["basis"]["input_digest"], "expected_previous_revision_id": admission_preview["head_revision_id"],
        "decision": "approve", "reason": "Explicit independent protocol case admission, not business gold"}, key=uuid4().hex)
    assert pending_admission.status_code == 200 and pending_admission.json()["status"] == "waiting_confirmation", pending_admission.text
    admission_command = completed(confirm(v, pending_admission.json()))
    admission_id = admission_command["result"]["object_refs"][0].split(":", 1)[1]
    with actor_scope(UserProfile.model_validate(v["owner"])):
        admission = app.state.container.case_approvals.read(v["project_id"], admission_id)
    selection = ScriptExecutionSelection.model_validate({**selection.model_dump(mode="json"),
        "case_approval_revision_id": admission_id, "case_approval_artifact_hash": admission["revision"]["artifact_hash"]})
    with actor_scope(UserProfile.model_validate(v["owner"])):
        preview = service.preview(selection)
    v.update(script_service=service, script_selection=selection, script_preview=preview,
        script_request=ScriptExecutionRequest.model_validate(preview["request"]), script_config=config,
        script_encrypted=encrypted, script_calls=calls, script_sent=sent, script_transport=transport, script_mapping=head,
        script_admission=admission)
    return v


def run_confirmed(v, *, key=None):
    pending = invoke(v, SCRIPT_TOOL, v["script_preview"]["request"], key=key or uuid4().hex)
    assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
    return pending.json(), confirm(v, pending.json())


def read_draft(v, command, *, headers=None):
    ident = command["result"]["object_refs"][0].split(":", 1)[1]
    return v["client"].get(f"/v1/projects/{v['project_id']}/quality/automation-script-revisions/{ident}",
        headers=headers or v["headers"])


def assert_case_admission_consumption(v, *, monkeypatch=None):
    from apps.api.app.domain.quality_loop.case_approval import CASE_APPROVAL_TOOL
    preview_url = f"/v1/projects/{v['project_id']}/quality/automation-script-previews"
    legacy = {key: value for key, value in v["script_selection"].model_dump(mode="json").items()
        if not key.startswith("case_approval_")}
    rejected = v["client"].post(preview_url, headers=v["headers"], json=legacy)
    assert rejected.status_code == 409 and rejected.json()["detail"]["error"]["code"] == "case_admission_changed", rejected.text
    assert len(v["script_calls"]) == count(v, Reservation) == 0
    _, response = run_confirmed(v)
    command = completed(response)
    original = read_draft(v, command).json()
    if monkeypatch is not None:
        from apps.api.tests.automation_admission_parent_reads import assert_script_parent_read
        assert_script_parent_read(v, command, original, monkeypatch)
    with session_scope() as session:
        row = session.get(Reservation, command["id"])
        assert session.bind.dialect.name == "postgresql"
        assert row.case_approval_revision_id == v["script_admission"]["revision"]["revision_id"]
        assert row.case_approval_artifact_hash == v["script_admission"]["revision"]["artifact_hash"]
        assert row.payload["request"]["case_approval_revision_id"] == row.case_approval_revision_id
        # The FK is enforced independently of application validation and does not mutate the original.
        with pytest.raises(IntegrityError, match="fk_automation_case_admission"):
            with session.begin_nested():
                ident = uuid4().hex
                session.add(ToolInvocationRecord(id=ident, tool_id=SCRIPT_TOOL, status="running", summary="Explicit FK rejection specimen",
                    conversation_id=v["conversation"].json()["id"], input_payload={}))
                session.flush()
                session.add(Reservation(invocation_id=ident, project_id=row.project_id, generation_id=row.generation_id,
                    mapping_revision_id=row.mapping_revision_id, case_approval_revision_id=uuid4().hex,
                    case_approval_artifact_hash=row.case_approval_artifact_hash, call_id=uuid4().hex,
                    payload=deepcopy(row.payload), content_hash=row.content_hash))
                session.flush()
    admission = v["script_admission"]
    withdraw = {**v["script_selection"].selection().model_dump(mode="json"),
        "expected_input_digest": admission["basis"]["input_digest"], "expected_previous_revision_id": admission["revision"]["revision_id"],
        "decision": "withdraw", "reason": "Explicit admission withdrawal protocol specimen"}
    pending = invoke(v, CASE_APPROVAL_TOOL, withdraw, key=uuid4().hex)
    completed(confirm(v, pending.json()))
    historical = read_draft(v, command)
    assert historical.status_code == 200, historical.text
    assert historical.json()["result"] == original["result"] and historical.json()["metadata"] == original["metadata"]
    assert historical.json()["current_use"] == {"input_current": False, "execution_authorized": False}
    rejected = v["client"].post(preview_url, headers=v["headers"], json=v["script_selection"].model_dump(mode="json"))
    assert rejected.status_code == 409, rejected.text
    _, rejected_command = run_confirmed(v)
    assert rejected_command.status_code == 200 and rejected_command.json()["status"] == "failed", rejected_command.text
    assert len(v["script_calls"]) == count(v, Reservation) == count(v, Result) == 1
    assert read_draft(v, command).json()["result"] == original["result"]


def test_case_admission_is_required_persisted_and_rechecked_after_withdrawal(native_scripts):
    assert_case_admission_consumption(native_scripts)


def test_fixed_exweb_script_case_admission_consumes_original_pins(native_scripts, monkeypatch):
    v = native_scripts
    with actor_scope(UserProfile.model_validate(v["owner"])):
        prepared = v["script_service"].inputs.prepare(v["script_selection"].selection())
    verify_fixed_exweb_archive(v, prepared)
    assert_case_admission_consumption(native_scripts, monkeypatch=monkeypatch)


def test_http_binding_version_requires_a_new_exact_confirmation_before_native_generation(native_scripts):
    from apps.api.tests.test_http_binding_scripts import binding_script_output
    v = native_scripts
    altered = {**v["script_preview"]["request"], "http_protocol": "nasus.runner-http-execution.v2"}
    pending = invoke(v, SCRIPT_TOOL, altered).json()
    assert pending["status"] == "waiting_confirmation"
    rejected = confirm(v, pending)
    assert rejected.status_code == 200 and rejected.json()["status"] == "failed", rejected.text
    assert len(v["script_calls"]) == count(v, Reservation) == count(v, Result) == 0
    selection = ScriptExecutionSelection.model_validate({**v["script_selection"].model_dump(mode="json"),
        "http_protocol": "nasus.runner-http-execution.v2"})
    with actor_scope(UserProfile.model_validate(v["owner"])):
        new_preview = v["script_service"].preview(selection)
    assert new_preview["request"]["input_digest"] == altered["input_digest"]
    assert new_preview["request"]["execution"]["plan_digest"] != altered["execution"]["plan_digest"]
    v["script_preview"] = new_preview
    v["script_transport"].output = binding_script_output
    _, response = run_confirmed(v)
    value = read_draft(v, completed(response)).json()
    assert value["result"]["proposal"]["schema"] == "nasus.automation-script-proposal.v2"
    assert value["result"]["request"]["http_protocol"] == "nasus.runner-http-execution.v2"
    assert len(v["script_calls"]) == count(v, Reservation) == count(v, Result) == 1
    assert value["metadata"]["execution_authorized"] is False


def test_script_history_pins_mapping_paginates_and_preserves_unknown_calls(native_scripts):
    v = native_scripts
    _, response = run_confirmed(v)
    first = completed(response)
    selection = {"project_id": v["project_id"], "mapping_revision_id": v["script_selection"].mapping_revision_id,
        "mapping_artifact_hash": v["script_selection"].mapping_artifact_hash, "limit": 20, "after_id": ""}
    observation = completed(invoke(v, SCRIPT_HISTORY_TOOL, selection))
    receipt = observation["result"]["automation_script_history"]
    assert len(receipt["items"]) == 1 and receipt["items"][0]["invocation_id"] == first["id"]
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(observation["id"], v["project_id"]) == receipt
    _, response = run_confirmed(v)
    second = completed(response)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(PlatformApplicationError, match="Script history changed"):
            app.state.container.tool_evidence.describe(observation["id"], v["project_id"])
    v["script_transport"].fault = "missing_usage"
    pending, response = run_confirmed(v)
    assert response.json()["status"] == "failed"
    url = f"/v1/projects/{v['project_id']}/quality/automation-script-history"
    params = {"mapping_revision_id": v["script_selection"].mapping_revision_id,
        "mapping_artifact_hash": v["script_selection"].mapping_artifact_hash, "limit": 1}
    cursor, items = "", []
    while True:
        page = v["client"].get(url, params={**params, "after_id": cursor}, headers=v["headers"])
        assert page.status_code == 200 and page.headers["cache-control"] == "private, no-store"
        value = page.json()
        assert value["request"] == {**params, "project_id": v["project_id"], "after_id": cursor}
        assert not value["generation_authorized"] and not value["execution_authorized"]
        assert len(value["items"]) <= 1
        assert all("raw_output" not in item and "artifact_ref" not in item and "model_config_id" not in item for item in value["items"])
        items.extend(value["items"])
        cursor = value["next_after_id"]
        if cursor is None:
            break
    assert [item["invocation_id"] for item in items] == sorted((first["id"], second["id"], pending["id"]))
    unknown = next(item for item in items if item["invocation_id"] == pending["id"])
    assert unknown["call_reserved"] and unknown["provider_outcome_unknown"] and not unknown["reply_archived"]
    assert unknown["script_revision_id"] is None and unknown["artifact_hash"] is None
    for item in items:
        if item is unknown:
            continue
        assert item["reply_archived"] and not item["provider_outcome_unknown"]
        draft = v["client"].get(f"/v1/projects/{v['project_id']}/quality/automation-script-revisions/{item['script_revision_id']}", headers=v["headers"])
        assert draft.status_code == 200 and draft.json()["metadata"]["artifact_hash"] == item["artifact_hash"]
    assert len(v["script_calls"]) == 3
    bad = v["client"].get(url, params={**params, "mapping_artifact_hash": "sha256:" + "0" * 64}, headers=v["headers"])
    assert bad.status_code == 502
    assert v["client"].get(url, params={**params, "limit": 21}, headers=v["headers"]).status_code == 422
    grant_member(v)
    restrict_source(v)
    denied = v["client"].get(url, params={**params, "after_id": "z" * 128}, headers=v["member_headers"])
    assert denied.status_code == 403 and "items" not in denied.json()
    assert len(v["script_calls"]) == 3


def seed_internal_command(v, *, expired=False):
    ident = uuid4().hex
    confirmed_at = datetime.now(timezone.utc) - timedelta(minutes=16 if expired else 0)
    with session_scope() as session:
        session.add(ToolInvocationRecord(id=ident, tool_id=SCRIPT_TOOL, status="running", conversation_id=v["conversation"].json()["id"],
            summary="Internal rollback/expiry specimen, not canonical HTTP confirmation proof",
            input_payload={**v["script_request"].model_dump(mode="json"), "confirmed_by_user": True,
                "confirmed_actor_id": v["owner"]["id"], "confirmed_at": confirmed_at.isoformat()}))
    return ident


def execute_internal(v, ident):
    with actor_scope(UserProfile.model_validate(v["owner"])):
        return asyncio.run(v["script_service"].execute(v["script_request"], invocation_id=ident))


def script_calls(v):
    with session_scope() as session:
        return session.scalars(select(LLMCallRecord).where(LLMCallRecord.project_id == v["project_id"], LLMCallRecord.purpose == SCRIPT_TOOL)).all()


def script_review_request(v, draft):
    actions, assertions = decisions(draft["result"]["proposal"])
    return {"project_id": v["project_id"], "script_revision_id": draft["metadata"]["script_revision_id"],
        "script_artifact_hash": draft["metadata"]["artifact_hash"], "expected_previous_revision_id": None,
        "decision": "review", "actions": actions, "assertions": assertions,
        "reason": "Independent protocol review, not exweb business or target approval"}


def independent_reviewer(v):
    url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    response = v["client"].put(url, headers=v["headers"], json={"role": "qa_lead"})
    assert response.status_code == 200, response.text
    conversation = v["client"].post("/v1/conversations", headers=v["member_headers"], json={
        "space_type": "project", "space_id": v["project_id"], "title": "Independent script protocol review"})
    assert conversation.status_code == 200, conversation.text
    return {**v, "headers": v["member_headers"], "owner": v["member"], "conversation": conversation}


def submit_script_review(v, request, *, key=None):
    pending = invoke(v, SCRIPT_REVIEW_TOOL, request, key=key or uuid4().hex)
    if pending.status_code != 200 or pending.json()["status"] != "waiting_confirmation":
        return pending
    return confirm(v, pending.json())


def read_script_review(v, ident, headers=None):
    return v["client"].get(f"/v1/projects/{v['project_id']}/quality/automation-script-reviews/{ident}", headers=headers or v["headers"])


def test_independent_canonical_script_review_reject_accept_withdraw_preserves_zero_execution(native_scripts):
    v = native_scripts
    _, response = run_confirmed(v)
    generated = completed(response)
    draft = read_draft(v, generated).json()
    request = script_review_request(v, draft)
    query = {key: request[key] for key in ("project_id", "script_revision_id", "script_artifact_hash")}
    inspect_url = f"/v1/projects/{v['project_id']}/quality/automation-script-revisions/{query['script_revision_id']}/review"
    initial = v["client"].get(inspect_url, headers=v["headers"], params={"artifact_hash": query["script_artifact_hash"]})
    assert initial.status_code == 200 and initial.json()["head"] is None, initial.text
    grant_member(v)
    viewer_conversation = v["client"].post("/v1/conversations", headers=v["member_headers"], json={
        "space_type": "project", "space_id": v["project_id"], "title": "Viewer cannot approve scripts"})
    assert viewer_conversation.status_code == 200, viewer_conversation.text
    viewer = {**v, "headers": v["member_headers"], "conversation": viewer_conversation}
    denied = invoke(viewer, SCRIPT_REVIEW_TOOL, request)
    assert denied.status_code == 200 and denied.json()["status"] == "failed", denied.text
    assert denied.json()["result"]["followup_reason"] == "authorization_denied" and count(v, Review) == 0
    reviewer = independent_reviewer(v)
    bad = deepcopy(request)
    bad["assertions"].pop()
    rejected = submit_script_review(reviewer, bad)
    assert rejected.status_code == 200 and rejected.json()["status"] == "failed" and count(v, Review) == 0
    mixed = deepcopy(request)
    mixed["actions"][0]["decision"] = "defer"
    first_command = completed(submit_script_review(reviewer, mixed))
    first_id = first_command["result"]["object_refs"][0].split(":", 1)[1]
    first = read_script_review(v, first_id)
    assert first.status_code == 200 and first.headers["cache-control"] == "private, no-store", first.text
    assert first.json()["revision"]["authority_actor"] == v["member"]["id"] != draft["result"]["actor_id"]
    assert first.json()["assessment"]["deferred_count"] == 1 and not first.json()["current_use"]["review_complete"]
    accepted_request = {**request, "expected_previous_revision_id": first_id}
    key = uuid4().hex
    pending = invoke(reviewer, SCRIPT_REVIEW_TOOL, {**accepted_request, "confirmed_by_user": True}, key=key)
    assert pending.json()["status"] == "waiting_confirmation" and count(v, Review) == 1
    command = completed(confirm(reviewer, pending.json()))
    assert completed(invoke(reviewer, SCRIPT_REVIEW_TOOL, accepted_request, key=key))["id"] == command["id"]
    assert completed(confirm(reviewer, pending.json()))["id"] == command["id"] and count(v, Review) == 2
    second_id = command["result"]["object_refs"][0].split(":", 1)[1]
    current = read_script_review(v, second_id).json()
    assert current["current_use"] == {"review_current": True, "review_complete": True, "execution_authorized": False}
    assert current["assessment"]["automated_count"] == current["assessment"]["executed_on_target_count"] == current["assessment"]["passed_count"] == 0
    assert read_draft(v, generated).json() == draft and len(v["script_calls"]) == 1
    observed = completed(invoke(reviewer, SCRIPT_REVIEW_QUERY_TOOL, query))
    assert observed["result"]["automation_script_review"]["review_complete"]
    with actor_scope(UserProfile.model_validate(v["member"])):
        assert app.state.container.tool_evidence.describe(observed["id"], v["project_id"]) == observed["result"]["automation_script_review"]
    stale = submit_script_review(reviewer, accepted_request)
    assert stale.status_code == 200 and stale.json()["status"] == "failed" and count(v, Review) == 2
    withdrawn = completed(submit_script_review(reviewer, {**request, "expected_previous_revision_id": second_id,
        "decision": "withdraw", "actions": None, "assertions": None}))
    third_id = withdrawn["result"]["object_refs"][0].split(":", 1)[1]
    assert read_script_review(v, third_id).json()["revision"]["status"] == "withdrawn"
    assert read_script_review(v, second_id).json()["assessment"] == current["assessment"]
    assert not read_script_review(v, second_id).json()["current_use"]["review_complete"]
    with actor_scope(UserProfile.model_validate(v["member"])):
        with pytest.raises(PlatformApplicationError):
            app.state.container.tool_evidence.describe(observed["id"], v["project_id"])
    for statement in (update(Review).values(status="withdrawn"), delete(Review)):
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as session:
                session.execute(statement.where(Review.project_id == v["project_id"]))
    with session_scope() as session:
        audits = session.scalars(select(AuditEventRecord).where(AuditEventRecord.action == "quality.automation.script_reviewed",
            AuditEventRecord.tool_invocation_id.in_([first_command["id"], command["id"], withdrawn["id"]]))).all()
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id.in_([first_id, second_id, third_id]),
            SSEEventOutboxRecord.event_type == "quality.automation.script_reviewed")).all()
        assert len(audits) == len(events) == 3
        assert {row.status for row in audits} == {"reviewed", "withdrawn"}
        assert all(event.event_payload["query_keys"] == [["automation-script-reviews", v["project_id"], request["script_revision_id"]]] for event in events)
        assert "Independent protocol review" not in json.dumps([event.event_payload for event in events])
    # Reading an unrelated command must still deserialize the complete audit
    # history without turning a valid independent review into a server error.
    audit_history = v["client"].get("/v1/audit-events", headers=v["headers"],
        params={"tool_invocation_id": command["id"]})
    assert audit_history.status_code == 200, audit_history.text
    assert any(row["status"] == "reviewed" and row["action"] == "quality.automation.script_reviewed"
        for row in audit_history.json())
    restrict_source(v)
    forbidden = read_script_review(v, second_id, headers=v["member_headers"])
    assert forbidden.status_code == 403 and "HTTP 400" not in forbidden.text
    assert read_script_review(v, second_id).status_code == 200 and len(v["script_calls"]) == 1


def test_script_review_outbox_failure_rolls_back_review_and_source_change_blocks_commit(native_scripts, monkeypatch):
    v = native_scripts
    _, response = run_confirmed(v)
    draft = read_draft(v, completed(response)).json()
    request = script_review_request(v, draft)
    reviewer = independent_reviewer(v)
    original = EventOutboxRepository.append
    def fail(self, event, **kwargs):
        if event.event_type == "quality.automation.script_reviewed":
            raise RuntimeError("private injected script review outbox failure")
        return original(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    failed = submit_script_review(reviewer, request)
    assert failed.status_code == 200 and failed.json()["status"] == "failed", failed.text
    assert "private injected" not in failed.text and count(v, Review) == 0 and len(v["script_calls"]) == 1
    with session_scope() as session:
        assert not session.scalars(select(AuditEventRecord).where(AuditEventRecord.tool_invocation_id == failed.json()["id"],
            AuditEventRecord.action == "quality.automation.script_reviewed")).all()
    monkeypatch.setattr(EventOutboxRepository, "append", original)
    service = app.state.container.automation_script_reviews
    put = service.artifacts.put
    def revoke_after_archive(project, payload):
        result = put(project, payload)
        restrict_source(v)
        return result
    monkeypatch.setattr(service.artifacts, "put", revoke_after_archive)
    changed = submit_script_review(reviewer, request)
    assert changed.status_code == 200 and changed.json()["status"] == "failed", changed.text
    assert count(v, Review) == 0 and len(v["script_calls"]) == 1


def test_script_review_corrupt_history_is_hidden_and_cannot_be_repaired_by_new_write(native_scripts, monkeypatch):
    v = native_scripts
    _, generated = run_confirmed(v)
    draft = read_draft(v, completed(generated)).json()
    reviewer = independent_reviewer(v)
    request = script_review_request(v, draft)
    first = completed(submit_script_review(reviewer, request))
    ident = first["result"]["object_refs"][0].split(":", 1)[1]
    service = app.state.container.automation_script_reviews
    original = service.artifacts.read

    def corrupt(*args):
        value = original(*args)
        value["request"]["reason"] = "private corrupt review body must not leak"
        return value

    monkeypatch.setattr(service.artifacts, "read", corrupt)
    response = read_script_review(v, ident)
    assert response.status_code == 502 and "private corrupt" not in response.text, response.text
    second = submit_script_review(reviewer, {**request, "expected_previous_revision_id": ident})
    assert second.status_code == 200 and second.json()["status"] == "failed", second.text
    assert "private corrupt" not in second.text and count(v, Review) == 1
    monkeypatch.setattr(service.artifacts, "read", original)
    assert read_script_review(v, ident).status_code == 200 and read_draft(v, completed(generated)).json() == draft
    assert len(v["script_calls"]) == 1


def test_competing_canonical_script_reviews_commit_one_head_without_rewriting_history(native_scripts, monkeypatch):
    v = native_scripts
    _, generated = run_confirmed(v)
    draft = read_draft(v, completed(generated)).json()
    reviewer = independent_reviewer(v)
    request = script_review_request(v, draft)
    commands = [invoke(reviewer, SCRIPT_REVIEW_TOOL, {**request, "reason": f"Independent competing review {index}"}, key=uuid4().hex)
        for index in range(2)]
    assert all(command.status_code == 200 and command.json()["status"] == "waiting_confirmation" for command in commands)
    artifacts = app.state.container.automation_script_reviews.artifacts
    original, barrier = artifacts.put, Barrier(2)

    def meet_after_archive(*args):
        result = original(*args)
        barrier.wait(timeout=120)
        return result

    monkeypatch.setattr(artifacts, "put", meet_after_archive)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda command: confirm(reviewer, command.json()), commands))
    assert all(response.status_code == 200 for response in responses)
    assert sorted(response.json()["status"] for response in responses) == ["completed", "failed"]
    assert count(v, Review) == 1 and len(v["script_calls"]) == 1
    winner = next(response.json() for response in responses if response.json()["status"] == "completed")
    loser = next(response.json() for response in responses if response.json()["status"] == "failed")
    ident = winner["result"]["object_refs"][0].split(":", 1)[1]
    assert read_script_review(v, ident).json()["revision"]["sequence"] == 1
    assert read_draft(v, completed(generated)).json() == draft
    with session_scope() as session:
        assert not session.scalars(select(AuditEventRecord).where(AuditEventRecord.tool_invocation_id == loser["id"],
            AuditEventRecord.action == "quality.automation.script_reviewed")).all()


def test_script_review_foreign_project_fk_and_populated_downgrade_refuse_history_loss(native_scripts):
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from apps.api.app.infrastructure.persistence.database import engine
    v = native_scripts
    _, generated = run_confirmed(v)
    draft = read_draft(v, completed(generated)).json()
    reviewer = independent_reviewer(v)
    request = script_review_request(v, draft)
    reviewed = completed(submit_script_review(reviewer, request))
    ident = reviewed["result"]["object_refs"][0].split(":", 1)[1]
    other = v["client"].post("/v1/projects", headers=v["headers"], json={"name": "Foreign review namespace"}).json()["id"]
    url = f"/v1/projects/{other}/quality/automation-script-reviews/{ident}"
    assert v["client"].get(url, headers=v["headers"]).status_code == 404
    command_id = seed_internal_command(v)
    with pytest.raises(IntegrityError, match="foreign key constraint"):
        with session_scope() as session:
            first = session.get(Review, ident)
            payload = {**deepcopy(first.payload), "project_id": other, "revision_id": uuid4().hex,
                "invocation_id": command_id, "previous_revision_id": ident, "sequence": 2}
            session.add(Review(**{key: payload[key] for key in ("revision_id", "project_id", "script_revision_id",
                "previous_revision_id", "sequence", "status", "invocation_id")}, artifact_ref=first.artifact_ref,
                payload=payload, content_hash=acceptance_digest(payload)))
    migration = importlib.import_module("apps.api.migrations.versions.0099_automation_script_reviews")
    with engine.begin() as connection:
        original = migration.op
        try:
            migration.op = Operations(MigrationContext.configure(connection))
            with pytest.raises(RuntimeError, match="populated automation script review"):
                migration.downgrade()
        finally:
            migration.op = original
    assert count(v, Review) == 1 and read_script_review(v, ident).status_code == 200 and len(v["script_calls"]) == 1


def test_script_review_rejects_expired_future_and_other_actor_internal_confirmation(native_scripts):
    from apps.api.app.application.quality_loop.automation_script_review_inputs import ScriptReviewRequest
    from apps.api.app.domain.quality_loop.automation_script_review import ScriptReviewIntegrityError
    v = native_scripts
    _, generated = run_confirmed(v)
    draft = read_draft(v, completed(generated)).json()
    reviewer = independent_reviewer(v)
    request = ScriptReviewRequest.model_validate(script_review_request(v, draft))
    service = app.state.container.automation_script_reviews
    for fault in ("expired", "future", "other_actor"):
        now, ident = datetime.now(timezone.utc), uuid4().hex
        confirmed = now - timedelta(minutes=16) if fault == "expired" else now + timedelta(minutes=1) if fault == "future" else now
        actor = v["owner"]["id"] if fault == "other_actor" else v["member"]["id"]
        with session_scope() as session:
            session.add(ToolInvocationRecord(id=ident, tool_id=SCRIPT_REVIEW_TOOL, status="running",
                conversation_id=reviewer["conversation"].json()["id"],
                summary="Internal negative consent specimen, not a public confirmation proof",
                input_payload={**request.model_dump(mode="json"), "confirmed_by_user": True,
                    "confirmed_actor_id": actor, "confirmed_at": confirmed.isoformat()}))
        with actor_scope(UserProfile.model_validate(v["member"])):
            with pytest.raises(ScriptReviewIntegrityError):
                service.review(request, invocation_id=ident, recorded_at=now.isoformat())
        assert count(v, Review) == 0 and len(v["script_calls"]) == 1


def test_preview_is_readonly_private_and_agent_receipt_is_revalidated(native_scripts, monkeypatch):
    v = native_scripts
    baseline = count(v, LLMCallRecord)
    response = v["client"].post(f"/v1/projects/{v['project_id']}/quality/automation-script-previews",
        headers=v["headers"], json=v["script_selection"].model_dump(mode="json"))
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store", response.text
    assert response.json() == v["script_preview"] and len(response.json()["request"]["execution"]["source_binding_ids"]) == 3
    result = completed(invoke(v, SCRIPT_PREVIEW_TOOL, v["script_selection"].model_dump(mode="json")))
    assert result["result"]["automation_execution_preview"] == v["script_preview"]
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(result["id"], v["project_id"]) == v["script_preview"]
    assert count(v, LLMCallRecord) == baseline and not v["script_calls"]
    assert count(v, Reservation) == count(v, Reply) == count(v, Result) == 0
    for private in ("HTTP 400", "native-script-transport-fixture-key", "raw_output", "artifact_ref"):
        assert private not in response.text + json.dumps(result)
    def changed(binding):
        return SimpleNamespace(policy=policy(binding, input_nanos_per_token=1001), count=lambda *args: 32000)
    monkeypatch.setattr(v["script_service"].policies, "resolve", changed)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises((PlatformApplicationError, ValueError)):
            app.state.container.tool_evidence.describe(result["id"], v["project_id"])
    assert not v["script_calls"]


def test_canonical_confirm_archives_native_reply_and_immutable_script_with_atomic_events(native_scripts):
    v = native_scripts
    key = uuid4().hex
    pending = invoke(v, SCRIPT_TOOL, {**v["script_preview"]["request"], "confirmed_by_user": True}, key=key)
    assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
    assert not v["script_calls"] and count(v, Reservation) == 0
    done = completed(confirm(v, pending.json()))
    assert len(v["script_calls"]) == 1 and count(v, Reservation) == count(v, Reply) == count(v, Result) == 1
    assert completed(invoke(v, SCRIPT_TOOL, v["script_preview"]["request"], key=key))["id"] == done["id"]
    assert completed(confirm(v, pending.json()))["id"] == done["id"] and len(v["script_calls"]) == 1
    read = read_draft(v, done)
    assert read.status_code == 200 and read.headers["cache-control"] == "private, no-store", read.text
    view, payload = read.json(), read.json()["result"]
    assert payload["request"] == v["script_preview"]["request"] and payload["prepared"] == v["script_sent"][0]
    assert payload["status"] == "draft" and payload["proposal"]["review_status"] == "pending_independent_review"
    assert all(script["kind"] == "http" for script in payload["proposal"]["scripts"])
    assert payload["proposal"]["script_count"] == len(payload["prepared"]["cases"])
    assert payload["proposal"]["automated_count"] == payload["proposal"]["executed_on_target_count"] == payload["proposal"]["passed_count"] == 0
    assert view["current_use"] == {"input_current": True, "execution_authorized": False}
    assert acceptance_digest(payload) == view["metadata"]["artifact_hash"] and "artifact_ref" not in read.text
    assert "native-script-transport-fixture-key" not in read.text
    calls = script_calls(v)
    assert len(calls) == 1 and calls[0].usage_source == "provider" and calls[0].outcome == "success"
    assert calls[0].input_token_count == 123 and calls[0].output_token_count == 45
    assert calls[0].response_hash == response_digest(payload["raw_output"])
    with session_scope() as session:
        reservation = session.get(Reservation, done["id"])
        assert reservation.payload["actor_id"] == v["owner"]["id"] and reservation.payload["reservation"]["reserved_tokens"] == 136192
        receipt = session.get(Reply, done["id"])
        assert receipt.payload["usage"]["cost_nanos_at_policy_rates"] == 168000
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == done["id"],
            SSEEventOutboxRecord.event_type.in_(["quality.automation.call_reserved", "quality.automation.reply_archived", "quality.automation.draft_saved"]))).all()
        audits = session.scalars(select(AuditEventRecord).where(AuditEventRecord.entity_id == done["id"],
            AuditEventRecord.action.in_(["quality.automation.call_reserved", "quality.automation.reply_archived", "quality.automation.draft_saved"]))).all()
        assert len(events) == len(audits) == 3
        assert all(event.event_payload["query_keys"] == [["automation-script-revisions", v["project_id"]]] for event in events)
        persisted = json.dumps(reservation.payload) + json.dumps([event.event_payload for event in events]) + json.dumps(done)
        assert "HTTP 400" not in persisted and "native-script-transport-fixture-key" not in persisted
    for model in (Reservation, Reply, Result):
        for statement in (delete(model), update(model).values(project_id="forged")):
            with pytest.raises(IntegrityError, match="append-only"):
                with session_scope() as session:
                    session.execute(statement.where(model.project_id == v["project_id"]))
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from apps.api.app.infrastructure.persistence.database import engine
    migration = importlib.import_module("apps.api.migrations.versions.0098_automation_script_drafts")
    with engine.begin() as connection:
        original = migration.op
        try:
            migration.op = Operations(MigrationContext.configure(connection))
            with pytest.raises(RuntimeError, match="populated automation"):
                migration.downgrade()
        finally:
            migration.op = original


def test_readers_can_read_but_not_egress_and_source_revocation_hides_history(native_scripts):
    v = native_scripts
    _, response = run_confirmed(v)
    done = completed(response)
    grant_member(v)
    assert read_draft(v, done, headers=v["member_headers"]).status_code == 200
    preview_url = f"/v1/projects/{v['project_id']}/quality/automation-script-previews"
    assert v["client"].post(preview_url, headers=v["member_headers"], json=v["script_selection"].model_dump(mode="json")).status_code == 403
    assert v["client"].post(preview_url, json=v["script_selection"].model_dump(mode="json")).status_code == 401
    other = v["client"].post("/v1/projects", headers=v["headers"], json={"name": "Unrelated script project"}).json()["id"]
    ident = done["result"]["object_refs"][0].split(":", 1)[1]
    assert v["client"].get(f"/v1/projects/{other}/quality/automation-script-revisions/{ident}", headers=v["headers"]).status_code == 404
    assert v["client"].post(preview_url.replace(v["project_id"], other), headers=v["headers"],
        json=v["script_selection"].model_dump(mode="json")).status_code == 422
    restrict_source(v)
    denied = read_draft(v, done, headers=v["member_headers"])
    assert denied.status_code == 403 and "raw_output" not in denied.text and "HTTP 400" not in denied.text
    assert read_draft(v, done).status_code == 200 and len(v["script_calls"]) == 1


@pytest.mark.parametrize("dependency", ["mapping", "scope", "model", "policy"])
def test_changed_dependency_prevents_reservation_and_source_egress(native_scripts, monkeypatch, dependency):
    v = native_scripts
    if dependency == "mapping":
        completed(mapping_submit(v, {**v["mapping_request"], "expected_previous_revision_id": v["script_selection"].mapping_revision_id,
            "decision": "withdraw", "mappings": None}))
    elif dependency == "scope":
        completed(scope_submit(v, {**v["scope_request"], "expected_previous_revision_id": v["execution"]["request"].scope_revision_id,
            "decision": "withdraw", "contract": None}))
    elif dependency == "model":
        v["script_service"].profiles.repository.save_model_config(v["script_config"].model_copy(update={"model_name": "changed"}), v["script_encrypted"])
    else:
        monkeypatch.setattr(v["script_service"].policies, "resolve", lambda binding: SimpleNamespace(
            policy=policy(binding, context_tokens=127999), count=lambda *args: 32000))
    _, response = run_confirmed(v)
    assert response.status_code == 200 and response.json()["status"] == "failed", response.text
    assert not v["script_calls"] and not script_calls(v)
    assert count(v, Reservation) == count(v, Reply) == count(v, Result) == 0


def test_expired_confirmation_cannot_reserve_or_send(native_scripts):
    v = native_scripts
    with pytest.raises(TestDesignResultIntegrityError, match="expired"):
        execute_internal(v, seed_internal_command(v, expired=True))
    assert count(v, Reservation) == 0 and not v["script_calls"]


def test_database_refuses_cross_project_generation_and_mapping_reservation(native_scripts):
    v = native_scripts
    _, response = run_confirmed(v)
    done = completed(response)
    ident = seed_internal_command(v)
    with session_scope() as session:
        original = session.get(Reservation, done["id"])
        payload = {**deepcopy(original.payload), "project_id": "foreign-project", "invocation_id": ident, "call_id": uuid4().hex}
        generation_id = original.generation_id
    with pytest.raises(IntegrityError):
        with session_scope() as session:
            session.add(Reservation(invocation_id=ident, project_id="foreign-project", generation_id=generation_id,
                mapping_revision_id=v["script_selection"].mapping_revision_id, call_id=payload["call_id"],
                payload=payload, content_hash=acceptance_digest(payload)))
    assert count(v, Reservation) == 1 and len(v["script_calls"]) == 1


@pytest.mark.parametrize("fault", ["disconnect", "missing_usage", "over_budget", "invalid_dsl"])
def test_failed_or_invalid_model_call_is_not_resent_and_never_grants_execution(native_scripts, fault):
    v = native_scripts
    v["script_transport"].fault = fault
    pending, response = run_confirmed(v)
    assert response.status_code == 200 and response.json()["status"] == "failed", response.text
    assert count(v, Reservation) == 1 and count(v, Result) == 0 and len(v["script_calls"]) == 1
    assert confirm(v, pending).json()["status"] == "failed" and len(v["script_calls"]) == 1
    assert count(v, Reply) == (1 if fault == "invalid_dsl" else 0)
    native = script_calls(v)
    assert len(native) == 1 and native[0].outcome == ("success" if fault == "invalid_dsl" else "error")
    v["script_transport"].fault = None
    with pytest.raises(ValueError if fault == "invalid_dsl" else GenerationOutcomeUnknown):
        execute_internal(v, pending["id"])
    assert len(v["script_calls"]) == 1 and count(v, Result) == 0


def test_outbox_rollback_keeps_native_charge_and_replays_without_resending(native_scripts, monkeypatch):
    v = native_scripts
    ident = seed_internal_command(v)
    original = EventOutboxRepository.append
    def fail(self, event, **kwargs):
        if event.event_type == "quality.automation.draft_saved":
            raise RuntimeError("injected automation outbox transaction failure")
        return original(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    with pytest.raises(RuntimeError, match="transaction failure"):
        execute_internal(v, ident)
    assert count(v, Reservation) == count(v, Reply) == 1 and count(v, Result) == 0 and len(v["script_calls"]) == 1
    with session_scope() as session:
        assert not session.scalars(select(AuditEventRecord).where(AuditEventRecord.entity_id == ident,
            AuditEventRecord.action == "quality.automation.draft_saved")).all()
        assert not session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == ident,
            SSEEventOutboxRecord.event_type == "quality.automation.draft_saved")).all()
    monkeypatch.setattr(EventOutboxRepository, "append", original)
    metadata = execute_internal(v, ident)
    assert metadata["status"] == "draft" and execute_internal(v, ident) == metadata
    assert count(v, Result) == 1 and len(v["script_calls"]) == len(script_calls(v)) == 1


@pytest.mark.parametrize("dependency", ["mapping", "scope"])
def test_stale_history_preserves_original_bytes_but_is_not_current(native_scripts, dependency):
    v = native_scripts
    _, response = run_confirmed(v)
    done = completed(response)
    before = read_draft(v, done).json()
    if dependency == "mapping":
        completed(mapping_submit(v, {**v["mapping_request"], "expected_previous_revision_id": v["script_selection"].mapping_revision_id,
            "decision": "withdraw", "mappings": None}))
    else:
        completed(scope_submit(v, {**v["scope_request"], "expected_previous_revision_id": v["execution"]["request"].scope_revision_id,
            "decision": "withdraw", "contract": None}))
    after = read_draft(v, done)
    assert after.status_code == 200, after.text
    assert after.json()["result"] == before["result"] and after.json()["metadata"] == before["metadata"]
    assert after.json()["current_use"] == {"input_current": False, "execution_authorized": False}
    assert len(v["script_calls"]) == 1


def test_model_changes_do_not_rewrite_original_script_and_native_archive_corruption_is_hidden(native_scripts, monkeypatch):
    v = native_scripts
    _, response = run_confirmed(v)
    done = completed(response)
    original_view = read_draft(v, done).json()
    v["script_service"].profiles.repository.save_model_config(v["script_config"].model_copy(update={"model_name": "replacement"}), v["script_encrypted"])
    assert read_draft(v, done).json() == original_view
    original = v["script_service"].replies.read
    def corrupt(*args):
        value = original(*args)
        value["content"] = "secret-corrupted-response"
        return value
    monkeypatch.setattr(v["script_service"].replies, "read", corrupt)
    result = read_draft(v, done)
    assert result.status_code == 502 and "secret-corrupted-response" not in result.text
    assert len(v["script_calls"]) == 1


def test_fixed_exweb_native_script_draft_preserves_source_case_step_and_oracle_pins(native_scripts):
    v = native_scripts
    _, response = run_confirmed(v)
    done = completed(response)
    read = read_draft(v, done)
    assert read.status_code == 200, read.text
    payload = read.json()["result"]
    prepared = payload["prepared"]
    source_pin, member_count = verify_fixed_exweb_archive(v, prepared)
    assert prepared == v["script_sent"][0] and len(v["script_calls"]) == 1
    assert prepared["context_pin"] == v["original_result"]["result"]["context_pin"]
    assert prepared["scope_pin"] == v["original_result"]["result"]["scope_pin"]
    assert prepared["mapping_pin"]["artifact_hash"] == v["script_mapping"]["revision"]["artifact_hash"]
    originals = {case["case_id"]: case for case in prepared["cases"]}
    for script in payload["proposal"]["scripts"]:
        case = originals[script["case_id"]]
        assert script["case_digest"] == acceptance_digest(case)
        assert {index for action in script["actions"] for index in action["source_step_indices"]} == set(range(len(case["steps"])))
        assert {(item["row_id"], item["oracle_digest"], item["source_step_index"]) for item in script["assertions"]} == {
            (item["row_id"], item["oracle_digest"], item["step_index"]) for item in case["assertions"]}
    assert payload["proposal"]["automated_count"] == payload["proposal"]["executed_on_target_count"] == payload["proposal"]["passed_count"] == 0
    report = os.getenv("EXWEB_AUTOMATION_SCRIPT_REPORT")
    if report:
        with Path(report).open("x") as output:
            json.dump({"schema": "nasus.exweb-native-script-provenance-verification.v1", "verified_at": datetime.now(timezone.utc).isoformat(),
                "repository": "https://github.com/kunben-duck/exweb.git", "commit": v["exweb_commit"], "tree_hash": v["exweb_tree_hash"],
                "exweb_source_pin": source_pin, "exweb_file_count": 126, "exweb_frozen_code_member_count": member_count,
                "all_126_archived_blobs_equal_fixed_git_tree": True, "postgres_private_minio": True,
                "canonical_invocation_id": done["id"], "script_revision": read.json()["metadata"],
                "context_pin": prepared["context_pin"], "scope_pin": prepared["scope_pin"], "generation_pin": prepared["generation_pin"],
                "mapping_pin": prepared["mapping_pin"], "input_digest": prepared["input_digest"],
                "constraint_denominator": prepared["constraint_denominator"], "obligation_denominator": prepared["obligation_denominator"],
                "all_original_cases_steps_oracles_preserved": True, "native_http_adapter_protocol_verified": True,
                "provider_transport": "explicit_httpx_mock_transport_not_external_model", "tokenizer": "explicit_policy_counter_specimen",
                "oracle_basis": "explicit_protocol_fixture_not_exweb_maintainer_approval", "additional_code_source": "isolated Orders protocol fixture",
                "independent_script_review_verified": False, "target_execution_verified": False, "external_model_verified": False,
                "all_five_context_purposes_verified": False, "full_quality_closure_verified": False}, output, indent=2)


def test_fixed_exweb_native_script_review_keeps_original_oracles_and_zero_execution(native_scripts):
    v = native_scripts
    _, response = run_confirmed(v)
    generated = completed(response)
    draft = read_draft(v, generated).json()
    source_pin, member_count = verify_fixed_exweb_archive(v, draft["result"]["prepared"])
    reviewer = independent_reviewer(v)
    history_input = {"project_id": v["project_id"], "mapping_revision_id": v["script_selection"].mapping_revision_id,
        "mapping_artifact_hash": v["script_selection"].mapping_artifact_hash, "after_id": "", "limit": 10}
    history = v["client"].get(f"/v1/projects/{v['project_id']}/quality/automation-script-history",
        headers=reviewer["headers"], params={key: value for key, value in history_input.items() if key != "project_id"})
    assert history.status_code == 200 and history.headers["cache-control"] == "private, no-store", history.text
    page = history.json()
    assert page["request"] == history_input and page["next_after_id"] is None and len(page["items"]) == 1
    assert page["items"][0]["script_revision_id"] == draft["metadata"]["script_revision_id"]
    assert page["items"][0]["artifact_hash"] == draft["metadata"]["artifact_hash"]
    assert not page["generation_authorized"] and not page["execution_authorized"]
    observed = completed(invoke(reviewer, SCRIPT_HISTORY_TOOL, history_input))
    assert observed["result"]["automation_script_history"] == page
    with actor_scope(UserProfile.model_validate(v["member"])):
        assert app.state.container.tool_evidence.describe(observed["id"], v["project_id"]) == page
    assert len(v["script_calls"]) == 1
    request = script_review_request(v, draft)
    reviewed = completed(submit_script_review(reviewer, request))
    ident = reviewed["result"]["object_refs"][0].split(":", 1)[1]
    response = read_script_review(v, ident)
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["revision"]["authority_actor"] == v["member"]["id"] != draft["result"]["actor_id"]
    assert view["current_use"] == {"review_current": True, "review_complete": True, "execution_authorized": False}
    assert view["script_pin"] == app.state.container.automation_script_reviews._pin(draft)
    assert view["request"]["actions"] == request["actions"] and view["request"]["assertions"] == request["assertions"]
    assert view["assessment"]["automated_count"] == view["assessment"]["executed_on_target_count"] == view["assessment"]["passed_count"] == 0
    assert read_draft(v, generated).json() == draft and len(v["script_calls"]) == 1
    from apps.api.app.infrastructure.persistence.automation_provenance_v1 import AutomationProvenanceProjectorV1
    from apps.api.app.infrastructure.persistence.derivation_registry_models import DerivationRegistryRecord
    with session_scope() as session:
        projector = AutomationProvenanceProjectorV1()
        script_row = session.get(Result, draft["metadata"]["script_revision_id"])
        script_ancestry = projector.verify(session, script_row)
        review_ancestry = projector.reviews(session, script_row, [session.get(Review, ident)])[0]
        assert script_ancestry.artifact_hash == draft["metadata"]["artifact_hash"]
        assert review_ancestry.artifact_hash == view["revision"]["artifact_hash"]
        assert review_ancestry.parents == ((script_ancestry.key, script_ancestry.artifact_hash, script_ancestry.content_hash),)
        for key, artifact_hash, registration_hash in script_ancestry.parents:
            parent = session.get(DerivationRegistryRecord, (v["project_id"], key))
            assert parent.context_id == script_ancestry.context_id
            assert parent.artifact_hash == artifact_hash and parent.content_hash == registration_hash
        assert {key for key, _, _ in script_ancestry.parents if key.startswith("case:")} == {
            "case:" + draft["result"]["prepared"]["generation_pin"]["generation_id"] + "/" + case_id
            for case_id in draft["result"]["prepared"]["selected_case_ids"]}
    report = os.getenv("EXWEB_AUTOMATION_SCRIPT_REVIEW_REPORT")
    if report:
        with Path(report).open("x") as output:
            json.dump({"schema": "nasus.exweb-script-review-provenance-verification.v1", "verified_at": datetime.now(timezone.utc).isoformat(),
                "repository": "https://github.com/kunben-duck/exweb.git", "commit": v["exweb_commit"], "tree_hash": v["exweb_tree_hash"],
                "exweb_source_pin": source_pin, "exweb_file_count": 126, "exweb_frozen_code_member_count": member_count,
                "all_126_archived_blobs_equal_fixed_git_tree": True, "postgres_private_minio": True,
                "script_revision": draft["metadata"], "independent_review_revision": view["revision"],
                "script_pin": view["script_pin"], "assessment": view["assessment"],
                "canonical_history_query_id": observed["id"], "readonly_history_page": page,
                "independent_reviewer_http_and_agent_history_verified": True,
                "independent_canonical_review_protocol_verified": True, "original_script_unchanged": True,
                "reviewer_is_different_from_generating_actor": True,
                "script_provenance": script_ancestry.payload_v1, "script_provenance_hash": script_ancestry.content_hash,
                "review_provenance": review_ancestry.payload_v1, "review_provenance_hash": review_ancestry.content_hash,
                "registered_script_and_review_ancestry_verified": True,
                "unified_project_delta_dag_verified": False, "nasus_run_plan_verified": False,
                "provider_transport": "explicit_httpx_mock_transport_not_external_model", "tokenizer": "explicit_policy_counter_specimen",
                "oracle_basis": "explicit_protocol_fixture_not_exweb_maintainer_approval", "additional_code_source": "isolated Orders protocol fixture",
                "business_oracle_equivalence_verified": False, "target_execution_verified": False, "external_model_verified": False,
                "all_five_context_purposes_verified": False, "full_quality_closure_verified": False}, output, indent=2)
