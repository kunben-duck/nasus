from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from apps.api.app.infrastructure.persistence.version_delivery_models import VersionImageAdoptionRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_version_delivery_api import (
    evidence_api, documents, publication, publish, create, delivery,
)
from apps.api.tests.test_requirement_reviews_api import command


@pytest.fixture
def adoption(evidence_api, tmp_path, monkeypatch):
    from apps.api.tests.test_git_source_connector import _git, _create_repository
    from apps.api.tests.test_source_tracked_ref_api import install_connector, register_refs
    from apps.api.tests.test_reference_links_api import candidate
    from apps.api.app.domain.system_image.publication import PUBLICATION_POLICY
    v = dict(evidence_api)
    # This acceptance scope is Git-only, not the fixture's loose source file.
    created = v["client"].post("/v1/projects", headers=v["headers"], json={"name": "Image adoption " + uuid4().hex})
    assert created.status_code == 200
    v["project_id"] = created.json()["id"]
    v["conversation"] = v["client"].post("/v1/conversations", headers=v["headers"], json={
        "space_type": "project", "space_id": v["project_id"], "title": "Git image adoption"})
    assert v["conversation"].status_code == 200
    def invoke(tool, payload=None):
        result = command(v, tool, {"project_id": v["project_id"], **(payload or {})})
        assert result["status"] == "completed", result
    v["invoke"] = invoke
    origin = tmp_path / "origin"
    _create_repository(origin)
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
    v["version"] = response.json()["id"]
    v["before"] = delivery(v, v["version"]).json()
    (origin / "checkout.py").write_text("def updated():\n    return 3\n")
    _git(origin, "add", ".")
    _git(origin, "commit", "-m", "injected test revision")
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    newer = candidate(v)
    v["option_url"] = f"/v1/projects/{v['project_id']}/versions/{v['version']}/delivery/image-options/{newer['image_revision_id']}"
    option = v["client"].get(v["option_url"], headers=v["headers"])
    assert option.status_code == 200, option.text
    assert option.json()["adoption_authorized"] is False
    assert option.headers["cache-control"] == "private, no-store"
    v["adopt_request"] = {**option.json()["request"], "reason": "Explicitly adopt injected defect for acceptance"}
    v["new_sha"] = _git(origin, "rev-parse", "HEAD")
    return v


def test_adoption_is_confirmed_append_only_cas_and_keeps_baseline(adoption):
    v = adoption
    pending = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "tool_id": "quality.iteration_image.adopt", "input": v["adopt_request"], "idempotency_key": uuid4().hex}).json()
    assert pending["status"] == "waiting_confirmation", pending
    assert delivery(v, v["version"]).json() == v["before"]
    result = v["client"].post(f"/v1/tool-invocations/{pending['id']}/confirm", headers=v["headers"])
    assert result.status_code == 200 and result.json()["status"] == "completed", result.text
    after = delivery(v, v["version"]).json()
    assert after["baseline"] == v["before"]["baseline"]
    assert after["iteration_image"]["publication_id"] is None
    assert after["iteration_image"]["adoption_id"]
    assert after["code_revisions"][0]["commit_sha"] == v["new_sha"]
    assert after["code_revisions"] != v["before"]["code_revisions"]
    assert after["iteration_image"]["release_authorized"] is False
    assert command(v, "quality.iteration_image.adopt", v["adopt_request"])["status"] == "failed"
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(VersionImageAdoptionRecord).where(
            VersionImageAdoptionRecord.project_id == v["project_id"])) == 1
    with pytest.raises(IntegrityError, match="append-only"):
        with session_scope() as session:
            session.execute(delete(VersionImageAdoptionRecord).where(VersionImageAdoptionRecord.project_id == v["project_id"]))


def test_adoption_mismatched_commit_is_rejected_without_write(adoption):
    v = adoption
    wrong = {**v["adopt_request"], "code_commits": {key: "f" * 40 for key in v["adopt_request"]["code_commits"]}}
    result = command(v, "quality.iteration_image.adopt", wrong)
    assert result["status"] == "failed", result
    assert delivery(v, v["version"]).json() == v["before"]
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(VersionImageAdoptionRecord).where(
            VersionImageAdoptionRecord.project_id == v["project_id"])) == 0


def test_adoption_outbox_failure_preserves_current_binding(adoption, monkeypatch):
    from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
    v = adoption
    append = EventOutboxRepository.append
    def fail(self, event, **kwargs):
        if event.event_type == "version.image.adopted":
            raise RuntimeError("injected adoption outbox failure")
        return append(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    assert command(v, "quality.iteration_image.adopt", v["adopt_request"])["status"] == "failed"
    assert delivery(v, v["version"]).json() == v["before"]
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(VersionImageAdoptionRecord).where(
            VersionImageAdoptionRecord.project_id == v["project_id"])) == 0


