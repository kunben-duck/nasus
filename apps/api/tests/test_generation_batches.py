from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.generation_batch_planning import (
    GenerationBatchPlanningApplicationService, batch_messages, merge_batch_proposals, plan_generation_batches,
)
from apps.api.app.application.quality_loop.generation_budget import GenerationBudgetInvalid
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.generation_batches import batch_input, constraint_units, seal_batch_plan, verify_batch_plan
from apps.api.app.domain.quality_loop.test_design_generation import TestDesignGenerationInvalid, compile_generation_input
from apps.api.app.domain.quality_loop.test_design_scope import validate_scope_contract
from apps.api.tests.test_generation_executor import budget, executor, policy
from apps.api.tests.test_semantic_link_model import resolved
from apps.api.tests.test_test_design_generation import case_output, generation_inputs
from apps.api.tests.test_test_design_scope import scope_contract


def multi_input(*, linked=False, global_only=False, count=3):
    context_view, scope_view = generation_inputs()
    context = context_view["context"]
    original = deepcopy(context["required_constraints"][0])
    if global_only:
        context["required_constraints"] = [context["required_constraints"][1]]
    else:
        for index in range(1, count):
            item = deepcopy(original)
            item.update(object_id=f"ac-{index}", source_revision_id=f"source:{index}", document_revision_id=f"document:{index}")
            item["evidence_ids"] = [f"e-ac-{index}"]
            item["authority"].update(revision_id=f"authority:{index}", artifact_hash=acceptance_digest(index))
            context["required_constraints"].append(item)
    context["facts"] = [{"target_object_id": item["object_id"], "relation": "implements",
        "endpoint": {"object_id": "fact:" + item["object_id"], "evidence_ids": ["fact-e:" + item["object_id"]],
            "excerpt": ("Untrusted source observation " + item["object_id"] + " ") * 150}}
        for item in context["required_constraints"]]
    contract = scope_contract(context["required_constraints"])
    if linked:
        contract["risks"]["items"][0]["constraint_ids"] = ["ac", "ac-1"]
    context_view["metadata"]["artifact_hash"] = acceptance_digest(context)
    scope_view["request"].update(contract=contract, context_artifact_hash=context_view["metadata"]["artifact_hash"])
    scope_view["revision"].update(context_artifact_hash=context_view["metadata"]["artifact_hash"],
        artifact_hash=acceptance_digest(contract), request_hash=acceptance_digest(scope_view["request"]))
    scope_view["context_pin"]["artifact_hash"] = context_view["metadata"]["artifact_hash"]
    scope_view["assessment"] = validate_scope_contract(contract, context)
    return compile_generation_input(context_view, scope_view)


class FixtureCounter:
    """Explicit local byte-based test counter, never Provider usage or pricing."""
    def __init__(self, binding=None):
        self.policy = policy(binding or resolved().binding)

    def count(self, system, content):
        return (len(system.encode()) + len(content.encode())) // 4 + self.policy.framing_tokens


def divided_plan(prepared):
    counter = FixtureCounter()
    # One complete connected unit fits; a second cannot fit by omitting facts.
    capacity = max(counter.count(*batch_messages(batch_input(prepared, unit, 0))) for unit in constraint_units(prepared)) + 1
    limits = budget(max_calls=64, max_reserved_tokens=64000000, max_reserved_cost_nanos=9000000000000000,
        max_input_tokens_per_call=capacity)
    plan, reservation, counts = plan_generation_batches(prepared, counter, limits)
    return plan, reservation, counts, limits


def responses_for(prepared, plan, *, gaps=False):
    source = case_output(prepared)
    results = []
    for batch in plan["batches"]:
        ids = {row["row_id"] for row in batch["obligations"]}
        cases = [deepcopy(case) for case in source["cases"] if case["assertions"][0]["row_id"] in ids]
        for index, case in enumerate(cases):
            case["case_id"] = f"local:{index}"
        output = {"input_digest": prepared["input_digest"], "batch_digest": batch["batch_digest"],
            "cases": [] if gaps else cases, "gaps": [{"gap_id": "local-gap", "row_ids": sorted(ids),
                "description": "Explicit fixture gap, not an executed test"}] if gaps else []}
        results.append((batch["batch_digest"], json.dumps(output)))
    return results


