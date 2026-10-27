"""Trusted-tokenizer batch planning and complete proposal validation, not execution."""
from copy import deepcopy
from dataclasses import asdict, dataclass, field
import json
from typing import Tuple

from pydantic import Field

from .generation_budget import GenerationBudgetInvalid, reserve_generation_budget
from .generation_execution_inputs import GENERATION_INSTRUCTIONS, GenerationExecutionSelection
from .test_design_output import Digest, GenerationGap, PlannedCase, TestDesignModelOutput, parse_test_design_output, validate_test_design_output
from .test_design_results import response_digest
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.generation_batches import batch_input, constraint_units, seal_batch_plan, verify_batch_plan
from ...domain.quality_loop.test_design_generation import TestDesignGenerationInvalid, planned_coverage, verify_batch_proposal


MAX_BATCH_CONTENT_BYTES = 1024 * 1024


class TestDesignBatchModelOutput(TestDesignModelOutput):
    __test__ = False
    batch_digest: Digest


class TestDesignAggregateOutput(TestDesignModelOutput):
    """Internal v3 aggregate, never the schema sent to a single Provider call."""
    cases: Tuple[PlannedCase, ...] = Field(max_length=64 * 512)
    gaps: Tuple[GenerationGap, ...] = Field(max_length=64 * 512)


