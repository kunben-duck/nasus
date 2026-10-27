"""Exact batch budget and call receipts; neither a preview nor a lease is consent."""
from typing import Literal, Tuple

from pydantic import Field, model_validator

from .generation_budget import GenerationModelPolicy, reserve_generation_budget, verify_generation_usage
from .generation_execution_inputs import GenerationExecutionConsent, GenerationExecutionSelection
from .test_design_output import Digest, GenerationValue, Id
from .test_design_results import GenerationResultRequest, TestDesignResultIntegrityError, response_digest
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.generation_batches import verify_batch_plan


BATCH_RESERVATION_SCHEMA = "nasus.test-design-batch-reservation.v1"
BATCH_REPLY_SCHEMA = "nasus.test-design-batch-native-reply.v1"


class BatchModelBinding(GenerationValue):
    config_id: Id
    config_digest: Digest
    provider: Literal["openai", "openai_compatible", "anthropic", "gemini"]
    model_name: str = Field(strict=True, min_length=1, max_length=256)
    base_url: str = Field(strict=True, min_length=1, max_length=2048)


class BatchCallSpec(GenerationValue):
    sequence: int = Field(strict=True, ge=0, le=63)
    batch_digest: Digest
    messages_hash: Digest
    estimated_input_tokens: int = Field(strict=True, gt=0, le=1000000)


class BatchBudgetReservation(GenerationValue):
    currency: Literal["USD", "CNY"]
    call_count: int = Field(strict=True, ge=1, le=64)
    estimated_input_tokens: int = Field(strict=True, gt=0, le=64000000)
    reserved_input_tokens_per_call: int = Field(strict=True, gt=0, le=1000000)
    max_output_tokens_per_call: int = Field(strict=True, ge=512, le=32768)
    reserved_tokens: int = Field(strict=True, gt=0, le=64000000)
    reserved_cost_nanos: int = Field(strict=True, ge=0, le=9000000000000000)
    count_basis: Literal["local_tokenizer_with_operator_framing"]
    cost_basis: Literal["operator_rate_ceiling_not_provider_invoice"]


class GenerationBatchReservation(GenerationValue):
    schema_version: Literal["nasus.test-design-batch-reservation.v1"] = BATCH_RESERVATION_SCHEMA
    project_id: Id
    invocation_id: Id
    actor_id: Id
    request: GenerationResultRequest
    model_binding: BatchModelBinding
    policy: GenerationModelPolicy
    plan_digest: Digest
    batches: Tuple[BatchCallSpec, ...] = Field(min_length=1, max_length=64)
    reservation: BatchBudgetReservation

    @model_validator(mode="after")
    def exact_envelope(self):
        request, consent, binding = self.request, self.request.execution, self.model_binding
        if consent is None or request.project_id != self.project_id:
            raise ValueError("batch reservation requires exact project and source/budget consent")
        if (request.model_config_id != binding.config_id or request.model_config_digest != binding.config_digest
                or any(getattr(binding, key) != getattr(self.policy, key) for key in ("config_id", "provider", "model_name", "base_url"))
                or consent.policy_digest != acceptance_digest(self.policy.model_dump(mode="json"))):
            raise ValueError("batch model and operator policy pins differ")
        if ([item.sequence for item in self.batches] != list(range(len(self.batches)))
                or len({item.batch_digest for item in self.batches}) != len(self.batches)):
            raise ValueError("batch reservation must contain the complete unique ordered call set")
        expected = reserve_generation_budget(self.policy, consent.budget, [item.estimated_input_tokens for item in self.batches])
        if self.reservation.model_dump(mode="json") != expected:
            raise ValueError("batch reservation changed the complete cumulative envelope")
        selection = GenerationExecutionSelection(**request.selection().model_dump(mode="json"),
            model_config_id=request.model_config_id, budget=consent.budget)
        planning = {"schema": "nasus.test-design-batch-planning.v1", "selection": selection.model_dump(mode="json"),
            "model_binding": binding.model_dump(mode="json"), "policy": self.policy.model_dump(mode="json"),
            "source_binding_ids": list(consent.source_binding_ids), "source_scope_digest": consent.source_scope_digest,
            "plan_digest": self.plan_digest, "reservation": expected,
            "messages_hashes": [item.messages_hash for item in self.batches]}
        if acceptance_digest(planning) != consent.plan_digest:
            raise ValueError("batch reservation differs from the exact confirmed planning digest")
        return self


def batch_execution_request(planned):
    """Produce a confirmation DTO, not permission to invoke the provider."""
    verify_batch_plan(planned.input, planned.plan)
    view = planned.preview
    planning = {key: view[key] for key in ("schema", "selection", "model_binding", "policy", "source_binding_ids",
        "source_scope_digest", "plan_digest", "reservation", "messages_hashes")}
    if (view["planning_digest"] != planned.digest or view["input_digest"] != planned.input["input_digest"]
            or acceptance_digest(planning) != planned.digest or view["plan_digest"] != planned.plan["plan_digest"]):
        raise TestDesignResultIntegrityError("batch planning receipt mismatch")
    selected = GenerationExecutionSelection.model_validate(view["selection"])
    if (planned.input["project_id"] != selected.project_id
            or planned.input["scope_pin"]["revision_id"] != selected.scope_revision_id
            or planned.input["scope_pin"]["artifact_hash"] != selected.scope_artifact_hash):
        raise TestDesignResultIntegrityError("batch planning scope or project mismatch")
    return GenerationResultRequest(**selected.selection().model_dump(mode="json"), input_digest=view["input_digest"],
        model_config_id=selected.model_config_id, model_config_digest=view["model_binding"]["config_digest"],
        execution=GenerationExecutionConsent(policy_digest=acceptance_digest(view["policy"]), plan_digest=planned.digest,
            source_binding_ids=view["source_binding_ids"], source_scope_digest=view["source_scope_digest"], budget=selected.budget))


