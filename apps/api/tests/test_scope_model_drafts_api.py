"""PG/MinIO protocol regressions; these do not replace retained live acceptance."""
from copy import deepcopy
from datetime import timedelta
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from apps.api.app.infrastructure.persistence import scope_draft_repository
from apps.api.app.infrastructure.persistence.db_models import LLMCallRecord

from apps.api.app.infrastructure.llm.test_design_model import HTTPTestDesignModel
from apps.api.app.infrastructure.persistence.scope_draft_models import ScopeDraftEventRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_test_design_scope_api import design_scope, publication, documents, evidence_api, submit
from apps.api.tests.test_semantic_evaluations_api import completed, confirm, invoke
from apps.api.tests.test_generation_executor import budget, policy
from apps.api.tests.test_semantic_link_model import saved_config, native_reply
from apps.api.app.application.quality_loop.scope_draft_inputs import SCOPE_DRAFT_TOOL


@pytest.fixture
def model_scope(design_scope, monkeypatch):
    v = design_scope
    service = v["scope_service"].drafts
    config = saved_config(config_id=uuid4().hex)
    service.profiles.repository.save_model_config(config, service.profiles.secrets.encrypt_api_key("scope-transport-fixture"))
    monkeypatch.setattr(service.policies, "resolve", lambda binding: SimpleNamespace(policy=policy(binding), count=lambda *_: 4000))
    calls = []
    def handle(request):
        calls.append(request)
        prepared = json.loads(json.loads(request.content)["messages"][-1]["content"])["input"]
        contract = deepcopy(v["scope_request"]["contract"])
        contract["authority_basis"] = "model_suggestion"
        for example in contract["examples"]:
            example["positive"] = next(item["oracle"] for item in prepared["context"]["required_constraints"]
                if item["object_id"] == example["constraint_id"])
        return httpx.Response(200, json=native_reply("openai_compatible", json.dumps({
            "input_digest": prepared["input_digest"], "contract": contract})))
    monkeypatch.setattr(service, "provider", HTTPTestDesignModel(transport=httpx.MockTransport(handle)))
    selection = {key: v["scope_request"][key] for key in ("project_id", "context_id", "context_artifact_hash")}
    selection.update(model_config_id=config.config_id, budget=budget().model_dump(mode="json"))
    url = f"/v1/projects/{v['project_id']}/quality/scope-drafts"
    preview = v["client"].post(url + "/preview", headers=v["headers"], json=selection)
    assert preview.status_code == 200, preview.text
    v.update(draft_request=preview.json()["request"], draft_url=url, draft_calls=calls)
    return v


