import json
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, update, delete
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.domain.system_image.semantic_review import SEMANTIC_REVIEW_TOOL
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.llm.semantic_link_model import HTTPSemanticLinkModel
from apps.api.app.infrastructure.persistence.semantic_review_models import SemanticAssertionRecord, SemanticDecisionRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, SSEEventOutboxRecord
from apps.api.tests.test_semantic_evaluations_api import semantic, documents, evidence_api, invoke, confirm, completed, count, unknown_output
from apps.api.tests.test_semantic_link_model import native_reply
from apps.api.tests.test_source_access_api import grant_member


def evaluate(v):
    result = completed(confirm(v, invoke(v, "system_image.links.evaluate", v["request"]).json()))
    subject = v["request"]["subject_object_ids"][0]
    url = f"{v['image_url']}/semantic-evaluations/{result['id']}/subjects/{subject}/reviews"
    response = v["client"].get(url, headers=v["headers"])
    assert response.status_code == 200, response.text
    body = response.json()
    assertion = body["assertion"]
    payload = {key: assertion[key] for key in ("project_id", "evaluation_id", "subject_object_id", "assertion_id", "assertion_digest", "evidence_digest")}
    payload.update(policy_revision=body["policy_revision"], expected_previous_decision_id=body["head_decision_id"], decision="reject", reason="No independently approved oracle")
    return url, payload, body


def submit(v, payload, *, key=None, headers=None):
    pending = invoke(v, SEMANTIC_REVIEW_TOOL, payload, key=key or uuid4().hex, headers=headers)
    if pending.status_code != 200 or pending.json()["status"] != "waiting_confirmation":
        return pending
    return v["client"].post(f"/v1/tool-invocations/{pending.json()['id']}/confirm", headers=headers or v["headers"])


def support(v, monkeypatch):
    def handle(request):
        v["calls"].append(request)
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        output = unknown_output(payload)
        for judgment in output["judgments"]:
            spans = [s for s in payload["excerpts"] if s["object_id"] in {judgment["subject_object_id"], judgment["target_object_id"]}]
            expected = next(s for s in spans if s["role"] == "expected_result")
            judgment.update(assessment="supports", unknowns=[], oracle={"span_id": expected["span_id"], "expected_value": expected["text"]},
                evidence=[{"span_id": s["span_id"], "start": 0, "end": len(s["text"]), "quote": s["text"]} for s in spans])
        return httpx.Response(200, json=native_reply("openai_compatible", json.dumps(output)))
    monkeypatch.setattr(v["service"], "provider", HTTPSemanticLinkModel(transport=httpx.MockTransport(handle)))