def batch_messages(batch):
    instructions = GENERATION_INSTRUCTIONS + """
This is an exact projection of a larger frozen generation input, not its full
denominator. Return input_digest = generation_input_digest and the exact
batch_digest. Account for every row in obligations; do not assert or gap rows
owned by other batches. global_obligations remain binding constraints in every
batch, but only their owner produces assertions. All global_rule_ids must be
inherited by every case. Cite only facts sent in this batch. Never invent missing
evidence, discard owned obligations or replace an independent oracle.
"""
    system = instructions + "\nJSON Schema:\n" + json.dumps(
        TestDesignBatchModelOutput.model_json_schema(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    content = json.dumps(batch, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return system, content


def plan_generation_batches(prepared, counter, limits):
    units = constraint_units(prepared)
    capacity = min(limits.max_input_tokens_per_call, counter.policy.context_tokens - limits.max_output_tokens_per_call)
    batches, current = [], []

    def measured(ids, sequence):
        batch = batch_input(prepared, sorted(ids), sequence)
        system, content = batch_messages(batch)
        count = counter.count(system, content)
        if type(count) is not int or count <= 0:
            raise GenerationBudgetInvalid("generation tokenizer returned an invalid count")
        return batch, count, len(content.encode()) <= MAX_BATCH_CONTENT_BYTES and count <= capacity

    for unit in units:
        _, _, fits = measured([*current, *unit], len(batches))
        if fits:
            current = [*current, *unit]
            continue
        if not current:
            raise GenerationBudgetInvalid("an indivisible AC scope with all global rules exceeds the model budget; nothing was truncated")
        batches.append(measured(current, len(batches))[0])
        if len(batches) >= min(64, limits.max_calls):
            raise GenerationBudgetInvalid("complete generation exceeds the call envelope; no remaining unit was dropped")
        current = list(unit)
        if not measured(current, len(batches))[2]:
            raise GenerationBudgetInvalid("an indivisible AC scope with all global rules exceeds the model budget; nothing was truncated")
    batches.append(measured(current, len(batches))[0])
    plan = seal_batch_plan(prepared, batches)
    counts = [counter.count(*batch_messages(batch)) for batch in batches]
    reservation = reserve_generation_budget(counter.policy, limits, counts)
    return plan, reservation, counts


def validate_batch_output(prepared, batch, content):
    output = parse_test_design_output(content, TestDesignBatchModelOutput)
    if output.pop("batch_digest") != batch["batch_digest"]:
        raise TestDesignGenerationInvalid("model response belongs to another generation batch")
    verify_batch_proposal(prepared, output, row_ids={row["row_id"] for row in batch["obligations"]},
        fact_ids={fact["endpoint"]["object_id"] for fact in batch["facts"]})
    return output


def merge_batch_proposals(prepared, plan, responses, *, aggregate=False):
    """No partial merge: exactly one independently validated response per batch."""
    verify_batch_plan(prepared, plan)
    if type(responses) not in {list, tuple} or len(responses) != len(plan["batches"]):
        raise TestDesignGenerationInvalid("every generation batch needs exactly one complete response")
    expected = {batch["batch_digest"]: batch for batch in plan["batches"]}
    received = {}
    for entry in responses:
        if type(entry) not in {list, tuple} or len(entry) != 2 or type(entry[0]) is not str:
            raise TestDesignGenerationInvalid("invalid generation batch response identity")
        ident, content = entry
        if ident not in expected or ident in received:
            raise TestDesignGenerationInvalid("duplicate or foreign generation batch response")
        received[ident] = content
    merged = {"input_digest": prepared["input_digest"], "cases": [], "gaps": []}
    provenance = []
    for batch in plan["batches"]:
        ident = batch["batch_digest"]
        content = received[ident]
        output = validate_batch_output(prepared, batch, content)
        case_ids, gap_ids = {}, {}
        for collection, field_name, mapping, prefix in (("cases", "case_id", case_ids, "case_"), ("gaps", "gap_id", gap_ids, "gap_")):
            for item in output[collection]:
                local_id = item[field_name]
                stable_id = prefix + acceptance_digest([prepared["input_digest"], ident, local_id])[7:]
                mapping[local_id] = stable_id
                value = deepcopy(item)
                value[field_name] = stable_id
                merged[collection].append(value)
        provenance.append({"batch_digest": ident, "response_hash": response_digest(content),
            "case_id_map": case_ids, "gap_id_map": gap_ids})
    merged_content = json.dumps(merged, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if aggregate:
        output = parse_test_design_output(merged_content, TestDesignAggregateOutput, max_bytes=64 * MAX_BATCH_CONTENT_BYTES)
        proposal = {"cases": output["cases"], "gaps": output["gaps"], "coverage": planned_coverage(prepared, output)}
    else:
        proposal = validate_test_design_output(prepared, merged_content)
    return {"proposal": proposal, "provenance": provenance, "merged_content": merged_content,
        "plan_digest": plan["plan_digest"], "generation_authorized": False, "execution_authorized": False}


@dataclass(frozen=True)
class PreparedGenerationBatchPlan:
    digest: str
    preview: dict
    input: dict = field(repr=False)
    plan: dict = field(repr=False)


class GenerationBatchPlanningApplicationService:
    def __init__(self, generation, profiles, policies, authorization, sources):
        self.generation, self.profiles, self.policies = generation, profiles, policies
        self.authorization, self.sources = authorization, sources

    def prepare(self, selection):
        selection = GenerationExecutionSelection.model_validate(selection.model_dump(mode="json"))
        access = self.authorization.scope(selection.project_id)
        if access.effective_project_role not in {"project_admin", "platform_admin"}:
            raise PermissionError("generation batch planning requires a project administrator")
        prepared = self.generation.prepare(selection.selection())
        model = self.profiles.resolve(selection.model_config_id)
        if model.binding.config_id != selection.model_config_id:
            raise TestDesignGenerationInvalid("generation batch model binding differs from the selected configuration")
        counter = self.policies.resolve(model.binding)
        sources = tuple(self.sources.bindings(prepared))
        if not sources or tuple(sorted(set(sources))) != sources:
            raise TestDesignGenerationInvalid("generation batch source inventory must be complete, unique and sorted")
        for binding_id in sources:
            access.require_binding(binding_id)
        plan, reservation, counts = plan_generation_batches(prepared, counter, selection.budget)
        payload = {"schema": "nasus.test-design-batch-planning.v1", "selection": selection.model_dump(mode="json"),
            "model_binding": asdict(model.binding), "policy": counter.policy.model_dump(mode="json"),
            "source_binding_ids": list(sources), "source_scope_digest": access.fingerprint,
            "plan_digest": plan["plan_digest"], "reservation": reservation,
            "messages_hashes": [acceptance_digest(list(batch_messages(batch))) for batch in plan["batches"]]}
        digest = acceptance_digest(payload)
        preview = {**payload, "planning_digest": digest, "input_digest": prepared["input_digest"],
            "batches": [{"batch_digest": batch["batch_digest"], "sequence": batch["sequence"],
                "owned_obligation_count": len(batch["obligations"]), "local_constraint_count": len(batch["local_constraint_ids"]),
                "global_rule_count": len(batch["global_rule_ids"]), "selected_fact_count": len(batch["facts"]),
                "estimated_input_tokens": count} for batch, count in zip(plan["batches"], counts)],
            "generation_authorized": False, "execution_authorized": False,
            "remaining_gates": ["fresh_batch_confirmation", "durable_multi_call_reservation",
                "per_batch_native_receipts", "atomic_merged_result_commit"]}
        self.authorization.require_current(access)
        return PreparedGenerationBatchPlan(digest, preview, prepared, plan)

    def preview(self, selection):
        return self.prepare(selection).preview

    def check_outputs(self, selection, *, expected_planning_digest, responses, aggregate=False):
        prepared = self.prepare(selection)
        if prepared.digest != expected_planning_digest:
            raise TestDesignGenerationInvalid("generation batch dependencies changed; discard uncommitted responses")
        result = merge_batch_proposals(prepared.input, prepared.plan, responses, aggregate=aggregate)
        # This is proposal checking, not a reservation or persistent commit.
        current = self.prepare(selection)
        if current.digest != prepared.digest:
            raise TestDesignGenerationInvalid("generation batch dependencies changed during result validation")
        return result