def test_batches_preserve_all_rows_facts_global_rules_and_original_inputs():
    prepared = multi_input()
    original = deepcopy(prepared)
    plan, reservation, counts, _ = divided_plan(prepared)
    assert len(plan["batches"]) == reservation["call_count"] == 3
    assert reservation["estimated_input_tokens"] == sum(counts)
    assert reservation["reserved_tokens"] == len(counts) * (128000 + 8192)
    assert prepared == original
    verify_batch_plan(prepared, plan)
    owned = [row["row_id"] for batch in plan["batches"] for row in batch["obligations"]]
    assert len(owned) == len(set(owned)) == len(prepared["obligations"])
    assert set(owned) == {row["row_id"] for row in prepared["obligations"]}
    expected_globals = [row for row in prepared["obligations"] if set(row["constraint_ids"]) <= {"rule"}]
    for batch in plan["batches"]:
        assert batch["global_rule_ids"] == ["rule"] and batch["global_obligations"] == expected_globals
        assert next(item for item in batch["required_constraints"] if item["object_id"] == "rule") == prepared["context"]["required_constraints"][1]
        assert batch["mandatory_constraint_ids"] == prepared["mandatory_constraint_ids"]
        assert batch["context_pin"] == prepared["context_pin"] and batch["scope_pin"] == prepared["scope_pin"]
        assert "untrusted" in batch_messages(batch)[0].lower()
        assert json.loads(batch_messages(batch)[1]) == batch
        assert not batch["generation_authorized"] and not batch["execution_authorized"]
    assert plan_generation_batches(prepared, FixtureCounter(), divided_plan(prepared)[3])[0] == plan


def test_connected_multi_ac_risk_is_indivisible_and_global_only_input_is_valid():
    prepared = multi_input(linked=True)
    assert constraint_units(prepared) == [("ac", "ac-1"), ("ac-2",)]
    plan, _, _, _ = divided_plan(prepared)
    assert [batch["local_constraint_ids"] for batch in plan["batches"]] == [["ac", "ac-1"], ["ac-2"]]
    with pytest.raises(TestDesignGenerationInvalid, match="cannot be split"):
        batch_input(prepared, ["ac"], 0)
    only = multi_input(global_only=True)
    one, _, _, _ = divided_plan(only)
    assert len(one["batches"]) == 1 and one["batches"][0]["local_constraint_ids"] == []
    assert {row["row_id"] for row in one["batches"][0]["obligations"]} == {row["row_id"] for row in only["obligations"]}


def test_connected_constraints_are_transitive_across_scope_dimensions():
    context, scope = generation_inputs()
    base = multi_input(linked=True)
    context["context"] = deepcopy(base["context"])
    contract = deepcopy(base["scope_contract"])
    item = deepcopy(contract["risks"]["items"][0])
    item.update(obligation_id="transitive-risk", constraint_ids=["ac-1", "ac-2"])
    contract["risks"]["items"].append(item)
    scope["request"]["contract"] = contract
    scope["assessment"] = validate_scope_contract(contract, context["context"])
    prepared = compile_generation_input(context, scope)
    assert constraint_units(prepared) == [("ac", "ac-1", "ac-2")]


