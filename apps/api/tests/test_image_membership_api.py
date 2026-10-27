from uuid import uuid4

import pytest
from sqlalchemy import select, func, update, delete
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.infrastructure.persistence.image_revision_models import ImageRevisionRecord, ImageAssertionMemberRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.tests.test_link_decisions_api import setup_review, submit
from apps.api.tests.test_document_projection_api import documents, REQUIREMENT
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_access_api import grant_member


def setup_freeze(v):
    saved, endpoint, review = setup_review(v)
    assert submit(v, review).json()["status"] == "completed"
    decision = v["client"].get(endpoint, headers=v["headers"]).json()["head_decision_id"]
    payload = {"project_id": v["project_id"], "parent_revision_id": saved["image_revision_id"],
        "parent_artifact_hash": saved["image_artifact_hash"], "proposal_id": saved["proposal_id"],
        "proposal_digest": saved["digest"], "decision_ids": [decision]}
    return payload, review, endpoint


def freeze(v, payload, *, confirm=True, headers=None, key=None):
    headers = headers or v["headers"]
    response = v["client"].post("/v1/tool-invocations", headers=headers, json={
        "tool_id": "system_image.revisions.freeze_links", "conversation_id": v["conversation"].json()["id"],
        "input": payload, "idempotency_key": key or str(uuid4())})
    if confirm and response.status_code == 200 and response.json()["status"] == "waiting_confirmation":
        return v["client"].post(f"/v1/tool-invocations/{response.json()['id']}/confirm", headers=headers)
    return response


def child(v, response):
    assert response.status_code == 200 and response.json()["status"] == "completed", response.text
    revision_id = response.json()["result"]["object_refs"][0].split(":", 1)[1]
    url = f"{v['image_url']}/revisions/{revision_id}"
    page = v["client"].get(url, headers=v["headers"], params={"section": "assertion_members"})
    assert page.status_code == 200, page.text
    assert page.headers["cache-control"] == "private, no-store"
    return url, page.json()


def count(v):
    with session_scope() as session:
        return session.scalar(select(func.count()).select_from(ImageRevisionRecord).where(
            ImageRevisionRecord.project_id == v["project_id"], ImageRevisionRecord.parent_revision_id.is_not(None)))


