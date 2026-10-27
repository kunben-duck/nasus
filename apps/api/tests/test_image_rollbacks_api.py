"""Knowledge rollback uses a new approval and immutable CAS history, not deployment."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from apps.api.app.main import app
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.system_image.publications import RollbackPublishInput
from apps.api.app.domain.system_image.publication import ROLLBACK_POLICY, ROLLBACK_QUERY_TOOL, ROLLBACK_REVIEW_TOOL, ROLLBACK_TOOL
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, SSEEventOutboxRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.image_publication_models import ImagePublicationRecord, ImagePublicationReviewRecord
from apps.api.app.infrastructure.persistence.source_evidence_repository import SourceEvidenceRepository
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_image_publications_api import publication, inspect, history, review, review_request, publish_request
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_reference_links_api import candidate
from apps.api.tests.test_semantic_evaluations_api import invoke, confirm, completed, count
from apps.api.tests.test_source_access_api import grant_member


@pytest.fixture
def rollback(publication):
    v = publication
    approval, _ = review(v)
    completed(invoke(v, "baseline.promote", publish_request(v, approval)))
    old = history(v)["head"]
    v["path"].write_text("class Orders:\n    def submit(self):\n        return 'second revision'\n")
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    new = candidate(v)
    target = {**v["target"], "image_revision_id": new["image_revision_id"],
        "image_artifact_hash": new["artifact_hash"], "expected_head_id": old["publication_id"]}
    approval, _ = review(v, {**inspect(v, target)["target"], "expected_review_id": None,
        "expected_preview_digest": inspect(v, target)["preview_digest"], "decision": "approve", "reason": "Second fixture snapshot"})
    completed(invoke(v, "baseline.promote", publish_request(v, approval, target)))
    head = history(v)["head"]
    assert head["sequence"] == 2 and head["image_revision_id"] != old["image_revision_id"]
    v.update(old_publication=old, new_publication=head, rollback_target={
        "project_id": v["project_id"], "image_revision_id": old["image_revision_id"],
        "image_artifact_hash": old["image_artifact_hash"], "target_baseline_id": old["baseline_id"],
        "expected_head_id": head["publication_id"], "rollback_publication_id": old["publication_id"],
        "policy_revision": ROLLBACK_POLICY})
    return v


def rollback_preview(v, target=None, headers=None):
    request = target or v["rollback_target"]
    return v["client"].get(v["publication_url"] + "/rollback-preview", headers=headers or v["headers"],
        params={k: value for k, value in request.items() if k not in {"project_id", "policy_revision"}})


def rollback_review(v, *, decision="approve"):
    response = rollback_preview(v)
    assert response.status_code == 200, response.text
    view = response.json()
    request = {**view["target"], "expected_preview_digest": view["preview_digest"],
        "expected_review_id": view["review"]["review_id"] if view["review"] else None,
        "decision": decision, "reason": "Restore prior knowledge only; no deployment or business approval"}
    pending = invoke(v, ROLLBACK_REVIEW_TOOL, request, key=uuid4().hex)
    assert pending.json()["status"] == "waiting_confirmation", pending.text
    done = completed(confirm(v, pending.json()))
    approval = done["result"]["object_refs"][0].split(":", 1)[1]
    return {**view["target"], "expected_preview_digest": view["preview_digest"], "approval_id": approval}


def test_rollback_restores_exact_history_without_changing_sources_or_approvals(rollback):
    v = rollback
    before = history(v)
    working_before = v["client"].get(v["image_url"], params={"view": "working"}, headers=v["headers"]).json()
    response = rollback_preview(v)
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store", response.text
    view = response.json()
    assert view["rollback_source"] == v["old_publication"]
    assert view["readiness"]["quality_generation_authorized"] is False
    query = completed(invoke(v, ROLLBACK_QUERY_TOOL, v["rollback_target"]))
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(query["id"], v["project_id"]) == query["result"]["image_publication"]
    request = rollback_review(v)
    key = uuid4().hex
    done = completed(invoke(v, ROLLBACK_TOOL, request, key=key))
    assert completed(invoke(v, ROLLBACK_TOOL, request, key=key))["id"] == done["id"]
    result = history(v)
    head = result["head"]
    assert len(result["items"]) == 3 and result["items"][:2] == before["items"]
    assert head["sequence"] == 3 and head["previous_publication_id"] == v["new_publication"]["publication_id"]
    assert head["rollback_publication_id"] == v["old_publication"]["publication_id"]
    assert head["policy_revision"] == ROLLBACK_POLICY and head["approval_id"] == request["approval_id"]
    assert {key: head[key] for key in ("image_revision_id", "image_artifact_hash", "manifest_id", "manifest_hash")} == {
        key: v["old_publication"][key] for key in ("image_revision_id", "image_artifact_hash", "manifest_id", "manifest_hash")}
    assert head["quality_generation_authorized"] is False and head["release_authorized"] is False
    assert v["client"].get(v["image_url"], params={"view": "working"}, headers=v["headers"]).json() == working_before
    published = v["client"].get(v["image_url"], headers=v["headers"]).json()
    assert published["read_state"]["pin"]["publication_id"] == head["publication_id"]
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(PlatformApplicationError, match="changed"):
            app.state.container.tool_evidence.describe(query["id"], v["project_id"])
    with session_scope() as session:
        assert session.get(ImagePublicationRecord, head["publication_id"]).rollback_publication_id == request["rollback_publication_id"]
        assert session.get(ImagePublicationReviewRecord, head["approval_id"]).rollback_publication_id == request["rollback_publication_id"]
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == head["publication_id"])).all()
        assert {event.event_type for event in events} == {"system_image.publication.rolled_back"}
        audits = session.scalars(select(AuditEventRecord).where(AuditEventRecord.entity_id == head["publication_id"])).all()
        assert len(audits) == 1 and audits[0].tool_invocation_id == done["id"]


@pytest.mark.parametrize("change", ["head", "image", "hash", "source", "baseline"])
def test_rollback_rejects_wrong_historical_pins(rollback, change):
    v = rollback
    request = dict(v["rollback_target"])
    if change == "head": request["expected_head_id"] = v["old_publication"]["publication_id"]
    if change == "image": request["image_revision_id"] = v["new_publication"]["image_revision_id"]
    if change == "hash": request["image_artifact_hash"] = "sha256:" + "a" * 64
    if change == "source": request["rollback_publication_id"] = v["new_publication"]["publication_id"]
    if change == "baseline": request["target_baseline_id"] = "missing"
    response = rollback_preview(v, request)
    assert response.status_code in {404, 409}, response.text
    assert history(v)["head"] == v["new_publication"] and count(v, ImagePublicationRecord) == 2


def test_rollback_approval_cannot_be_reused_for_publication_or_release(rollback):
    v = rollback
    request = rollback_review(v)
    for tool in ("baseline.promote", "release.decision.submit"):
        assert invoke(v, tool, request).json()["status"] == "waiting_approval"
    assert invoke(v, ROLLBACK_TOOL, {**request, "approval_id": v["old_publication"]["approval_id"]}).json()["status"] == "waiting_approval"
    pending = invoke(v, "approval.decide", {"project_id": v["project_id"], "approval_id": request["approval_id"], "decision": "approved"})
    done = confirm(v, pending.json()) if pending.json()["status"] == "waiting_confirmation" else pending
    assert done.json()["status"] == "failed"
    assert history(v)["head"] == v["new_publication"]


def test_rollback_rejection_and_concurrent_head_cas(rollback):
    v = rollback
    rejected = rollback_review(v, decision="reject")
    assert invoke(v, ROLLBACK_TOOL, rejected).json()["status"] == "waiting_approval"
    request = rollback_review(v)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [response.json()["status"] for response in pool.map(lambda _: invoke(v, ROLLBACK_TOOL, request, key=uuid4().hex), range(2))]
    assert sorted(outcomes) == ["completed", "failed"]
    assert count(v, ImagePublicationRecord) == 3 and history(v)["head"]["sequence"] == 3
    assert rollback_preview(v).status_code == 409


def test_rollback_archived_evidence_and_live_roles_are_rechecked(rollback, monkeypatch):
    v = rollback
    target = SourceEvidenceRepository().get(v["project_id"], v["evidence"]["evidence_id"])
    storage = app.state.container.evidence.reader.storage
    original = storage.get_bytes
    monkeypatch.setattr(storage, "get_bytes", lambda ref, **kwargs:
        b"tampered private original" if ref == target.evidence.object_ref else original(ref, **kwargs))
    response = rollback_preview(v)
    assert response.status_code == 502 and "tampered private" not in response.text, response.text
    monkeypatch.setattr(storage, "get_bytes", original)
    rollback_review(v)
    grant_member(v)
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "project_admin"}).status_code == 200
    fresh = rollback_preview(v, headers=v["member_headers"]).json()
    request = {**fresh["target"], "expected_preview_digest": fresh["preview_digest"],
        "expected_review_id": fresh["review"]["review_id"], "decision": "approve", "reason": "No longer a reviewer"}
    assert v["client"].put(membership, headers=v["headers"], json={"role": "viewer"}).status_code == 200
    response = invoke(v, ROLLBACK_REVIEW_TOOL, request, headers=v["member_headers"])
    assert response.status_code == 403 or response.json()["status"] == "failed", response.text
    assert history(v)["head"] == v["new_publication"]


def test_rollback_outbox_failure_leaves_no_head_or_partial_publication(rollback, monkeypatch):
    v = rollback
    request = rollback_review(v)
    append = EventOutboxRepository.append
    def fail(self, event, **kwargs):
        if event.event_type == "system_image.publication.rolled_back":
            raise RuntimeError("Injected rollback outbox failure")
        return append(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    assert invoke(v, ROLLBACK_TOOL, request).json()["status"] == "failed"
    assert count(v, ImagePublicationRecord) == 2 and history(v)["head"] == v["new_publication"]
    monkeypatch.setattr(EventOutboxRepository, "append", append)
    completed(invoke(v, ROLLBACK_TOOL, request, key=uuid4().hex))


def test_committed_rollback_recovery_never_moves_a_newer_head_back(rollback):
    v = rollback
    request = rollback_review(v)
    done = completed(invoke(v, ROLLBACK_TOOL, request))
    restored = history(v)["head"]
    target = {**v["target"], "image_revision_id": v["new_publication"]["image_revision_id"],
        "image_artifact_hash": v["new_publication"]["image_artifact_hash"], "expected_head_id": restored["publication_id"]}
    approval, _ = review(v, review_request(v, target=target))
    completed(invoke(v, "baseline.promote", publish_request(v, approval, target)))
    newer = history(v)["head"]
    assert newer["sequence"] == 4 and newer["image_revision_id"] == v["new_publication"]["image_revision_id"]
    with session_scope() as session:
        session.get(ToolInvocationRecord, done["id"]).status = "running"
    with actor_scope(UserProfile.model_validate(v["owner"])):
        recovered = v["publication_service"].publish(RollbackPublishInput.model_validate(request),
            invocation_id=done["id"], recorded_at="recovery")
    assert recovered == restored and history(v)["head"] == newer and count(v, ImagePublicationRecord) == 4


def test_rollback_expired_review_and_changed_source_scope_do_not_restore(rollback, monkeypatch):
    v = rollback
    original = v["publication_service"].repository.review
    def expired(*args, **kwargs):
        return original(*args, **{**kwargs, "recorded_at": (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat()})
    monkeypatch.setattr(v["publication_service"].repository, "review", expired)
    request = rollback_review(v)
    expired_result = invoke(v, ROLLBACK_TOOL, request).json()
    assert expired_result["status"] == "failed"
    assert expired_result["result"]["followup_reason"] == "publication_inputs_changed"
    monkeypatch.setattr(v["publication_service"].repository, "review", original)
    request = rollback_review(v)
    repo = SourceAccessRepository()
    scope = repo.load_snapshot(v["project_id"])
    repo.set_policy(v["project_id"], v["evidence"]["binding_id"], SourceAccessRule("restricted"),
        expected_epoch=scope.acl_epoch, changed_by=v["owner"]["id"], invocation_id="rollback-acl-change-" + uuid4().hex)
    assert invoke(v, ROLLBACK_TOOL, request).json()["status"] == "failed"
    assert history(v)["head"] == v["new_publication"] and count(v, ImagePublicationRecord) == 2