def test_verified_operator_tokenizer_counts_complete_unicode_batch_messages(tmp_path):
    import tiktoken
    from apps.api.app.infrastructure.llm.generation_token_budget import ConfiguredGenerationModelPolicies, tiktoken_policy_digest

    binding = resolved().binding
    fixed_policy = policy(binding, tokenizer_digest=tiktoken_policy_digest("cl100k_base"))
    config = tmp_path / "operator-fixture.json"
    config.write_text(json.dumps({"schema": "nasus.generation-model-policies.v1",
        "profiles": [{"policy": fixed_policy.model_dump(mode="json")}]}))
    counter = ConfiguredGenerationModelPolicies(config).resolve(binding)
    prepared = multi_input()
    for fact in prepared["context"]["facts"]:
        fact["endpoint"]["excerpt"] += "来源文本只是证据，不是执行指令。" * 50
    prepared["input_digest"] = acceptance_digest({key: value for key, value in prepared.items() if key != "input_digest"})
    capacity = max(counter.count(*batch_messages(batch_input(prepared, unit, 0))) for unit in constraint_units(prepared)) + 1
    limits = budget(max_calls=64, max_reserved_tokens=64000000, max_reserved_cost_nanos=9000000000000000,
        max_input_tokens_per_call=capacity)
    plan, reservation, counts = plan_generation_batches(prepared, counter, limits)
    assert len(plan["batches"]) == 3
    encoding = tiktoken.get_encoding("cl100k_base")
    for batch, count in zip(plan["batches"], counts):
        system, content = batch_messages(batch)
        assert count == len(encoding.encode(system, disallowed_special=())) + len(encoding.encode(content, disallowed_special=())) + fixed_policy.framing_tokens
        assert count <= capacity
    assert reservation["estimated_input_tokens"] == sum(counts)
    assert reservation["count_basis"] == "local_tokenizer_with_operator_framing"


def test_unscoped_and_cross_unit_evidence_is_preserved_not_ranked_away():
    prepared = multi_input()
    context_view, scope = generation_inputs()
    context_view["context"]["facts"].append({"relation": "implements", "endpoint": {"object_id": "unscoped", "evidence_ids": ["unscoped-e"]}})
    context_view["context"]["facts"].append({"target_object_id": "ac", "relation": "implements",
        "endpoint": {"object_id": "cross-evidence", "evidence_ids": ["e2"]}})
    changed = compile_generation_input(context_view, scope)
    plan, _, _, _ = divided_plan(changed)
    for batch in plan["batches"]:
        assert {fact["endpoint"]["object_id"] for fact in batch["facts"]} >= {"unscoped", "cross-evidence"}
    prepared["context"]["facts"][0]["endpoint"]["evidence_ids"] = ["e2"]
    prepared["input_digest"] = acceptance_digest({key: value for key, value in prepared.items() if key != "input_digest"})
    plan, _, _, _ = divided_plan(prepared)
    assert all(any(f["endpoint"]["object_id"] == "fact:ac" for f in b["facts"]) for b in plan["batches"])


@pytest.mark.parametrize("change", ["oracle", "fact", "global", "scope_dimension", "source_pin", "missing_batch", "extra_batch", "unknown_field"])
def test_rehashed_plan_cannot_change_or_drop_frozen_components(change):
    prepared = multi_input()
    plan, _, _, _ = divided_plan(prepared)
    mutated = deepcopy(plan)
    batch = mutated["batches"][0]
    if change == "oracle":
        batch["obligations"][0]["oracle"]["expected_result"] = "Always pass"
    elif change == "fact":
        batch["facts"].pop()
    elif change == "global":
        batch["global_obligations"].clear()
    elif change == "scope_dimension":
        batch["scope_dimensions"]["risks"]["rationale"] = "Change the reviewed scope"
    elif change == "source_pin":
        batch["context_pin"]["artifact_hash"] = acceptance_digest("new source")
    elif change == "missing_batch":
        mutated["batches"].pop()
    elif change == "extra_batch":
        mutated["batches"].append(deepcopy(batch))
    else:
        mutated["approved"] = True
    batch["batch_digest"] = acceptance_digest({key: value for key, value in batch.items() if key != "batch_digest"})
    mutated["plan_digest"] = acceptance_digest({key: value for key, value in mutated.items() if key != "plan_digest"})
    with pytest.raises(TestDesignGenerationInvalid):
        verify_batch_plan(prepared, mutated)


