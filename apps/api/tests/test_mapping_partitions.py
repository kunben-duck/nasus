"""Partition integrity/capacity, not PG staging or public review approval."""
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from apps.api.app.application.quality_loop.mapping_partition_inputs import MappingPartitionPageInput
from apps.api.app.application.quality_loop.test_design_mapping_inputs import MappingReviewInput
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.mapping_partitions import (
    MAX_CASES, PART_SIZE, MappingPartitionOutOfRange, assess_partitioned_mappings,
    prepare_mapping_partitions, verify_partition_decisions,
)
from apps.api.app.domain.quality_loop.test_design_mapping import TestDesignMappingInvalid, assess_mappings
from apps.api.tests.test_test_design_mapping import proposal, reviews


def generation_pin(draft):
    return {"project_id": "partition-project", "generation_id": "partition-generation",
        "artifact_hash": acceptance_digest({"proposal": draft}),
        "context_pin": deepcopy(draft["coverage"]["context_pin"]),
        "scope_pin": deepcopy(draft["coverage"]["scope_pin"]),
        "input_digest": draft["coverage"]["input_digest"], "proposal_hash": acceptance_digest(draft)}


def large_proposal(case_count):
    draft = proposal()
    template = deepcopy(draft["cases"][0])
    for ordinal in range(case_count - len(draft["cases"])):
        case = deepcopy(template)
        case["case_id"] = "extra-case-%05d" % ordinal
        draft["cases"].append(case)
    for row in draft["coverage"]["rows"]:
        ids = sorted(case["case_id"] for case in draft["cases"]
            if any(item["row_id"] == row["row_id"] for item in case["assertions"]))
        row.update(planned_case_ids=ids, proposed_assertion_case_ids=ids, planned=bool(ids))
    return draft


def decision_parts(draft, pin, previous=None):
    plan, _ = prepare_mapping_partitions(draft, pin, previous)
    values = {(item["case_id"], item["row_id"]): item for item in reviews(draft)}
    for sequence in range(plan["part_count"]):
        # This test helper materializes pages; production assembly consumes an iterator.
        _, part = prepare_mapping_partitions(draft, pin, previous, sequence=sequence)
        yield {"sequence": sequence, "plan_digest": plan["plan_digest"], "part_digest": part["part_digest"],
            "decisions": [deepcopy(values[(item["case_id"], item["row_id"])]) for item in part["assertions"]]}


def test_partitioned_assessment_matches_v1_without_mutating_draft_or_claiming_execution():
    draft = proposal()
    original = deepcopy(draft)
    pin = generation_pin(draft)
    plan, _ = prepare_mapping_partitions(draft, pin, None)
    parts = list(decision_parts(draft, pin))
    parts[0]["decisions"][0]["decision"] = "reject"
    parts[0]["decisions"][1]["decision"] = "defer"
    combined = [item for part in parts for item in part["decisions"]]
    assessment = assess_partitioned_mappings(draft, pin, None, plan["plan_digest"], iter(parts))
    assert assessment == assess_mappings(draft, combined)
    assert draft == original and assessment["coverage"]["obligation_denominator"] == len(draft["coverage"]["rows"])
    assert assessment["coverage"]["executed_on_target_count"] == assessment["coverage"]["passed_count"] == 0
    assert not assessment["execution_authorized"]


def test_more_than_8192_pairs_are_all_partitioned_and_assessed_without_raising_v1_limits():
    draft = large_proposal(9000)
    pin = generation_pin(draft)
    plan, _ = prepare_mapping_partitions(draft, pin, None)
    decisions = sorted(reviews(draft), key=lambda item: (item["case_id"], item["row_id"]))
    assert plan["assertion_count"] == len(decisions) > 8192
    assert plan["part_count"] == (len(decisions) + PART_SIZE - 1) // PART_SIZE

    def parts():
        for sequence, start in enumerate(range(0, len(decisions), PART_SIZE)):
            subset = decisions[start:start + PART_SIZE]
            pairs = [{key: value for key, value in item.items() if key not in {"decision", "reason"}} for item in subset]
            yield {"sequence": sequence, "plan_digest": plan["plan_digest"],
                "part_digest": acceptance_digest({"sequence": sequence, "assertions": pairs}), "decisions": subset}

    assessment = assess_partitioned_mappings(draft, pin, None, plan["plan_digest"], parts())
    assert assessment["accepted_assertion_count"] == len(decisions)
    assert len(assessment["accepted_case_ids"]) == 9000
    assert assessment["coverage"]["constraint_denominator"] == draft["coverage"]["constraint_denominator"]
    assert assessment["coverage"]["obligation_denominator"] == draft["coverage"]["obligation_denominator"]
    with pytest.raises(ValidationError):
        MappingReviewInput.model_validate(dict(project_id=pin["project_id"], generation_id=pin["generation_id"],
            generation_artifact_hash=pin["artifact_hash"], expected_previous_revision_id=None,
            decision="review", mappings=decisions, reason="Not a v1-sized request"))


def test_maximum_case_count_has_a_bounded_manifest_and_last_page_without_omission():
    draft = large_proposal(MAX_CASES)
    pin = generation_pin(draft)
    plan, _ = prepare_mapping_partitions(draft, pin, None)
    selected_plan, part = prepare_mapping_partitions(draft, pin, None, sequence=plan["part_count"] - 1)
    assert selected_plan == plan and plan["case_count"] == MAX_CASES
    assert plan["assertion_count"] == sum(len(case["assertions"]) for case in draft["cases"])
    assert 1 <= len(part["assertions"]) <= PART_SIZE
    assert len(json.dumps(plan).encode()) < 4096 and len(json.dumps(part).encode()) < 65536
    assert "parts" not in plan and not plan["execution_authorized"]


