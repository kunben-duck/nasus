"""M2 confirmations are context authority, not publication or execution consent."""
import pytest
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest

from apps.api.app.main import app
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.system_image.context_pack_inputs import ContextPreviewInput
from apps.api.app.domain.system_image.context_pack import ContextIterationChanged, ContextPackIntegrityError
from apps.api.app.domain.quality_loop.test_design_scope import validate_scope_contract
from apps.api.app.application.quality_loop.test_design_generation import GenerationSelection
from apps.api.app.domain.quality_loop.test_design_scope import TestDesignScopeChanged
from apps.api.tests.test_test_design_scope import scope_contract
from apps.api.tests.test_requirement_reviews_api import (
    review_case, iteration, publication, documents, evidence_api, assessment, evaluate, review_url, command,
)
from apps.api.tests.test_context_packs_api import read


@pytest.fixture
def confirmed_iteration(review_case, monkeypatch):
    v = review_case
    async def unblocked(payload, prepared):
        return assessment(payload), prepared[0]
    monkeypatch.setattr(app.state.container.requirement_reviews.model, "evaluate", unblocked)
    assert evaluate(v, v["revision"])["status"] == "completed"
    review = v["client"].get(review_url(v, v["revision"]), headers=v["headers"]).json()
    result = v["client"].put(f"/v1/projects/{v['project_id']}/members/{v['member']['id']}",
        headers=v["headers"], json={"role": "project_admin"})
    assert result.status_code == 200
    for item in review["approval_requests"]:
        assert command(v, "quality.acceptance_specification.review", item["input"], headers=v["member_headers"])["status"] == "completed"
    result = command(v, "quality.requirement.confirm", {
        "project_id": v["project_id"], "version_id": v["version"], "revision_id": v["revision"]["revision_id"],
        "evaluation_id": review["evaluation"]["event_id"], "review_digest": review["evaluation"]["content_hash"],
        "reason": "Independent acceptance of exact criteria"}, headers=v["member_headers"])
    assert result["status"] == "completed", result
    confirmed = v["client"].get(review_url(v, v["revision"]), headers=v["headers"]).json()["confirmation"]
    projection = confirmed["payload"]["projection"]
    v["context_request"] = ContextPreviewInput(project_id=v["project_id"],
        image_revision_id=projection["image_revision_id"], image_artifact_hash=projection["image_artifact_hash"],
        policy_revision="nasus.test-design-context.v6", max_tokens=32768, iteration={
            "version_id": v["version"], "requirement_revision_id": v["revision"]["revision_id"],
            "confirmation_id": confirmed["event_id"], "confirmation_hash": confirmed["content_hash"]})
    v["review"] = review
    current = v["client"].get(review_url(v, v["revision"]), headers=v["headers"]).json()
    assert current["test_design_context_request"] == v["context_request"].model_dump(mode="json")
    query = command(v, "query.quality.requirement_review", dict(project_id=v["project_id"],
        version_id=v["version"], revision_id=v["revision"]["revision_id"]))
    assert query["status"] == "completed", query
    assert query["result"]["requirement_review"]["test_design_context_request"] == current["test_design_context_request"]
    return v


