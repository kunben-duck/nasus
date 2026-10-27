"""Real PG/canonical commands; the native embedding endpoint and workflow dispatch are explicit fixtures."""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.system_image.context_retrieval_ports import CONTEXT_RETRIEVE_TOOL, CONTEXT_CANCEL_TOOL, CONTEXT_RETRIEVAL_QUERY_TOOL, ContextRetrievalRequest
from apps.api.app.application.system_image.index_ports import IndexEmbeddingFailure
from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.infrastructure.persistence.context_retrieval_models import ContextRetrievalPlanRecord as Plan, ContextRetrievalCallRecord as Call
from apps.api.app.infrastructure.persistence.context_retrieval_models import ContextRetrievalBatchRecord as Batch, ContextRetrievalResultRecord as Result
from apps.api.app.infrastructure.persistence.frozen_index_models import FrozenRetrievalRecord as Trace
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, UserIdentityRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_frozen_indexes_api import indexed, publication, documents, evidence_api, grant_member, publish
from apps.api.tests.test_context_retrieval_plan_api import planned
from apps.api.tests.test_semantic_evaluations_api import invoke, confirm, completed, count
from apps.api.tests.test_published_context_packs import request_for, preview_response
from apps.api.tests.test_context_packs_api import archive, read
from apps.api.app.domain.system_image.context_partition import INDEXED_CONTEXT_POLICY


@pytest.fixture
def retrieval(indexed, monkeypatch):
    v = indexed
    _, result, _ = planned(v)
    preview = result["result"]["context_retrieval_preview"]
    request = {**preview["request"], "expected_plan_digest": preview["plan_digest"]}
    jobs = app.state.container.context_retrieval_jobs
    workflow = SimpleNamespace(start=AsyncMock(return_value=True), cancel=AsyncMock())
    monkeypatch.setattr(jobs, "workflow", workflow)
    v.update(retrieval_request=request, retrieval_preview=preview, jobs=jobs, workflow=workflow,
        calls_before=len(v["index_calls"]))
    return v


def queue(v, **changes):
    response = invoke(v, CONTEXT_RETRIEVE_TOOL, {**v["retrieval_request"], **changes}, key=uuid4().hex)
    assert response.status_code == 200 and response.json()["status"] == "waiting_confirmation", response.text
    accepted = confirm(v, response.json())
    assert accepted.status_code == 200 and accepted.json()["status"] == "running", accepted.text
    return accepted.json()["id"]


def run(v, ident):
    return asyncio.run(v["jobs"].run(ident))


def result(v, ident):
    return v["client"].get(v["image_url"] + f"/context-retrievals/{ident}", headers=v["headers"])


def test_confirmation_returns_before_provider_and_atomic_result_feeds_v5(retrieval):
    v = retrieval
    ident = queue(v, confirmed_actor_id="forged", confirmed_by_user=True)
    assert len(v["index_calls"]) == v["calls_before"] and count(v, Plan) == 0
    v["workflow"].start.assert_awaited_once_with(ident)
    assert result(v, ident).status_code == 404
    assert run(v, ident) == "completed"
    response = result(v, ident)
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store", response.text
    body = response.json()
    assert len(body["retrieval_bindings"]) == body["query_count"] == 1
    assert count(v, Plan) == count(v, Call) == count(v, Batch) == count(v, Result) == count(v, Trace) == 1
    assert len(v["index_calls"]) == v["calls_before"] + 1
    observed = completed(invoke(v, CONTEXT_RETRIEVAL_QUERY_TOOL, {"project_id": v["project_id"], "invocation_id": ident}))
    assert observed["result"]["context_retrieval_result"] == body
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(observed["id"], v["project_id"]) == body
    assert all(token not in response.text for token in ("private-index-key", "Empty input", "s3://", "local-object://"))
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, ident)
        assert row.status == "completed" and row.input_payload["confirmed_actor_id"] == v["owner"]["id"]
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == ident)).all()
        assert sum(e.event_type == "system_image.context_retrieval.completed" for e in events) == 1
    assert run(v, ident) == "completed"
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert asyncio.run(v["jobs"].application.execute(ContextRetrievalRequest.model_validate(v["retrieval_request"]), invocation_id=ident)) == body
    context = {**request_for(v, v["index_head"]), "policy_revision": INDEXED_CONTEXT_POLICY,
        "retrieval_bindings": body["retrieval_bindings"]}
    import json
    preview = preview_response(v, {**context, "retrieval_bindings": json.dumps(context["retrieval_bindings"])})
    assert preview.status_code == 200, preview.text
    done = completed(archive(v, preview.json())[0])
    restored, _ = read(v, done)
    assert restored["context"] == preview.json()["context"]
    assert len(v["index_calls"]) == v["calls_before"] + 1
    for model in (Plan, Call, Batch, Result):
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as session:
                session.execute(update(model).where(model.project_id == v["project_id"]).values(project_id="changed"))


