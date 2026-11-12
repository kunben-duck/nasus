"""Actual PG/MinIO intake: immutable drafts are never review or generation authority."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.infrastructure.persistence.db_models import (
    AuditEventRecord, SSEEventOutboxRecord, USWorkItemRecord, QualityAssetPackRecord, RunRecord, ReleaseReadinessRecord,
)
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.requirement_revision_models import RequirementRevisionRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.tests.test_version_delivery_api import publication, documents, evidence_api, create, publish, delivery, history


@pytest.fixture
def iteration(publication):
    v = publication
    v["version"] = create(v, publish(v)).json()["id"]
    pin = delivery(v, v["version"]).json()["iteration_image"]
    v["request"] = dict(project_id=v["project_id"], version_id=v["version"],
        image_revision_id=pin["image_revision_id"], image_artifact_hash=pin["image_artifact_hash"],
        title="US-001 Article editing", text="Support editing articles", clarification_answers=[])
    return v


def save(v, request=None, *, key=None, headers=None):
    response = v["client"].post("/v1/tool-invocations", headers=headers or v["headers"], json={
        "tool_id": "quality.requirement.revise", "input": request or v["request"],
        "idempotency_key": key or uuid4().hex, "initiator_actor": "user", "initiator_surface": "api"})
    assert response.status_code == 200, response.text
    return response.json()


def read(v, **params):
    return v["client"].get(f"/v1/projects/{v['project_id']}/versions/{v['version']}/requirements",
        headers=v["headers"], params=params)


def test_intake_replay_history_and_clarification_are_durable_but_unapproved(iteration):
    v = iteration
    key = uuid4().hex
    created = save(v, key=key)
    assert created["status"] == "completed", created
    assert save(v, key=key)["id"] == created["id"]
    response = read(v)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    first = response.json()["items"][0]
    assert first["status"] == "draft" and first["generation_authorized"] is False
    assert first["text"] == first["original_text"] == v["request"]["text"]
    revised = {**v["request"], "us_id": first["us_id"], "expected_revision_id": first["revision_id"],
        "text": "Only the author may edit an article", "clarification_answers": [
            {"question": "May another user edit it?", "answer": "No, reject it without changing the article."}]}
    assert save(v, revised)["status"] == "completed"
    latest = read(v).json()["items"][0]
    assert latest["sequence"] == 2 and latest["previous_revision_id"] == first["revision_id"]
    assert latest["original_text"] == first["text"]
    assert latest["clarification_answers"] == revised["clarification_answers"]
    assert read(v, us_id=first["us_id"]).json()["items"] == [latest, first]
    assert save(v, revised)["status"] == "failed"  # stale parent, even with a different command key
    assert save(v, {**revised, "expected_revision_id": latest["revision_id"], "clarification_answers": []})["status"] == "failed"
    assert read(v).json()["items"] == [latest]
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(RequirementRevisionRecord)
            .where(RequirementRevisionRecord.version_id == v["version"])) == 2
        assert session.scalar(select(func.count()).select_from(AuditEventRecord)
            .where(AuditEventRecord.action == "requirement.revised", AuditEventRecord.entity_id == latest["revision_id"])) == 1
        assert session.scalar(select(func.count()).select_from(SSEEventOutboxRecord)
            .where(SSEEventOutboxRecord.event_type == "requirement.revised", SSEEventOutboxRecord.entity_id == latest["revision_id"])) == 1
    for operation in (delete(RequirementRevisionRecord), update(RequirementRevisionRecord).values(content_hash="tampered")):
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as session:
                session.execute(operation.where(RequirementRevisionRecord.revision_id == first["revision_id"]))


def test_wrong_iteration_image_or_parent_rejected_without_us_rows(iteration):
    v = iteration
    before = read(v).json()
    for changes in ({"version_id": "missing"}, {"image_artifact_hash": "sha256:" + "b" * 64},
            {"us_id": "other", "expected_revision_id": "other"}, {"version_id": ""}):
        assert save(v, {**v["request"], **changes})["status"] == "failed"
    assert read(v).json() == before
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(USWorkItemRecord)
            .where(USWorkItemRecord.version_id == v["version"])) == 0


def test_concurrent_revision_cas_has_one_winner(iteration):
    v = iteration
    assert save(v)["status"] == "completed"
    first = read(v).json()["items"][0]
    request = {**v["request"], "us_id": first["us_id"], "expected_revision_id": first["revision_id"]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda text: save(v, {**request, "text": text}), ["Edit article title", "Edit article body"]))
    assert sorted(item["status"] for item in results) == ["completed", "failed"], results
    assert len(read(v, us_id=first["us_id"]).json()["items"]) == 2


def test_requirement_and_us_rollback_when_outbox_append_fails(iteration, monkeypatch):
    v = iteration
    original = EventOutboxRepository.append
    def fail(self, event, **kwargs):
        if event.event_type == "requirement.revised":
            raise RuntimeError("injected requirement outbox failure")
        return original(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    response = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "tool_id": "quality.requirement.revise", "input": v["request"], "idempotency_key": uuid4().hex})
    assert response.status_code == 500 or response.json()["status"] == "failed"
    assert read(v).json()["items"] == []
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(USWorkItemRecord)
            .where(USWorkItemRecord.version_id == v["version"])) == 0


def test_source_revoke_blocks_list_write_and_completed_receipt_replay(iteration):
    v = iteration
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    created = save(v, headers=v["member_headers"], key="member-draft")
    assert created["status"] == "completed", created
    sources = delivery(v, v["version"]).json()["code_revisions"]
    repository = SourceAccessRepository()
    snapshot = repository.load_snapshot(v["project_id"])
    repository.set_policy(v["project_id"], sources[0]["binding_id"], SourceAccessRule("restricted"),
        expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="revoke-" + uuid4().hex)
    base = f"/v1/projects/{v['project_id']}/versions/{v['version']}/requirements"
    assert v["client"].get(base, headers=v["member_headers"]).status_code == 403
    assert v["client"].get(f"/v1/tool-invocations/{created['id']}", headers=v["member_headers"]).status_code == 403
    replay = v["client"].post("/v1/tool-invocations", headers=v["member_headers"], json={
        "tool_id": "quality.requirement.revise", "input": v["request"], "idempotency_key": "member-draft",
        "initiator_actor": "user", "initiator_surface": "api"})
    assert replay.status_code == 403, replay.text
    assert save(v, headers=v["member_headers"])["status"] == "failed"
    assert len(read(v).json()["items"]) == 1


def test_two_iterations_cannot_reuse_requirement_parent(iteration):
    v = iteration
    assert save(v)["status"] == "completed"
    first = read(v).json()["items"][0]
    other = create(v, history(v)["head"], name="Second iteration").json()["id"]
    rejected = save(v, {**v["request"], "version_id": other,
        "us_id": first["us_id"], "expected_revision_id": first["revision_id"]})
    assert rejected["status"] == "failed", rejected
    assert read(v).json()["items"] == [first]


def test_legacy_mutation_cannot_overwrite_delivery_requirement_facts(iteration):
    v = iteration
    assert save(v)["status"] == "completed"
    before = read(v).json()["items"]
    response = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "tool_id": "version.inputs.import", "input": {"project_id": v["project_id"], "version_id": v["version"],
            "us_items": [{"id": before[0]["us_id"], "title": "Overwrite via shortcut"}]}})
    assert response.status_code == 200 and response.json()["status"] == "failed", response.text
    assert read(v).json()["items"] == before
    with session_scope() as session:
        assert session.get(USWorkItemRecord, before[0]["us_id"]).title == before[0]["title"]


def test_legacy_quality_shortcuts_cannot_promote_an_unreviewed_requirement(iteration, monkeypatch):
    from apps.api.app.infrastructure.llm import LLMQualityGenerationAdapter
    v = iteration
    assert save(v)["status"] == "completed"
    draft = read(v).json()["items"][0]

    async def no_model(*args, **kwargs):
        pytest.fail("An unreviewed iteration requirement reached model generation")
    monkeypatch.setattr(LLMQualityGenerationAdapter, "generate", no_model)

    def facts():
        with session_scope() as session:
            return {model.__tablename__: [dict(row.__dict__, _sa_instance_state=None) for row in session.scalars(
                select(model).where(model.project_id == v["project_id"])).all()]
                for model in (QualityAssetPackRecord, RunRecord, ReleaseReadinessRecord, USWorkItemRecord)}

    before = facts()
    for tool in ("quality.scope.generate", "quality.scenario.generate", "quality.plan.generate", "quality.case.generate",
            "quality.asset-pack.refresh", "automation.generate", "quality.change-doc.generate", "run.start",
            "release.advice.get", "release.assess"):
        for version in ({}, {"version_id": v["version"]}):
            response = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
                "tool_id": tool, "input": {"project_id": v["project_id"], "us_id": draft["us_id"], **version}})
            assert response.status_code == 200, response.text
            if response.json()["status"] == "waiting_confirmation":
                response = v["client"].post(f"/v1/tool-invocations/{response.json()['id']}/confirm", headers=v["headers"])
            assert response.status_code == 200 and response.json()["status"] == "failed", response.text
            assert "iteration" in response.json()["summary"], response.text
    assert facts() == before
    assert read(v).json()["items"] == [draft]
