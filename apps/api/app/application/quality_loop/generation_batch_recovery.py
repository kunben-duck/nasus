"""Complete archived-call pins for recovery; a receipt is not command authority."""
from typing import Literal, Protocol, Tuple
from dataclasses import asdict

from pydantic import Field, model_validator

from .generation_batch_ledger import GenerationBatchReservation, batch_call_request_hash, validate_batch_reply
from .generation_batch_planning import merge_batch_proposals
from .generation_batch_results import verify_result_plan
from .generation_budget import verify_generation_usage
from .generation_work_lease import GenerationLeaseLost, GenerationWorkLease
from .test_design_output import Digest, GenerationValue, Id
from .test_design_results import TestDesignResultIntegrityError
from ...domain.quality_loop.acceptance_specification import acceptance_digest


BATCH_RECOVERY_SCHEMA = "nasus.test-design-batch-recovery.v1"


class GenerationBatchRecoveryPort(Protocol):
    def require_confirmation(self, request, authority_id, actor_id): ...
    def recovery_offer(self, source, invocation_id, actor_id, *, require_current): ...
    def reservation_for_recovery(self, request, *, lease): ...
    def require_lease(self, lease): ...
    def load_for_recovery(self, request, prepared, batch_plan, *, lease, require_current): ...
    def by_invocation(self, project_id, invocation_id): ...
    def get(self, project_id, generation_id): ...
    def record_recovered(self, request, plan, payload, ref, digest, *, lease, require_current): ...


class BatchRecoveryReplyPin(GenerationValue):
    sequence: int = Field(strict=True, ge=0, le=63)
    batch_digest: Digest
    call_id: Id
    request_hash: Digest
    reply_artifact_hash: Digest
    response_hash: Digest
    usage_digest: Digest
    audit_digest: Digest


