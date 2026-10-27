"""Exercise the generation contract using explicit companion fixtures, not an LLM."""
from copy import deepcopy
import json
from uuid import uuid4

import pytest

from apps.api.app.application.quality_loop.test_design_generation import GenerationSelection, TestDesignGenerationApplicationService
from apps.api.app.application.quality_loop.test_design_scope_inputs import ScopeReviewInput
from apps.api.app.domain.quality_loop.test_design_generation import TestDesignGenerationInvalid
from apps.api.app.domain.quality_loop.test_design_scope import SCOPE_TOOL
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_test_design_generation import case_output


def verify_exweb_generation_contract(scopes, scope_view, authorization, recorded_at):
    application = TestDesignGenerationApplicationService(scopes)
    old = scope_view["revision"]
    selection = GenerationSelection(project_id=old["project_id"], scope_revision_id=old["revision_id"], scope_artifact_hash=old["artifact_hash"])
    with pytest.raises(TestDesignGenerationInvalid):
        application.prepare(selection)

    # This new review supplies a fixture oracle. The old unknown partition stays
    # in immutable history; it is neither removed nor mislabeled not-applicable.
    request = deepcopy(scope_view["request"])
    request.update(expected_previous_revision_id=old["revision_id"],
        reason="Explicit synthetic negative-oracle fixture for contract validation only; not exweb product or maintainer approval")
    for example in request["contract"]["examples"]:
        example.update(negative={"preconditions": "Isolated synthetic request fixture; no exweb process or provider is running",
            "action": "Construct a disallowed request without sending it to a target",
            "observation": "Fixture protocol rejection and absence of an execution record",
            "expected_result": "The fixture marks the disallowed input rejected and records zero target executions"},
            negative_gap_id=None, negative_not_applicable_reason=None)
    request["contract"]["gaps"] = []
    command = ScopeReviewInput.model_validate(request)
    invocation_id = str(uuid4())
    with session_scope() as session:
        session.add(ToolInvocationRecord(id=invocation_id, tool_id=SCOPE_TOOL, status="running", summary="Review synthetic generation contract fixture",
            input_payload={**command.model_dump(mode="json"), "confirmed_by_user": True,
                "confirmed_actor_id": authorization.scope(old["project_id"]).actor_id}))
    revision = scopes.review(command, invocation_id=invocation_id, recorded_at=recorded_at)
    selection = GenerationSelection(project_id=old["project_id"], scope_revision_id=revision["revision_id"], scope_artifact_hash=revision["artifact_hash"])
    prepared = application.prepare(selection)
    assert prepared["context_pin"] == scope_view["context_pin"]
    assert set(prepared["mandatory_constraint_ids"]) == set(scope_view["assessment"]["constraint_ids"])
    assert len(prepared["global_rule_ids"]) == 1
    output = case_output(prepared)
    result = application.check_output(selection, expected_input_digest=prepared["input_digest"], content=json.dumps(output))
    matrix = result["coverage"]
    assert matrix["constraint_denominator"] == matrix["planned_constraint_count"] == 2
    assert matrix["obligation_denominator"] == matrix["planned_obligation_count"] == 8
    assert matrix["passed_count"] == matrix["executed_on_target_count"] == matrix["assertion_mapped_count"] == 0
    original = scopes.read(old["project_id"], old["revision_id"])
    assert original["request"] == scope_view["request"] and original["assessment"] == scope_view["assessment"]
    invalid = deepcopy(output)
    invalid["cases"][0]["assertions"][0]["oracle"]["expected_result"] = "Silently replace the approved expectation"
    with pytest.raises(TestDesignGenerationInvalid):
        application.check_output(selection, expected_input_digest=prepared["input_digest"], content=json.dumps(invalid))
    return application, selection, {"input_digest": prepared["input_digest"], "scope_revision": revision,
        "coverage": matrix, "original_incomplete_scope_blocked": True, "original_gap_history_preserved": True,
        "changed_model_oracle_rejected": True, "all_ac_and_global_rules_preserved": True,
        "proposal_source": "explicit_protocol_fixture_not_model_generation", "persisted_case_artifact": False,
        "reviewer_basis": "explicit_fixture_not_exweb_maintainer", "generation_authorized": False, "target_executed": False}
