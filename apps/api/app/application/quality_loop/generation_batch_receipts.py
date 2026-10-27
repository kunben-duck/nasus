"""Private, source-authorized batch receipt operations for a future native executor."""
from datetime import datetime, timezone
from typing import Protocol

from .generation_batch_ledger import BATCH_REPLY_SCHEMA, batch_execution_request, batch_reservation, validate_batch_reply
from .generation_execution_inputs import GenerationExecutionSelection
from .generation_executor import GenerationOutcomeUnknown
from .generation_work_lease import GenerationLeaseLost
from .test_design_results import GenerationResultRequest, TestDesignResultIntegrityError, response_digest
from .generation_budget import verify_generation_usage
from ...domain.platform.llm_call import LLMCall
from ...domain.quality_loop.acceptance_specification import acceptance_digest


class GenerationBatchLedgerPort(Protocol):
    def reserve(self, plan, *, lease, require_current): ...
    def claim_call(self, plan, sequence, *, lease, require_current): ...
    def record_reply(self, plan, sequence, payload, artifact_ref, artifact_hash, call, *, lease, require_current): ...
    def record_failure(self, plan, sequence, call): ...
    def read(self, plan, *, lease, require_current): ...


class GenerationBatchReceiptApplicationService:
    """No public import endpoint, native I/O, coverage commit or new lifecycle."""
    def __init__(self, planning, authorization, leases, repository: GenerationBatchLedgerPort, artifacts):
        self.planning, self.authorization, self.leases = planning, authorization, leases
        self.repository, self.artifacts = repository, artifacts

    def _prepare(self, request, lease):
        request = GenerationResultRequest.model_validate(request.model_dump(mode="json"))
        if request.execution is None or request.project_id != lease.project_id:
            raise GenerationLeaseLost("batch receipt operations require exact project, consent and worker ownership")
        self.leases.require_lease(lease)
        access = self.authorization.scope(request.project_id)
        selection = GenerationExecutionSelection(**request.selection().model_dump(mode="json"),
            model_config_id=request.model_config_id, budget=request.execution.budget)
        planned = self.planning.prepare(selection)
        if request != batch_execution_request(planned):
            raise TestDesignResultIntegrityError("batch dependencies differ from the exact confirmed request")
        plan = batch_reservation(planned, invocation_id=lease.invocation_id, actor_id=access.actor_id)
        self.authorization.require_current(access)
        self.leases.require_lease(lease)
        return plan

    def _current(self, request, plan, lease):
        def require_current():
            if self._prepare(request, lease) != plan:
                raise TestDesignResultIntegrityError("batch dependencies changed before transactional submission")
        return require_current

    def reserve(self, request, *, lease):
        plan = self._prepare(request, lease)
        self.repository.reserve(plan, lease=lease, require_current=self._current(request, plan, lease))
        return plan

    def _read(self, request, plan, lease):
        view = self.repository.read(plan, lease=lease, require_current=self._current(request, plan, lease))
        contents = []
        for receipt in view["replies"]:
            sequence = receipt["sequence"]
            payload = self.artifacts.read(plan.project_id, receipt["artifact_ref"], receipt["artifact_hash"])
            checked = validate_batch_reply(plan, sequence, view["calls"][sequence], payload)
            if (acceptance_digest(payload) != receipt["artifact_hash"]
                    or any(checked[key] != receipt[key] for key in checked)):
                raise TestDesignResultIntegrityError("batch private reply archive differs from its provider receipt")
            contents.append((receipt["batch_digest"], payload["content"]))
        self._current(request, plan, lease)()
        return {**view, "responses": contents}

    def read(self, request, *, lease):
        return self._read(request, self._prepare(request, lease), lease)

    def claim(self, request, sequence, *, lease):
        plan = self._prepare(request, lease)
        view = self._read(request, plan, lease)
        if view["budget"]["unknown_calls"]:
            raise GenerationOutcomeUnknown("a prior native batch outcome is unknown; never resend or start another batch")
        return self.repository.claim_call(plan, sequence, lease=lease, require_current=self._current(request, plan, lease))

    def archive_reply(self, request, sequence, reply, *, lease, latency_ms):
        plan = self._prepare(request, lease)
        if type(sequence) is not int or not 0 <= sequence < len(plan.batches):
            raise TestDesignResultIntegrityError("native batch sequence is outside the complete plan")
        if reply.usage_source != "provider":
            raise TestDesignResultIntegrityError("native batch requires authoritative provider usage")
        view = self._read(request, plan, lease)
        if sequence >= len(view["calls"]):
            raise TestDesignResultIntegrityError("native batch has not been reserved")
        claim = view["calls"][sequence]
        usage = verify_generation_usage(plan.policy, request.execution.budget, reply.input_tokens, reply.output_tokens)
        payload = {"schema": BATCH_REPLY_SCHEMA, "project_id": plan.project_id, "invocation_id": plan.invocation_id,
            "actor_id": plan.actor_id, "request": request.model_dump(mode="json"), "plan_digest": plan.plan_digest,
            "sequence": sequence, "batch_digest": plan.batches[sequence].batch_digest,
            "messages_hash": plan.batches[sequence].messages_hash, "call_id": claim["call_id"],
            "content": reply.content, "usage": usage}
        validate_batch_reply(plan, sequence, claim, payload)
        ref, digest = self.artifacts.put(plan.project_id, payload)
        call = self._call(plan, claim, reply, outcome="success", latency_ms=latency_ms)
        return self.repository.record_reply(plan, sequence, payload, ref, digest, call, lease=lease,
            require_current=self._current(request, plan, lease))

    @staticmethod
    def _call(plan, claim, reply, *, outcome, latency_ms):
        if type(latency_ms) is not int or latency_ms < 0:
            raise ValueError("native batch latency must be a non-negative integer")
        valid_usage = reply is not None and reply.usage_source == "provider" and all(
            type(value) is int and value >= 0 for value in (reply.input_tokens, reply.output_tokens))
        binding = plan.model_binding
        return LLMCall(id=claim["call_id"], occurred_at=datetime.now(timezone.utc), route="chat", purpose="quality.test_design.generate",
            provider=binding.provider, model_name=binding.model_name, selected_provider=binding.provider,
            selected_model_name=binding.model_name, runtime_mode="live", outcome=outcome,
            reason="native_batch_reply_archived" if outcome == "success" else "reserved_batch_failed_or_unknown_no_resend",
            project_id=plan.project_id, tool_invocation_id=plan.invocation_id,
            prompt_id="nasus.test-design-generation", prompt_version="batch-v1", model_calls=1,
            request_hash=claim["request_hash"], response_hash=response_digest(reply.content) if reply else "",
            input_token_count=reply.input_tokens if valid_usage else 0, output_token_count=reply.output_tokens if valid_usage else 0,
            usage_source="provider" if valid_usage else "none", latency_ms=latency_ms)
