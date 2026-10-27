"""Three real source ACs/PG, native HTTP protocol fixtures, no external calls."""
import asyncio
import json

import httpx
import pytest
from sqlalchemy import select

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.generation_batch_executor import GenerationBatchExecutorApplicationService
from apps.api.app.application.quality_loop.generation_executor import GenerationOutcomeUnknown
from apps.api.app.infrastructure.llm.test_design_model import HTTPTestDesignModel, TestDesignModelFailure
from apps.api.app.infrastructure.persistence.db_models import LLMCallRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_generation_batch_ledger_api import (
    ledger, execution, design_scope, publication, documents, evidence_api, view, count,
    Plan, Claim, BatchReply, Reservation, Reply, Result,
)
from apps.api.tests.test_generation_batches import responses_for
from apps.api.tests.test_semantic_link_model import native_reply


@pytest.mark.parametrize("documents", [3], indirect=True)
@pytest.mark.parametrize("failure_sequence", [None, 0, 1])
def test_native_batch_collection_and_resume_use_exact_pg_receipts_without_duplicate_egress(ledger, failure_sequence):
    v = ledger
    sent = []
    outputs = dict(responses_for(v["batch_planned"].input, v["batch_planned"].plan))
    def handle(request):
        wire = json.loads(request.content)
        batch = json.loads(wire["messages"][-1]["content"])
        sent.append(batch["batch_digest"])
        assert batch == v["batch_planned"].plan["batches"][len(sent) - 1]
        assert wire["max_tokens"] == v["batch_request"].execution.budget.max_output_tokens_per_call
        if failure_sequence == len(sent) - 1:
            return httpx.Response(503, text="explicit provider failure fixture; not external")
        return httpx.Response(200, json=native_reply("openai_compatible", outputs[batch["batch_digest"]]))
    service = GenerationBatchExecutorApplicationService(v["batch_receipts"],
        HTTPTestDesignModel(transport=httpx.MockTransport(handle)))
    with actor_scope(UserProfile.model_validate(v["owner"])):
        if failure_sequence is None:
            checked = asyncio.run(service.collect(v["batch_request"], lease=v["batch_lease"]))
            assert checked["proposal"]["coverage"]["obligation_denominator"] == len(v["batch_planned"].input["obligations"])
            assert checked["proposal"]["coverage"]["passed_count"] == 0 and not checked["aggregate_result_committed"]
            assert asyncio.run(service.collect(v["batch_request"], lease=v["batch_lease"])) == checked
            assert len(sent) == 3
        else:
            with pytest.raises(TestDesignModelFailure):
                asyncio.run(service.collect(v["batch_request"], lease=v["batch_lease"]))
            with pytest.raises(GenerationOutcomeUnknown):
                asyncio.run(service.collect(v["batch_request"], lease=v["batch_lease"]))
            assert len(sent) == failure_sequence + 1
        replay = view(v)
        completed = 3 if failure_sequence is None else failure_sequence
        assert replay["budget"]["claimed_calls"] == len(sent)
        assert replay["budget"]["archived_calls"] == completed
        assert replay["budget"]["unknown_calls"] == int(failure_sequence is not None)
        assert replay["budget"]["known_input_tokens"] == completed * 123
        assert replay["budget"]["known_output_tokens"] == completed * 45
        assert replay["budget"]["reserved_tokens"] == 3 * 136192 and not replay["budget"]["reservation_released"]
    assert count(v, Plan) == 1 and count(v, Claim) == len(sent) and count(v, BatchReply) == completed
    assert count(v, Reservation) == count(v, Reply) == count(v, Result) == 0 and not v["native_calls"]
    with session_scope() as session:
        calls = session.scalars(select(LLMCallRecord).where(
            LLMCallRecord.tool_invocation_id == v["batch_invocation_id"])).all()
        assert len(calls) == len(sent) and len({call.request_hash for call in calls}) == len(sent)
        assert all(call.model_calls == 1 and call.prompt_version == "batch-v1" for call in calls)
        assert sum(call.outcome == "error" for call in calls) == int(failure_sequence is not None)
    assert v["jobs"].repository.command(v["batch_invocation_id"])[1] == "running"
    assert not v["batch_renewal_errors"]