def test_freeze_pins_rejected_decision_and_parent_then_later_review_requires_new_candidate(documents):
    v = documents
    payload, review, endpoint = setup_freeze(v)
    pending = freeze(v, payload, confirm=False, key="freeze")
    assert pending.json()["status"] == "waiting_confirmation" and count(v) == 0
    done = v["client"].post(f"/v1/tool-invocations/{pending.json()['id']}/confirm", headers=v["headers"])
    url, first = child(v, done)
    assert first["revision"]["parent_revision_id"] == payload["parent_revision_id"]
    assert first["revision"]["parent_artifact_hash"] == payload["parent_artifact_hash"]
    assert first["revision"]["policy_version"] == "nasus.image-candidate.v2" and first["revision"]["assertion_count"] == 1
    assert first["items"][0]["decision_id"] == payload["decision_ids"][0] and first["items"][0]["decision"] == "reject"
    assert first["items"][0]["predicate"] == "references" and first["revision"]["publication"] == "blocked_pending_revision_governance"
    assert freeze(v, payload, key="freeze").json()["id"] == done.json()["id"] and count(v) == 1
    assert child(v, freeze(v, payload))[1] == first and count(v) == 1
    parent_url = f"{v['image_url']}/revisions/{payload['parent_revision_id']}"
    parent = v["client"].get(parent_url, headers=v["headers"], params={"section": "assertion_members"}).json()
    assert parent["items"] == [] and parent["revision"]["artifact_hash"] == payload["parent_artifact_hash"]
    for section in ("objects", "relationships", "members", "source_members"):
        assert v["client"].get(url, headers=v["headers"], params={"section": section}).json()["items"] == v["client"].get(
            parent_url, headers=v["headers"], params={"section": section}).json()["items"]
    query = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={"tool_id": "query.system_image.revisions.read",
        "input": {"project_id": v["project_id"], "image_revision_id": first["revision"]["image_revision_id"], "section": "assertion_members"}})
    assert query.json()["status"] == "completed", query.text
    assert "reject" not in str(query.json()["result"]["image_query"])
    changed = submit(v, {**review, "expected_previous_decision_id": payload["decision_ids"][0], "decision": "accept", "reason": "Correct explicit reference"})
    assert changed.json()["status"] == "completed", changed.text
    assert v["client"].get(f"/v1/tool-invocations/{query.json()['id']}/image-query", headers=v["headers"]).json() == first
    assert freeze(v, payload).json()["result"]["followup_reason"] == "stale_link_decision"
    new_decision = v["client"].get(endpoint, headers=v["headers"]).json()["head_decision_id"]
    updated = {**payload, "parent_revision_id": first["revision"]["image_revision_id"],
        "parent_artifact_hash": first["revision"]["artifact_hash"], "decision_ids": [new_decision]}
    _, second = child(v, freeze(v, updated))
    assert second["items"][0]["decision"] == "accept" and second["revision"]["artifact_hash"] != first["revision"]["artifact_hash"]
    assert v["client"].get(url, headers=v["headers"], params={"section": "assertion_members"}).json() == first
    for statement in (update(ImageAssertionMemberRecord).where(ImageAssertionMemberRecord.project_id == v["project_id"]).values(content_hash="bad"),
                      delete(ImageAssertionMemberRecord).where(ImageAssertionMemberRecord.project_id == v["project_id"])):
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as session:
                session.execute(statement)
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).resolve().parents[1] / "migrations/versions/0045_image_review_membership.py"
    spec = importlib.util.spec_from_file_location("review_membership_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with pytest.raises(RuntimeError, match="cannot discard"):
        with session_scope() as session:
            migration.op = Operations(MigrationContext.configure(session.connection()))
            migration.downgrade()
    assert v["client"].get(url, headers=v["headers"], params={"section": "assertion_members"}).json() == first


def test_freeze_rejects_bad_pins_roles_and_foreign_endpoint_revision(documents):
    v = documents
    payload, _, _ = setup_freeze(v)
    grant_member(v)
    denied = freeze(v, payload, headers=v["member_headers"])
    assert denied.status_code == 403 or denied.json()["status"] in {"denied", "failed"}, denied.text
    for change in ({"parent_artifact_hash": "sha256:" + "0" * 64}, {"proposal_digest": "sha256:" + "0" * 64},
                   {"decision_ids": []}, {"decision_ids": [payload["decision_ids"][0]] * 2}, {"decision_ids": ["missing"]},
                   {"parent_revision_id": "missing"}, {"publication": "approved"}):
        result = freeze(v, {**payload, **change})
        assert result.status_code == 200 and result.json()["status"] == "failed", result.text
    assert count(v) == 0
    v["requirement_path"].write_text(REQUIREMENT.replace("400", "422"))
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    new, _, _ = setup_freeze(v)
    assert freeze(v, {**payload, "parent_revision_id": new["parent_revision_id"], "parent_artifact_hash": new["parent_artifact_hash"]}).json()["status"] == "failed"
    # Historical candidates remain usable even when the mutable source head advances.
    assert child(v, freeze(v, payload))[1]["items"][0]["decision"] == "reject"


def test_freeze_checks_head_inside_commit_and_rolls_back_outbox_failure(documents, monkeypatch):
    v = documents
    payload, review, endpoint = setup_freeze(v)
    service = app.state.container.image_membership
    put = service.images.artifacts.put
    def concurrent_review(*args):
        result = put(*args)
        assert submit(v, {**review, "expected_previous_decision_id": payload["decision_ids"][0], "decision": "defer"}).json()["status"] == "completed"
        return result
    monkeypatch.setattr(service.images.artifacts, "put", concurrent_review)
    assert freeze(v, payload).json()["result"]["followup_reason"] == "stale_link_decision" and count(v) == 0
    monkeypatch.setattr(service.images.artifacts, "put", put)
    payload["decision_ids"] = [v["client"].get(endpoint, headers=v["headers"]).json()["head_decision_id"]]
    append = EventOutboxRepository.append
    def fail(self, event, **kwargs):
        if event.event_type == "system_image.candidate.frozen":
            raise RuntimeError("outbox unavailable")
        return append(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    assert freeze(v, payload).json()["status"] == "failed" and count(v) == 0


def test_frozen_review_read_reauthorizes_all_sources(documents):
    v = documents
    payload, _, _ = setup_freeze(v)
    url, page = child(v, freeze(v, payload))
    grant_member(v)
    assert v["client"].get(url, headers=v["member_headers"], params={"section": "assertion_members"}).json() == page
    repo = SourceAccessRepository()
    snapshot = repo.load_snapshot(v["project_id"])
    repo.set_policy(v["project_id"], snapshot.bindings[0].binding_id, SourceAccessRule("restricted"),
        expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="frozen-review-revoke")
    result = v["client"].get(url, headers=v["member_headers"], params={"section": "assertion_members"})
    assert result.status_code == 403 and page["items"][0]["decision_id"] not in result.text


def test_reviewer_role_revoked_during_archive_cannot_commit_membership(documents, monkeypatch):
    v = documents
    payload, _, _ = setup_freeze(v)
    member_url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(member_url, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    artifacts = app.state.container.image_membership.images.artifacts
    put = artifacts.put
    def revoke(*args):
        result = put(*args)
        assert v["client"].put(member_url, headers=v["headers"], json={"role": "viewer"}).status_code == 200
        return result
    monkeypatch.setattr(artifacts, "put", revoke)
    response = freeze(v, payload, headers=v["member_headers"])
    assert response.json()["status"] == "failed" and count(v) == 0