def test_confirmed_review_is_immutable_and_rerun_cannot_reset_human_rejection(semantic):
    v = semantic
    url, payload, original = evaluate(v)
    assert not original["assertion"]["can_accept"]
    assert submit(v, {**payload, "decision": "accept"}).json()["status"] == "failed"
    pending = invoke(v, SEMANTIC_REVIEW_TOOL, {**payload, "confirmed_by_user": True}, key="first-review").json()
    assert pending["status"] == "waiting_confirmation" and count(v, SemanticDecisionRecord) == 0
    done = completed(confirm(v, pending))
    assert completed(invoke(v, SEMANTIC_REVIEW_TOOL, payload, key="first-review"))["id"] == done["id"]
    assert count(v, SemanticDecisionRecord) == count(v, SemanticAssertionRecord) == 1
    page = v["client"].get(url, headers=v["headers"])
    assert page.headers["cache-control"] == "private, no-store"
    first = page.json()["items"][0]
    assert first["decision"] == "reject" and first["reviewer_actor"] == v["owner"]["id"]
    empty = v["client"].get(url, headers=v["headers"], params={"through_decision_id": ""}).json()
    assert empty["items"] == [] and empty["head"] is None and empty["total"] == 0
    assert v["client"].get(url, headers=v["headers"], params={"through_decision_id": "foreign"}).status_code == 404
    assert v["client"].get(url, headers=v["headers"], params={"offset": -1}).status_code == 422
    blocked = confirm(v, invoke(v, "system_image.links.evaluate", v["request"]).json())
    assert blocked.json()["status"] == "failed" and len(v["calls"]) == 1
    stale = submit(v, {**payload, "expected_previous_decision_id": None})
    assert stale.json()["result"]["followup_reason"] == "stale_semantic_decision"
    completed(submit(v, {**payload, "decision": "defer", "reason": "Human re-review permits new inference without acceptance",
        "expected_previous_decision_id": first["decision_id"]}))
    v["request"] = completed(invoke(v, "query.system_image.links.evaluation_preview", v["selection"]))["result"]["semantic_preview"]["request"]
    again_url, again_payload, again = evaluate(v)
    assert again["assertion"]["claim_id"] == original["assertion"]["claim_id"]
    assert again["assertion"]["assertion_id"] != original["assertion"]["assertion_id"]
    assert again["head_decision_id"] != first["decision_id"] and again["items"][0] == page.json()["items"][0]
    stale = submit(v, {**again_payload, "expected_previous_decision_id": None})
    assert stale.json()["result"]["followup_reason"] == "stale_semantic_decision"
    assert count(v, SemanticAssertionRecord) == 1
    completed(submit(v, {**again_payload, "decision": "defer", "reason": "New evidence still requires authority"}))
    updated = v["client"].get(again_url, headers=v["headers"], params={"limit": 1}).json()
    assert updated["total"] == 3 and updated["next_offset"] == 1
    historical = v["client"].get(url, headers=v["headers"], params={"through_decision_id": first["decision_id"]}).json()
    assert historical == page.json()
    assert len(v["calls"]) == 2  # Reviews themselves never call the model.
    assert original["assertion"] == v["client"].get(url, headers=v["headers"]).json()["assertion"]
    for model in (SemanticAssertionRecord, SemanticDecisionRecord):
        for statement in (delete(model).where(model.project_id == v["project_id"]),
                          update(model).where(model.project_id == v["project_id"]).values(content_hash="tampered")):
            with pytest.raises(IntegrityError, match="append-only"):
                with session_scope() as session:
                    session.execute(statement)
    with session_scope() as session:
        persisted = str(session.scalars(select(SemanticAssertionRecord.payload).where(SemanticAssertionRecord.project_id == v["project_id"])).all())
    for raw in ("HTTP 400", "Empty input", "private-provider-key", "local-object://"):
        assert raw not in persisted


def test_supported_relation_acceptance_has_cas_and_does_not_approve_authority(semantic, monkeypatch):
    v = semantic
    support(v, monkeypatch)
    url, payload, page = evaluate(v)
    assert page["assertion"]["can_accept"] and page["assertion"]["oracle_digest"]
    pending = [invoke(v, SEMANTIC_REVIEW_TOOL, {**payload, "decision": value}).json() for value in ("accept", "reject")]
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda item: confirm(v, item), pending))
    assert sorted(item.json()["status"] for item in outcomes) == ["completed", "failed"]
    assert count(v, SemanticDecisionRecord) == 1
    current = v["client"].get(url, headers=v["headers"]).json()
    completed(submit(v, {**payload, "decision": "accept", "expected_previous_decision_id": current["head_decision_id"]}))
    result = v["client"].get(url, headers=v["headers"]).json()
    assert result["items"][-1]["decision"] == "accept"
    assert result["assertion"]["authority_status"] == "pending_confirmation"
    assert result["assertion"]["status"] == "proposed" and result["publication"] == "not_in_image_membership"
    assert len(v["calls"]) == 1


def test_review_requires_role_scope_and_exact_pins(semantic):
    v = semantic
    url, payload, _ = evaluate(v)
    assert v["client"].get(url).status_code == 401
    grant_member(v)
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 200
    denied = submit(v, payload, headers=v["member_headers"])
    assert denied.status_code == 403 or denied.json()["status"] in {"failed", "denied"}
    for change in ({"assertion_digest": "sha256:" + "a" * 64}, {"evidence_digest": "sha256:" + "b" * 64},
                   {"evaluation_id": "foreign"}, {"assertion_id": "foreign"}, {"subject_object_id": "foreign"},
                   {"reviewer_actor": "forged"}, {"policy_revision": "all-versions"}, {"reason": " "}, {"expected_previous_decision_id": ""}):
        result = submit(v, {**payload, **change})
        assert result.status_code == 200 and result.json()["status"] == "failed", result.text
    assert count(v, SemanticDecisionRecord) == count(v, SemanticAssertionRecord) == 0
    other = v["client"].post("/v1/projects", headers=v["headers"], json={"name": "Other semantic project"}).json()["id"]
    assert submit(v, {**payload, "project_id": other}).json()["status"] == "failed"


