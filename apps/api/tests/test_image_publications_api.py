"""Pinned image publication through the canonical runtime and disposable PostgreSQL."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.system_image.publications import PublicationPublishInput
from apps.api.app.domain.system_image.publication import PUBLICATION_POLICY, PUBLICATION_QUERY_TOOL, PUBLICATION_REVIEW_TOOL, PUBLICATION_HEAD_TOOL, PublicationIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.db_models import ApprovalRecord, ToolInvocationRecord, SSEEventOutboxRecord, AuditEventRecord
from apps.api.app.infrastructure.persistence.image_publication_models import ImagePublicationRecord, ImagePublicationReviewRecord, ImagePublicationHeadRecord
from apps.api.app.infrastructure.persistence.image_revision_models import ImageRevisionRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_reference_links_api import candidate
from apps.api.tests.test_semantic_evaluations_api import invoke, confirm, completed, count
from apps.api.tests.test_source_access_api import grant_member


@pytest.fixture
def publication(documents):
    v = documents
    image = candidate(v)
    v.update(publication_image=image, publication_url=v["image_url"] + "/publications",
        publication_service=app.state.container.image_publications,
        target=dict(project_id=v["project_id"], image_revision_id=image["image_revision_id"],
            image_artifact_hash=image["artifact_hash"], target_baseline_id=image["baseline_id"],
            expected_head_id=None, policy_revision=PUBLICATION_POLICY))
    return v


def inspect(v, target=None):
    target = target or v["target"]
    response = v["client"].get(v["publication_url"] + "/preview", headers=v["headers"],
        params={k: value for k, value in target.items() if k not in {"project_id", "policy_revision"} and value is not None})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    return response.json()


def history(v, **params):
    response = v["client"].get(v["publication_url"], headers=v["headers"],
        params={"baseline_id": v["target"]["target_baseline_id"], **params})
    assert response.status_code == 200, response.text
    return response.json()


def review_request(v, *, target=None, decision="approve", **overrides):
    preview = inspect(v, target)
    return {**preview["target"], "expected_preview_digest": preview["preview_digest"],
        "expected_review_id": preview["review"]["review_id"] if preview["review"] else None,
        "decision": decision, "reason": "Explicit fixture knowledge publication review; not business acceptance.", **overrides}


def review(v, request=None):
    pending = invoke(v, PUBLICATION_REVIEW_TOOL, request or review_request(v), key=uuid4().hex)
    assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
    done = completed(confirm(v, pending.json()))
    return done["result"]["object_refs"][0].split(":", 1)[1], done


def publish_request(v, approval_id, target=None):
    preview = inspect(v, target)
    return {**preview["target"], "expected_preview_digest": preview["preview_digest"], "approval_id": approval_id}


def test_confirmed_publication_is_immutable_pinned_audited_and_not_quality_authority(publication):
    v = publication
    before = inspect(v)
    assert before["head"] is None and before["review"] is None and before["can_review"] is True
    assert before["readiness"]["quality_generation_authorized"] is False
    query = completed(invoke(v, PUBLICATION_QUERY_TOOL, v["target"]))
    receipt = query["result"]["image_publication"]
    assert receipt["request"] == v["target"] and receipt["review_id"] is None
    assert "Empty input" not in json.dumps(receipt) and "local-object://" not in json.dumps(before)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(query["id"], v["project_id"]) == receipt
    pending = invoke(v, PUBLICATION_REVIEW_TOOL, {**review_request(v), "confirmed_by_user": True}).json()
    assert pending["status"] == "waiting_confirmation" and count(v, ImagePublicationReviewRecord) == 0
    done = completed(confirm(v, pending))
    assert completed(confirm(v, pending))["id"] == done["id"]
    approval_id = done["result"]["object_refs"][0].split(":", 1)[1]
    assert history(v)["head"] is None
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(PlatformApplicationError, match="Publication preview changed"):
            app.state.container.tool_evidence.describe(query["id"], v["project_id"])
    request = publish_request(v, approval_id)
    key = uuid4().hex
    published = completed(invoke(v, "baseline.promote", request, key=key))
    assert completed(invoke(v, "baseline.promote", request, key=key))["id"] == published["id"]
    result = history(v)
    assert len(result["items"]) == 1 and result["head"] == result["items"][0]
    head = result["head"]
    assert head["approval_id"] == approval_id and head["previous_publication_id"] is None and head["sequence"] == 1
    assert head["image_artifact_hash"] == v["target"]["image_artifact_hash"]
    assert head["quality_generation_authorized"] is False and head["release_authorized"] is False
    with session_scope() as session:
        image = session.get(ImageRevisionRecord, head["image_revision_id"])
        assert image.status == "candidate" and image.artifact_hash == v["target"]["image_artifact_hash"]
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id.in_([approval_id, head["publication_id"]]))).all()
        assert {e.event_type for e in events} == {"system_image.publication.reviewed", "system_image.publication.published"}
        assert "Explicit fixture" not in json.dumps([e.event_payload for e in events])
        audits = session.scalars(select(AuditEventRecord).where(AuditEventRecord.entity_id.in_([approval_id, head["publication_id"]]))).all()
        assert len(audits) == 2 and all(a.actor == v["owner"]["id"] for a in audits)
    for model in (ImagePublicationRecord, ImagePublicationReviewRecord):
        for statement in (delete(model), update(model).values(content_hash="tampered")):
            with pytest.raises(IntegrityError, match="append-only"):
                with session_scope() as session:
                    session.execute(statement.where(model.project_id == v["project_id"]))


def test_agent_resolves_head_and_refuses_stale_observation(publication):
    v = publication
    request = {key: v["target"][key] for key in ("project_id", "target_baseline_id")}
    initial = completed(invoke(v, PUBLICATION_HEAD_TOOL, request))
    receipt = initial["result"]["image_publication_head"]
    assert receipt == {"request": request, "head": None,
        "quality_generation_authorized": False, "release_authorized": False}
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(initial["id"], v["project_id"]) == receipt
    approval_id, _ = review(v)
    completed(invoke(v, "baseline.promote", publish_request(v, approval_id)))
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(PlatformApplicationError, match="Publication preview changed"):
            app.state.container.tool_evidence.describe(initial["id"], v["project_id"])
    current = completed(invoke(v, PUBLICATION_HEAD_TOOL, request, key=uuid4().hex))
    pin = current["result"]["image_publication_head"]["head"]
    assert pin == {key: history(v)["head"][key] for key in
        ("publication_id", "image_revision_id", "image_artifact_hash", "sequence")}
    target = {**v["target"], "expected_head_id": pin["publication_id"]}
    preview = completed(invoke(v, PUBLICATION_QUERY_TOOL, target))
    assert preview["result"]["image_publication"]["request"] == target
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(current["id"], v["project_id"]) == current["result"]["image_publication_head"]


def test_publication_approval_cannot_authorize_other_tools_or_unpinned_promotion(publication):
    v = publication
    approval_id, _ = review(v)
    # Creating unrelated governance approvals must preserve the scoped mirror.
    generic_pending = invoke(v, "approval.request", {"project_id": v["project_id"], "purpose": "release_governance"})
    assert generic_pending.json()["status"] == "waiting_confirmation"
    completed(confirm(v, generic_pending.json()))
    with session_scope() as session:
        assert session.get(ApprovalRecord, approval_id).policy_reason == PUBLICATION_POLICY
    for tool in ("release.decision.submit", "baseline.promote"):
        response = invoke(v, tool, {"project_id": v["project_id"], "approval_id": approval_id})
        assert response.status_code == 200 and response.json()["status"] != "completed", response.text
    pending = invoke(v, "approval.decide", {"project_id": v["project_id"], "approval_id": approval_id, "decision": "approved"})
    response = confirm(v, pending.json()) if pending.json()["status"] == "waiting_confirmation" else pending
    assert response.json()["status"] == "failed", response.text
    with session_scope() as session:
        generic = str(uuid4())
        session.add(ApprovalRecord(id=generic, project_id=v["project_id"], title="Generic release approval", status="approved",
            summary="Not bound to an image", policy_reason="release", conflict_fields=[], recommended_resolution="", evidence=[], sort_order=9))
    assert invoke(v, "baseline.promote", publish_request(v, generic)).json()["status"] == "failed"
    completed(invoke(v, "baseline.promote", publish_request(v, approval_id)))
    # Once a project uses pinned heads it cannot return to the mutable legacy path.
    response = invoke(v, "baseline.promote", {"project_id": v["project_id"], "approval_id": generic})
    assert response.json()["status"] == "failed" and count(v, ImagePublicationRecord) == 1


def test_competing_reviews_and_publications_compare_and_swap(publication):
    v = publication
    request = review_request(v)
    pending = [invoke(v, PUBLICATION_REVIEW_TOOL, {**request, "reason": f"review {i}"}, key=uuid4().hex).json() for i in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [r.json() for r in pool.map(lambda p: confirm(v, p), pending)]
    assert sorted(r["status"] for r in results) == ["completed", "failed"]
    approval_id = inspect(v)["review"]["review_id"]
    publish = publish_request(v, approval_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [r.json() for r in pool.map(lambda _: invoke(v, "baseline.promote", publish, key=uuid4().hex), range(2))]
    assert sorted(r["status"] for r in results) == ["completed", "failed"]
    assert count(v, ImagePublicationRecord) == count(v, ImagePublicationHeadRecord) == 1


def test_rejection_expiry_and_changed_manifest_invalidate_approval(publication, monkeypatch):
    v = publication
    approval_id, _ = review(v)
    old = publish_request(v, approval_id)
    review(v, review_request(v, decision="reject"))
    assert invoke(v, "baseline.promote", old).json()["status"] == "failed"
    service = v["publication_service"]
    original = service.repository.review
    def expired(*args, **kwargs):
        return original(*args, **{**kwargs, "recorded_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()})
    monkeypatch.setattr(service.repository, "review", expired)
    expired_id, _ = review(v)
    assert invoke(v, "baseline.promote", publish_request(v, expired_id)).json()["status"] == "failed"
    monkeypatch.setattr(service.repository, "review", original)
    fresh_id, _ = review(v)
    fresh = publish_request(v, fresh_id)
    v["requirement_path"].write_text(v["requirement_path"].read_text().replace("400", "422"))
    v["invoke"]("system_image.sources.ingest")
    assert invoke(v, "baseline.promote", fresh).json()["status"] == "failed"
    assert history(v)["head"] is None


def test_review_and_publication_outbox_failures_roll_back_all_facts(publication, monkeypatch):
    v = publication
    append = EventOutboxRepository.append
    def fail(self, event, **kwargs):
        if event.event_type.startswith("system_image.publication."):
            raise RuntimeError("Injected outbox failure")
        return append(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    pending = invoke(v, PUBLICATION_REVIEW_TOOL, review_request(v)).json()
    assert confirm(v, pending).json()["status"] == "failed"
    assert count(v, ImagePublicationReviewRecord) == count(v, ApprovalRecord) == 0
    monkeypatch.setattr(EventOutboxRepository, "append", append)
    approval_id, _ = review(v)
    request = publish_request(v, approval_id)
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    assert invoke(v, "baseline.promote", request).json()["status"] == "failed"
    assert count(v, ImagePublicationRecord) == count(v, ImagePublicationHeadRecord) == 0
    monkeypatch.setattr(EventOutboxRepository, "append", append)
    completed(invoke(v, "baseline.promote", request, key=uuid4().hex))


def test_recovery_returns_original_commit_without_moving_newer_head(publication):
    v = publication
    approval_id, _ = review(v)
    first_request = publish_request(v, approval_id)
    first = completed(invoke(v, "baseline.promote", first_request))
    first_head = history(v)["head"]
    target = {**v["target"], "expected_head_id": first_head["publication_id"]}
    second_id, _ = review(v, review_request(v, target=target))
    completed(invoke(v, "baseline.promote", publish_request(v, second_id, target)))
    second_head = history(v)["head"]
    assert second_head["sequence"] == 2 and second_head["previous_publication_id"] == first_head["publication_id"]
    page = history(v, limit=1)
    assert page["items"] == [first_head] and page["next_after_sequence"] == 1
    assert history(v, after_sequence=1)["items"] == [second_head]
    with session_scope() as session:
        session.get(ToolInvocationRecord, first["id"]).status = "running"
    with actor_scope(UserProfile.model_validate(v["owner"])):
        replay = v["publication_service"].publish(PublicationPublishInput.model_validate(first_request), invocation_id=first["id"], recorded_at="retry")
        assert replay == first_head
        changed = {**first_request, "expected_preview_digest": "sha256:" + "f" * 64}
        with session_scope() as session:
            row = session.get(ToolInvocationRecord, first["id"])
            original_payload = dict(row.input_payload)
            row.input_payload = {**row.input_payload, "expected_preview_digest": changed["expected_preview_digest"]}
        try:
            with pytest.raises(PublicationIntegrityError):
                v["publication_service"].publish(PublicationPublishInput.model_validate(changed), invocation_id=first["id"], recorded_at="retry")
            response = v["client"].get(v["publication_url"], headers=v["headers"],
                params={"baseline_id": v["target"]["target_baseline_id"]})
            assert response.status_code == 502, response.text
        finally:
            with session_scope() as session:
                session.get(ToolInvocationRecord, first["id"]).input_payload = original_payload
    assert history(v)["head"] == second_head and count(v, ImagePublicationRecord) == 2


def test_review_requires_project_admin_and_publish_revalidates_acl_epoch(publication):
    v = publication
    grant_member(v)
    request = review_request(v)
    denied = invoke(v, PUBLICATION_REVIEW_TOOL, request, headers=v["member_headers"])
    assert denied.status_code == 200 and denied.json()["status"] == "failed", denied.text
    assert denied.json()["result"]["followup_reason"] == "authorization_denied"
    approval_id, _ = review(v)
    publish = publish_request(v, approval_id)
    repo = SourceAccessRepository()
    snapshot = repo.load_snapshot(v["project_id"])
    binding_id = inspect(v)["source_members"][0]["binding_id"]
    repo.set_policy(v["project_id"], binding_id, SourceAccessRule("restricted"), expected_epoch=snapshot.acl_epoch,
        changed_by=v["owner"]["id"], invocation_id="publication-acl-change")
    assert invoke(v, "baseline.promote", publish).json()["status"] == "failed"
    assert count(v, ImagePublicationRecord) == 0


def test_code_only_can_publish_and_later_source_updates_do_not_rewrite_head(evidence_api):
    v = evidence_api
    v["image_url"] = f"/v1/projects/{v['project_id']}/system-image"
    image = candidate(v)
    v.update(publication_url=v["image_url"] + "/publications", target=dict(project_id=v["project_id"],
        image_revision_id=image["image_revision_id"], image_artifact_hash=image["artifact_hash"],
        target_baseline_id=image["baseline_id"], expected_head_id=None, policy_revision=PUBLICATION_POLICY))
    view = inspect(v)
    assert {m["source_type"] for m in view["source_members"]} == {"code"}
    approval_id, _ = review(v)
    completed(invoke(v, "baseline.promote", publish_request(v, approval_id)))
    old = history(v)["head"]
    v["path"].write_text(v["path"].read_text().replace("original", "new code revision"))
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    assert candidate(v)["artifact_hash"] != image["artifact_hash"]
    assert history(v)["head"] == old
    assert count(v, ImagePublicationRecord) == 1
    assert v["client"].get(v["publication_url"], params={"baseline_id": v["target"]["target_baseline_id"]}).status_code == 401


def test_wrong_pins_and_corrupt_original_evidence_never_publish(publication, monkeypatch):
    v = publication
    approval_id, _ = review(v)
    request = publish_request(v, approval_id)
    for change in ({"image_artifact_hash": "sha256:" + "f" * 64}, {"expected_head_id": "foreign"},
            {"target_baseline_id": "foreign"}, {"project_id": "foreign"}, {"image_revision_id": "foreign"},
            {"expected_preview_digest": "sha256:" + "f" * 64}):
        result = invoke(v, "baseline.promote", {**request, **change})
        assert result.status_code in {403, 404} or result.json()["status"] in {"failed", "denied"}, result.text
    reader = app.state.container.evidence.reader
    monkeypatch.setattr(reader.storage, "get_bytes", lambda *args, **kwargs: b"tampered private source")
    result = invoke(v, "baseline.promote", request)
    assert result.json()["status"] == "failed" and "tampered private source" not in result.text
    assert count(v, ImagePublicationRecord) == 0


@pytest.mark.parametrize("change", ["membership", "role", "policy"])
def test_publication_batch_stops_after_first_read_when_live_access_changes(publication, monkeypatch, change):
    v = publication
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    role = "project_admin" if change == "role" else "viewer"
    assert v["client"].put(membership, headers=v["headers"], json={"role": role}).status_code == 200
    repo = SourceAccessRepository()
    if change != "membership":
        for binding in repo.load_snapshot(v["project_id"]).bindings:
            snapshot = repo.load_snapshot(v["project_id"])
            readers = (v["member"]["id"],) if change == "policy" else ()
            repo.set_policy(v["project_id"], binding.binding_id, SourceAccessRule("restricted", readers),
                expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id=uuid4().hex)
    reader = app.state.container.evidence.reader
    original = reader.read
    calls = []

    def change_access(target):
        body = original(target)
        calls.append(target)
        if change == "membership":
            assert v["client"].delete(membership, headers=v["headers"]).status_code == 200
        elif change == "role":
            assert v["client"].put(membership, headers=v["headers"], json={"role": "viewer"}).status_code == 200
        else:
            snapshot = repo.load_snapshot(v["project_id"])
            repo.set_policy(v["project_id"], target.evidence.binding_id, SourceAccessRule("restricted"),
                expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id=uuid4().hex)
        return body

    monkeypatch.setattr(reader, "read", change_access)
    response = v["client"].get(v["publication_url"] + "/preview", headers=v["member_headers"],
        params={key: value for key, value in v["target"].items() if key not in {"project_id", "policy_revision"} and value is not None})
    assert response.status_code == 403, response.text
    assert len(calls) == 1, "no further archived file may be fetched after revocation"
    assert calls[0].evidence.object_ref not in response.text and "HTTP 400" not in response.text
    assert count(v, ImagePublicationRecord) == count(v, ImagePublicationReviewRecord) == 0
