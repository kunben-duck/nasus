from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import select, update, delete, func
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.infrastructure.persistence.link_decision_models import LinkDecisionRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.tests.test_reference_links_api import proposal
from apps.api.tests.test_document_projection_api import documents, REQUIREMENT
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_access_api import grant_member


def setup_review(v):
    saved, url, _ = proposal(v)
    edge = saved["items"][0]
    endpoint = f"{url}/assertions/{edge['assertion_id']}/decisions"
    current = v["client"].get(endpoint, headers=v["headers"])
    assert current.status_code == 200, current.text
    body = current.json()
    payload = {key: body[key] for key in ("project_id", "proposal_id", "assertion_id", "proposal_digest", "evidence_digest", "policy_revision")}
    payload.update(expected_previous_decision_id=body["head_decision_id"], decision="reject", reason="Stale reference, do not count as coverage")
    return saved, endpoint, payload


def submit(v, payload, *, headers=None, confirm=True, key=None):
    headers = headers or v["headers"]
    response = v["client"].post("/v1/tool-invocations", headers=headers, json={
        "tool_id": "system_image.links.review", "conversation_id": v["conversation"].json()["id"],
        "input": payload, "idempotency_key": key or str(uuid4())})
    if confirm and response.status_code == 200 and response.json()["status"] == "waiting_confirmation":
        return v["client"].post(f"/v1/tool-invocations/{response.json()['id']}/confirm", headers=headers)
    return response


def query(v, payload):
    result = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "tool_id": "query.system_image.links.decisions", "input": {key: payload[key] for key in ("project_id", "proposal_id", "assertion_id")}})
    assert result.status_code == 200 and result.json()["status"] == "completed", result.text
    return result.json(), f"/v1/tool-invocations/{result.json()['id']}/image-query"


def count(v):
    with session_scope() as session:
        return session.scalar(select(func.count()).select_from(LinkDecisionRecord).where(LinkDecisionRecord.project_id == v["project_id"]))


def test_confirmed_review_is_immutable_idempotent_and_does_not_change_image_or_proposal(documents):
    v = documents
    saved, endpoint, payload = setup_review(v)
    empty_receipt, empty_url = query(v, payload)
    pending = submit(v, payload, confirm=False, key="first")
    assert pending.json()["status"] == "waiting_confirmation" and count(v) == 0, pending.text
    done = v["client"].post(f"/v1/tool-invocations/{pending.json()['id']}/confirm", headers=v["headers"])
    assert done.status_code == 200 and done.json()["status"] == "completed", done.text
    assert submit(v, payload, key="first").json()["id"] == done.json()["id"] and count(v) == 1
    page = v["client"].get(endpoint, headers=v["headers"])
    assert page.status_code == 200 and page.headers["cache-control"] == "private, no-store"
    decision = page.json()["items"][0]
    assert decision["decision"] == "reject" and decision["reviewer_actor"] == v["owner"]["id"]
    assert decision["reason"] == payload["reason"] and decision["sequence"] == 1
    assert proposal(v)[0] == saved
    receipt, receipt_url = query(v, payload)
    assert payload["reason"] not in str(receipt["result"]) and receipt["result"]["image_query"]["head_decision_id"] == decision["decision_id"]
    assert v["client"].get(empty_url, headers=v["headers"]).json()["items"] == []
    changed = submit(v, {**payload, "expected_previous_decision_id": decision["decision_id"], "decision": "defer", "reason": "Await revised requirement"})
    assert changed.json()["status"] == "completed", changed.text
    assert v["client"].get(receipt_url, headers=v["headers"]).json() == page.json()
    latest = v["client"].get(endpoint, headers=v["headers"], params={"limit": 1}).json()
    assert latest["total"] == 2 and latest["next_offset"] == 1
    final = v["client"].get(endpoint, headers=v["headers"], params={"offset": 1}).json()["items"][0]
    assert final["previous_decision_id"] == decision["decision_id"] and final["decision"] == "defer"
    for statement in (update(LinkDecisionRecord).where(LinkDecisionRecord.project_id == v["project_id"]).values(content_hash="tampered"),
                      delete(LinkDecisionRecord).where(LinkDecisionRecord.project_id == v["project_id"])):
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as session:
                session.execute(statement)


