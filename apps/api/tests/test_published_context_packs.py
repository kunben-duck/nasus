"""Published context derivations preserve history without retaining live head authority."""
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from apps.api.app.main import app
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.system_image.context_pack_inputs import ContextPreviewInput, ContextCompileInput
from apps.api.app.domain.system_image.context_partition import PUBLISHED_CONTEXT_POLICY
from apps.api.app.domain.system_image.context_pack import ContextPublicationChanged
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.context_pack_models import ContextPackRecord
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, BaselineRecord
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_image_publications_api import publication, review, publish_request, history
from apps.api.tests.test_published_image_reads import publish
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_semantic_evaluations_api import invoke, completed, count
from apps.api.tests.test_source_access_api import grant_member
from apps.api.tests.test_context_packs_api import archive, read


def request_for(v, head):
    return dict(project_id=v["project_id"], image_revision_id=head["image_revision_id"],
        image_artifact_hash=head["image_artifact_hash"], policy_revision=PUBLISHED_CONTEXT_POLICY,
        publication_id=head["publication_id"])


def preview_response(v, request, headers=None):
    return v["client"].get(v["image_url"] + "/context-packs/preview", headers=headers or v["headers"],
        params={k: value for k, value in request.items() if k != "project_id"})


def advance(v, head):
    v["target"] = {**v["target"], "expected_head_id": head["publication_id"]}
    return publish(v)


def test_context_request_serialization_preserves_legacy_hash_inputs():
    base = dict(project_id="project", image_revision_id="image", image_artifact_hash="sha256:" + "a" * 64,
        purpose="test_design", max_tokens=12000, candidate_limit=5)
    for version in (1, 2, 3):
        payload = {**base, "policy_revision": f"nasus.test-design-context.v{version}"}
        assert ContextPreviewInput.model_validate(payload).model_dump(mode="json") == payload
        command = {**payload, "expected_input_digest": "sha256:" + "b" * 64}
        assert json.loads(ContextCompileInput.model_validate(command).model_dump_json()) == command
        with pytest.raises(ValidationError):
            ContextPreviewInput.model_validate({**payload, "publication_id": "publication"})
    with pytest.raises(ValidationError):
        ContextPreviewInput.model_validate({**base, "policy_revision": PUBLISHED_CONTEXT_POLICY})


def test_published_context_archive_pins_head_and_replays_after_republication(publication):
    v = publication
    head = publish(v)
    response = preview_response(v, request_for(v, head))
    assert response.status_code == 200, response.text
    view = response.json()
    assert response.headers["cache-control"] == "private, no-store"
    pin = view["context"]["publication_pin"]
    assert all(head[key] == value for key, value in pin.items())
    assert "image_not_published" not in view["context"]["readiness"]["reason_codes"]
    assert view["context"]["readiness"]["status"] == "blocked"  # Publication is not oracle approval.
    assert all(part["context"]["publication_pin"] == pin for part in view["context"]["parts"])
    done_response, payload = archive(v, view)
    done = completed(done_response)
    before, url = read(v, done)
    query = completed(invoke(v, "query.system_image.context.preview", view["request"]))
    assert query["result"]["context_pack"]["request"]["publication_id"] == head["publication_id"]
    assert "Empty input" not in json.dumps(query["result"]["context_pack"])
    next_head = advance(v, head)
    assert next_head["sequence"] == head["sequence"] + 1
    stale = preview_response(v, request_for(v, head))
    assert stale.status_code == 409 and stale.json()["detail"]["error"]["code"] == "context_inputs_changed"
    after = v["client"].get(url, headers=v["headers"])
    assert after.status_code == 200, after.text
    assert after.json()["context"] == before["context"]
    assert after.json()["current_use"] == {"stale": True, "generation_authorized": False, "reason": "published_image_head_changed"}
    with session_scope() as session:
        session.get(ToolInvocationRecord, done["id"]).status = "running"
    with actor_scope(UserProfile.model_validate(v["owner"])):
        restored = app.state.container.context_packs.compile(ContextCompileInput.model_validate(payload), invocation_id=done["id"], recorded_at="retry")
        assert restored == before["metadata"]
        with pytest.raises(ContextPublicationChanged, match="changed"):
            app.state.container.tool_evidence.describe(query["id"], v["project_id"])
    assert count(v, ContextPackRecord) == 1


