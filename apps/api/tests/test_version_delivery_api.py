"""M1 API, canonical runtime, immutable facts, and real PostgreSQL commit fences."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.tool_models import ToolInvocation
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.db_models import (
    AuditEventRecord, ProjectRecord, ReleaseReadinessRecord, SSEEventOutboxRecord, ToolInvocationRecord, UserIdentityRecord,
)
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceBindingRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.persistence.version_delivery_models import (
    ProjectDeliveryRecord, VersionCreationRecord, VersionImageBindingRecord,
)
from apps.api.app.main import app
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_image_publications_api import publication, history, review, review_request, publish_request
from apps.api.tests.test_semantic_evaluations_api import completed, invoke, count


def publish(v, previous=None):
    target = {**v["target"], "expected_head_id": previous["publication_id"] if previous else None}
    approval, _ = review(v, review_request(v, target=target))
    completed(invoke(v, "baseline.promote", publish_request(v, approval, target), key=uuid4().hex))
    return history(v)["head"]


def binding(head):
    return {key: head[key] for key in ("publication_id", "image_revision_id", "image_artifact_hash")} | {
        "expected_head_id": head["publication_id"]}


def create(v, head=None, *, name="M1", key=None, project_id=None, headers=None):
    return v["client"].post(f"/v1/projects/{project_id or v['project_id']}/versions",
        headers={**(headers or v["headers"]), **({"Idempotency-Key": key} if key else {})},
        json={"name": name, **({"image_binding": binding(head)} if head else {})})


def delivery(v, version_id, *, project_id=None, headers=None):
    return v["client"].get(f"/v1/projects/{project_id or v['project_id']}/versions/{version_id}/delivery",
        headers=headers or v["headers"])


def test_legacy_opt_in_atomic_version_and_read_contract(publication):
    v = publication
    legacy = create(v, name="Legacy")
    assert legacy.status_code == 200, legacy.text
    old = delivery(v, legacy.json()["id"])
    assert old.status_code == 200 and old.json()["stage"] == "legacy"
    assert old.json()["enabled"] is False and old.json()["baseline"] is None
    head = publish(v)
    key = uuid4().hex
    response = create(v, head, key=key)
    assert response.status_code == 200, response.text
    version = response.json()
    assert set(version) == {"id", "name", "status", "branch_name", "us_total", "us_closed", "pending_runs", "pending_approvals"}
    read = delivery(v, version["id"])
    assert read.status_code == 200, read.text
    assert read.headers["cache-control"] == "private, no-store"
    result = read.json()
    assert set(result) == {"project_id", "version_id", "name", "enabled", "stage", "baseline", "iteration_image",
        "code_revisions", "blockers", "pending_confirmations", "available_actions"}
    assert result["baseline"] == result["iteration_image"]
    assert result["baseline"]["publication_id"] == head["publication_id"]
    assert result["baseline"]["quality_generation_authorized"] is False
    assert result["baseline"]["release_authorized"] is False
    assert result["stage"] == "image_pinned" and result["enabled"] is True
    assert result["blockers"] == ["requirement_input_required"] and result["pending_confirmations"] == []
    assert result["available_actions"] == ["view_pinned_image"] and len(result["code_revisions"]) == 1
    assert result["code_revisions"][0]["commit_sha"] is None
    assert create(v, head, key=key).json() == version
    assert create(v, head, key=key, name="changed").status_code == 409
    assert create(v).status_code == 409
    assert delivery(v, legacy.json()["id"]).json() == old.json()
    with session_scope() as session:
        receipt = session.scalar(select(VersionCreationRecord).where(VersionCreationRecord.version_id == version["id"]))
        command = session.get(ToolInvocationRecord, receipt.invocation_id)
        assert command.tool_id == "version.create" and command.result_payload["version_delivery"] == result
        assert session.get(ProjectDeliveryRecord, v["project_id"]).enabled_by_version_id == version["id"]
        assert session.get(ReleaseReadinessRecord, version["id"]).score == 0
        assert session.scalar(select(func.count()).select_from(AuditEventRecord).where(
            AuditEventRecord.action == "version.created", AuditEventRecord.entity_id == version["id"])) == 1
        assert session.scalar(select(func.count()).select_from(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.event_type == "version.created", SSEEventOutboxRecord.entity_id == version["id"])) == 1
    for model in (VersionCreationRecord, VersionImageBindingRecord, ProjectDeliveryRecord):
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as session:
                session.execute(delete(model).where(model.project_id == v["project_id"]))
    with pytest.raises(IntegrityError, match="append-only"):
        with session_scope() as session:
            session.execute(update(VersionImageBindingRecord).where(VersionImageBindingRecord.version_id == version["id"]).values(content_hash="bad"))


def test_current_head_cross_project_and_version_isolation(publication):
    v = publication
    first = publish(v)
    one = create(v, first, name="One", key="one").json()
    before = delivery(v, one["id"]).json()
    second = publish(v, first)
    assert create(v, first, name="Stale").status_code == 409
    two = create(v, second, name="Two").json()
    assert two["id"] != one["id"]
    assert delivery(v, two["id"]).json()["baseline"]["publication_id"] == second["publication_id"]
    assert delivery(v, one["id"]).json() == before
    assert create(v, first, name="One", key="one").json() == one
    other = v["client"].post("/v1/projects", headers=v["headers"], json={"name": uuid4().hex}).json()["id"]
    assert create(v, second, project_id=other).status_code == 404
    assert delivery(v, one["id"], project_id=other).status_code == 404
    for replacement in ({"image_revision_id": "foreign"}, {"image_artifact_hash": "sha256:" + "b" * 64},
            {"expected_head_id": first["publication_id"]}):
        response = v["client"].post(f"/v1/projects/{v['project_id']}/versions", headers=v["headers"],
            json={"name": "Mismatch", "image_binding": {**binding(second), **replacement}})
        assert response.status_code == 409, response.text
    assert count(v, VersionImageBindingRecord) == 2
    # A committed invocation can recover after losing its runtime completion, without rechecking today's head.
    with session_scope() as session:
        receipt = session.scalar(select(VersionCreationRecord).where(VersionCreationRecord.version_id == one["id"]))
        row = session.get(ToolInvocationRecord, receipt.invocation_id)
        row.status = "running"
        invocation = ToolInvocation(id=row.id, tool_id=row.tool_id, status="running", summary="recover", input_payload=row.input_payload)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        version, recovered = app.state.container.version_delivery.create(v["project_id"], invocation)
        assert version.id == one["id"] and recovered.model_dump(mode="json") == before
    assert count(v, VersionCreationRecord) == 2


def test_outbox_failure_rolls_back_version_binding_opt_in_and_audit(publication, monkeypatch):
    v = publication
    head = publish(v)
    before = v["client"].get(f"/v1/projects/{v['project_id']}/versions", headers=v["headers"]).json()
    with session_scope() as session:
        active_before = session.get(ProjectRecord, v["project_id"]).active_version
    original = EventOutboxRepository.append
    def fail(self, event, **kwargs):
        if event.event_type == "version.created":
            raise RuntimeError("Injected Version outbox failure")
        return original(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    assert create(v, head).status_code == 500
    for model in (VersionCreationRecord, VersionImageBindingRecord, ProjectDeliveryRecord):
        assert count(v, model) == 0
    assert v["client"].get(f"/v1/projects/{v['project_id']}/versions", headers=v["headers"]).json() == before
    with session_scope() as session:
        assert session.get(ProjectRecord, v["project_id"]).active_version == active_before
        assert session.scalar(select(AuditEventRecord.id).where(AuditEventRecord.action == "version.created",
            AuditEventRecord.event_metadata["project_id"].as_string() == v["project_id"])) is None


def test_current_head_change_before_commit_rejects_create(publication, monkeypatch):
    v = publication
    first = publish(v)
    repository = app.state.container.version_delivery.repository
    original = repository.create
    changed = []
    def race(*args, **kwargs):
        changed.append(publish(v, first))
        return original(*args, **kwargs)
    monkeypatch.setattr(repository, "create", race)
    response = create(v, first)
    assert response.status_code == 409, response.text
    assert changed and count(v, VersionCreationRecord) == 0 and count(v, ProjectDeliveryRecord) == 0


def test_two_concurrent_versions_and_same_key_are_isolated(publication):
    v = publication
    head = publish(v)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda name: create(v, head, name=name, key=name), ("One", "Two")))
    assert all(result.status_code == 200 for result in results), [r.text for r in results]
    assert len({result.json()["id"] for result in results}) == 2
    with ThreadPoolExecutor(max_workers=2) as pool:
        repeated = list(pool.map(lambda _: create(v, head, name="Three", key="three"), range(2)))
    assert all(result.status_code in {200, 409} for result in repeated), [r.text for r in repeated]
    assert create(v, head, name="Three", key="three").status_code == 200
    assert count(v, VersionCreationRecord) == count(v, VersionImageBindingRecord) == 3


def test_distinct_creator_source_revoke_blocks_read_and_original_replay(publication):
    v = publication
    head = publish(v)
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    response = create(v, head, headers=v["member_headers"], key="member-create")
    assert response.status_code == 200, response.text
    version_id = response.json()["id"]
    initial = delivery(v, version_id, headers=v["member_headers"])
    assert initial.status_code == 200
    with session_scope() as session:
        receipt = session.scalar(select(VersionCreationRecord).where(VersionCreationRecord.version_id == version_id))
        assert receipt.actor_id == v["member"]["id"] and receipt.actor_id != head["actor_id"]
        invocation_id = receipt.invocation_id
    repository = SourceAccessRepository()
    snapshot = repository.load_snapshot(v["project_id"])
    repository.set_policy(v["project_id"], initial.json()["code_revisions"][0]["binding_id"], SourceAccessRule("restricted"),
        expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="revoke-" + uuid4().hex)
    assert delivery(v, version_id, headers=v["member_headers"]).status_code == 403
    assert create(v, head, headers=v["member_headers"], key="member-create").status_code == 403
    assert v["client"].get(f"/v1/tool-invocations/{invocation_id}", headers=v["member_headers"]).status_code == 403
    assert create(v, head, headers=v["member_headers"], key="new-after-revoke").status_code == 403
    assert delivery(v, version_id).json() == initial.json()
    assert count(v, VersionCreationRecord) == 1


def test_revocation_between_request_and_commit_leaves_no_version(publication, monkeypatch):
    v = publication
    head = publish(v)
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    repository = app.state.container.version_delivery.repository
    original = repository.create
    def revoke(*args, **kwargs):
        assert v["client"].delete(membership, headers=v["headers"]).status_code == 200
        return original(*args, **kwargs)
    monkeypatch.setattr(repository, "create", revoke)
    assert create(v, head, headers=v["member_headers"]).status_code == 403
    assert count(v, VersionCreationRecord) == count(v, ProjectDeliveryRecord) == 0


def test_git_ref_sha_are_captured_and_later_publication_preserves_history(evidence_api, tmp_path, monkeypatch):
    from apps.api.tests.test_git_source_connector import _git, _create_repository
    from apps.api.tests.test_source_tracked_ref_api import install_connector, register_refs
    from apps.api.tests.test_reference_links_api import candidate
    from apps.api.app.domain.system_image.publication import PUBLICATION_POLICY
    v = evidence_api
    origin = tmp_path / "origin"
    commit = _create_repository(origin)
    _git(origin, "branch", "-M", "main")
    install_connector(monkeypatch, tmp_path)
    register_refs(v, origin, ["refs/heads/main"])
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    v["image_url"] = f"/v1/projects/{v['project_id']}/system-image"
    image = candidate(v)
    v.update(publication_url=v["image_url"] + "/publications", target=dict(project_id=v["project_id"],
        image_revision_id=image["image_revision_id"], image_artifact_hash=image["artifact_hash"],
        target_baseline_id=image["baseline_id"], expected_head_id=None, policy_revision=PUBLICATION_POLICY))
    head = publish(v)
    response = create(v, head)
    assert response.status_code == 200, response.text
    version_id = response.json()["id"]
    old = delivery(v, version_id).json()
    code = next(item for item in old["code_revisions"] if item["repository"] == origin.as_uri())
    assert code["tracked_ref"] == "refs/heads/main" and code["commit_sha"] == commit
    assert code["external_revision"] == commit
    # Migration 0093 already protects the source identity independently of M1.
    with pytest.raises(IntegrityError, match="source binding identity is immutable"):
        with session_scope() as session:
            session.get(SourceBindingRecord, code["binding_id"]).tracked_ref = "refs/heads/relabelled"
    assert delivery(v, version_id).json() == old
    (origin / "checkout.py").write_text("def updated():\n    return 3\n")
    _git(origin, "add", ".")
    _git(origin, "commit", "-m", "later revision")
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    newer = candidate(v)
    v["target"].update(image_revision_id=newer["image_revision_id"], image_artifact_hash=newer["artifact_hash"])
    next_head = publish(v, head)
    second = create(v, next_head, name="Next").json()
    next_code = next(item for item in delivery(v, second["id"]).json()["code_revisions"] if item["repository"] == origin.as_uri())
    assert next_code["commit_sha"] == _git(origin, "rev-parse", "HEAD") != commit
    assert delivery(v, version_id).json() == old


def test_committed_result_survives_missing_handler_completion(publication, monkeypatch):
    from apps.api.app.application.platform.tool_handlers.project_version import ProjectVersionToolHandler
    v = publication
    head = publish(v)
    async def no_completion(self, invocation, result):
        pass
    monkeypatch.setattr(ProjectVersionToolHandler, "_complete_result", no_completion)
    first = create(v, head, key="lost-completion")
    assert first.status_code == 200, first.text
    assert create(v, head, key="lost-completion").json() == first.json()
    assert count(v, VersionCreationRecord) == count(v, VersionImageBindingRecord) == 1


def test_global_admin_downgrade_cannot_reuse_request_source_privileges(publication, monkeypatch):
    v = publication
    head = publish(v)
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    with session_scope() as session:
        session.get(UserIdentityRecord, v["member"]["id"]).role = "platform_admin"
    repository = app.state.container.version_delivery.repository
    original = repository.create
    def downgrade(*args, **kwargs):
        with session_scope() as session:
            session.get(UserIdentityRecord, v["member"]["id"]).role = "tester"
        return original(*args, **kwargs)
    monkeypatch.setattr(repository, "create", downgrade)
    response = create(v, head, headers=v["member_headers"])
    assert response.status_code == 403, response.text
    assert count(v, VersionCreationRecord) == count(v, ProjectDeliveryRecord) == 0
