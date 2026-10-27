"""Lossless projections of frozen inputs; batch plans are not egress authority."""
from copy import deepcopy

from .acceptance_specification import acceptance_digest
from .test_design_generation import SCOPE_DIMENSIONS, TestDesignGenerationInvalid, verify_generation_input


BATCH_INPUT_SCHEMA = "nasus.test-design-batch-input.v1"
BATCH_PLAN_SCHEMA = "nasus.test-design-batch-plan.v1"


def constraint_units(prepared):
    """Keep cross-AC obligations indivisible; global rules accompany every unit."""
    verify_generation_input(prepared)
    locals_ = set(prepared["mandatory_constraint_ids"]) - set(prepared["global_rule_ids"])
    groups = {ident: {ident} for ident in locals_}
    for row in prepared["obligations"]:
        related = set(row["constraint_ids"]) & locals_
        if related:
            union = set().union(*(groups[ident] for ident in related))
            for ident in union:
                groups[ident] = union
    return sorted({tuple(sorted(group)) for group in groups.values()}) or [()]


def batch_input(prepared, local_ids, sequence):
    """Project exact source fields without re-summarizing or ranking them away."""
    if type(sequence) is not int or not 0 <= sequence < 64:
        raise TestDesignGenerationInvalid("invalid generation batch sequence")
    global_ids = set(prepared["global_rule_ids"])
    locals_ = set(prepared["mandatory_constraint_ids"]) - global_ids
    selected = set(local_ids)
    if tuple(sorted(selected)) != tuple(local_ids) or not selected.issubset(locals_):
        raise TestDesignGenerationInvalid("invalid generation batch constraint selection")
    owned, shared = [], []
    for row in prepared["obligations"]:
        related = set(row["constraint_ids"]) - global_ids
        if related & selected:
            if not related.issubset(selected):
                raise TestDesignGenerationInvalid("a cross-constraint obligation cannot be split")
            owned.append(row)
        elif not related:
            shared.append(row)
            if sequence == 0:
                owned.append(row)
    if not owned:
        raise TestDesignGenerationInvalid("a batch must own at least one obligation")
    visible = selected | global_ids
    required_evidence = {ident for row in (*owned, *shared) for ident in row["evidence_ids"]}
    context, contract = prepared["context"], prepared["scope_contract"]
    facts = [fact for fact in context["facts"] if fact.get("target_object_id") is None
        or fact["target_object_id"] in visible or required_evidence.intersection(fact["endpoint"]["evidence_ids"])]
    context_header = {key: deepcopy(value) for key, value in context.items()
        if key not in {"required_constraints", "facts", "parts", "budget", "schema_version"}}
    dimensions = {}
    for category in SCOPE_DIMENSIONS:
        original = contract[category]
        dimensions[category] = {**deepcopy(original), "items": [deepcopy(item) for item in original["items"]
            if set(item["constraint_ids"]).issubset(visible)]}
    payload = {"schema": BATCH_INPUT_SCHEMA, "project_id": prepared["project_id"], "sequence": sequence,
        "generation_input_digest": prepared["input_digest"],
        "context_pin": deepcopy(prepared["context_pin"]), "scope_pin": deepcopy(prepared["scope_pin"]),
        "mandatory_constraint_ids": list(prepared["mandatory_constraint_ids"]), "global_rule_ids": list(prepared["global_rule_ids"]),
        "local_constraint_ids": list(local_ids), "context_header": context_header,
        "source_context_schema": context.get("schema_version"), "source_context_budget": deepcopy(context.get("budget")),
        "source_context_parts": [{"part_id": part["part_id"], "content_hash": acceptance_digest(part["context"])}
            for part in context.get("parts", [])],
        "required_constraints": [deepcopy(item) for item in context["required_constraints"] if item["object_id"] in visible],
        "facts": deepcopy(facts), "scope_assessments": {key: deepcopy(value) for key, value in contract.items()
            if key not in {*SCOPE_DIMENSIONS, "examples"}},
        "scope_dimensions": dimensions, "examples": [deepcopy(item) for item in contract["examples"] if item["constraint_id"] in visible],
        "obligations": deepcopy(owned), "global_obligations": deepcopy(shared),
        "source_policy": prepared["source_policy"], "generation_authorized": False, "execution_authorized": False}
    return {**payload, "batch_digest": acceptance_digest(payload)}


def verify_batch_plan(prepared, plan):
    verify_generation_input(prepared)
    if (plan.get("schema") != BATCH_PLAN_SCHEMA or plan.get("input_digest") != prepared["input_digest"]
            or set(plan) != {"schema", "input_digest", "batches", "plan_digest"}
            or acceptance_digest({key: value for key, value in plan.items() if key != "plan_digest"}) != plan["plan_digest"]
            or type(plan["batches"]) is not list or not 1 <= len(plan["batches"]) <= 64):
        raise TestDesignGenerationInvalid("generation batch plan integrity mismatch")
    seen_constraints, seen_rows, seen_facts = set(), set(), set()
    for sequence, batch in enumerate(plan["batches"]):
        ids = batch.get("local_constraint_ids", [])
        if batch != batch_input(prepared, ids, sequence) or seen_constraints.intersection(ids):
            raise TestDesignGenerationInvalid("generation batch projection differs from the fixed input")
        rows = {row["row_id"] for row in batch["obligations"]}
        if seen_rows.intersection(rows):
            raise TestDesignGenerationInvalid("generation obligation has multiple batch owners")
        seen_constraints.update(ids)
        seen_rows.update(rows)
        seen_facts.update(acceptance_digest(fact) for fact in batch["facts"])
    if (seen_constraints != set(prepared["mandatory_constraint_ids"]) - set(prepared["global_rule_ids"])
            or seen_rows != {row["row_id"] for row in prepared["obligations"]}
            or seen_facts != {acceptance_digest(fact) for fact in prepared["context"]["facts"]}):
        raise TestDesignGenerationInvalid("generation batch plan dropped a constraint, obligation or selected fact")


def seal_batch_plan(prepared, batches):
    payload = {"schema": BATCH_PLAN_SCHEMA, "input_digest": prepared["input_digest"], "batches": deepcopy(batches)}
    plan = {**payload, "plan_digest": acceptance_digest(payload)}
    verify_batch_plan(prepared, plan)
    return plan