def test_context_rechecks_head_after_artifact_write_and_does_not_commit(publication, monkeypatch):
    v = publication
    head = publish(v)
    view = preview_response(v, request_for(v, head)).json()
    artifacts = app.state.container.context_packs.artifacts
    original = artifacts.put
    def change_head(*args):
        result = original(*args)
        advance(v, head)
        return result
    monkeypatch.setattr(artifacts, "put", change_head)
    response, _ = archive(v, view)
    assert response.json()["status"] == "failed", response.text
    assert response.json()["result"]["followup_reason"] == "context_inputs_changed"
    assert count(v, ContextPackRecord) == 0


def test_context_pin_is_required_and_cannot_relabel_unpublished_or_other_image(publication):
    v = publication
    approval, _ = review(v)
    fake = {**v["target"], "publication_id": approval, "policy_revision": PUBLISHED_CONTEXT_POLICY}
    request = {key: fake[key] for key in ("project_id", "image_revision_id", "image_artifact_hash", "publication_id", "policy_revision")}
    assert preview_response(v, request).status_code == 502  # A review is not a publication.
    completed(invoke(v, "baseline.promote", publish_request(v, approval)))
    head = history(v)["head"]
    request = request_for(v, head)
    for changed in ({"publication_id": "missing"}, {"image_revision_id": "other"}, {"image_artifact_hash": "sha256:" + "b" * 64}):
        assert preview_response(v, {**request, **changed}).status_code == 502
    assert preview_response(v, {k: value for k, value in request.items() if k != "publication_id"}).status_code == 422
    assert preview_response(v, {**request, "policy_revision": "nasus.test-design-context.v3"}).status_code == 422


def test_context_checks_head_again_after_retrieval(publication, monkeypatch):
    v = publication
    head = publish(v)
    sources = app.state.container.context_packs.sources
    original = sources.image_queries.execute_with_observation
    changed = False
    def change_head(*args, **kwargs):
        nonlocal changed
        result = original(*args, **kwargs)
        if not changed:
            changed = True
            advance(v, head)
        return result
    monkeypatch.setattr(sources.image_queries, "execute_with_observation", change_head)
    assert preview_response(v, request_for(v, head)).status_code == 409
    assert changed


def test_published_context_read_revalidates_acl_and_hides_corrupt_pins(publication, monkeypatch):
    v = publication
    head = publish(v)
    view = preview_response(v, request_for(v, head)).json()
    done = completed(archive(v, view)[0])
    _, url = read(v, done)
    grant_member(v)
    assert preview_response(v, request_for(v, head), v["member_headers"]).status_code == 200
    service = app.state.container.image_publications
    original = service.repository.publication
    def corrupt(*args):
        result = original(*args)
        return {**result, "manifest_hash": "sha256:" + "a" * 64}
    with monkeypatch.context() as patch:
        patch.setattr(service.repository, "publication", corrupt)
        assert v["client"].get(url, headers=v["headers"]).status_code == 502
    repo = SourceAccessRepository()
    snapshot = repo.load_snapshot(v["project_id"])
    repo.set_policy(v["project_id"], snapshot.bindings[0].binding_id, SourceAccessRule("restricted"),
        expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="published-context-revoke")
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 403
    assert preview_response(v, request_for(v, head), v["member_headers"]).status_code == 403


def test_version_published_context_does_not_follow_official_head(publication):
    v = publication
    official = publish(v)
    official_target = dict(v["target"])
    with session_scope() as session:
        baseline_id = str(uuid4())
        session.add(BaselineRecord(id=baseline_id, project_id=v["project_id"], kind="version_working",
            source_version_id="context-version", updated_at="2026-09-19T00:00:00Z"))
    v["target"] = {**official_target, "target_baseline_id": baseline_id, "expected_head_id": None}
    version = publish(v)
    request = request_for(v, version)
    before = preview_response(v, request)
    assert before.status_code == 200 and before.json()["context"]["publication_pin"]["baseline_id"] == baseline_id
    v["target"] = official_target
    advance(v, official)
    assert preview_response(v, request).json() == before.json()
