"""Real PG source/image/context joins and canonical query replay, no target execution."""
import json
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
import pytest

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.context_pack_models import ContextPackRecord
from apps.api.app.infrastructure.persistence.context_pack_repository import ContextPackRepository
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, SSEEventOutboxRecord, LLMCallRecord
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_context_change_impact_api import (
    impact, mapping, generation_result, design_scope, publication, documents, evidence_api,
)
from apps.api.tests.test_semantic_evaluations_api import completed, invoke, count
from apps.api.tests.test_published_context_packs import preview_response, request_for
from apps.api.tests.test_context_packs_api import archive, read as read_context
from apps.api.tests.test_source_access_api import grant_member
from apps.api.tests.test_reference_links_api import proposal
from apps.api.tests.test_link_decisions_api import submit as review_reference
from apps.api.tests.test_image_membership_api import freeze, child


TOOL = "query.system_image.sources.context_roots"


def request(v, **changes):
    return {key: value for key, value in {**v["impact_request"], **changes}.items()
            if key not in {"context_id", "context_artifact_hash"}}


def read(v, headers=None, **changes):
    return v["client"].get(v["image_url"] + "/source-context-roots", headers=headers or v["headers"],
        params={key: value for key, value in request(v, **changes).items() if key != "project_id"})


def query(v, headers=None, **changes):
    return invoke(v, TOOL, request(v, **changes), headers=headers, key=uuid4().hex)


def expand(v, command, headers=None):
    return v["client"].get(f"/v1/tool-invocations/{command['id']}/image-query", headers=headers or v["headers"])


def clone_context(v):
    view = preview_response(v, request_for(v, v["context_head"])).json()
    return read_context(v, completed(archive(v, view)[0]))[0]


def archive_child_context(v):
    saved, url, _ = proposal(v, v["publication_image"])
    edge = saved["items"][0]
    endpoint = f"{url}/assertions/{edge['assertion_id']}/decisions"
    current = v["client"].get(endpoint, headers=v["headers"])
    assert current.status_code == 200, current.text
    current = current.json()
    review = {key: current[key] for key in
        ("project_id", "proposal_id", "assertion_id", "proposal_digest", "evidence_digest", "policy_revision")}
    completed(review_reference(v, {**review, "expected_previous_decision_id": current["head_decision_id"],
        "decision": "defer", "reason": "Protocol fixture; preserve pending business authority"}))
    current = v["client"].get(endpoint, headers=v["headers"]).json()
    _, page = child(v, freeze(v, {"project_id": v["project_id"], "parent_revision_id": saved["image_revision_id"],
        "parent_artifact_hash": saved["image_artifact_hash"], "proposal_id": saved["proposal_id"],
        "proposal_digest": saved["digest"], "decision_ids": [current["head_decision_id"]]}))
    image = page["revision"]
    response = v["client"].get(v["image_url"] + "/context-packs/preview", headers=v["headers"], params={
        "image_revision_id": image["image_revision_id"], "image_artifact_hash": image["artifact_hash"],
        "policy_revision": "nasus.test-design-context.v1"})
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["context"]["readiness"]["status"] == "blocked"
    return read_context(v, completed(archive(v, view)[0]))[0]


def test_reverse_lookup_includes_other_frozen_images_and_contexts_without_selected_hits(impact):
    v = impact
    old = read(v)
    assert old.status_code == 200, old.text
    old_command = completed(query(v))
    added = archive_child_context(v)
    assert added["metadata"]["image_revision_id"] != v["context"]["metadata"]["image_revision_id"]
    # A blocked child still depends on the source/query scope. It must not
    # disappear from impact discovery merely because it cannot generate tests.
    assert not added["current_use"]["generation_authorized"]
    response = read(v)
    assert response.status_code == 200, response.text
    roots = response.json()["inventory"]
    assert roots["total"] == 2 and roots["next_after_id"] is None
    assert {item["context_id"] for item in roots["items"]} == {
        added["metadata"]["context_id"], v["context"]["metadata"]["context_id"]}
    assert len({item["image_revision_id"] for item in roots["items"]}) == 2
    assert expand(v, old_command).json() == old.json()
    command = completed(query(v))
    assert expand(v, command).json() == response.json()