def test_confirmed_working_image_can_compile_without_claiming_publication(confirmed_iteration, monkeypatch):
    v = confirmed_iteration
    with actor_scope(UserProfile.model_validate(v["owner"])):
        preview = app.state.container.context_packs.preview(v["context_request"])
    assert "publication_pin" not in preview["context"]
    assert preview["context"]["iteration_pin"]["version_id"] == v["version"]
    assert preview["context"]["iteration_pin"]["code_revisions"]
    assert preview["context"]["readiness"]["status"] == "partial"
    payload = {**preview["request"], "expected_input_digest": preview["input_digest"]}
    done = command(v, "system_image.context.compile", payload)
    assert done["status"] == "completed", done
    archive, url = read(v, done)
    assert snapshot_digest(archive["context"]) == snapshot_digest(preview["context"])
    assert not archive["current_use"]["stale"] and not archive["current_use"]["generation_authorized"]
    with actor_scope(UserProfile.model_validate(v["owner"])):
        identity = app.state.container.context_packs.review_identity(v["project_id"], archive["metadata"]["context_id"])
        assert identity["metadata"] == archive["metadata"]
        assert identity["context"] == {"policy_version": "nasus.test-design-context.v6"}
    with monkeypatch.context() as patch, actor_scope(UserProfile.model_validate(v["owner"])):
        def no_rebuild(*args, **kwargs):
            raise AssertionError("Identity lookup must not recompile the complete context")
        patch.setattr(app.state.container.context_packs, "_prepare", no_rebuild)
        assert app.state.container.context_packs.review_identity(v["project_id"], archive["metadata"]["context_id"]) == identity
    constraint = archive["context"]["required_constraints"][0]
    contract = {key: {"applicability": "not_applicable", "rationale": "Fixture only", "items": []}
        for key in ("risks", "permissions", "transitions", "invariants")}
    contract.update(examples=[{"constraint_id": constraint["object_id"], "positive": constraint["oracle"]}],
        conflicts=[], gaps=[], reused_case_ids=[])
    assert validate_scope_contract(contract, archive["context"])["scope_complete"]
    scope_payload = dict(project_id=v["project_id"], context_id=archive["metadata"]["context_id"],
        context_artifact_hash=archive["metadata"]["artifact_hash"], expected_previous_revision_id=None,
        decision="approve", contract=scope_contract(archive["context"]["required_constraints"]),
        reason="Independent iteration scope review", policy_revision="nasus.test-design-scope.v1")
    approved = command(v, "quality.test_design_scope.review", scope_payload, headers=v["member_headers"])
    assert approved["status"] == "completed", approved
    with actor_scope(UserProfile.model_validate(v["owner"])):
        scope = app.state.container.test_design_scopes.inspect(v["project_id"], scope_payload["context_id"])["head"]["revision"]
        selection = GenerationSelection(project_id=v["project_id"], scope_revision_id=scope["revision_id"],
            scope_artifact_hash=scope["artifact_hash"])
        prepared = app.state.container.test_design_generation.prepare(selection)
        assert prepared["context"]["iteration_pin"] == archive["context"]["iteration_pin"]
        assert prepared["generation_authorized"] is False
        receipt = app.state.container.test_design_generation.preview(selection)
        assert receipt["generation_authorized"] is receipt["execution_authorized"] is False
        assert "tested_model_binding" in receipt["remaining_gates"]
    item = v["review"]["approval_requests"][0]
    current = v["client"].get(review_url(v, v["revision"]), headers=v["headers"]).json()["approval_requests"][0]["current"]
    withdrawn = command(v, "quality.acceptance_specification.review", {**item["input"],
        "decision": "withdraw", "oracle": None, "authority_basis": None,
        "expected_previous_revision_id": current["revision_id"], "reason": "Withdraw for correction"}, headers=v["member_headers"])
    assert withdrawn["status"] == "completed", withdrawn
    assert v["client"].get(review_url(v, v["revision"]), headers=v["headers"]).json()["test_design_context_request"] is None
    with actor_scope(UserProfile.model_validate(v["owner"])), pytest.raises(ContextIterationChanged):
        app.state.container.context_packs.preview(v["context_request"])
    historical = v["client"].get(url, headers=v["headers"])
    assert historical.status_code == 200, historical.text
    assert historical.json()["context"] == archive["context"]
    assert historical.json()["current_use"]["stale"] is True
    with actor_scope(UserProfile.model_validate(v["owner"])), pytest.raises(TestDesignScopeChanged):
        app.state.container.test_design_generation.prepare(selection)
    with monkeypatch.context() as patch, actor_scope(UserProfile.model_validate(v["owner"])):
        from apps.api.app.domain.system_image.source_access import SourceAccessDenied
        def deny_source(*args):
            raise SourceAccessDenied("source access withdrawn")
        patch.setattr(app.state.container.context_packs.sources, "require_image", deny_source)
        with pytest.raises(SourceAccessDenied):
            app.state.container.context_packs.review_identity(v["project_id"], archive["metadata"]["context_id"])


@pytest.mark.parametrize("field,value", [("version_id", "another-iteration"),
    ("confirmation_id", "invented"), ("confirmation_hash", "sha256:" + "f" * 64),
    ("requirement_revision_id", "another-requirement")])
def test_iteration_context_rejects_mismatching_lineage(confirmed_iteration, field, value):
    v = confirmed_iteration
    payload = v["context_request"].model_dump(mode="json")
    payload["iteration"][field] = value
    request = ContextPreviewInput.model_validate(payload)
    with actor_scope(UserProfile.model_validate(v["owner"])), pytest.raises((KeyError, ContextPackIntegrityError)):
        app.state.container.context_packs.preview(request)


def test_legacy_context_hash_shape_and_iteration_selection_are_separate():
    from pydantic import ValidationError
    base = dict(project_id="p", image_revision_id="i", image_artifact_hash="sha256:" + "a" * 64)
    assert "iteration" not in ContextPreviewInput(**base).model_dump()
    with pytest.raises(ValidationError):
        ContextPreviewInput(**base, policy_revision="nasus.test-design-context.v6")
    with pytest.raises(ValidationError):
        ContextPreviewInput(**base, iteration={"version_id": "v", "requirement_revision_id": "r",
            "confirmation_id": "c", "confirmation_hash": "sha256:" + "b" * 64})
