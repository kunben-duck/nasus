"""Atomic multi-call drafts, never independent approval or target-run evidence."""
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from .generation_batch_ledger import GenerationBatchReservation, batch_call_request_hash, batch_reservation, validate_batch_reply
from .generation_batch_planning import batch_messages, merge_batch_proposals
from .generation_execution_inputs import GenerationExecutionSelection
from .test_design_results import BATCH_RESULT_SCHEMA, RECOVERED_BATCH_RESULT_SCHEMA, GenerationResultRequest, TestDesignResultIntegrityError, response_digest
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.test_design_generation import replay_generation_input
from ...domain.quality_loop.generation_batches import verify_batch_plan


class GenerationBatchResultPort(Protocol):
    def by_invocation(self, project_id, invocation_id): ...
    def get(self, project_id, generation_id): ...
    def verified_calls(self, plan, *, lease, require_current): ...
    def record_batch(self, plan, payload, ref, digest, *, lease, require_current): ...


def verify_result_plan(plan, prepared, batch_plan, calls):
    verify_batch_plan(prepared, batch_plan)
    if (prepared["project_id"] != plan.project_id or prepared["input_digest"] != plan.request.input_digest
            or batch_plan["plan_digest"] != plan.plan_digest or len(batch_plan["batches"]) != len(plan.batches)
            or type(calls) is not list or len(calls) != len(plan.batches)):
        raise TestDesignResultIntegrityError("aggregate requires the complete fixed input and every native call")
    for sequence, (batch, spec, proof) in enumerate(zip(batch_plan["batches"], plan.batches, calls)):
        if (batch["batch_digest"] != spec.batch_digest or acceptance_digest(list(batch_messages(batch))) != spec.messages_hash
                or set(proof) != {"claim", "reply", "audit"}):
            raise TestDesignResultIntegrityError("aggregate batch messages or call provenance changed")
        claim, reply, audit = proof["claim"], proof["reply"], proof["audit"]
        if (set(claim) != {"project_id", "invocation_id", "sequence", "batch_digest", "call_id", "request_hash", "reserved_at"}
                or set(reply) != {"project_id", "invocation_id", "sequence", "batch_digest", "call_id", "response_hash", "usage", "artifact_ref", "artifact_hash"}
                or set(audit) != {"id", "provider", "model_name", "request_hash", "response_hash", "input_tokens", "output_tokens", "usage_source", "occurred_at"}
                or type(audit["input_tokens"]) is not int or type(audit["output_tokens"]) is not int):
            raise TestDesignResultIntegrityError("aggregate native proof has unknown fields or invalid usage types")
        common = {"project_id": plan.project_id, "invocation_id": plan.invocation_id, "sequence": sequence,
                  "batch_digest": spec.batch_digest}
        if (any(claim.get(key) != value or reply.get(key) != value for key, value in common.items())
                or type(claim.get("sequence")) is not int or type(reply.get("sequence")) is not int
                or claim.get("request_hash") != batch_call_request_hash(plan, sequence)
                or claim.get("call_id") != reply.get("call_id") or audit.get("id") != claim.get("call_id")
                or audit.get("request_hash") != claim["request_hash"] or audit.get("response_hash") != reply.get("response_hash")
                or audit.get("provider") != plan.model_binding.provider or audit.get("model_name") != plan.model_binding.model_name
                or audit.get("usage_source") != "provider" or audit.get("input_tokens") != reply["usage"]["input_tokens"]
                or audit.get("output_tokens") != reply["usage"]["output_tokens"]):
            raise TestDesignResultIntegrityError("aggregate contains a foreign, skipped or fabricated native call")


