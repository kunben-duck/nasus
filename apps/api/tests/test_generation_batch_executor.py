"""Unit ports are explicit fixtures; PG/MinIO behavior is tested separately."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.generation_batch_executor import GenerationBatchExecutorApplicationService
from apps.api.app.application.quality_loop.generation_batch_planning import merge_batch_proposals
from apps.api.app.application.quality_loop.generation_batch_receipts import GenerationBatchReceiptApplicationService
from apps.api.app.application.quality_loop.generation_budget import GenerationBudgetInvalid, verify_generation_usage
from apps.api.app.application.quality_loop.generation_executor import GenerationOutcomeUnknown, NativeGenerationReply
from apps.api.app.application.quality_loop.generation_work_lease import GenerationLeaseLost
from apps.api.app.application.quality_loop.test_design_results import TestDesignResultIntegrityError
from apps.api.app.domain.quality_loop.test_design_generation import TestDesignGenerationInvalid
from apps.api.tests.test_generation_batch_ledger import prepared_ledger
from apps.api.tests.test_generation_batches import responses_for
from apps.api.tests.test_semantic_link_model import resolved


def collector():
    prepared, plan = prepared_ledger()
    failures, claims, responses, sent = [], [], [], []
    model = resolved()

    class Leases:
        lost = False
        def require_lease(self, lease):
            if self.lost:
                raise GenerationLeaseLost("explicit fixture lease loss")

    leases = Leases()
    planning = SimpleNamespace(profiles=SimpleNamespace(resolve=lambda ident: model), prepare=lambda selection: prepared)

    def check(selection, *, expected_planning_digest, responses):
        assert expected_planning_digest == prepared.digest
        return merge_batch_proposals(prepared.input, prepared.plan, responses)

    planning.check_outputs = check

    class Receipts:
        repository = SimpleNamespace(record_failure=lambda plan, sequence, call: failures.append(call))
        _call = staticmethod(GenerationBatchReceiptApplicationService._call)
        def reserve(self, request, *, lease):
            leases.require_lease(lease)
            assert request == plan.request
            return plan
        def read(self, request, *, lease):
            leases.require_lease(lease)
            return {"responses": deepcopy(responses), "budget": {
                "unknown_calls": len(claims) - len(responses), "reservation_released": False}}
        def claim(self, request, sequence, *, lease):
            leases.require_lease(lease)
            assert sequence == len(claims) == len(responses)
            value = {"call_id": "call-" + str(sequence), "request_hash": plan.batches[sequence].messages_hash}
            claims.append(value)
            return value
        def archive_reply(self, request, sequence, reply, *, lease, latency_ms):
            leases.require_lease(lease)
            if reply.usage_source != "provider":
                raise GenerationBudgetInvalid("explicit native usage fixture is unavailable")
            verify_generation_usage(plan.policy, request.execution.budget, reply.input_tokens, reply.output_tokens)
            assert sequence == len(responses) and latency_ms >= 0
            responses.append((plan.batches[sequence].batch_digest, reply.content))

    receipts = Receipts()
    receipts.planning, receipts.leases = planning, leases
    outputs = dict(responses_for(prepared.input, prepared.plan))

    class Provider:
        failure = None
        usage_source = "provider"
        callback = None
        corrupt = False
        async def generate(self, system, content, selected_model, *, max_output_tokens):
            batch = json.loads(content)
            assert selected_model is model and max_output_tokens == plan.request.execution.budget.max_output_tokens_per_call
            assert "batch_digest" in system and batch == prepared.plan["batches"][len(sent)]
            sent.append(batch["batch_digest"])
            if self.callback:
                await self.callback()
            if self.failure:
                raise self.failure
            output = "{}" if self.corrupt else outputs[batch["batch_digest"]]
            return NativeGenerationReply(output, 100, 50, self.usage_source)

    provider = Provider()
    service = GenerationBatchExecutorApplicationService(receipts, provider)
    return SimpleNamespace(service=service, request=plan.request, lease=SimpleNamespace(invocation_id=plan.invocation_id),
        plan=plan, prepared=prepared, planning=planning, leases=leases, receipts=receipts, provider=provider,
        sent=sent, failures=failures, claims=claims, responses=responses, model=model)


def collect(v):
    return asyncio.run(v.service.collect(v.request, lease=v.lease))


def test_native_batch_collector_preserves_full_denominator_and_replays_without_resending():
    v = collector()
    checked = collect(v)
    assert len(v.sent) == len(v.claims) == len(v.responses) == 3 and not v.failures
    assert checked["proposal"]["coverage"]["obligation_denominator"] == len(v.prepared.input["obligations"])
    assert checked["proposal"]["coverage"]["passed_count"] == 0
    assert not checked["aggregate_result_committed"] and not checked["generation_authorized"]
    assert collect(v) == checked and len(v.sent) == 3


@pytest.mark.parametrize("phase", ["provider_failure", "missing_usage", "lost_lease"])
def test_native_batch_failure_preserves_unknown_claim_and_never_sends_another_batch(phase):
    v = collector()
    if phase == "provider_failure":
        v.provider.failure = RuntimeError("explicit provider transport failure")
    elif phase == "missing_usage":
        v.provider.usage_source = "none"
    else:
        async def lose():
            v.leases.lost = True
        v.provider.callback = lose
    with pytest.raises((RuntimeError, GenerationBudgetInvalid, GenerationLeaseLost)):
        collect(v)
    assert len(v.sent) == len(v.claims) == len(v.failures) == 1 and not v.responses
    assert v.failures[0].model_calls == 1 and v.failures[0].outcome == "error"
    v.leases.lost = False
    with pytest.raises(GenerationOutcomeUnknown):
        collect(v)
    assert len(v.sent) == 1


def test_invalid_archived_reply_is_revalidated_and_stops_before_next_native_request():
    v = collector()
    v.provider.corrupt = True
    with pytest.raises(ValueError):
        collect(v)
    assert len(v.sent) == len(v.responses) == 1 and not v.failures
    with pytest.raises(ValueError):
        collect(v)
    assert len(v.sent) == 1


def test_changed_model_is_blocked_after_claim_and_never_consumes_a_different_route():
    v = collector()
    v.planning.profiles.resolve = lambda ident: replace(v.model, binding=replace(v.model.binding, model_name="unconfirmed"))
    with pytest.raises(TestDesignResultIntegrityError, match="confirmed configuration"):
        collect(v)
    assert not v.sent and len(v.claims) == 1 and not v.failures


def test_changed_prepared_dependencies_stop_before_claim_or_provider():
    v = collector()
    value = deepcopy(v.prepared.preview)
    value["messages_hashes"][0] = value["messages_hashes"][1]
    v.planning.prepare = lambda selection: replace(v.prepared, preview=value)
    with pytest.raises((TestDesignResultIntegrityError, TestDesignGenerationInvalid)):
        collect(v)
    assert not v.claims and not v.sent and not v.failures


def test_cancellation_while_provider_waits_retains_exact_unknown_call_and_no_replay():
    v = collector()
    async def scenario():
        entered = asyncio.Event()
        async def wait():
            entered.set()
            await asyncio.Event().wait()
        v.provider.callback = wait
        task = asyncio.create_task(v.service.collect(v.request, lease=v.lease))
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(scenario())
    assert len(v.sent) == len(v.claims) == len(v.failures) == 1 and not v.responses
    with pytest.raises(GenerationOutcomeUnknown):
        collect(v)
    assert len(v.sent) == 1
