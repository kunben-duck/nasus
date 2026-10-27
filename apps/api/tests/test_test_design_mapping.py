from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from apps.api.app.application.quality_loop.test_design_mapping_inputs import MappingReviewInput
from apps.api.app.application.quality_loop.test_design_output import validate_test_design_output
from apps.api.app.domain.quality_loop.test_design_mapping import assess_mappings, TestDesignMappingInvalid
from apps.api.app.domain.quality_loop.test_design_generation import compile_generation_input
from apps.api.tests.test_test_design_generation import generation_inputs, case_output


def reviews(proposal, decision="accept"):
    return [{"case_id": case["case_id"], "row_id": item["row_id"], "step_index": item["step_index"],
             "oracle_digest": item["oracle_digest"], "decision": decision,
             "reason": "Independently inspected the frozen action and observable oracle"}
            for case in proposal["cases"] for item in case["assertions"]]


def proposal():
    prepared = compile_generation_input(*generation_inputs())
    return validate_test_design_output(prepared, json.dumps(case_output(prepared)))


def test_review_preserves_draft_and_denominators_and_never_claims_execution():
    draft = proposal()
    original = deepcopy(draft)
    assessment = assess_mappings(draft, reviews(draft))
    assert draft == original and draft["coverage"]["assertion_mapped_count"] == 0
    coverage = assessment["coverage"]
    assert assessment["mapping_complete"] and len(assessment["accepted_case_ids"]) == len(draft["cases"])
    assert coverage["assertion_mapped_count"] == coverage["obligation_denominator"]
    assert coverage["constraint_denominator"] == draft["coverage"]["constraint_denominator"]
    assert coverage["unknown_count"] == coverage["obligation_denominator"]
    assert coverage["automated_count"] == coverage["executed_on_target_count"] == coverage["passed_count"] == 0
    assert not assessment["execution_authorized"] and all(row["unknown"] and not row["passed"] for row in coverage["rows"])


def test_partial_decisions_do_not_make_rejected_cases_or_obligations_approved():
    draft = proposal()
    decisions = reviews(draft)
    decisions[0]["decision"], decisions[1]["decision"] = "reject", "defer"
    assessment = assess_mappings(draft, decisions)
    assert not assessment["mapping_complete"]
    assert assessment["rejected_assertion_count"] == assessment["deferred_assertion_count"] == 1
    assert decisions[0]["case_id"] not in assessment["accepted_case_ids"]
    assert decisions[1]["case_id"] not in assessment["accepted_case_ids"]
    assert assessment["coverage"]["assertion_mapped_count"] == len(draft["coverage"]["rows"]) - 2


def test_multiple_cases_cannot_inflate_obligation_denominator_or_pass_count():
    prepared = compile_generation_input(*generation_inputs())
    output = case_output(prepared)
    duplicate = deepcopy(output["cases"][0])
    duplicate["case_id"] = "different-case-same-obligation"
    output["cases"].append(duplicate)
    draft = validate_test_design_output(prepared, json.dumps(output))
    assessment = assess_mappings(draft, reviews(draft))
    assert assessment["accepted_assertion_count"] > assessment["coverage"]["assertion_mapped_count"]
    assert assessment["coverage"]["obligation_denominator"] == len(prepared["obligations"])
    assert assessment["coverage"]["passed_count"] == 0


@pytest.mark.parametrize("change", ["case", "row", "step", "bool_step", "oracle", "omit", "duplicate", "decision", "empty_reason"])
def test_review_cannot_rewrite_or_omit_proposed_assertion_pairs(change):
    draft = proposal()
    values = reviews(draft)
    if change == "omit":
        values.pop()
    elif change == "duplicate":
        values.append(deepcopy(values[0]))
    else:
        key, value = {"case": ("case_id", "other"), "row": ("row_id", "other"), "step": ("step_index", 1),
            "bool_step": ("step_index", False), "oracle": ("oracle_digest", "sha256:" + "0" * 64),
            "decision": ("decision", "pass"), "empty_reason": ("reason", " ")}[change]
        values[0][key] = value
    with pytest.raises(TestDesignMappingInvalid):
        assess_mappings(draft, values)


def test_explicit_generation_gaps_remain_blockers_even_after_review():
    prepared = compile_generation_input(*generation_inputs())
    output = {"input_digest": prepared["input_digest"], "cases": [], "gaps": [{"gap_id": "missing-fixture",
        "row_ids": [row["row_id"] for row in prepared["obligations"]], "description": "No fixture exists"}]}
    draft = validate_test_design_output(prepared, json.dumps(output))
    assessment = assess_mappings(draft, [])
    assert not assessment["mapping_complete"] and assessment["accepted_case_ids"] == []
    assert assessment["coverage"]["gap_obligation_count"] == len(prepared["obligations"])


def test_dto_requires_explicit_withdrawal_and_no_authority_or_oracle_injection():
    request = dict(project_id="p", generation_id="g", generation_artifact_hash="sha256:" + "1" * 64,
        expected_previous_revision_id=None, decision="review", mappings=reviews(proposal()), reason="Independent fixture")
    assert MappingReviewInput.model_validate(request).decision == "review"
    for changes in ({"mappings": None}, {"decision": "withdraw"}, {"execution_authorized": True}, {"authority_actor": "forged"}):
        with pytest.raises(ValidationError):
            MappingReviewInput.model_validate({**request, **changes})
    for value in (True, "0", 1.0):
        changed = deepcopy(request)
        changed["mappings"][0]["step_index"] = value
        with pytest.raises(ValidationError):
            MappingReviewInput.model_validate(changed)
    assert MappingReviewInput.model_validate({**request, "decision": "withdraw", "mappings": None}).mappings is None