def test_concurrent_adoptions_have_one_current_head(adoption):
    v = adoption
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda reason: command(v, "quality.iteration_image.adopt", {
            **v["adopt_request"], "reason": reason}), ["Adoption A", "Adoption B"]))
    assert sorted(item["status"] for item in results) == ["completed", "failed"], results
    after = delivery(v, v["version"]).json()
    assert after["baseline"] == v["before"]["baseline"]
    assert after["code_revisions"][0]["commit_sha"] == v["new_sha"]


def test_adoption_invalidates_confirmed_requirement_and_context_entry(adoption, monkeypatch):
    from apps.api.app.main import app
    from apps.api.tests.test_requirement_revisions_api import save, read
    from apps.api.tests.test_requirement_reviews_api import assessment, evaluate, review_url
    v = adoption
    pin = v["before"]["iteration_image"]
    v["request"] = dict(project_id=v["project_id"], version_id=v["version"],
        image_revision_id=pin["image_revision_id"], image_artifact_hash=pin["image_artifact_hash"],
        title="Article ownership", text="Only the author may update an article", clarification_answers=[])
    assert save(v)["status"] == "completed"
    revision = read(v).json()["items"][0]
    model = app.state.container.requirement_reviews.model
    monkeypatch.setattr(model, "prepare", lambda: ({"digest": "sha256:" + "a" * 64,
        "provider": "explicit_test_fixture", "model": "fixture", "prompt_version": "test"}, None, None))
    async def reviewed(payload, prepared):
        return assessment(payload), prepared[0]
    monkeypatch.setattr(model, "evaluate", reviewed)
    assert evaluate(v, revision)["status"] == "completed"
    view = v["client"].get(review_url(v, revision), headers=v["headers"]).json()
    assert v["client"].put(f"/v1/projects/{v['project_id']}/members/{v['member']['id']}",
        headers=v["headers"], json={"role": "project_admin"}).status_code == 200
    for item in view["approval_requests"]:
        assert command(v, "quality.acceptance_specification.review", item["input"], headers=v["member_headers"])["status"] == "completed"
    assert command(v, "quality.requirement.confirm", {"project_id": v["project_id"], "version_id": v["version"],
        "revision_id": revision["revision_id"], "evaluation_id": view["evaluation"]["event_id"],
        "review_digest": view["evaluation"]["content_hash"], "reason": "Independent confirmation"},
        headers=v["member_headers"])["status"] == "completed"
    confirmed = v["client"].get(review_url(v, revision), headers=v["headers"]).json()
    assert confirmed["status"] == "confirmed" and confirmed["test_design_context_request"] is not None
    before = delivery(v, v["version"]).json()
    request = {**v["adopt_request"], "expected_image_revision_id": before["iteration_image"]["image_revision_id"],
        "expected_image_artifact_hash": before["iteration_image"]["image_artifact_hash"]}
    result = command(v, "quality.iteration_image.adopt", request)
    assert result["status"] == "completed", result
    invalid = v["client"].get(review_url(v, revision), headers=v["headers"]).json()
    assert invalid["status"] == "image_changed" and invalid["test_design_context_request"] is None
    assert invalid["can_confirm"] is False
    after = delivery(v, v["version"]).json()
    assert after["baseline"] == v["before"]["baseline"]
    assert after["stage"] != "requirements_confirmed"


def test_adoption_preview_and_receipt_require_current_source_access(adoption):
    from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
    from apps.api.app.domain.system_image.source_access import SourceAccessRule
    v = adoption
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "viewer"}).status_code == 200
    assert v["client"].get(v["option_url"], headers=v["member_headers"]).status_code == 403
    assert v["client"].put(membership, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    option = v["client"].get(v["option_url"], headers=v["member_headers"])
    assert option.status_code == 200 and option.json()["adoption_authorized"] is False
    done = command(v, "quality.iteration_image.adopt", v["adopt_request"], headers=v["member_headers"])
    assert done["status"] == "completed", done
    access = SourceAccessRepository()
    snapshot = access.load_snapshot(v["project_id"])
    access.set_policy(v["project_id"], next(iter(v["adopt_request"]["code_commits"])), SourceAccessRule("restricted"),
        expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="revoke-adopted-source")
    for url in (v["option_url"], f"/v1/tool-invocations/{done['id']}",
            f"/v1/projects/{v['project_id']}/versions/{v['version']}/delivery"):
        response = v["client"].get(url, headers=v["member_headers"])
        assert response.status_code == 403, response.text
        assert v["new_sha"] not in response.text