def test_confirmed_native_draft_is_durable_and_not_self_approved(model_scope):
    v = model_scope
    # The Context panel submits an actor-scoped command, not a chat-scoped one.
    pending_response = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "tool_id": SCOPE_DRAFT_TOOL, "input": v["draft_request"], "idempotency_key": uuid4().hex})
    assert pending_response.status_code == 200
    pending = pending_response.json()
    assert pending["status"] == "waiting_confirmation" and not v["draft_calls"]
    recovered = v["client"].get("/v1/tool-invocations/resolve", headers=v["headers"], params={
        "project_id": v["project_id"], "tool_id": SCOPE_DRAFT_TOOL, "request_key": pending["input_payload"]["idempotency_key"]})
    assert recovered.status_code == 200 and recovered.json()["id"] == pending["id"]
    assert recovered.json()["status"] == "waiting_confirmation" and not v["draft_calls"]
    command = completed(confirm(v, pending))
    response = v["client"].get(v["draft_url"] + "/" + command["id"], headers=v["headers"])
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft["contract"]["authority_basis"] == "model_suggestion" and not draft["generation_authorized"]
    assert len(v["draft_calls"]) == 1
    audit = v["client"].get("/v1/audit-events", params={"tool_invocation_id": command["id"]}, headers=v["headers"])
    assert audit.status_code == 200, audit.text
    assert any(row["action"] == "quality.scope_draft.replied" and row["status"] == "recorded" for row in audit.json())
    completed(confirm(v, pending))
    assert len(v["draft_calls"]) == 1
    denied = submit(v, {**v["scope_request"], "contract": {**draft["contract"], "authority_basis": "user_confirmed_test_design_scope"},
        "draft_ref": {"invocation_id": command["id"], "artifact_hash": draft["artifact_hash"]}})
    assert denied.status_code in (403, 409) or denied.json()["status"] == "failed", denied.text
    with session_scope() as session:
        rows = session.scalars(select(ScopeDraftEventRecord).where(ScopeDraftEventRecord.invocation_id == command["id"])).all()
        assert {row.kind for row in rows} == {"reserved", "replied", "draft"}
        with pytest.raises(IntegrityError, match="append-only"):
            with session.begin_nested():
                session.execute(delete(ScopeDraftEventRecord).where(ScopeDraftEventRecord.invocation_id == command["id"]))
    member_url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(member_url, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    reviewed = submit(v, {**v["scope_request"], "contract": {**draft["contract"], "authority_basis": "user_confirmed_test_design_scope"},
        "draft_ref": {"invocation_id": command["id"], "artifact_hash": draft["artifact_hash"]}}, headers=v["member_headers"])
    completed(reviewed)
    assert len(v["draft_calls"]) == 1


def test_unconfirmed_and_changed_scope_draft_never_calls_provider(model_scope):
    v = model_scope
    pending = invoke(v, SCOPE_DRAFT_TOOL, {**v["draft_request"], "confirmed_by_user": True}, key=uuid4().hex).json()
    assert pending["status"] == "waiting_confirmation" and not v["draft_calls"]
    pending = invoke(v, SCOPE_DRAFT_TOOL, {**v["draft_request"], "plan_digest": "sha256:" + "0" * 64}, key=uuid4().hex).json()
    response = confirm(v, pending)
    assert response.status_code != 200 or response.json()["status"] == "failed"
    assert not v["draft_calls"]
    assert v["client"].get(v["draft_url"], params={"context_id": v["draft_request"]["context_id"]}).status_code == 401


def test_expired_confirmation_has_no_reservation_or_provider_call(model_scope, monkeypatch):
    v = model_scope
    clock = scope_draft_repository.confirmation_time
    monkeypatch.setattr(scope_draft_repository, "confirmation_time", lambda session: clock(session) + timedelta(minutes=16))
    pending = invoke(v, SCOPE_DRAFT_TOOL, v["draft_request"], key=uuid4().hex).json()
    response = confirm(v, pending)
    assert response.status_code != 200 or response.json()["status"] == "failed"
    assert not v["draft_calls"]
    with session_scope() as session:
        assert session.scalar(select(ScopeDraftEventRecord).where(ScopeDraftEventRecord.invocation_id == pending["id"])) is None


def test_history_reverifies_native_call_and_current_source_permission(model_scope):
    from apps.api.tests.test_source_access_api import policy
    v = model_scope
    pending = invoke(v, SCOPE_DRAFT_TOOL, v["draft_request"], key=uuid4().hex).json()
    command = completed(confirm(v, pending))
    with session_scope() as session:
        call = session.scalar(select(LLMCallRecord).where(LLMCallRecord.tool_invocation_id == command["id"]))
        original = call.response_hash
        call.response_hash = "sha256:" + "0" * 64
    bad = v["client"].get(v["draft_url"] + "/" + command["id"], headers=v["headers"])
    assert bad.status_code == 502 and "contract" not in bad.json()
    with session_scope() as session:
        session.scalar(select(LLMCallRecord).where(LLMCallRecord.tool_invocation_id == command["id"])).response_hash = original
    member_url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(member_url, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    draft_url = v["draft_url"] + "/" + command["id"]
    receipt_url = "/v1/tool-invocations/" + command["id"]
    assert v["client"].get(draft_url, headers=v["member_headers"]).status_code == 200
    assert v["client"].get(receipt_url, headers=v["member_headers"]).status_code == 200
    policy(v)
    assert v["client"].get(draft_url, headers=v["member_headers"]).status_code == 403
    assert v["client"].get(receipt_url, headers=v["member_headers"]).status_code == 403
    assert v["client"].get(v["draft_url"], params={"context_id": v["draft_request"]["context_id"]}, headers=v["member_headers"]).status_code == 403
    # Source policy retains its existing administrator inspection rule.
    assert v["client"].get(draft_url, headers=v["headers"]).status_code == 200