def test_actual_project_reverse_lookup_and_canonical_page_preserve_immutable_history(impact):
    v = impact
    model_counts = [count(v, model) for model in (ContextPackRecord, LLMCallRecord)]
    response = read(v)
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store", response.text
    body = response.json()
    inventory = body["inventory"]
    assert inventory["total"] == 1 and inventory["items"][0]["context_id"] == v["impact_request"]["context_id"]
    assert body["page_evidence_verified"] and body["source_change_requires_reinvestigation"]
    assert not body["downstream_dependency_graphs_verified"] and not body["impact_complete"]
    assert not body["invalidation_applied"] and not body["execution_authorized"]
    command = completed(query(v))
    receipt = command["result"]["image_query"]
    assert receipt["operation"] == "source_context_roots" and receipt["total"] == 1
    assert expand(v, command).json() == body
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(command["id"], v["project_id"]) == receipt
    assert [count(v, model) for model in (ContextPackRecord, LLMCallRecord)] == model_counts
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, command["id"])
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == command["id"])).all()
        durable = json.dumps(row.result_payload) + json.dumps([event.event_payload for event in events])
    for forbidden in ("Orders", "changed dependency fixture", "HTTP 400", "oracle", "source_fields", "artifact_ref", "s3://"):
        assert forbidden not in durable + response.text
    clone = clone_context(v)
    assert clone["metadata"]["context_id"] != receipt["roots"][0]["context_id"]
    assert expand(v, command).json() == body
    first = read(v, limit=1).json()["inventory"]
    assert first["total"] == 2 and first["next_after_id"] == first["items"][0]["context_id"]
    second = read(v, limit=1, after_id=first["next_after_id"]).json()["inventory"]
    assert second["total"] == 2 and second["next_after_id"] is None
    assert first["items"][0]["context_id"] != second["items"][0]["context_id"]
    empty = read(v, after_id=second["items"][0]["context_id"]).json()["inventory"]
    assert empty == {"items": [], "total": 2, "next_after_id": None}
    new_source = read(v, before_revision_id=v["impact_request"]["after_revision_id"])
    assert new_source.status_code == 200 and new_source.json()["inventory"]["total"] == 0
    assert not new_source.json()["source_change_requires_reinvestigation"]
    assert read(v, limit=51).status_code == 422
    failed = query(v, invalidation_applied=True)
    assert failed.json()["status"] == "failed" and failed.json()["result"]["image_query"] is None


def test_reverse_discovery_and_receipt_replay_recheck_all_source_access(impact):
    v = impact
    assert v["client"].get(v["image_url"] + "/source-context-roots", params=request(v)).status_code == 401
    grant_member(v)
    command = completed(query(v, headers=v["member_headers"]))
    assert expand(v, command, headers=v["member_headers"]).status_code == 200
    repository = SourceAccessRepository()
    scope = repository.load_snapshot(v["project_id"])
    repository.set_policy(v["project_id"], v["impact_binding"], SourceAccessRule("restricted"),
        expected_epoch=scope.acl_epoch, changed_by=v["owner"]["id"], invocation_id="fixture-" + uuid4().hex)
    denied = read(v, headers=v["member_headers"])
    assert denied.status_code in (403, 404) and "context_artifact_hash" not in denied.text
    denied = expand(v, command, headers=v["member_headers"])
    assert denied.status_code in (403, 404, 409) and "roots" not in denied.text
    assert query(v, headers=v["member_headers"]).json()["status"] == "failed"


def test_total_and_empty_pages_do_not_reveal_images_with_another_restricted_source(impact):
    v = impact
    grant_member(v)
    command = completed(query(v, headers=v["member_headers"]))
    empty_command = completed(query(v, headers=v["member_headers"], after_id="z"))
    assert empty_command["result"]["image_query"]["total"] == 1
    assert empty_command["result"]["image_query"]["roots"] == []
    repository = SourceAccessRepository()
    scope = repository.load_snapshot(v["project_id"])
    hidden = next(binding.binding_id for binding in scope.bindings if binding.binding_id != v["impact_binding"])
    repository.set_policy(v["project_id"], hidden, SourceAccessRule("restricted"),
        expected_epoch=scope.acl_epoch, changed_by=v["owner"]["id"], invocation_id="fixture-" + uuid4().hex)
    for cursor in ("", "z"):
        response = read(v, headers=v["member_headers"], after_id=cursor)
        assert response.status_code == 200, response.text
        assert response.json()["inventory"] == {"items": [], "total": 0, "next_after_id": None}
    for old in (command, empty_command):
        denied = expand(v, old, headers=v["member_headers"])
        assert denied.status_code == 409 and "total" not in denied.text and "roots" not in denied.text
    assert read(v).json()["inventory"]["total"] == 1


