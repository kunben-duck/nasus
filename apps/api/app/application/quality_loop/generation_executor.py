"""Budgeted native generation with durable no-resend reservations."""
import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import time
from typing import Protocol
from uuid import uuid4

from .generation_budget import reserve_generation_budget, verify_generation_usage, GenerationBudgetInvalid, GenerationModelPolicy
from .generation_batch_planning import GenerationBatchPlanningApplicationService
from .generation_batch_ledger import batch_execution_request, batch_execution_preview
from .generation_execution_inputs import (
    GENERATION_REPLY_SCHEMA, GENERATION_TIMEOUT_SECONDS, GenerationExecutionConsent,
    GenerationExecutionSelection, generation_messages, generation_plan_digest,
)
from .test_design_results import GENERATION_TOOL, GenerationResultRequest, TestDesignResultIntegrityError, response_digest
from .generation_job_ports import GenerationRecoveryRequest
from ...domain.platform.llm_call import LLMCall
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.test_design_generation import TestDesignGenerationInvalid


class GenerationOutcomeUnknown(RuntimeError):
    pass


@dataclass(frozen=True)
class NativeGenerationReply:
    content: str
    input_tokens: int
    output_tokens: int
    usage_source: str


class GenerationNativeModelPort(Protocol):
    async def generate(self, system, content, model, *, max_output_tokens) -> NativeGenerationReply: ...


class GenerationSourceInventoryPort(Protocol):
    def bindings(self, prepared): ...


class GenerationExecutionRepositoryPort(Protocol):
    def get(self, project_id, invocation_id): ...
    def reserve(self, request, payload, *, require_current): ...
    def record_reply(self, request, payload, artifact_ref, artifact_hash, call, *, require_current): ...
    def record_failure(self, request, invocation_id, call): ...


