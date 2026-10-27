import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.domain.system_image.semantic_membership import FREEZE_SEMANTIC_TOOL
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.semantic_membership_models import ImageSemanticMemberRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.application.system_image.semantic_membership import SemanticFreezeInput
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.tests.test_semantic_review_api import semantic, documents, evidence_api, evaluate, submit, support, completed, invoke, confirm, count
from apps.api.tests.test_source_access_api import grant_member


def setup(v):
    url, review, _ = evaluate(v)
    completed(submit(v, review))
    page = v["client"].get(url, headers=v["headers"]).json()
    payload = dict(project_id=v["project_id"], parent_revision_id=v["request"]["image_revision_id"],
                   parent_artifact_hash=v["request"]["expected_image_hash"], decision_ids=[page["head_decision_id"]])
    return url, review, payload, page


def freeze(v, payload, *, key=None, headers=None, confirmed=True):
    pending = invoke(v, FREEZE_SEMANTIC_TOOL, payload, key=key or uuid4().hex, headers=headers)
    if confirmed and pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation":
        return v["client"].post(f"/v1/tool-invocations/{pending.json()['id']}/confirm", headers=headers or v["headers"])
    return pending


def child(v, response):
    result = completed(response)
    revision = result["result"]["object_refs"][0].split(":", 1)[1]
    url = f"{v['image_url']}/revisions/{revision}"
    page = v["client"].get(url, headers=v["headers"], params={"section": "semantic_assertion_members"})
    assert page.status_code == 200, page.text
    assert page.headers["cache-control"] == "private, no-store"
    return url, page.json()