class GenerationBatchRecoveryRequest(GenerationValue):
    schema_version: Literal["nasus.test-design-batch-recovery.v1"] = BATCH_RECOVERY_SCHEMA
    project_id: Id
    invocation_id: Id
    request_hash: Digest
    reservation_hash: Digest
    plan_digest: Digest
    replies_digest: Digest
    replies: Tuple[BatchRecoveryReplyPin, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def complete_ordered_pins(self):
        if ([item.sequence for item in self.replies] != list(range(len(self.replies)))
                or len({item.call_id for item in self.replies}) != len(self.replies)
                or len({item.batch_digest for item in self.replies}) != len(self.replies)):
            raise ValueError("recovery must pin each unique archived call in complete sequence order")
        return self


def archived_batch_recovery_request(plan, calls):
    """Metadata-only offer; execution must still validate the private bodies."""
    try:
        plan = GenerationBatchReservation.model_validate(plan.model_dump(mode="json"))
        if type(calls) is not list or len(calls) != len(plan.batches):
            raise TestDesignResultIntegrityError("recovery requires every archived call")
        pins = []
        for sequence, proof in enumerate(calls):
            claim, reply, audit = proof["claim"], proof["reply"], proof["audit"]
            spec = plan.batches[sequence]
            if (set(proof) != {"claim", "reply", "audit"}
                    or set(claim) != {"project_id", "invocation_id", "sequence", "batch_digest", "call_id", "request_hash", "reserved_at"}
                    or set(reply) != {"project_id", "invocation_id", "sequence", "batch_digest", "call_id", "response_hash", "usage", "artifact_ref", "artifact_hash"}
                    or set(audit) != {"id", "provider", "model_name", "request_hash", "response_hash", "input_tokens", "output_tokens", "usage_source", "occurred_at"}
                    or type(audit["input_tokens"]) is not int or type(audit["output_tokens"]) is not int
                    or any(item.get("project_id") != plan.project_id or item.get("invocation_id") != plan.invocation_id
                    or type(item.get("sequence")) is not int or item["sequence"] != sequence
                    or item.get("batch_digest") != spec.batch_digest for item in (claim, reply))
                    or claim["request_hash"] != batch_call_request_hash(plan, sequence)
                    or reply["call_id"] != claim["call_id"] or audit["id"] != claim["call_id"]
                    or audit["request_hash"] != claim["request_hash"] or audit["response_hash"] != reply["response_hash"]
                    or audit["provider"] != plan.model_binding.provider or audit["model_name"] != plan.model_binding.model_name
                    or audit["usage_source"] != "provider"):
                raise TestDesignResultIntegrityError("recovery native receipt pins differ from the complete plan")
            usage = reply["usage"]
            if usage != verify_generation_usage(plan.policy, plan.request.execution.budget,
                    usage.get("input_tokens"), usage.get("output_tokens")) or (
                    audit["input_tokens"], audit["output_tokens"]) != (usage["input_tokens"], usage["output_tokens"]):
                raise TestDesignResultIntegrityError("recovery requires exact native usage, not a refund or invoice")
            pins.append(BatchRecoveryReplyPin(sequence=sequence, batch_digest=claim["batch_digest"],
                call_id=claim["call_id"], request_hash=claim["request_hash"],
                reply_artifact_hash=reply["artifact_hash"], response_hash=reply["response_hash"],
                usage_digest=acceptance_digest(usage), audit_digest=acceptance_digest(audit)))
        return GenerationBatchRecoveryRequest(project_id=plan.project_id, invocation_id=plan.invocation_id,
            request_hash=acceptance_digest(plan.request.model_dump(mode="json")),
            reservation_hash=acceptance_digest(plan.model_dump(mode="json")), plan_digest=plan.plan_digest,
            replies_digest=acceptance_digest(calls), replies=tuple(pins))
    except TestDesignResultIntegrityError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise TestDesignResultIntegrityError("complete archived batch recovery pins could not be verified") from exc


def batch_recovery_request(plan, prepared, batch_plan, calls):
    """No partial recovery, source body, private address, or synthetic model call."""
    try:
        verify_result_plan(plan, prepared, batch_plan, calls)
        return archived_batch_recovery_request(plan, calls)
    except TestDesignResultIntegrityError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise TestDesignResultIntegrityError("complete archived batch recovery pins could not be verified") from exc


def verify_batch_recovery_request(request, plan, prepared, batch_plan, calls):
    """Rebuild from authoritative receipts, never trust request hashes alone."""
    try:
        request = GenerationBatchRecoveryRequest.model_validate(request.model_dump(mode="json"))
        if request != batch_recovery_request(plan, prepared, batch_plan, calls):
            raise TestDesignResultIntegrityError("archived batch recovery source or per-call pins changed")
    except TestDesignResultIntegrityError:
        raise
    except (ValueError, TypeError, AttributeError) as exc:
        raise TestDesignResultIntegrityError("batch recovery request could not be verified") from exc
    return request


def prepare_archived_batch_recovery(request, plan, prepared, batch_plan, calls, artifacts, *,
                                    authority_invocation_id, lease, leases, require_current):
    """Private preflight only: canonical authorization and atomic commit remain separate."""
    lease = GenerationWorkLease(**asdict(lease))
    if (lease.project_id != plan.project_id or lease.invocation_id != authority_invocation_id
            or authority_invocation_id == plan.invocation_id):
        raise GenerationLeaseLost("batch recovery requires a distinct new command's exact worker lease")

    def current():
        leases.require_lease(lease)
        require_current()
        leases.require_lease(lease)

    current()
    verify_batch_recovery_request(request, plan, prepared, batch_plan, calls)
    responses = []
    for sequence, proof in enumerate(calls):
        current()
        receipt = proof["reply"]
        native = artifacts.read(plan.project_id, receipt["artifact_ref"], receipt["artifact_hash"])
        checked = validate_batch_reply(plan, sequence, proof["claim"], native)
        if (acceptance_digest(native) != receipt["artifact_hash"]
                or any(checked[key] != receipt[key] for key in checked)):
            raise TestDesignResultIntegrityError("batch recovery private archive differs from its fixed native receipt")
        current()
        responses.append((receipt["batch_digest"], native["content"]))
    proposal = merge_batch_proposals(prepared, batch_plan, responses, aggregate=True)
    current()
    return proposal