class GenerationExecutorApplicationService:
    def __init__(self, generation, results, profiles, policies, authorization, sources: GenerationSourceInventoryPort,
                 provider: GenerationNativeModelPort, repository: GenerationExecutionRepositoryPort, artifacts):
        self.generation, self.results, self.profiles, self.policies = generation, results, profiles, policies
        self.authorization, self.sources, self.provider, self.repository, self.artifacts = authorization, sources, provider, repository, artifacts
        self.batch_planning = GenerationBatchPlanningApplicationService(generation, profiles, policies, authorization, sources)
        self.batch_executor = None

    def _access(self, project_id):
        access = self.authorization.scope(project_id)
        if access.effective_project_role not in {"project_admin", "platform_admin"}:
            raise PermissionError("generation source egress requires a project administrator")
        return access

    def _prepare(self, selection):
        selection = GenerationExecutionSelection.model_validate(selection.model_dump(mode="json"))
        access = self._access(selection.project_id)
        prepared = self.generation.prepare(selection.selection())
        model = self.profiles.resolve(selection.model_config_id)
        counter = self.policies.resolve(model.binding)
        policy = counter.policy.model_dump(mode="json")
        binding = asdict(model.binding)
        sources = self.sources.bindings(prepared)
        for ident in sources:
            access.require_binding(ident)
        system, content = generation_messages(prepared)
        reservation = reserve_generation_budget(counter.policy, selection.budget, [counter.count(system, content)])
        consent = GenerationExecutionConsent(policy_digest=acceptance_digest(policy), source_binding_ids=sources,
            source_scope_digest=access.fingerprint, budget=selection.budget,
            plan_digest=generation_plan_digest(prepared, binding, policy, sources, access.fingerprint,
                selection.budget.model_dump(mode="json"), reservation))
        request = GenerationResultRequest(**selection.selection().model_dump(mode="json"), input_digest=prepared["input_digest"],
            model_config_id=model.binding.config_id, model_config_digest=model.binding.config_digest, execution=consent)
        self.authorization.require_current(access)
        return access, prepared, model, counter.policy, reservation, request

    def preview(self, selection):
        _, prepared, model, policy, reservation, request = self._prepare(selection)
        return {"request": request.model_dump(mode="json"), "provider": model.binding.provider, "model_name": model.binding.model_name,
            "destination": model.binding.base_url, "policy": policy.model_dump(mode="json"), "reservation": reservation,
            "input_bytes": len(generation_messages(prepared)[1].encode()), "timeout_seconds": GENERATION_TIMEOUT_SECONDS,
            "call_count": 1, "batching": "one_complete_input_no_truncation", "generation_authorized": False,
            "execution_authorized": False, "remaining_gates": ["fresh_user_confirmation", "durable_call_reservation"]}

    def preview_batches(self, selection):
        return batch_execution_preview(self.batch_planning.prepare(selection))

    @staticmethod
    def _selection(request):
        return GenerationExecutionSelection(**request.selection().model_dump(mode="json"),
            model_config_id=request.model_config_id, budget=request.execution.budget)

    def _read_reply(self, request, stored, access):
        actor_id = access.actor_id
        if stored["reservation"]["request"] != request.model_dump(mode="json") or stored["reservation"]["actor_id"] != actor_id:
            raise TestDesignResultIntegrityError("generation reservation was rebound")
        if not stored.get("reply"):
            raise GenerationOutcomeUnknown("generation call already reserved; never resend an uncertain provider outcome")
        for binding_id in request.execution.source_binding_ids:
            access.require_binding(binding_id)
        self.authorization.require_current(access)
        reply = stored["reply"]
        payload = self.artifacts.read(request.project_id, reply["artifact_ref"], reply["artifact_hash"])
        if (acceptance_digest(payload) != reply["artifact_hash"] or payload.get("schema") != GENERATION_REPLY_SCHEMA
                or payload.get("project_id") != request.project_id or payload.get("request") != request.model_dump(mode="json")
                or payload.get("invocation_id") != stored["reservation"]["invocation_id"]
                or payload.get("actor_id") != actor_id or payload.get("call_id") != stored["reservation"]["call_id"]
                or response_digest(payload["content"]) != reply["response_hash"]):
            raise TestDesignResultIntegrityError("generation response archive mismatch")
        usage = payload.get("usage", {})
        policy = GenerationModelPolicy.model_validate(stored["reservation"]["policy"])
        expected_usage = verify_generation_usage(policy, request.execution.budget, usage.get("input_tokens"), usage.get("output_tokens"))
        if usage != expected_usage or reply.get("usage") != expected_usage:
            raise TestDesignResultIntegrityError("generation response usage archive mismatch")
        self.authorization.require_current(access)
        return payload

    async def execute(self, request: GenerationResultRequest, *, invocation_id, require_work=None, work_lease=None):
        request = GenerationResultRequest.model_validate(request.model_dump(mode="json"))
        if request.execution is None:
            raise GenerationBudgetInvalid("generation requires explicit destination/source/token/cost consent")
        if require_work:
            await asyncio.to_thread(require_work)
        access = self._access(request.project_id)
        stored = await asyncio.to_thread(self.repository.get, request.project_id, invocation_id)
        if self.batch_executor is not None:
            batch = await asyncio.to_thread(self.batch_executor.receipts.repository.get_plan, request.project_id, invocation_id)
            matches = batch is not None
            if not matches and stored is None and work_lease is not None:
                try:
                    planned = await asyncio.to_thread(self.batch_planning.prepare, self._selection(request))
                    matches = batch_execution_request(planned) == request
                except GenerationBudgetInvalid:
                    # A legacy complete-input plan is a different confirmed hash.
                    # No fallback is allowed once any batch budget exists.
                    matches = False
            if matches:
                if stored is not None or work_lease is None or (work_lease.project_id, work_lease.invocation_id) != (request.project_id, invocation_id):
                    raise TestDesignResultIntegrityError("batch execution requires its exact canonical lease and no single-call reservation")
                return await self.batch_executor.execute(request, lease=work_lease)
        if stored is not None:
            payload = await asyncio.to_thread(self._read_reply, request, stored, access)
            # Only replay an archived provider response, never repeat the call.
            return await asyncio.to_thread(self.results.commit, request, invocation_id=invocation_id,
                call_id=payload["call_id"], content=payload["content"], require_work=require_work)
        access, prepared, model, policy, reservation, expected = await asyncio.to_thread(self._prepare, self._selection(request))
        if expected != request:
            raise TestDesignGenerationInvalid("generation consent changed; preview and confirm again")

        def current():
            if require_work:
                require_work()
            self.authorization.require_current(access)
            _, _, _, _, _, fresh = self._prepare(self._selection(request))
            if fresh != request:
                raise TestDesignGenerationInvalid("generation dependencies changed before egress")
            if require_work:
                require_work()

        call_id = str(uuid4())
        reserved = {"schema": "nasus.test-design-call-reservation.v1", "project_id": request.project_id,
            "invocation_id": invocation_id, "actor_id": access.actor_id, "call_id": call_id,
            "request": request.model_dump(mode="json"), "policy": policy.model_dump(mode="json"),
            "model_binding": asdict(model.binding), "reservation": reservation, "reserved_at": datetime.now(timezone.utc).isoformat()}
        await asyncio.to_thread(self.repository.reserve, request, reserved, require_current=current)
        await asyncio.to_thread(current)
        system, content = generation_messages(prepared)
        started, reply = time.monotonic(), None
        try:
            reply = await asyncio.wait_for(self.provider.generate(system, content, model,
                max_output_tokens=request.execution.budget.max_output_tokens_per_call), timeout=GENERATION_TIMEOUT_SECONDS)
            if reply.usage_source != "provider":
                raise GenerationBudgetInvalid("native generation lacks provider usage; retain reservation")
            usage = verify_generation_usage(policy, request.execution.budget, reply.input_tokens, reply.output_tokens)
            await asyncio.to_thread(current)
            payload = {"schema": GENERATION_REPLY_SCHEMA, "project_id": request.project_id, "invocation_id": invocation_id,
                "actor_id": access.actor_id, "request": request.model_dump(mode="json"), "call_id": call_id,
                "content": reply.content, "usage": usage}
            ref, digest = await asyncio.to_thread(self.artifacts.put, request.project_id, payload)
            call = self._call(request, model, call_id, invocation_id, started, reply, outcome="success")
            await asyncio.to_thread(self.repository.record_reply, request, payload, ref, digest, call, require_current=current)
        except BaseException:
            # Preserve a charged/unknown reservation on timeout, cancellation,
            # invalid usage or persistence failure. No retry/fallback is legal.
            call = self._call(request, model, call_id, invocation_id, started, reply, outcome="error")
            await asyncio.to_thread(self.repository.record_failure, request, invocation_id, call)
            raise
        return await asyncio.to_thread(self.results.commit, request, invocation_id=invocation_id,
            call_id=call_id, content=reply.content, require_work=require_work)

    async def recover(self, recovery: GenerationRecoveryRequest, request, *, authority_invocation_id, require_work=None):
        """An explicit new command may finalize a failed call, never resend it."""
        if require_work:
            await asyncio.to_thread(require_work)
        access = self._access(recovery.project_id)
        stored = await asyncio.to_thread(self.repository.get, recovery.project_id, recovery.invocation_id)
        if (stored is None or not stored.get("reply") or recovery.project_id != request.project_id
                or recovery.request_hash != acceptance_digest(request.model_dump(mode="json"))
                or recovery.reply_artifact_hash != stored["reply"]["artifact_hash"]
                or recovery.response_hash != stored["reply"]["response_hash"]):
            raise TestDesignResultIntegrityError("generation recovery requires the exact archived native reply")
        await asyncio.to_thread(self.results.repository.require_recovery, request, recovery.invocation_id,
            access.actor_id, authority_invocation_id)
        payload = await asyncio.to_thread(self._read_reply, request, stored, access)
        return await asyncio.to_thread(self.results.commit, request, invocation_id=recovery.invocation_id,
            call_id=payload["call_id"], content=payload["content"], authority_invocation_id=authority_invocation_id, require_work=require_work)

    @staticmethod
    def _call(request, model, call_id, invocation_id, started, reply, *, outcome):
        valid_usage = (reply is not None and reply.usage_source == "provider"
            and type(reply.input_tokens) is int and type(reply.output_tokens) is int
            and reply.input_tokens >= 0 and reply.output_tokens >= 0)
        return LLMCall(id=call_id, occurred_at=datetime.now(timezone.utc), route="chat", purpose=GENERATION_TOOL,
            provider=model.binding.provider, model_name=model.binding.model_name, selected_provider=model.binding.provider,
            selected_model_name=model.binding.model_name, runtime_mode="live", outcome=outcome,
            reason="native_reply_archived" if outcome == "success" else "reserved_call_failed_or_unknown_no_resend",
            project_id=request.project_id, tool_invocation_id=invocation_id, prompt_id="nasus.test-design-generation", prompt_version="v1",
            model_calls=1, request_hash=acceptance_digest(request.model_dump(mode="json")), response_hash=response_digest(reply.content) if reply else "",
            input_token_count=reply.input_tokens if valid_usage else 0, output_token_count=reply.output_tokens if valid_usage else 0,
            usage_source="provider" if valid_usage else "none", latency_ms=int((time.monotonic() - started) * 1000))
