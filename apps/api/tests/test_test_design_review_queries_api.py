from uuid import uuid4

import pytest

from apps.api.app.main import app
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.quality_loop.test_design_results import TestDesignResultIntegrityError
from apps.api.app.application.quality_loop.test_design_review_queries import REVIEW_DRAFT_QUERY_TOOL
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.system_image.source_access import SourceAccessDenied, SourceAccessRule
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.db_models import LLMCallRecord
from apps.api.tests.test_test_design_results_api import generation_result, commit
from apps.api.tests.test_test_design_scope_api import design_scope, submit
from apps.api.tests.test_image_publications_api import publication
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_semantic_evaluations_api import completed, count, invoke
from apps.api.tests.test_source_access_api import grant_member
from apps.api.tests.test_design_result_fixture import seed_generation_execution


def listing(v, *, headers=None, **params):
    return v["client"].get(f"/v1/projects/{v['project_id']}/quality/test-design-review-drafts",
        headers=headers or v["headers"], params=params)


def reviewer(v):
    grant_member(v)
    url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(url, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    return url


def second_result(v):
    with actor_scope(UserProfile.model_validate(v["owner"])):
        execution = seed_generation_execution(v["result_service"], v["execution"]["request"].selection(), v["owner"]["id"],
            conversation_id=v["conversation"].json()["id"], config=v["execution"]["config"])
        return v["result_service"].commit(**{key: execution[key] for key in ("request", "invocation_id", "call_id", "content")})


def test_review_discovery_is_project_wide_paged_private_and_model_free(generation_result, monkeypatch):
    v = generation_result
    assert listing(v).json()["items"] == []
    first = commit(v)
    second = second_result(v)
    calls = count(v, LLMCallRecord)
    def no_model(*args, **kwargs):
        raise AssertionError("discovery must not resolve a live model or generate output")
    monkeypatch.setattr(v["result_service"].profiles, "resolve", no_model)
    response = listing(v, limit=1)
    assert response.status_code == 200, response.text
    page = response.json()
    assert response.headers["cache-control"] == "private, no-store"
    assert page["request"] == dict(project_id=v["project_id"], after_id="", limit=1)
    expected = sorted([first, second], key=lambda item: item["generation_id"])
    assert page["items"][0]["metadata"] == expected[0]
    assert page["next_after_id"] == expected[0]["generation_id"]
    tail = listing(v, after_id=page["next_after_id"], limit=1).json()
    assert tail["items"][0]["metadata"] == expected[1] and tail["next_after_id"] is None
    assert tail["can_review"] and not tail["generation_authorized"] and not tail["execution_authorized"]
    assert count(v, LLMCallRecord) == calls
    for secret in ("raw_output", "artifact_ref", "synthetic-result-fixture-key", "HTTP 400", "expected_result"):
        assert secret not in response.text
    assert listing(v, after_id="foreign").status_code == 404
    assert listing(v, limit=6).status_code == 422


def test_qa_can_discover_historical_drafts_without_admin_egress_permission(generation_result):
    v = generation_result
    metadata = commit(v)
    grant_member(v)
    assert listing(v, headers=v["member_headers"]).status_code == 403
    reviewer(v)
    response = listing(v, headers=v["member_headers"])
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["metadata"] == metadata
    completed(submit(v, {**v["scope_request"], "expected_previous_revision_id": v["execution"]["request"].scope_revision_id,
        "decision": "withdraw", "contract": None}))
    assert listing(v, headers=v["member_headers"]).json()["items"][0]["metadata"] == metadata
    repo = SourceAccessRepository()
    snapshot = repo.load_snapshot(v["project_id"])
    repo.set_policy(v["project_id"], v["evidence"]["binding_id"], SourceAccessRule("restricted"),
        expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id=uuid4().hex)
    denied = listing(v, headers=v["member_headers"])
    assert denied.status_code == 403 and metadata["generation_id"] not in denied.text
    assert listing(v).status_code == 200


def test_unreadable_lookahead_fails_the_whole_page_without_ids_or_cursor(generation_result, monkeypatch):
    v = generation_result
    first, second = commit(v), second_result(v)
    ordered = sorted([first, second], key=lambda item: item["generation_id"])
    original = v["result_service"].artifacts.read
    def corrupt(project, ref, digest):
        value = original(project, ref, digest)
        if digest == ordered[1]["artifact_hash"]:
            value["generation_id"] = "tampered"
        return value
    monkeypatch.setattr(v["result_service"].artifacts, "read", corrupt)
    response = listing(v, limit=1)
    assert response.status_code == 502, response.text
    assert all(item["generation_id"] not in response.text for item in ordered)
    assert "next_after_id" not in response.text


def test_membership_demotion_during_discovery_discards_the_entire_page(generation_result, monkeypatch):
    v = generation_result
    metadata = commit(v)
    url = reviewer(v)
    original = v["result_service"].read
    def demote(project, generation):
        value = original(project, generation)
        assert v["client"].put(url, headers=v["headers"], json={"role": "viewer"}).status_code == 200
        return value
    monkeypatch.setattr(v["result_service"], "read", demote)
    response = listing(v, headers=v["member_headers"])
    assert response.status_code == 409, response.text
    assert metadata["generation_id"] not in response.text and "items" not in response.text


def member_conversation(v):
    response = v["client"].post("/v1/conversations", headers=v["member_headers"],
        json={"space_type": "project", "space_id": v["project_id"]})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def member_query(v, conversation_id, *, key=None):
    return v["client"].post("/v1/tool-invocations", headers=v["member_headers"], json={
        "tool_id": REVIEW_DRAFT_QUERY_TOOL, "conversation_id": conversation_id,
        "input": {"project_id": v["project_id"]}, "idempotency_key": key})


def test_canonical_query_has_typed_persisted_receipt_without_model_or_generation_access(generation_result, monkeypatch):
    v = generation_result
    metadata = commit(v)
    grant_member(v)
    conversation = member_conversation(v)
    denied = member_query(v, conversation)
    assert denied.status_code == 200 and denied.json()["status"] == "failed", denied.text
    assert denied.json()["result"]["followup_reason"] == "authorization_denied"
    reviewer(v)
    calls = count(v, LLMCallRecord)
    def no_model(*args, **kwargs):
        raise AssertionError("a reviewer query cannot resolve or call a model")
    monkeypatch.setattr(v["result_service"].profiles, "resolve", no_model)
    key = uuid4().hex
    command = completed(member_query(v, conversation, key=key))
    assert completed(member_query(v, conversation, key=key))["id"] == command["id"]
    receipt = command["result"]["test_design_review_drafts"]
    assert receipt["generation_ids"] == [metadata["generation_id"]]
    assert receipt["page_digest"] == acceptance_digest(listing(v, headers=v["member_headers"]).json())
    assert receipt["observation"] == "review_draft_page_requires_revalidation"
    assert not receipt["generation_authorized"] and not receipt["execution_authorized"]
    assert command["result"]["object_refs"] == [] and command["result"]["evidence_refs"] == []
    with actor_scope(UserProfile.model_validate(v["member"])):
        assert app.state.container.tool_evidence.describe(command["id"], v["project_id"]) == receipt
    assert count(v, LLMCallRecord) == calls
    for secret in ("raw_output", "artifact_ref", "HTTP 400", "synthetic-result-fixture-key", "expected_result"):
        assert secret not in str(receipt)


def test_saved_canonical_receipt_is_invalidated_by_a_new_committed_draft(generation_result):
    v = generation_result
    metadata = commit(v)
    request = {"project_id": v["project_id"]}
    command = completed(invoke(v, REVIEW_DRAFT_QUERY_TOOL, request))
    with actor_scope(UserProfile.model_validate(v["owner"])):
        original = app.state.container.tool_evidence.describe(command["id"], v["project_id"])
    assert original["generation_ids"] == [metadata["generation_id"]]
    second_result(v)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(TestDesignResultIntegrityError, match="observation changed"):
            app.state.container.tool_evidence.describe(command["id"], v["project_id"])
    fresh = completed(invoke(v, REVIEW_DRAFT_QUERY_TOOL, request))["result"]["test_design_review_drafts"]
    assert len(fresh["generation_ids"]) == 2 and fresh["page_digest"] != original["page_digest"]


@pytest.mark.parametrize("revocation", ["source", "role"])
def test_canonical_observations_recheck_current_source_and_reviewer_access(generation_result, revocation):
    v = generation_result
    metadata = commit(v)
    url = reviewer(v)
    conversation = member_conversation(v)
    command = completed(member_query(v, conversation))
    if revocation == "role":
        assert v["client"].put(url, headers=v["headers"], json={"role": "viewer"}).status_code == 200
    else:
        repository = SourceAccessRepository()
        snapshot = repository.load_snapshot(v["project_id"])
        repository.set_policy(v["project_id"], v["evidence"]["binding_id"], SourceAccessRule("restricted"),
            expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id=uuid4().hex)
    with actor_scope(UserProfile.model_validate(v["member"])):
        with pytest.raises((PermissionError, SourceAccessDenied)):
            app.state.container.tool_evidence.describe(command["id"], v["project_id"])
    failed = member_query(v, conversation)
    assert failed.status_code == 200 and failed.json()["status"] == "failed", failed.text
    assert failed.json()["result"]["test_design_review_drafts"] is None
    assert metadata["generation_id"] not in failed.text