def _validate_batch_result(prepared, payload, reply_artifacts):
    required = {"schema", "project_id", "generation_id", "invocation_id", "actor_id", "request", "context_pin", "scope_pin",
                "model_binding", "reservation", "batch_plan", "calls", "proposal", "provenance", "merged_output_hash",
                "status", "mapping_status", "execution_authorized"}
    recovered = payload.get("schema") == RECOVERED_BATCH_RESULT_SCHEMA
    if recovered:
        required |= {"recovery_invocation_id", "recovery_request"}
    if (set(payload) != required or payload["schema"] not in {BATCH_RESULT_SCHEMA, RECOVERED_BATCH_RESULT_SCHEMA} or payload["status"] != "draft"
            or payload["mapping_status"] != "pending_independent_review" or payload["execution_authorized"] is not False):
        raise TestDesignResultIntegrityError("aggregate schema or authority mismatch")
    plan = GenerationBatchReservation.model_validate(payload["reservation"])
    if (any(payload[key] != getattr(plan, key) for key in ("project_id", "invocation_id", "actor_id"))
            or payload["request"] != plan.request.model_dump(mode="json")
            or payload["model_binding"] != plan.model_binding.model_dump(mode="json")
            or payload["context_pin"] != prepared["context_pin"] or payload["scope_pin"] != prepared["scope_pin"]
            or payload["generation_id"] != str(uuid5(NAMESPACE_URL, "nasus:test-design:" + plan.invocation_id))):
        raise TestDesignResultIntegrityError("aggregate request, source or identity mismatch")
    verify_result_plan(plan, prepared, payload["batch_plan"], payload["calls"])
    if recovered:
        from .generation_batch_recovery import GenerationBatchRecoveryRequest, verify_batch_recovery_request
        from .test_design_output import Id
        from pydantic import TypeAdapter
        authority_id = TypeAdapter(Id).validate_python(payload["recovery_invocation_id"])
        if authority_id != payload["recovery_invocation_id"] or authority_id == plan.invocation_id:
            raise TestDesignResultIntegrityError("batch recovery must reference a distinct command")
        recovery = GenerationBatchRecoveryRequest.model_validate(payload["recovery_request"])
        verify_batch_recovery_request(recovery, plan, prepared, payload["batch_plan"], payload["calls"])
    responses = []
    for sequence, proof in enumerate(payload["calls"]):
        receipt = proof["reply"]
        native = reply_artifacts.read(plan.project_id, receipt["artifact_ref"], receipt["artifact_hash"])
        checked = validate_batch_reply(plan, sequence, proof["claim"], native)
        if (acceptance_digest(native) != receipt["artifact_hash"] or any(checked[key] != receipt[key] for key in checked)):
            raise TestDesignResultIntegrityError("aggregate native reply differs from its archived receipt")
        responses.append((receipt["batch_digest"], native["content"]))
    merged = merge_batch_proposals(prepared, payload["batch_plan"], responses, aggregate=True)
    if (payload["proposal"] != merged["proposal"] or payload["provenance"] != merged["provenance"]
            or payload["merged_output_hash"] != response_digest(merged["merged_content"])):
        raise TestDesignResultIntegrityError("aggregate cases, full coverage or ID lineage changed")
    return plan


def validate_batch_result(prepared, payload, reply_artifacts):
    try:
        return _validate_batch_result(prepared, payload, reply_artifacts)
    except TestDesignResultIntegrityError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise TestDesignResultIntegrityError("aggregate native provenance or complete proposal could not be verified") from exc


def read_batch_result(service, access, stored, payload, project_id, generation_id):
    metadata = stored["metadata"]
    if (service.batch_replies is None or acceptance_digest(payload) != metadata["artifact_hash"]
            or metadata.get("schema") != payload.get("schema") or metadata.get("call_id") is not None
            or payload.get("project_id") != project_id or payload.get("generation_id") != generation_id
            or payload.get("invocation_id") != metadata["invocation_id"]):
        raise TestDesignResultIntegrityError("aggregate metadata or private reply reader unavailable")
    if ((payload.get("schema") == RECOVERED_BATCH_RESULT_SCHEMA
            and payload.get("recovery_invocation_id") != metadata.get("recovery_invocation_id"))
            or payload.get("schema") == BATCH_RESULT_SCHEMA and "recovery_invocation_id" in metadata):
        raise TestDesignResultIntegrityError("aggregate recovery metadata mismatch")
    request = GenerationResultRequest.model_validate(payload["request"])
    if request.project_id != project_id or request.scope_revision_id != metadata["scope_revision_id"]:
        raise TestDesignResultIntegrityError("aggregate request scope mismatch")
    scope, context = service.generation.scopes.read_inputs(project_id, request.scope_revision_id, request.scope_artifact_hash)
    prepared = replay_generation_input(context, scope)
    plan = validate_batch_result(prepared, payload, service.batch_replies)
    service.repository.verify_batch_history(payload)
    proposal = payload["proposal"]
    if (metadata.get("call_ids") != [proof["claim"]["call_id"] for proof in payload["calls"]]
            or metadata.get("batch_count") != len(plan.batches) or metadata.get("plan_digest") != plan.plan_digest
            or metadata.get("case_count") != len(proposal["cases"]) or metadata.get("gap_count") != len(proposal["gaps"])
            or stored["cases"] != sorted(proposal["cases"], key=lambda case: case["case_id"])
            or stored["coverage"] != proposal["coverage"]):
        raise TestDesignResultIntegrityError("aggregate persisted projections differ from the full native proposal")
    service.authorization.require_current(access)
    return {"metadata": metadata, "result": payload, "historical_not_live": True,
            "current_use": {"scope_current": scope["current_use"]["scope_current"],
                "mapping_approved": False, "execution_authorized": False}}


