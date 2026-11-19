"""Deterministic v6 integration regression, not live model acceptance evidence."""
from apps.api.app.main import app
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.quality_loop.test_design_generation import GenerationSelection
from apps.api.tests.test_iteration_context_api import (
    confirmed_iteration, review_case, iteration, publication, documents, evidence_api,
)
from apps.api.tests.test_requirement_reviews_api import command
from apps.api.tests.test_test_design_scope import scope_contract
from apps.api.tests.test_design_result_fixture import seed_generation_execution
from apps.api.tests.test_realworld_m3_live import edit_and_review_live_cases


def test_iteration_case_edit_mapping_and_independent_admission(confirmed_iteration):
    v = confirmed_iteration
    container = app.state.container
    with actor_scope(UserProfile.model_validate(v["owner"])):
        preview = container.context_packs.preview(v["context_request"])
    compiled = command(v, "system_image.context.compile", {
        **preview["request"], "expected_input_digest": preview["input_digest"]})
    assert compiled["status"] == "completed", compiled
    context_id = next(ref.split(":", 1)[1] for ref in compiled["result"]["object_refs"] if ref.startswith("context_pack:"))
    with actor_scope(UserProfile.model_validate(v["owner"])):
        context = container.context_packs.read(v["project_id"], context_id)
    scoped = command(v, "quality.test_design_scope.review", {
        "project_id": v["project_id"], "context_id": context_id,
        "context_artifact_hash": context["metadata"]["artifact_hash"], "expected_previous_revision_id": None,
        "decision": "approve", "contract": scope_contract(context["context"]["required_constraints"]),
        "reason": "Independent deterministic integration scope"}, headers=v["member_headers"])
    assert scoped["status"] == "completed", scoped
    with actor_scope(UserProfile.model_validate(v["owner"])):
        scope = container.test_design_scopes.inspect(v["project_id"], context_id)["head"]["revision"]
        selection = GenerationSelection(project_id=v["project_id"], scope_revision_id=scope["revision_id"],
            scope_artifact_hash=scope["artifact_hash"])
        execution = seed_generation_execution(container.test_design_results, selection,
            v["owner"]["id"], conversation_id=v["conversation"].json()["id"])
        metadata = container.test_design_results.commit(**{key: execution[key]
            for key in ("request", "invocation_id", "call_id", "content")})
        draft = container.test_design_results.read(v["project_id"], metadata["generation_id"])
    stages = []
    result = edit_and_review_live_cases(v, draft, lambda stage, **values: stages.append(stage))
    assert stages == ["case_revision_saved", "case_mapping_reviewed", "case_admission_saved"]
    assert result["approval"]["current_use"]["case_admission_current"]
    assert result["approval"]["current_use"]["execution_authorized"] is False