def test_empty_code_only_context_remains_visible_when_other_image_documents_are_restricted(impact):
    v = impact
    candidates = v["client"].get(v["image_url"] + "/revisions", headers=v["headers"])
    assert candidates.status_code == 200, candidates.text
    image = next(row for row in candidates.json()["items"]
        if row["manifest_id"] == v["image"]["source_manifest"]["manifest_id"])
    response = v["client"].get(v["image_url"] + "/context-packs/preview", headers=v["headers"], params={
        "image_revision_id": image["image_revision_id"], "image_artifact_hash": image["artifact_hash"],
        "policy_revision": "nasus.test-design-context.v1"})
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["context"]["facts"] == [] and view["context"]["required_constraints"] == []
    assert "missing_requirements" in view["context"]["readiness"]["reason_codes"]
    empty = read_context(v, completed(archive(v, view)[0]))[0]
    grant_member(v)
    assert read(v, headers=v["member_headers"]).json()["inventory"]["total"] == 2
    repository = SourceAccessRepository()
    scope = repository.load_snapshot(v["project_id"])
    hidden = next(binding.binding_id for binding in scope.bindings if binding.binding_id != v["impact_binding"])
    repository.set_policy(v["project_id"], hidden, SourceAccessRule("restricted"),
        expected_epoch=scope.acl_epoch, changed_by=v["owner"]["id"], invocation_id="fixture-" + uuid4().hex)
    response = read(v, headers=v["member_headers"])
    assert response.status_code == 200, response.text
    page = response.json()["inventory"]
    assert page["total"] == 1 and page["next_after_id"] is None
    assert page["items"][0]["context_id"] == empty["metadata"]["context_id"]
    command = completed(query(v, headers=v["member_headers"]))
    assert expand(v, command, headers=v["member_headers"]).json() == response.json()


@pytest.mark.parametrize("phase", ["inventory", "diagnostic"])
def test_actual_acl_revocation_during_inventory_hides_counts_and_private_diagnostics(impact, monkeypatch, phase):
    v = impact
    grant_member(v)
    repository = SourceAccessRepository()
    inventory = app.state.container.source_context_roots.inventory
    original = inventory.list
    def revoke(*args, **kwargs):
        result = original(*args, **kwargs)
        scope = repository.load_snapshot(v["project_id"])
        repository.set_policy(v["project_id"], v["impact_binding"], SourceAccessRule("restricted"),
            expected_epoch=scope.acl_epoch, changed_by=v["owner"]["id"], invocation_id="fixture-" + uuid4().hex)
        if phase == "diagnostic":
            raise RuntimeError("private dependency count and source details")
        return result
    monkeypatch.setattr(inventory, "list", revoke)
    response = read(v, headers=v["member_headers"])
    assert response.status_code == 409, response.text
    for forbidden in ("context_id", "total", "inventory", "private dependency count", "source details"):
        assert forbidden not in response.text


def test_corrupt_metadata_and_archive_never_return_a_partially_verified_page(impact, monkeypatch):
    v = impact
    clone_context(v)
    command = completed(query(v))
    with pytest.raises(IntegrityError, match="append-only"):
        with session_scope() as session:
            session.execute(update(ContextPackRecord).where(ContextPackRecord.context_id == v["impact_request"]["context_id"])
                .values(content_hash="sha256:" + "0" * 64))

    metadata = ContextPackRepository._metadata
    def corrupt_metadata(row):
        if row.context_id == v["impact_request"]["context_id"]:
            row = SimpleNamespace(**{key: getattr(row, key) for key in
                ("context_id", "project_id", "image_revision_id", "invocation_id", "payload")},
                content_hash="sha256:" + "0" * 64)
        return metadata(row)
    with monkeypatch.context() as patch:
        patch.setattr(ContextPackRepository, "_metadata", staticmethod(corrupt_metadata))
        response = read(v)
        assert response.status_code == 502 and "integrity" in response.text, response.text
        assert expand(v, command).status_code == 502
        assert query(v).json()["status"] == "failed"

    artifacts = app.state.container.context_packs.artifacts
    original = artifacts.read
    def corrupt_archive(*args):
        value = original(*args)
        value["context"]["required_constraints"][0]["source_fields"][0]["value"] = "injected private source"
        return value
    with monkeypatch.context() as patch:
        patch.setattr(artifacts, "read", corrupt_archive)
        response = read(v)
        assert response.status_code == 502 and "injected private source" not in response.text
        assert expand(v, command).status_code == 502
        assert query(v).json()["status"] == "failed"
    assert read(v).status_code == 200 and expand(v, command).status_code == 200
