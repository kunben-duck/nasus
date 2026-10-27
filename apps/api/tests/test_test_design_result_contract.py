from copy import deepcopy

import pytest

from apps.api.app.application.quality_loop.test_design_results import GenerationResultRequest, response_digest
from apps.api.app.domain.quality_loop.test_design_generation import TestDesignGenerationInvalid, compile_generation_input, replay_generation_input
from apps.api.tests.test_test_design_generation import generation_inputs


def test_historical_replay_preserves_pins_without_granting_current_generation():
    context, scope = generation_inputs()
    prepared = compile_generation_input(context, scope)
    context["current_use"]["stale"] = True
    scope["current_use"].update(scope_current=False, scope_complete=False)
    original = deepcopy((context, scope))
    assert replay_generation_input(context, scope) == prepared
    assert not prepared["generation_authorized"]
    assert (context, scope) == original
    with pytest.raises(TestDesignGenerationInvalid):
        compile_generation_input(context, scope)


@pytest.mark.parametrize("change", ["withdrawn", "pin", "oracle", "gap"])
def test_historical_replay_does_not_relax_immutable_contract_validation(change):
    context, scope = generation_inputs()
    if change == "withdrawn":
        scope["revision"]["status"] = "withdrawn"
    elif change == "pin":
        scope["request"]["context_id"] = "another-context"
    elif change == "oracle":
        context["context"]["required_constraints"][0]["oracle"] = None
    else:
        scope["request"]["contract"]["gaps"] = [{"id": "missing", "constraint_ids": ["ac"], "description": "Unresolved boundary"}]
    with pytest.raises((TestDesignGenerationInvalid, ValueError)):
        replay_generation_input(context, scope)


def test_result_request_forbids_user_provided_coverage_or_execution_claims():
    context, scope = generation_inputs()
    prepared = compile_generation_input(context, scope)
    value = {"project_id": "p", "scope_revision_id": "scope-revision", "scope_artifact_hash": scope["revision"]["artifact_hash"],
             "input_digest": prepared["input_digest"], "model_config_id": "model", "model_config_digest": response_digest("model")}
    request = GenerationResultRequest.model_validate(value)
    assert request.selection().scope_revision_id == "scope-revision"
    for key in ("content", "passed_count", "coverage", "confirmed_by_user", "execution_authorized"):
        with pytest.raises(ValueError):
            GenerationResultRequest.model_validate({**value, key: True})
    assert response_digest("draft") != response_digest("draft ")