def test_semantic_freeze_pins_exact_history_and_query_receipt_survives_redecision(semantic, monkeypatch):
    v = semantic
    support(v, monkeypatch)
    url, review, payload, original = setup(v)
    pending = freeze(v, {**payload, "confirmed_by_user": True}, confirmed=False, key="freeze-semantic")
    assert pending.json()["status"] == "waiting_confirmation" and count(v, ImageSemanticMemberRecord) == 0
    done = confirm(v, pending.json())
    child_url, first = child(v, done)
    assert first["revision"]["policy_version"] == "nasus.image-candidate.v3" and first["revision"]["assertion_count"] == 1
    assert first["items"][0]["decision"] == original["head"]
    assert first["items"][0]["assertion"]["authority_status"] == "pending_confirmation"
    assert first["revision"]["parent_revision_id"] == payload["parent_revision_id"]
    assert first["revision"]["publication"] == "blocked_pending_revision_governance"
    assert child(v, freeze(v, payload))[1] == first and count(v, ImageSemanticMemberRecord) == 1
    parent_url = f"{v['image_url']}/revisions/{payload['parent_revision_id']}"
    for section in ("objects", "members", "source_members", "relationships", "assertion_members"):
        assert v["client"].get(child_url, headers=v["headers"], params={"section": section}).json()["items"] == v["client"].get(
            parent_url, headers=v["headers"], params={"section": section}).json()["items"]
    query = completed(invoke(v, "query.system_image.revisions.read", dict(project_id=v["project_id"],
        image_revision_id=first["revision"]["image_revision_id"], section="semantic_assertion_members")))
    assert review["reason"] not in str(query["result"]["image_query"])
    assert query["result"]["image_query"]["item_ids"] == [original["assertion"]["claim_id"]]
    completed(submit(v, {**review, "decision": "accept", "expected_previous_decision_id": payload["decision_ids"][0]}))
    assert freeze(v, payload).json()["result"]["followup_reason"] == "stale_semantic_decision"
    assert completed(freeze(v, payload, key="freeze-semantic"))["id"] == done.json()["id"]
    assert v["client"].get(f"/v1/tool-invocations/{query['id']}/image-query", headers=v["headers"]).json() == first
    changed = v["client"].get(url, headers=v["headers"]).json()
    _, second = child(v, freeze(v, {**payload, "parent_revision_id": first["revision"]["image_revision_id"],
        "parent_artifact_hash": first["revision"]["artifact_hash"], "decision_ids": [changed["head_decision_id"]]}))
    assert second["items"][0]["decision"]["decision"] == "accept"
    assert v["client"].get(child_url, headers=v["headers"], params={"section": "semantic_assertion_members"}).json() == first
    assert len(v["calls"]) == 1
    for statement in (delete(ImageSemanticMemberRecord).where(ImageSemanticMemberRecord.project_id == v["project_id"]),
                      update(ImageSemanticMemberRecord).where(ImageSemanticMemberRecord.project_id == v["project_id"]).values(content_hash="bad")):
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as session:
                session.execute(statement)
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    spec = importlib.util.spec_from_file_location("semantic_membership_migration", Path(__file__).resolve().parents[1] / "migrations/versions/0049_semantic_membership.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with pytest.raises(RuntimeError, match="cannot discard"):
        with session_scope() as session:
            migration.op = Operations(MigrationContext.configure(session.connection()))
            migration.downgrade()


def test_semantic_freeze_rejects_bad_pins_duplicates_roles_and_project_scope(semantic):
    v = semantic
    _, _, payload, _ = setup(v)
    grant_member(v)
    denied = freeze(v, payload, headers=v["member_headers"])
    assert denied.status_code == 403 or denied.json()["status"] in {"failed", "denied"}
    for change in ({"decision_ids": []}, {"decision_ids": payload["decision_ids"] * 2}, {"decision_ids": ["missing"]},
                   {"decision_ids": [""]}, {"parent_artifact_hash": "sha256:" + "f" * 64}, {"parent_revision_id": "foreign"},
                   {"project_id": "foreign"}, {"approved_coverage": True}):
        result = freeze(v, {**payload, **change})
        assert result.status_code in {403, 404} or result.json()["status"] in {"failed", "denied"}, result.text
    assert count(v, ImageSemanticMemberRecord) == 0


def test_semantic_freeze_rechecks_head_and_rolls_back_transaction_failure(semantic, monkeypatch):
    v = semantic
    url, review, payload, _ = setup(v)
    artifacts = app.state.container.semantic_membership.images.artifacts
    put = artifacts.put
    def race(*args):
        result = put(*args)
        completed(submit(v, {**review, "decision": "defer", "expected_previous_decision_id": payload["decision_ids"][0]}))
        return result
    monkeypatch.setattr(artifacts, "put", race)
    assert freeze(v, payload).json()["result"]["followup_reason"] == "stale_semantic_decision"
    assert count(v, ImageSemanticMemberRecord) == 0
    monkeypatch.setattr(artifacts, "put", put)
    payload["decision_ids"] = [v["client"].get(url, headers=v["headers"]).json()["head_decision_id"]]
    append = EventOutboxRepository.append
    def fail(self, event, **kwargs):
        if event.event_type == "system_image.candidate.frozen":
            raise RuntimeError("injected outbox failure")
        return append(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    assert freeze(v, payload).json()["status"] == "failed" and count(v, ImageSemanticMemberRecord) == 0
    monkeypatch.setattr(EventOutboxRepository, "append", append)
    child(v, freeze(v, payload))


def test_semantic_frozen_reads_and_freeze_commit_reauthorize(semantic, monkeypatch):
    v = semantic
    _, _, payload, _ = setup(v)
    child_url, page = child(v, freeze(v, payload))
    grant_member(v)
    assert v["client"].get(child_url, headers=v["member_headers"], params={"section": "semantic_assertion_members"}).json() == page
    member_url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(member_url, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    artifacts = app.state.container.semantic_membership.images.artifacts
    put = artifacts.put
    def revoke(*args):
        result = put(*args)
        assert v["client"].put(member_url, headers=v["headers"], json={"role": "viewer"}).status_code == 200
        return result
    monkeypatch.setattr(artifacts, "put", revoke)
    assert freeze(v, payload, headers=v["member_headers"]).json()["status"] == "failed"
    assert count(v, ImageSemanticMemberRecord) == 1
    repo = SourceAccessRepository()
    snapshot = repo.load_snapshot(v["project_id"])
    repo.set_policy(v["project_id"], snapshot.bindings[0].binding_id, SourceAccessRule("restricted"),
        expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="semantic-member-revoke")
    denied = v["client"].get(child_url, headers=v["member_headers"], params={"section": "semantic_assertion_members"})
    assert denied.status_code == 403 and page["items"][0]["decision"]["reason"] not in denied.text


def test_lost_completion_replays_frozen_output_after_review_head_changes(semantic):
    v = semantic
    _, review, payload, _ = setup(v)
    done = freeze(v, payload)
    _, original = child(v, done)
    completed(submit(v, {**review, "decision": "defer", "expected_previous_decision_id": payload["decision_ids"][0]}))
    with session_scope() as session:
        session.get(ToolInvocationRecord, done.json()["id"]).status = "running"
    # Simulate worker recovery after the fact commit but before its terminal
    # status. Reconfirming a running HTTP invocation is deliberately a no-op.
    with actor_scope(UserProfile.model_validate(v["owner"])):
        retried = app.state.container.semantic_membership.freeze(SemanticFreezeInput.model_validate(payload),
            invocation_id=done.json()["id"], recorded_at="recovery")
        assert retried.image_revision_id == original["revision"]["image_revision_id"]
        assert retried.artifact_hash == original["revision"]["artifact_hash"]
    assert count(v, ImageSemanticMemberRecord) == 1


def test_semantic_freeze_canonical_payload_tamper_cannot_commit(semantic, monkeypatch):
    v = semantic
    _, _, payload, _ = setup(v)
    repository = app.state.container.semantic_membership.images.repository
    record = repository.record
    def tamper(*args, **kwargs):
        with session_scope() as session:
            invocation = session.get(ToolInvocationRecord, kwargs["invocation_id"])
            invocation.input_payload = {**invocation.input_payload, "parent_artifact_hash": "sha256:" + "a" * 64}
        return record(*args, **kwargs)
    monkeypatch.setattr(repository, "record", tamper)
    assert freeze(v, payload).json()["status"] == "failed"
    assert count(v, ImageSemanticMemberRecord) == 0


def test_semantic_decision_cannot_move_to_new_source_revision(semantic):
    from apps.api.tests.test_document_projection_api import REQUIREMENT
    from apps.api.tests.test_reference_links_api import candidate
    v = semantic
    _, _, payload, _ = setup(v)
    v["requirement_path"].write_text(REQUIREMENT.replace("400", "422"))
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    newer = candidate(v)
    assert newer["image_revision_id"] != payload["parent_revision_id"]
    invalid = freeze(v, {**payload, "parent_revision_id": newer["image_revision_id"], "parent_artifact_hash": newer["artifact_hash"]})
    assert invalid.json()["status"] == "failed" and count(v, ImageSemanticMemberRecord) == 0
    assert child(v, freeze(v, payload))[1]["items"][0]["decision"]["decision"] == "reject"