@pytest.mark.parametrize("field", ["project_id", "generation_id", "artifact_hash", "context_pin", "scope_pin", "input_digest"])
def test_plan_is_bound_to_full_generation_and_predecessor(field):
    draft = proposal()
    pin = generation_pin(draft)
    plan, _ = prepare_mapping_partitions(draft, pin, None)
    changed = deepcopy(pin)
    if field in {"context_pin", "scope_pin"}:
        changed[field]["artifact_hash"] = "sha256:" + "0" * 64
    elif field in {"artifact_hash", "input_digest"}:
        changed[field] = "sha256:" + "0" * 64
    else:
        changed[field] += "-other"
    other, _ = prepare_mapping_partitions(draft, changed, None)
    assert other["plan_digest"] != plan["plan_digest"]
    assert prepare_mapping_partitions(draft, pin, "new-review-head")[0]["plan_digest"] != plan["plan_digest"]
    with pytest.raises(TestDesignMappingInvalid):
        assess_partitioned_mappings(draft, changed, None, plan["plan_digest"], decision_parts(draft, changed))


@pytest.mark.parametrize("change", ["omit", "extra", "wrong_sequence", "bool_sequence", "plan", "part", "oracle", "step", "bool_step", "empty_reason", "long_reason", "authority", "reorder"])
def test_partition_rejects_missing_repeated_changed_or_unpinned_decisions(change):
    draft = proposal()
    pin = generation_pin(draft)
    plan, _ = prepare_mapping_partitions(draft, pin, None)
    parts = list(decision_parts(draft, pin))
    if change == "omit":
        parts.pop()
    elif change == "extra":
        parts.append(deepcopy(parts[0]))
    elif change in {"wrong_sequence", "bool_sequence", "plan", "part"}:
        key, value = {"wrong_sequence": ("sequence", 1), "bool_sequence": ("sequence", False),
            "plan": ("plan_digest", "sha256:" + "0" * 64), "part": ("part_digest", "sha256:" + "0" * 64)}[change]
        parts[0][key] = value
    elif change == "reorder":
        parts[0]["decisions"].reverse()
    else:
        key, value = {"oracle": ("oracle_digest", "sha256:" + "0" * 64), "step": ("step_index", 63),
            "bool_step": ("step_index", False), "empty_reason": ("reason", " "), "long_reason": ("reason", "x" * 2001),
            "authority": ("execution_authorized", True)}[change]
        parts[0]["decisions"][0][key] = value
    with pytest.raises(TestDesignMappingInvalid):
        assess_partitioned_mappings(draft, pin, None, plan["plan_digest"], iter(parts))


@pytest.mark.parametrize("change", ["duplicate_case", "duplicate_assertion", "oracle", "coverage_oracle", "proposal_hash", "case_limit"])
def test_partition_layout_rejects_corrupt_proposals_without_truncation(change):
    draft = proposal()
    if change == "duplicate_case":
        draft["cases"].append(deepcopy(draft["cases"][0]))
    elif change == "duplicate_assertion":
        draft["cases"][0]["assertions"].append(deepcopy(draft["cases"][0]["assertions"][0]))
    elif change == "oracle":
        draft["cases"][0]["assertions"][0]["oracle"]["expected_result"] = "different independent expectation"
    elif change == "coverage_oracle":
        draft["coverage"]["rows"][0]["oracle_digest"] = "sha256:" + "0" * 64
    elif change == "case_limit":
        draft["cases"] = [draft["cases"][0]] * (MAX_CASES + 1)
    pin = generation_pin(draft)
    if change == "proposal_hash":
        pin["proposal_hash"] = "sha256:" + "0" * 64
    with pytest.raises(TestDesignMappingInvalid):
        prepare_mapping_partitions(draft, pin, None)


def test_page_cursor_is_strict_and_empty_gap_plan_cannot_claim_complete():
    draft = proposal()
    draft["cases"] = []
    for row in draft["coverage"]["rows"]:
        row.update(planned=False, planned_case_ids=[], proposed_assertion_case_ids=[], gap_ids=["missing-fixture"])
    pin = generation_pin(draft)
    plan, part = prepare_mapping_partitions(draft, pin, None)
    assert plan["assertion_count"] == plan["part_count"] == 0 and part is None
    value = assess_partitioned_mappings(draft, pin, None, plan["plan_digest"], iter(()))
    assert not value["mapping_complete"] and value["accepted_case_ids"] == []
    with pytest.raises(MappingPartitionOutOfRange):
        prepare_mapping_partitions(draft, pin, None, sequence=0)
    for sequence in (True, "0", -1, 1.0):
        with pytest.raises(ValidationError):
            MappingPartitionPageInput(project_id=pin["project_id"], generation_id=pin["generation_id"],
                generation_artifact_hash=pin["artifact_hash"], plan_digest=plan["plan_digest"], sequence=sequence)


@pytest.mark.parametrize("change", ["missing_middle", "swapped", "last_incomplete", "last_foreign_plan"])
def test_failure_after_valid_first_partition_never_returns_a_partial_assessment(change):
    draft = large_proposal(PART_SIZE * 3)
    original = deepcopy(draft)
    pin = generation_pin(draft)
    plan, _ = prepare_mapping_partitions(draft, pin, None)
    parts = list(decision_parts(draft, pin))
    assert len(parts) >= 3
    if change == "missing_middle":
        parts.pop(1)
    elif change == "swapped":
        parts[1], parts[2] = parts[2], parts[1]
    elif change == "last_incomplete":
        parts[-1]["decisions"].pop()
    else:
        parts[-1]["plan_digest"] = "sha256:" + "0" * 64
    with pytest.raises(TestDesignMappingInvalid):
        assess_partitioned_mappings(draft, pin, None, plan["plan_digest"], iter(parts))
    assert draft == original