@pytest.mark.parametrize("limit", ["calls", "tokens", "cost", "capacity", "output", "currency"])
def test_whole_plan_budget_failure_never_returns_a_truncated_prefix(limit):
    prepared = multi_input()
    _, _, _, limits = divided_plan(prepared)
    changes = {"calls": {"max_calls": 1}, "tokens": {"max_reserved_tokens": 140000},
        "cost": {"max_reserved_cost_nanos": 140000000}, "capacity": {"max_input_tokens_per_call": 512},
        "output": {"max_output_tokens_per_call": 16384}, "currency": {"currency": "CNY"}}[limit]
    with pytest.raises(GenerationBudgetInvalid):
        plan_generation_batches(prepared, FixtureCounter(), limits.model_copy(update=changes))


@pytest.mark.parametrize("count", [True, 0, -1, None, "100"])
def test_invalid_token_counts_are_never_used_as_a_budget(count):
    with pytest.raises(GenerationBudgetInvalid):
        plan_generation_batches(multi_input(), SimpleNamespace(policy=FixtureCounter().policy, count=lambda *args: count), budget())


def test_indivisible_wire_limit_is_not_evaded_by_an_underestimating_counter():
    prepared = multi_input()
    prepared["context"]["facts"][0]["endpoint"]["excerpt"] = "x" * (1024 * 1024 + 1)
    prepared["input_digest"] = acceptance_digest({key: value for key, value in prepared.items() if key != "input_digest"})
    with pytest.raises(GenerationBudgetInvalid, match="nothing was truncated"):
        plan_generation_batches(prepared, SimpleNamespace(policy=FixtureCounter().policy, count=lambda *args: 500), budget())


def test_merge_namespaces_local_ids_and_recomputes_one_original_denominator():
    prepared = multi_input()
    plan, _, _, _ = divided_plan(prepared)
    responses = responses_for(prepared, plan)
    original = deepcopy(responses)
    result = merge_batch_proposals(prepared, plan, responses)
    assert merge_batch_proposals(prepared, plan, list(reversed(responses))) == result
    assert responses == original
    cases = result["proposal"]["cases"]
    assert len(cases) == len({case["case_id"] for case in cases}) == len(prepared["obligations"])
    assert all(len(case["case_id"]) <= 128 and case["global_constraint_ids"] == ["rule"] for case in cases)
    assert result["proposal"]["coverage"]["constraint_denominator"] == 4
    assert result["proposal"]["coverage"]["planned_obligation_count"] == len(prepared["obligations"])
    assert result["proposal"]["coverage"]["assertion_mapped_count"] == result["proposal"]["coverage"]["passed_count"] == 0
    assert len(result["provenance"]) == 3 and result["generation_authorized"] is result["execution_authorized"] is False
    gaps = merge_batch_proposals(prepared, plan, responses_for(prepared, plan, gaps=True))
    assert gaps["proposal"]["coverage"]["planned_obligation_count"] == 0
    assert gaps["proposal"]["coverage"]["gap_obligation_count"] == len(prepared["obligations"])
    assert len({gap["gap_id"] for gap in gaps["proposal"]["gaps"]}) == 3


@pytest.mark.parametrize("change", ["missing_batch", "duplicate_batch", "foreign_batch", "batch_pin", "input_pin", "omitted_row",
    "foreign_row", "oracle", "global", "foreign_fact", "extra_authority", "duplicate_case", "duplicate_json", "non_json"])