def batch_result_payload(plan, prepared, batch_plan, calls, merged):
    return {"schema": BATCH_RESULT_SCHEMA, "project_id": plan.project_id,
        "generation_id": str(uuid5(NAMESPACE_URL, "nasus:test-design:" + plan.invocation_id)),
        "invocation_id": plan.invocation_id, "actor_id": plan.actor_id, "request": plan.request.model_dump(mode="json"),
        "context_pin": prepared["context_pin"], "scope_pin": prepared["scope_pin"],
        "model_binding": plan.model_binding.model_dump(mode="json"), "reservation": plan.model_dump(mode="json"),
        "batch_plan": batch_plan, "calls": calls, "proposal": merged["proposal"], "provenance": merged["provenance"],
        "merged_output_hash": response_digest(merged["merged_content"]), "status": "draft",
        "mapping_status": "pending_independent_review", "execution_authorized": False}


class GenerationBatchResultApplicationService:
    """Trusted internal executor calls commit; no arbitrary reply import API."""
    def __init__(self, receipts, repository: GenerationBatchResultPort, artifacts):
        self.receipts, self.repository, self.artifacts = receipts, repository, artifacts

    def commit(self, request, *, lease):
        request = GenerationResultRequest.model_validate(request.model_dump(mode="json"))
        plan = self.receipts._prepare(request, lease)
        current = self.receipts._current(request, plan, lease)
        selected = GenerationExecutionSelection(**request.selection().model_dump(mode="json"),
            model_config_id=request.model_config_id, budget=request.execution.budget)
        prepared = self.receipts.planning.prepare(selected)
        if batch_reservation(prepared, invocation_id=lease.invocation_id, actor_id=plan.actor_id) != plan:
            raise TestDesignResultIntegrityError("aggregate dependencies changed before assembly")
        replay = self.receipts._read(request, plan, lease)
        calls = self.repository.verified_calls(plan, lease=lease, require_current=current)
        verify_result_plan(plan, prepared.input, prepared.plan, calls)
        merged = merge_batch_proposals(prepared.input, prepared.plan, replay["responses"], aggregate=True)
        payload = batch_result_payload(plan, prepared.input, prepared.plan, calls, merged)
        validate_batch_result(prepared.input, payload, self.receipts.artifacts)
        current()
        prior = self.repository.by_invocation(plan.project_id, plan.invocation_id)
        if prior is None:
            ref, digest = self.artifacts.put(plan.project_id, payload)
        else:
            digest = acceptance_digest(payload)
            if prior.get("schema") != BATCH_RESULT_SCHEMA or prior["artifact_hash"] != digest:
                raise TestDesignResultIntegrityError("aggregate invocation has a different archived result")
            ref = self.repository.get(plan.project_id, prior["generation_id"])["artifact_ref"]
            archived = self.artifacts.read(plan.project_id, ref, digest)
            if archived != payload:
                raise TestDesignResultIntegrityError("aggregate replay cannot rewrite its archived result")
        if digest != acceptance_digest(payload):
            raise TestDesignResultIntegrityError("aggregate private artifact write mismatch")

        def require_current():
            current()
            validate_batch_result(prepared.input, payload, self.receipts.artifacts)
            self.receipts.leases.require_lease(lease)

        result = self.repository.record_batch(plan, payload, ref, digest, lease=lease, require_current=require_current)
        current()
        return result
