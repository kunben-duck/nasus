import copy

import pytest

from apps.api.app.domain.system_image.context_pack import canonical_bytes, MandatoryContextTooLarge, ContextPackIntegrityError
from apps.api.app.domain.system_image.context_partition import partition_context, PARTITION_POLICY
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest


def base_context(count=5):
    return {"schema_version": "nasus.context-pack.v1", "purpose": "test_design", "policy_version": PARTITION_POLICY,
        "required_constraints": [{"object_id": "global", "kind": "business_rule", "oracle": None, "source_fields": ["Never expose credentials"]},
            *[{"object_id": f"ac-{n}", "kind": "acceptance_criterion", "oracle": {"expected_result": "批准的完整预期" * 25},
                "source_fields": [f"source-{n}"]} for n in range(count)]],
        "readiness": {"status": "blocked", "reason_codes": ["unapproved_mandatory_constraint", "model_budget_not_bound"]}}


def assert_complete(bundle, base, ceiling):
    assert bundle["required_constraints"] == base["required_constraints"]
    seen = []
    for part in bundle["parts"]:
        content = part["context"]
        assert snapshot_digest(content) == part["part_id"]
        assert len(canonical_bytes(content)) == content["budget"]["used_upper_bound"] <= ceiling
        assert content["partition"]["global_constraint_ids"] == ["global"]
        assert content["required_constraints"][0] == base["required_constraints"][0]
        seen.extend(content["partition"]["target_object_ids"])
    assert seen == [item["object_id"] for item in base["required_constraints"][1:]]
    assert bundle["budget"]["part_count"] == len(bundle["parts"])
    assert bundle["budget"]["total_upper_bound"] == sum(len(canonical_bytes(p["context"])) for p in bundle["parts"])


def test_partition_reserves_whole_ac_and_global_rules_before_optional_candidates():
    base = base_context()
    original = copy.deepcopy(base)
    facts = [{"target_object_id": f"ac-{n}", "title": "optional" * 1000} for n in range(5)]
    bundle = partition_context(base, facts, 2300)
    assert len(bundle["parts"]) > 1
    assert_complete(bundle, base, 2300)
    assert bundle["facts"] == [] and bundle["budget"]["omitted_optional_facts"] == 5
    assert all(p["context"]["readiness"]["status"] == "blocked" for p in bundle["parts"])
    assert base == original and partition_context(base, facts, 2300) == bundle
    # A smaller fact is kept only alongside its AC, never borrowed by another part.
    selected = partition_context(base, [{"target_object_id": "ac-4", "title": "small"}], 2300)
    assert len(selected["facts"]) == 1
    for part in selected["parts"]:
        assert all(f["target_object_id"] in part["context"]["partition"]["target_object_ids"] for f in part["context"]["facts"])


def test_more_than_legacy_32_constraints_are_all_partitioned():
    base = base_context(34)
    bundle = partition_context(base, [], 2300)
    assert_complete(bundle, base, 2300)
    assert len(bundle["required_constraints"]) == 35


@pytest.mark.parametrize("which", ["global", "target"])
def test_indivisible_constraints_fail_instead_of_partial_bundle(which):
    base = base_context()
    base["required_constraints"][0 if which == "global" else -1]["source_fields"] = ["不可截断" * 5000]
    with pytest.raises(MandatoryContextTooLarge):
        partition_context(base, [], 2300)


def test_empty_and_global_only_context_never_gets_ready_from_partitioning():
    base = base_context(0)
    bundle = partition_context(base, [], 2300)
    assert_complete(bundle, base, 2300)
    base["required_constraints"] = []
    empty = partition_context(base, [], 2300)
    assert len(empty["parts"]) == 1
    assert empty["parts"][0]["context"]["readiness"]["status"] == "blocked"
    assert "missing_requirements" in empty["parts"][0]["context"]["readiness"]["reason_codes"]


@pytest.mark.parametrize("corruption", ["duplicate", "foreign_fact", "kind"])
def test_partition_rejects_invalid_denominator_or_fact_scope(corruption):
    base, facts = base_context(), []
    if corruption == "duplicate":
        base["required_constraints"].append(base["required_constraints"][-1])
    elif corruption == "kind":
        base["required_constraints"][0]["kind"] = "unclassified"
    else:
        facts = [{"target_object_id": "foreign"}]
    with pytest.raises(ContextPackIntegrityError):
        partition_context(base, facts, 2300)


def test_partition_reserves_optional_omission_counter_bytes_at_budget_edge():
    base = base_context(1)
    facts = [{"target_object_id": "ac-0", "title": "X" * 9999} for _ in range(100)]
    result = partition_context(base, facts, 2300)
    edge = result["budget"]["used_upper_bound"]
    assert_complete(partition_context(base, facts, edge), base, edge)
    with pytest.raises(MandatoryContextTooLarge):
        partition_context(base, facts, edge - 1)


@pytest.mark.parametrize("field,value", [("policy_version", "nasus.test-design-context.v1"), ("purpose", "release"), ("schema_version", "unknown")])
def test_partition_policy_is_not_silently_applied_to_another_contract(field, value):
    base = base_context()
    base[field] = value
    with pytest.raises(ContextPackIntegrityError):
        partition_context(base, [], 2300)
