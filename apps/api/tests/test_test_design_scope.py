from copy import deepcopy

import pytest
from pydantic import ValidationError

from apps.api.app.application.quality_loop.test_design_scope_inputs import TestDesignContract
from apps.api.app.domain.quality_loop.test_design_scope import validate_scope_contract


ORACLE = dict(preconditions="Authenticated user", action="Submit empty search", observation="HTTP status", expected_result="HTTP 400")


def scope_contract(constraints):
    return {"authority_basis": "user_confirmed_test_design_scope",
        "risks": {"applicability": "applicable", "rationale": "Explicit fixture review of invalid input boundary", "items": [
            {"obligation_id": "invalid-input", "constraint_ids": [constraints[0]["object_id"]],
             "evidence_ids": constraints[0]["evidence_ids"], "boundary": "Empty input must not be executed", "oracle": ORACLE}]},
        **{key: {"applicability": "not_applicable", "rationale": "Explicit fixture scope assessment, not inferred from source code", "items": []}
           for key in ("permissions", "transitions", "invariants")},
        "examples": [{"constraint_id": item["object_id"], "positive": item["oracle"], "negative": ORACLE,
                      "negative_not_applicable_reason": None, "negative_gap_id": None} for item in constraints],
        "reused_case_ids": [], "reuse_assessment": "No approved reusable case selected in this fixture",
        "conflicts": [], "conflict_assessment": "Fixture reviewer checked all fixed constraints for contradictions", "gaps": []}


def fixed_context():
    return {"publication_pin": {"publication_id": "p"}, "facts": [], "required_constraints": [
        {"object_id": "ac", "kind": "acceptance_criterion", "authority": {"status": "approved"}, "oracle": ORACLE, "evidence_ids": ["e1"]},
        {"object_id": "rule", "kind": "business_rule", "authority": {"status": "approved"}, "oracle": ORACLE, "evidence_ids": ["e2"]}]}


def test_scope_keeps_complete_denominator_and_does_not_grant_generation():
    context = fixed_context()
    contract = TestDesignContract.model_validate(scope_contract(context["required_constraints"])).model_dump(mode="json")
    result = validate_scope_contract(contract, context)
    assert result["constraint_ids"] == ["ac", "rule"] and result["scope_complete"]
    assert result["obligation_ids"] == ["invalid-input"] and result["generation_authorized"] is False
    contract["gaps"] = [{"id": "g1", "constraint_ids": ["rule"], "description": "Unresolved permission boundary"}]
    contract["conflicts"] = [{"id": "c1", "constraint_ids": ["ac"], "description": "Alternative response", "resolution": None}]
    blocked = validate_scope_contract(contract, context)
    assert not blocked["scope_complete"] and len(blocked["blockers"]) == 2


@pytest.mark.parametrize("kind", ["missing_rule", "duplicate_example", "foreign_constraint", "foreign_evidence", "empty_dimension", "foreign_case", "duplicate_obligation", "unapproved", "unpublished"])
def test_scope_rejects_incomplete_or_unpinned_obligations(kind):
    context = fixed_context()
    contract = scope_contract(context["required_constraints"])
    if kind == "missing_rule":
        contract["examples"].pop()
    elif kind == "duplicate_example":
        contract["examples"][1] = deepcopy(contract["examples"][0])
    elif kind == "foreign_constraint":
        contract["risks"]["items"][0]["constraint_ids"] = ["foreign"]
    elif kind == "foreign_evidence":
        contract["risks"]["items"][0]["evidence_ids"] = ["foreign"]
    elif kind == "empty_dimension":
        contract["risks"]["items"] = []
    elif kind == "foreign_case":
        contract["reused_case_ids"] = ["outside-context"]
    elif kind == "duplicate_obligation":
        contract["risks"]["items"] *= 2
    elif kind == "unapproved":
        context["required_constraints"][0]["authority"]["status"] = "withdrawn"
    else:
        context["publication_pin"] = None
    with pytest.raises(ValueError):
        validate_scope_contract(TestDesignContract.model_validate(contract).model_dump(mode="json"), context)


@pytest.mark.parametrize("change", [{"authority_basis": "model_inferred"}, {"conflict_assessment": " "}, {"unexpected": True}])
def test_scope_input_requires_explicit_bounded_review(change):
    with pytest.raises(ValidationError):
        TestDesignContract.model_validate({**scope_contract(fixed_context()["required_constraints"]), **change})


def test_negative_oracle_cannot_be_silently_omitted():
    contract = scope_contract(fixed_context()["required_constraints"])
    contract["examples"][0]["negative"] = None
    with pytest.raises(ValidationError):
        TestDesignContract.model_validate(contract)
    contract["examples"][0]["negative_not_applicable_reason"] = "Explicitly no negative partition for this fixture invariant"
    assert TestDesignContract.model_validate(contract).examples[0].negative is None


def test_negative_gap_is_explicit_and_must_cover_the_same_constraint():
    context = fixed_context()
    contract = scope_contract(context["required_constraints"])
    contract["examples"][0].update(negative=None, negative_gap_id="gap")
    parsed = TestDesignContract.model_validate(contract).model_dump(mode="json")
    with pytest.raises(ValueError, match="same constraint"):
        validate_scope_contract(parsed, context)
    contract["gaps"] = [{"id": "gap", "constraint_ids": ["ac"], "description": "Negative behavior awaiting owner decision"}]
    result = validate_scope_contract(TestDesignContract.model_validate(contract).model_dump(mode="json"), context)
    assert result["blockers"] == ["explicit_gap:gap"] and not result["scope_complete"]


@pytest.mark.parametrize("category,fields", [
    ("permissions", {"actor": "guest", "operation": "POST", "resource": "/search", "expected": "denied"}),
    ("transitions", {"from_state": "idle", "event": "empty input", "to_state": "rejected"}),
    ("invariants", {"invariant": "Invalid input never changes stored business data"}),
])
def test_typed_behavior_dimensions_preserve_explicit_oracles(category, fields):
    context = fixed_context()
    contract = scope_contract(context["required_constraints"])
    obligation = {"obligation_id": category, "constraint_ids": ["ac", "rule"], "evidence_ids": ["e1", "e2"], "oracle": ORACLE, **fields}
    contract[category] = {"applicability": "applicable", "rationale": "Independent fixture review", "items": [obligation]}
    parsed = TestDesignContract.model_validate(contract).model_dump(mode="json")
    assert validate_scope_contract(parsed, context)["scope_complete"]
    assert parsed[category]["items"][0] == obligation
    obligation["oracle"] = {**ORACLE, "observation": " "}
    with pytest.raises(ValidationError):
        TestDesignContract.model_validate(contract)
