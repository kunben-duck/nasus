"""Real PG/canonical context commits; native embedding uses an explicit transport fixture."""
import json

import pytest

from apps.api.app.main import app
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.system_image.context_pack_inputs import ContextCompileInput
from apps.api.app.domain.system_image.context_partition import INDEXED_CONTEXT_POLICY
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.context_pack_models import ContextPackRecord
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_frozen_indexes_api import indexed, build, search
from apps.api.tests.test_image_publications_api import publication
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_published_image_reads import publish
from apps.api.tests.test_semantic_evaluations_api import invoke, completed, count
from apps.api.tests.test_context_packs_api import archive, read
from apps.api.tests.test_published_context_packs import request_for, preview_response
from apps.api.tests.test_source_access_api import grant_member
from apps.api.tests.test_semantic_review_api import semantic, evaluate, submit


@pytest.fixture
def recalled(indexed):
    v = indexed
    build(v)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        found = search(v)
        trace_id = found.retrieval_run_refs[0].split(":", 1)[1]
        _, image = app.state.container.image_revisions.frozen_snapshot(v["project_id"], v["index_head"]["image_revision_id"])
    targets = [obj["id"] for obj in image["objects"] if obj["type"] == "SourceAcceptanceCriterion"]
    assert targets
    v["context_request"] = {**request_for(v, v["index_head"]), "policy_revision": INDEXED_CONTEXT_POLICY,
        "retrieval_bindings": {target: trace_id for target in targets}, "candidate_limit": 1}
    v["trace_id"] = trace_id
    return v


def response(v, **changes):
    payload = {**v["context_request"], **changes}
    if "retrieval_bindings" in payload:
        payload["retrieval_bindings"] = json.dumps(payload["retrieval_bindings"])
    return preview_response(v, payload)


def change_model(v):
    v["index_service"].models.repository.save_model_config(
        v["index_config"].model_copy(update={"updated_at": "changed-after-trace"}), v["index_encrypted"])


def test_indexed_context_canonical_compile_and_replay_never_call_provider(recalled, monkeypatch):
    v = recalled
    calls = len(v["index_calls"])
    async def forbidden(*args, **kwargs):
        pytest.fail("Context compilation/replay must not invoke a provider")
    monkeypatch.setattr(v["index_service"], "_embed", forbidden)
    plain = preview_response(v, request_for(v, v["index_head"])).json()
    result = response(v)
    assert result.status_code == 200, result.text
    view = result.json()
    assert result.headers["cache-control"] == "private, no-store"
    assert view["context"]["required_constraints"] == plain["context"]["required_constraints"]
    assert view["context"]["facts"]
    assert view["context"]["retrieval"]["method"] == "nasus.link-recall.indexed-reviewed.v3"
    assert view["context"]["retrieval"]["fallback_used"] is False
    assert "lexical_retrieval_only" not in view["context"]["readiness"]["reason_codes"]
    done = completed(archive(v, view)[0])
    before, _ = read(v, done)
    assert before["context"] == view["context"] and not before["current_use"]["stale"]
    observed = completed(invoke(v, "query.system_image.context.preview", view["request"]))
    assert observed["result"]["context_pack"]["request"]["retrieval_bindings"] == v["context_request"]["retrieval_bindings"]
    # Simulate a lost completion receipt while the canonical worker is recovering.
    with session_scope() as session:
        session.get(ToolInvocationRecord, done["id"]).status = "running"
    with actor_scope(UserProfile.model_validate(v["owner"])):
        pack = app.state.container.context_packs
        metadata, ref = pack.repository.get(v["project_id"], before["metadata"]["context_id"])
        payload = pack.artifacts.read(v["project_id"], ref, metadata["artifact_hash"])
        receipts = payload["provenance"]["retrieval_runs"]
        assert len(receipts) == 2 * len(v["context_request"]["retrieval_bindings"])
        assert all(item["trace_pin"]["retrieval_id"] == v["trace_id"] for item in receipts)
        assert pack.compile(ContextCompileInput.model_validate(payload["request"]), invocation_id=done["id"], recorded_at="retry") == metadata
    assert len(v["index_calls"]) == calls and count(v, ContextPackRecord) == 1


def test_model_changes_keep_verified_history_but_invalidate_current_use(recalled):
    v = recalled
    view = response(v).json()
    done = completed(archive(v, view)[0])
    before, url = read(v, done)
    change_model(v)
    after = v["client"].get(url, headers=v["headers"])
    assert after.status_code == 200, after.text
    assert after.json()["context"] == before["context"]
    assert after.json()["current_use"] == {"stale": True, "generation_authorized": False, "reason": "retrieval_model_configuration_changed"}
    assert response(v).status_code == 409
    calls = len(v["index_calls"])
    again, _ = archive(v, view)
    assert again.json()["status"] == "failed" and again.json()["result"]["followup_reason"] == "context_inputs_changed"
    assert len(v["index_calls"]) == calls and count(v, ContextPackRecord) == 1