def test_outbox_and_acl_races_roll_back_assertion_and_decision(semantic, monkeypatch):
    v = semantic
    url, payload, _ = evaluate(v)
    append = EventOutboxRepository.append
    def fail(self, event, **kwargs):
        if event.event_type == "system_image.semantic.reviewed":
            raise RuntimeError("injected outbox error")
        return append(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    assert submit(v, payload).json()["status"] == "failed"
    assert count(v, SemanticAssertionRecord) == count(v, SemanticDecisionRecord) == 0
    monkeypatch.setattr(EventOutboxRepository, "append", append)
    completed(submit(v, payload))
    grant_member(v)
    reviews = app.state.container.semantic_reviews
    original = reviews.repository.history
    def revoke(*args):
        result = original(*args)
        access = SourceAccessRepository()
        snapshot = access.load_snapshot(v["project_id"])
        access.set_policy(v["project_id"], snapshot.bindings[0].binding_id, SourceAccessRule("restricted"),
            expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="semantic-review-revoke")
        return result
    monkeypatch.setattr(reviews.repository, "history", revoke)
    denied = v["client"].get(url, headers=v["member_headers"])
    assert denied.status_code in {403, 409} and payload["reason"] not in denied.text


def test_review_canonical_payload_and_commit_scope_are_rechecked(semantic, monkeypatch):
    v = semantic
    url, payload, _ = evaluate(v)
    reviews = app.state.container.semantic_reviews
    record = reviews.repository.record
    def tamper(request, assertion, **kwargs):
        with session_scope() as session:
            invocation = session.get(ToolInvocationRecord, kwargs["invocation_id"])
            invocation.input_payload = {**invocation.input_payload, "reason": "forged repository payload"}
        return record(request, assertion, **kwargs)
    monkeypatch.setattr(reviews.repository, "record", tamper)
    assert submit(v, payload).json()["status"] == "failed"
    assert count(v, SemanticDecisionRecord) == count(v, SemanticAssertionRecord) == 0
    def revoke(request, assertion, **kwargs):
        def deny():
            from apps.api.app.domain.system_image.source_access import StaleSourceAccessScope
            raise StaleSourceAccessScope("injected policy change before commit")
        return record(request, assertion, **{**kwargs, "require_current": deny})
    monkeypatch.setattr(reviews.repository, "record", revoke)
    assert submit(v, payload).json()["status"] == "failed"
    assert count(v, SemanticDecisionRecord) == count(v, SemanticAssertionRecord) == 0
    assert v["client"].get(url, headers=v["headers"]).json()["total"] == 0


def test_semantic_review_migration_and_outbox_retain_provenance(semantic):
    v = semantic
    url, payload, original = evaluate(v)
    completed(submit(v, payload))
    saved = v["client"].get(url, headers=v["headers"]).json()
    assert saved["assertion"] == original["assertion"] and saved["head"] == saved["items"][-1]
    with session_scope() as session:
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == saved["head_decision_id"])).all()
        assert len(events) == 1 and events[0].event_type == "system_image.semantic.reviewed"
        assert events[0].event_payload["query_keys"] == [["semantic-reviews", v["project_id"]]]
        serialized = json.dumps(events[0].event_payload)
        assert payload["reason"] not in serialized and "HTTP 400" not in serialized
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).resolve().parents[1] / "migrations/versions/0048_semantic_reviews.py"
    spec = importlib.util.spec_from_file_location("semantic_review_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with pytest.raises(RuntimeError, match="semantic reviews exist"):
        with session_scope() as session:
            migration.op = Operations(MigrationContext.configure(session.connection()))
            migration.downgrade()
    assert v["client"].get(url, headers=v["headers"]).json() == saved


def test_project_reviewer_can_decide_but_demoted_pending_invocation_cannot(semantic):
    v = semantic
    url, payload, _ = evaluate(v)
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    pending = invoke(v, SEMANTIC_REVIEW_TOOL, payload, headers=v["member_headers"]).json()
    assert pending["status"] == "waiting_confirmation"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "viewer"}).status_code == 200
    denied = v["client"].post(f"/v1/tool-invocations/{pending['id']}/confirm", headers=v["member_headers"])
    assert denied.status_code == 403 or denied.json()["status"] in {"failed", "denied"}
    assert count(v, SemanticDecisionRecord) == 0
    assert v["client"].put(membership, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    completed(submit(v, {**payload, "decision": "defer"}, headers=v["member_headers"]))
    head = v["client"].get(url, headers=v["member_headers"]).json()["head"]
    assert head["reviewer_actor"] == v["member"]["id"] and head["decision"] == "defer"