def test_worker_crash_after_durable_batch_resumes_without_provider_resend(retrieval, monkeypatch):
    v = retrieval
    ident = queue(v)
    repository = v["jobs"].repository
    original = repository.complete
    attempts = []
    def crash(*args, **kwargs):
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError("simulated worker loss before commit")
        return original(*args, **kwargs)
    monkeypatch.setattr(repository, "complete", crash)
    with pytest.raises(RuntimeError, match="worker loss"):
        run(v, ident)
    assert count(v, Batch) == 1 and count(v, Trace) == count(v, Result) == 0
    assert result(v, ident).status_code == 404
    calls = len(v["index_calls"])
    assert run(v, ident) == "completed"
    assert len(v["index_calls"]) == calls and result(v, ident).status_code == 200


@pytest.mark.parametrize("documents", [33], indirect=True)
def test_multiple_real_ac_batches_resume_with_complete_mapping(retrieval, monkeypatch):
    v = retrieval
    assert v["retrieval_preview"]["query_count"] == 33 and v["retrieval_preview"]["max_model_calls"] == 2
    ident = queue(v)
    original = v["index_service"].collect_candidates
    attempts = []
    def crash(*args, **kwargs):
        if not attempts:
            attempts.append(True)
            raise RuntimeError("worker lost after first durable batch")
        return original(*args, **kwargs)
    monkeypatch.setattr(v["index_service"], "collect_candidates", crash)
    with pytest.raises(RuntimeError, match="first durable batch"):
        run(v, ident)
    assert count(v, Batch) == 1 and count(v, Result) == count(v, Trace) == 0
    assert run(v, ident) == "completed"
    inputs = v["index_calls"][v["calls_before"]:]
    assert [len(call["input"]) for call in inputs] == [32, 1]
    body = result(v, ident)
    assert body.status_code == 200, body.text
    assert len(body.json()["retrieval_bindings"]) == count(v, Trace) == 33
    assert count(v, Call) == count(v, Batch) == 2


def test_two_workers_share_one_reserved_call(retrieval, monkeypatch):
    v = retrieval
    ident = queue(v)
    original = v["index_service"].provider.embed
    async def slow(*args):
        await asyncio.sleep(0.3)
        return await original(*args)
    monkeypatch.setattr(v["index_service"].provider, "embed", slow)
    async def compete():
        return await asyncio.gather(v["jobs"].run(ident), v["jobs"].run(ident))
    assert asyncio.run(compete()) == ["completed", "completed"]
    assert len(v["index_calls"]) == v["calls_before"] + 1
    assert count(v, Call) == count(v, Batch) == count(v, Trace) == count(v, Result) == 1


def test_unknown_reserved_provider_outcome_never_reissues(retrieval, monkeypatch):
    v = retrieval
    ident = queue(v)
    calls = []
    async def lose(*args):
        calls.append(True)
        raise RuntimeError("simulated provider acknowledgement loss")
    monkeypatch.setattr(v["index_service"].provider, "embed", lose)
    with pytest.raises(RuntimeError, match="acknowledgement loss"):
        run(v, ident)
    assert count(v, Call) == 1 and count(v, Batch) == 0
    from apps.api.app.application.system_image import context_retrieval
    monkeypatch.setattr(context_retrieval, "datetime", SimpleNamespace(now=lambda zone: datetime.now(timezone.utc) + timedelta(minutes=3)))
    assert run(v, ident) == "failed"
    assert calls == [True] and count(v, Trace) == count(v, Result) == 0


@pytest.mark.parametrize("change", ["cancel", "model", "head", "account", "commit"])
def test_state_changes_cannot_publish_partial_mappings(retrieval, monkeypatch, change):
    v = retrieval
    ident = queue(v)
    service = v["index_service"]
    def mutate():
        if change == "cancel":
            v["jobs"].repository.finish(v["project_id"], ident, "cancelled", "fixture cancellation")
        elif change == "account":
            with session_scope() as session:
                session.get(UserIdentityRecord, v["owner"]["id"]).status = "disabled"
        elif change in {"model", "commit"}:
            service.models.repository.save_model_config(v["index_config"].model_copy(update={"updated_at": "changed"}), v["index_encrypted"])
        else:
            v["target"] = {**v["target"], "expected_head_id": v["index_head"]["publication_id"]}
            publish(v)
    if change == "commit":
        original = service.artifacts.put
        def put(project_id, body):
            saved = original(project_id, body)
            if body["schema"] == "nasus.context-retrieval.v1":
                mutate()
            return saved
        monkeypatch.setattr(service.artifacts, "put", put)
    else:
        original = service.provider.embed
        async def embed(*args):
            reply = await original(*args)
            mutate()
            return reply
        monkeypatch.setattr(service.provider, "embed", embed)
    assert run(v, ident) == ("cancelled" if change == "cancel" else "failed")
    assert count(v, Trace) == count(v, Result) == 0