def test_model_changed_between_artifact_and_commit_cannot_archive(recalled, monkeypatch):
    v = recalled
    view = response(v).json()
    artifacts = app.state.container.context_packs.artifacts
    original = artifacts.put
    def race(*args):
        result = original(*args)
        change_model(v)
        return result
    monkeypatch.setattr(artifacts, "put", race)
    result, _ = archive(v, view)
    assert result.json()["status"] == "failed" and result.json()["result"]["followup_reason"] == "context_inputs_changed"
    assert count(v, ContextPackRecord) == 0


def test_explicit_bindings_validate_complete_ac_scope_and_original_actor(recalled):
    v = recalled
    assert response(v, retrieval_bindings={}).status_code == 502
    assert response(v, retrieval_bindings={**v["context_request"]["retrieval_bindings"], "unknown": v["trace_id"]}).status_code == 502
    grant_member(v)
    params = {**v["context_request"], "retrieval_bindings": json.dumps(v["context_request"]["retrieval_bindings"])}
    assert preview_response(v, params, v["member_headers"]).status_code == 403  # Trace query is private to its actor/admin.
    params["retrieval_bindings"] = '{"ac":"first","ac":"second"}'
    assert preview_response(v, params).status_code == 422
    for invalid in (None, [], {"ac": False}):
        assert response(v, retrieval_bindings=invalid).status_code == 422
    old_request = dict(v["context_request"])
    v["target"] = {**v["target"], "expected_head_id": v["index_head"]["publication_id"]}
    head = publish(v)
    assert response(v).status_code == 409
    assert response(v, publication_id=head["publication_id"]).status_code == 502  # Same image is not the same publication.
    assert v["context_request"] == old_request


def test_history_rejects_corrupt_trace_even_when_current_model_changed(recalled, monkeypatch):
    v = recalled
    done = completed(archive(v, response(v).json())[0])
    _, url = read(v, done)
    change_model(v)
    artifacts = v["index_service"].artifacts
    original = artifacts.read
    def corrupt(*args):
        result = original(*args)
        if result.get("schema") == "nasus.frozen-retrieval.v1":
            result["candidates"][0]["document"]["revision_id"] = "injected-untrusted"
        return result
    monkeypatch.setattr(artifacts, "read", corrupt)
    result = v["client"].get(url, headers=v["headers"])
    assert result.status_code == 502 and "injected-untrusted" not in result.text


def test_new_human_rejection_filters_indexed_recall_without_rewriting_history(recalled, semantic):
    v = recalled
    view = response(v).json()
    assert any(fact["relation"] == "asserts" for fact in view["context"]["facts"])
    done = completed(archive(v, view)[0])
    before, url = read(v, done)
    calls = len(v["index_calls"])
    _, decision, _ = evaluate(semantic)
    completed(submit(semantic, decision))
    filtered = response(v)
    assert filtered.status_code == 200, filtered.text
    assert not any(fact["relation"] == "asserts" for fact in filtered.json()["context"]["facts"])
    assert filtered.json()["input_digest"] != view["input_digest"]
    after = v["client"].get(url, headers=v["headers"])
    assert after.status_code == 200, after.text
    assert after.json()["context"] == before["context"] and after.json()["current_use"]["stale"]
    rejected, _ = archive(v, view)
    assert rejected.json()["status"] == "failed" and count(v, ContextPackRecord) == 1
    assert len(v["index_calls"]) == calls


def test_source_revocation_hides_indexed_history_from_original_trace_actor(recalled):
    v = recalled
    grant_member(v)
    with actor_scope(UserProfile.model_validate(v["member"])):
        own_trace = search(v).retrieval_run_refs[0].split(":", 1)[1]
    bindings = {target: own_trace for target in v["context_request"]["retrieval_bindings"]}
    view = response(v, retrieval_bindings=bindings).json()
    done = completed(archive(v, view)[0])
    _, url = read(v, done)
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 200
    repo = SourceAccessRepository()
    snapshot = repo.load_snapshot(v["project_id"])
    repo.set_policy(v["project_id"], snapshot.bindings[0].binding_id, SourceAccessRule("restricted"),
        expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="indexed-context-revoke")
    hidden = v["client"].get(url, headers=v["member_headers"])
    assert hidden.status_code == 403 and "Empty input" not in hidden.text and "HTTP 400" not in hidden.text