def batch_reservation(planned, *, invocation_id, actor_id):
    view = planned.preview
    request = batch_execution_request(planned)
    from .generation_batch_planning import batch_messages

    specs = []
    if len(view["batches"]) != len(planned.plan["batches"]) or len(view["messages_hashes"]) != len(view["batches"]):
        raise TestDesignResultIntegrityError("batch planning omitted call metadata")
    for batch, summary, messages_hash in zip(planned.plan["batches"], view["batches"], view["messages_hashes"]):
        if (batch["batch_digest"] != summary["batch_digest"] or batch["sequence"] != summary["sequence"]
                or acceptance_digest(list(batch_messages(batch))) != messages_hash):
            raise TestDesignResultIntegrityError("batch planning changed provider message pins")
        specs.append(BatchCallSpec(sequence=batch["sequence"], batch_digest=batch["batch_digest"],
            messages_hash=messages_hash, estimated_input_tokens=summary["estimated_input_tokens"]))
    return GenerationBatchReservation(project_id=request.project_id, invocation_id=invocation_id, actor_id=actor_id,
        request=request, model_binding=view["model_binding"], policy=view["policy"], plan_digest=planned.plan["plan_digest"],
        batches=specs, reservation=view["reservation"])


def batch_execution_preview(planned):
    from .generation_batch_planning import batch_messages
    from .generation_execution_inputs import GENERATION_TIMEOUT_SECONDS
    view, request = planned.preview, batch_execution_request(planned)
    summaries = [{"batch_digest": batch["batch_digest"], "sequence": batch["sequence"],
        "owned_obligation_count": len(batch["obligations"]), "local_constraint_count": len(batch["local_constraint_ids"]),
        "global_rule_count": len(batch["global_rule_ids"]), "selected_fact_count": len(batch["facts"]),
        "estimated_input_tokens": summary["estimated_input_tokens"]}
        for batch, summary in zip(planned.plan["batches"], view["batches"])]
    if len(summaries) != len(planned.plan["batches"]):
        raise TestDesignResultIntegrityError("batch preview omitted complete call metadata")
    gates = ["fresh_batch_confirmation", "durable_multi_call_reservation", "per_batch_native_receipts", "atomic_merged_result_commit"]
    planning = {**{key: view[key] for key in ("schema", "selection", "model_binding", "policy", "source_binding_ids",
        "source_scope_digest", "plan_digest", "reservation", "messages_hashes")},
        "planning_digest": planned.digest, "input_digest": planned.input["input_digest"], "batches": summaries,
        "generation_authorized": False, "execution_authorized": False, "remaining_gates": gates}
    return {"request": request.model_dump(mode="json"), "provider": view["model_binding"]["provider"],
        "model_name": view["model_binding"]["model_name"], "destination": view["model_binding"]["base_url"],
        "policy": view["policy"], "reservation": view["reservation"],
        "input_bytes": sum(len(batch_messages(batch)[1].encode()) for batch in planned.plan["batches"]),
        "timeout_seconds": GENERATION_TIMEOUT_SECONDS, "call_count": len(planned.plan["batches"]),
        "batching": "complete_constraint_batches_no_truncation", "batch_planning": planning,
        "generation_authorized": False, "execution_authorized": False, "remaining_gates": gates}


def batch_call_request_hash(plan, sequence):
    spec = plan.batches[sequence]
    return acceptance_digest({"schema": "nasus.test-design-batch-call.v1", "request": plan.request.model_dump(mode="json"),
        "plan_digest": plan.plan_digest, "sequence": sequence, "batch_digest": spec.batch_digest, "messages_hash": spec.messages_hash})


def validate_batch_reply(plan, sequence, claim, payload):
    spec = plan.batches[sequence]
    required = {"schema", "project_id", "invocation_id", "actor_id", "request", "plan_digest", "sequence", "batch_digest",
                "messages_hash", "call_id", "content", "usage"}
    if (type(payload) is not dict or set(payload) != required or payload["schema"] != BATCH_REPLY_SCHEMA
            or type(payload["sequence"]) is not int or payload["sequence"] != sequence
            or any(payload[key] != getattr(plan, key) for key in ("project_id", "invocation_id", "actor_id", "plan_digest"))
            or payload["request"] != plan.request.model_dump(mode="json") or payload["batch_digest"] != spec.batch_digest
            or payload["messages_hash"] != spec.messages_hash or payload["call_id"] != claim["call_id"]
            or type(payload["content"]) is not str or not payload["content"] or len(payload["content"].encode()) > 1024 * 1024):
        raise TestDesignResultIntegrityError("native batch response identity or content mismatch")
    usage = payload["usage"]
    if type(usage) is not dict or usage != verify_generation_usage(plan.policy, plan.request.execution.budget,
            usage.get("input_tokens"), usage.get("output_tokens")):
        raise TestDesignResultIntegrityError("native batch response usage mismatch")
    return {"project_id": plan.project_id, "invocation_id": plan.invocation_id, "sequence": sequence,
        "batch_digest": spec.batch_digest, "call_id": claim["call_id"], "response_hash": response_digest(payload["content"]),
        "usage": usage}