def test_concurrent_reviews_use_compare_and_swap_not_last_writer_wins(documents):
    v = documents
    _, endpoint, payload = setup_review(v)
    pending = [submit(v, {**payload, "decision": value}, confirm=False).json() for value in ("accept", "reject")]
    assert all(item["status"] == "waiting_confirmation" for item in pending)
    def confirm(item):
        return v["client"].post(f"/v1/tool-invocations/{item['id']}/confirm", headers=v["headers"])
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(confirm, pending))
    assert sorted(result.json()["status"] for result in results) == ["completed", "failed"], [r.text for r in results]
    failed = next(r.json() for r in results if r.json()["status"] == "failed")
    assert failed["result"]["followup_reason"] == "stale_link_decision" and count(v) == 1
    assert v["client"].get(endpoint, headers=v["headers"]).json()["total"] == 1


def test_review_requires_reviewer_confirmation_exact_pins_and_scope(documents):
    v = documents
    _, endpoint, payload = setup_review(v)
    assert v["client"].get(endpoint).status_code == 401
    grant_member(v)
    for role in ("viewer", "tester"):
        v["client"].put(f"/v1/projects/{v['project_id']}/members/{v['member']['id']}", headers=v["headers"], json={"role": role})
        denied = submit(v, payload, headers=v["member_headers"])
        assert denied.status_code == 403 or denied.json()["status"] in {"denied", "failed"}, denied.text
    for change in ({"evidence_digest": "sha256:" + "0" * 64}, {"proposal_digest": "sha256:" + "0" * 64},
                   {"policy_revision": "all-versions"}, {"assertion_id": "missing"}, {"reviewer_actor": "forged"},
                   {"decision": "approve_coverage"}, {"reason": " "}):
        result = submit(v, {**payload, **change})
        assert result.status_code == 200 and result.json()["status"] == "failed", result.text
    assert count(v) == 0
    # A forged confirmation flag cannot skip ToolRuntime confirmation.
    forged = submit(v, {**payload, "confirmed_by_user": True}, confirm=False)
    assert forged.status_code == 400 or forged.json()["status"] in {"failed", "waiting_confirmation"}, forged.text
    other = v["client"].post("/v1/projects", headers=v["headers"], json={"name": f"Other {uuid4().hex}"}).json()["id"]
    assert submit(v, {**payload, "project_id": other}).json()["status"] == "failed"


def test_revoked_role_or_source_access_cannot_submit_or_read_old_reviews(documents, monkeypatch):
    v = documents
    _, endpoint, payload = setup_review(v)
    member_url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    v["client"].put(member_url, headers=v["headers"], json={"role": "qa_lead"})
    pending = submit(v, payload, headers=v["member_headers"], confirm=False).json()
    assert pending["status"] == "waiting_confirmation"
    service = app.state.container.link_decisions
    original = service._assertion
    def revoke(*args):
        value = original(*args)
        v["client"].put(member_url, headers=v["headers"], json={"role": "viewer"})
        return value
    monkeypatch.setattr(service, "_assertion", revoke)
    result = v["client"].post(f"/v1/tool-invocations/{pending['id']}/confirm", headers=v["member_headers"])
    assert result.json()["status"] == "failed" and count(v) == 0
    monkeypatch.setattr(service, "_assertion", original)
    assert submit(v, payload).json()["status"] == "completed"
    receipt, expansion = query(v, payload)
    access = SourceAccessRepository()
    snapshot = access.load_snapshot(v["project_id"])
    access.set_policy(v["project_id"], snapshot.bindings[0].binding_id, SourceAccessRule("restricted"),
        expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="review-read-revoke")
    for url in (endpoint, expansion):
        response = v["client"].get(url, headers=v["member_headers"])
        assert response.status_code == 403 and payload["reason"] not in response.text


def test_review_outbox_failure_rolls_back_and_new_revision_never_inherits_acceptance(documents, monkeypatch):
    v = documents
    saved, endpoint, payload = setup_review(v)
    append = EventOutboxRepository.append
    def fail(self, event, **kwargs):
        if event.event_type == "system_image.link.reviewed":
            raise RuntimeError("outbox down")
        return append(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    assert submit(v, payload).json()["status"] == "failed" and count(v) == 0
    monkeypatch.setattr(EventOutboxRepository, "append", append)
    assert submit(v, {**payload, "decision": "accept"}).json()["status"] == "completed"
    original = v["client"].get(endpoint, headers=v["headers"]).json()
    v["requirement_path"].write_text(REQUIREMENT.replace("400", "422"))
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    changed, new_endpoint, new_payload = setup_review(v)
    assert changed["digest"] != saved["digest"]
    assert v["client"].get(new_endpoint, headers=v["headers"]).json()["total"] == 0
    assert submit(v, {**new_payload, "expected_previous_decision_id": original["head_decision_id"]}).json()["status"] == "failed"
    assert v["client"].get(endpoint, headers=v["headers"]).json() == original
