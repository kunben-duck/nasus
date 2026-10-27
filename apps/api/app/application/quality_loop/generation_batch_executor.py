"""Native batch collection only; aggregate result commit owns completion."""
import asyncio
from dataclasses import asdict
import time

from .generation_batch_ledger import batch_reservation
from .generation_batch_planning import batch_messages, validate_batch_output
from .generation_execution_inputs import GENERATION_TIMEOUT_SECONDS, GenerationExecutionSelection
from .generation_executor import GenerationNativeModelPort, GenerationOutcomeUnknown
from .test_design_results import GenerationResultRequest, TestDesignResultIntegrityError


class GenerationBatchExecutorApplicationService:
    """Requires an externally maintained canonical lease; never terminates it."""

    def __init__(self, receipts, provider: GenerationNativeModelPort, *, results=None):
        self.receipts, self.provider = receipts, provider
        self.results = results

    def _prepared(self, plan, lease):
        self.receipts.leases.require_lease(lease)
        selection = GenerationExecutionSelection(**plan.request.selection().model_dump(mode="json"),
            model_config_id=plan.request.model_config_id, budget=plan.request.execution.budget)
        prepared = self.receipts.planning.prepare(selection)
        expected = batch_reservation(prepared, invocation_id=plan.invocation_id, actor_id=plan.actor_id)
        if expected != plan:
            raise TestDesignResultIntegrityError("native batch plan dependencies changed; do not send another request")
        self.receipts.leases.require_lease(lease)
        return selection, prepared

    def _model(self, plan, lease):
        self._prepared(plan, lease)
        model = self.receipts.planning.profiles.resolve(plan.request.model_config_id)
        if asdict(model.binding) != plan.model_binding.model_dump(mode="json"):
            raise TestDesignResultIntegrityError("native batch model differs from the confirmed configuration")
        self.receipts.leases.require_lease(lease)
        return model

    async def collect(self, request, *, lease, aggregate=False):
        request = GenerationResultRequest.model_validate(request.model_dump(mode="json"))
        plan = await asyncio.to_thread(self.receipts.reserve, request, lease=lease)
        selected, prepared = await asyncio.to_thread(self._prepared, plan, lease)
        for sequence, batch in enumerate(prepared.plan["batches"]):
            replay = await asyncio.to_thread(self.receipts.read, request, lease=lease)
            if sequence < len(replay["responses"]):
                digest, content = replay["responses"][sequence]
                if digest != batch["batch_digest"]:
                    raise TestDesignResultIntegrityError("archived native response belongs to another batch")
                validate_batch_output(prepared.input, batch, content)
                continue
            if replay["budget"]["unknown_calls"]:
                raise GenerationOutcomeUnknown("reserved batch outcome is unknown; never resend or skip it")
            claim = await asyncio.to_thread(self.receipts.claim, request, sequence, lease=lease)
            # A pre-egress refusal retains the claim but is not a Provider call.
            model = await asyncio.to_thread(self._model, plan, lease)
            system, content = batch_messages(batch)
            started, reply = time.monotonic(), None
            try:
                reply = await asyncio.wait_for(self.provider.generate(system, content, model,
                    max_output_tokens=request.execution.budget.max_output_tokens_per_call), GENERATION_TIMEOUT_SECONDS)
                await asyncio.to_thread(self.receipts.archive_reply, request, sequence, reply, lease=lease,
                    latency_ms=int((time.monotonic() - started) * 1000))
            except BaseException:
                call = self.receipts._call(plan, claim, reply, outcome="error",
                    latency_ms=int((time.monotonic() - started) * 1000))
                await asyncio.to_thread(self.receipts.repository.record_failure, plan, sequence, call)
                raise
            # Archive charged responses even when invalid, but stop before any
            # later native request rather than spending the remaining envelope.
            validate_batch_output(prepared.input, batch, reply.content)
        replay = await asyncio.to_thread(self.receipts.read, request, lease=lease)
        options = {"aggregate": True} if aggregate else {}
        checked = await asyncio.to_thread(self.receipts.planning.check_outputs, selected,
            expected_planning_digest=prepared.digest, responses=replay["responses"], **options)
        await asyncio.to_thread(self.receipts.leases.require_lease, lease)
        return {**checked, "budget": replay["budget"], "aggregate_result_committed": False}

    async def execute(self, request, *, lease):
        if self.results is None:
            raise TestDesignResultIntegrityError("native batch execution requires its atomic aggregate result port")
        await asyncio.to_thread(self.receipts.leases.require_lease, lease)
        prior = await asyncio.to_thread(self.results.repository.by_invocation, request.project_id, lease.invocation_id)
        if prior is None:
            await self.collect(request, lease=lease, aggregate=True)
        # A committed result replays its ledger instead of reserving/sending again.
        return await asyncio.to_thread(self.results.commit, request, lease=lease)