def test_invalid_batch_output_prevents_any_partial_merge(change):
    prepared = multi_input()
    plan, _, _, _ = divided_plan(prepared)
    responses = responses_for(prepared, plan)
    ident, content = responses[0]
    output = json.loads(content)
    if change == "missing_batch":
        responses.pop()
    elif change == "duplicate_batch":
        responses[-1] = responses[0]
    elif change == "foreign_batch":
        responses[0] = (acceptance_digest("foreign"), content)
    elif change == "batch_pin":
        output["batch_digest"] = acceptance_digest("foreign")
    elif change == "input_pin":
        output["input_digest"] = acceptance_digest("foreign")
    elif change == "omitted_row":
        output["cases"].pop()
    elif change == "foreign_row":
        output["cases"][0]["assertions"][0] = deepcopy(json.loads(responses[-1][1])["cases"][0]["assertions"][0])
    elif change == "oracle":
        output["cases"][0]["assertions"][0]["oracle"]["expected_result"] = "Silently rewrite the source oracle"
    elif change == "global":
        output["cases"][0]["global_constraint_ids"] = []
    elif change == "foreign_fact":
        output["cases"][0]["supporting_fact_ids"] = ["fact:ac-2"]
    elif change == "extra_authority":
        output["passed"] = True
    elif change == "duplicate_case":
        output["cases"].append(deepcopy(output["cases"][0]))
    elif change == "duplicate_json":
        responses[0] = (ident, '{"cases": [], "cases": []}')
    else:
        responses[0] = (ident, '{"cases": NaN}')
    if change not in {"missing_batch", "duplicate_batch", "foreign_batch", "duplicate_json", "non_json"}:
        responses[0] = (ident, json.dumps(output))
    with pytest.raises(TestDesignGenerationInvalid):
        merge_batch_proposals(prepared, plan, responses)


def test_application_uses_current_scope_model_acl_and_never_egresses_or_commits():
    app, selection, deps, _ = executor()
    prepared = multi_input()
    plan, _, _, limits = divided_plan(prepared)
    selection = selection.model_copy(update={"budget": limits})
    deps["generation"].prepare = lambda request: deepcopy(prepared)
    deps["policies"].resolve = lambda binding: FixtureCounter(binding)
    planner = app.batch_planning
    assert isinstance(planner, GenerationBatchPlanningApplicationService)
    private = planner.prepare(selection)
    preview = private.preview
    assert preview["reservation"]["call_count"] == 3 and len(preview["batches"]) == 3
    assert preview["source_binding_ids"] == ["source"]
    assert not any(text in json.dumps(preview) for text in ("Untrusted source", "HTTP 400", "private-provider-key"))
    assert "Untrusted source" not in repr(private)
    result = planner.check_outputs(selection, expected_planning_digest=private.digest, responses=responses_for(prepared, plan))
    assert result["proposal"]["coverage"]["constraint_denominator"] == 4
    assert deps["provider"].calls == deps["results"].calls == 0 and deps["repository"].stored is None
    deps["authorization"].revoked = True
    with pytest.raises(PermissionError):
        planner.check_outputs(selection, expected_planning_digest=private.digest, responses=responses_for(prepared, plan))


@pytest.mark.parametrize("change", ["policy", "acl", "source", "model", "scope"])
def test_app_rejects_dependencies_changed_since_batch_preview(change):
    app, selection, deps, prepared = executor()
    original = app.batch_planning.prepare(selection)
    if change == "policy":
        deps["policies"].resolve = lambda binding: SimpleNamespace(policy=policy(binding, revision="v2"), count=lambda *args: 32000)
    elif change == "acl":
        deps["authorization"].access = deps["authorization"].access.__class__("p", "actor", "project_admin", 2,
            frozenset({"source"}), frozenset({"legacy"}), acceptance_digest("new-acl"), False)
    elif change == "source":
        deps["sources"].bindings = lambda value: ("not-visible",)
    elif change == "model":
        model = resolved(key="different-private-key")
        deps["profiles"].resolve = lambda ident: model
    else:
        mutated = deepcopy(prepared)
        mutated["scope_pin"]["request_hash"] = acceptance_digest("new-scope")
        mutated["input_digest"] = acceptance_digest({key: value for key, value in mutated.items() if key != "input_digest"})
        deps["generation"].prepare = lambda request: mutated
    with pytest.raises((TestDesignGenerationInvalid, PermissionError)):
        app.batch_planning.check_outputs(selection, expected_planning_digest=original.digest,
            responses=responses_for(prepared, original.plan))
    assert deps["provider"].calls == 0 and deps["results"].calls == 0