def test_native_failure_is_explicit_same_index_fts_fallback(retrieval, monkeypatch):
    v = retrieval
    ident = queue(v)
    async def unavailable(*args):
        raise IndexEmbeddingFailure("provider unavailable")
    monkeypatch.setattr(v["index_service"].provider, "embed", unavailable)
    assert run(v, ident) == "completed"
    body = result(v, ident).json()
    assert body["batches"][0]["fallback"] is True
    with actor_scope(UserProfile.model_validate(v["owner"])):
        trace = v["index_service"].read_trace(v["project_id"], next(iter(body["retrieval_bindings"].values())))
        assert trace["strategy"] == "published_lexical_embedding_unavailable" and trace["generation_id"] == v["retrieval_request"]["generation_id"]


def test_cancel_queued_command_and_cancel_after_completion(retrieval):
    v = retrieval
    ident = queue(v)
    done = completed(invoke(v, CONTEXT_CANCEL_TOOL, {"project_id": v["project_id"], "invocation_id": ident}))
    assert "cancelled" in done["summary"] and run(v, ident) == "cancelled"
    assert len(v["index_calls"]) == v["calls_before"] and count(v, Call) == 0
    ident2 = queue(v)
    assert run(v, ident2) == "completed"
    before = result(v, ident2).json()
    done = completed(invoke(v, CONTEXT_CANCEL_TOOL, {"project_id": v["project_id"], "invocation_id": ident2}))
    assert "completed" in done["summary"] and result(v, ident2).json() == before
    v["workflow"].cancel.assert_awaited_once_with(ident)


def test_no_direct_execution_or_changed_consent_or_unauthorized_result(retrieval):
    v = retrieval
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(ImageRevisionIntegrityError, match="canonical"):
            asyncio.run(v["jobs"].application.execute(ContextRetrievalRequest.model_validate(v["retrieval_request"]), invocation_id="fake"))
    ident = queue(v, expected_plan_digest="sha256:" + "0" * 64)
    assert run(v, ident) == "failed" and count(v, Call) == 0
    ident = queue(v)
    assert run(v, ident) == "completed"
    grant_member(v)
    denied = v["client"].get(v["image_url"] + f"/context-retrievals/{ident}", headers=v["member_headers"])
    assert denied.status_code == 403 and "retrieval_bindings" not in denied.text


def test_agent_revalidates_completed_mapping_receipt(retrieval):
    from apps.api.app.application.platform.errors import PlatformApplicationError
    from apps.api.app.application.platform.tool_models import ToolResult
    from apps.api.app.application.agent.observation_receipts import observation_receipt_fingerprint
    v = retrieval
    ident = queue(v)
    assert run(v, ident) == "completed"
    observed = completed(invoke(v, CONTEXT_RETRIEVAL_QUERY_TOOL, {"project_id": v["project_id"], "invocation_id": ident}))
    receipt = ToolResult.model_validate(observed["result"])
    fingerprint = observation_receipt_fingerprint(receipt)
    receipt.context_retrieval_result = {**receipt.context_retrieval_result, "retrieval_bindings": {}}
    assert observation_receipt_fingerprint(receipt) != fingerprint
    with session_scope() as session:
        session.get(ToolInvocationRecord, observed["id"]).result_payload = receipt.model_dump()
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(PlatformApplicationError, match="receipt changed"):
            app.state.container.tool_evidence.describe(observed["id"], v["project_id"])


@pytest.mark.skipif(not os.getenv("TEST_TEMPORAL_ADDRESS"), reason="requires explicit isolated Temporal task queue")
def test_real_temporal_dispatch_heartbeat_and_idempotent_workflow(retrieval, monkeypatch):
    from temporalio.client import Client
    from temporalio.worker import Worker
    from apps.api.app.infrastructure.workflow.context_retrieval_runtime import TemporalContextRetrievalRuntime, build_context_retrieval_activities, reconcile_context_retrievals_once
    from apps.api.app.infrastructure.workflow.nasus_context_retrieval_workflow import NasusContextRetrievalWorkflow
    from apps.api.app.infrastructure.config.agent_runtime_config import temporal_gateway_config_from_env
    from dataclasses import replace
    v = retrieval
    ident = queue(v)
    monkeypatch.setenv("NASUS_AGENT_WORKFLOW_RUNTIME", "temporal")
    async def verify():
        config = replace(temporal_gateway_config_from_env(), address=os.environ["TEST_TEMPORAL_ADDRESS"], task_queue="nasus-query-test-" + uuid4().hex)
        client = await Client.connect(config.address, namespace=config.namespace)
        runtime = TemporalContextRetrievalRuntime(config, client)
        repository = v["jobs"].repository
        scoped = SimpleNamespace(
            pending=lambda **kw: [(item, project) for item, project in repository.pending(**kw) if item == ident],
            pending_cancellations=lambda **kw: [], finish=repository.finish)
        async with Worker(client, task_queue=runtime.task_queue, workflows=[NasusContextRetrievalWorkflow], activities=build_context_retrieval_activities()):
            await reconcile_context_retrievals_once(runtime, scoped)
            handle = client.get_workflow_handle(f"nasus-context-retrieval:{ident}")
            assert await asyncio.wait_for(handle.result(), 90) == "completed"
            calls = len(v["index_calls"])
            assert await runtime.start(ident) is False
            assert len(v["index_calls"]) == calls
    asyncio.run(verify())
    assert result(v, ident).status_code == 200
