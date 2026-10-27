"""PG delivery intent and isolated real Temporal cancellation; provider calls are fixtures."""
import asyncio
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.infrastructure.persistence.context_retrieval_models import ContextRetrievalCancellationRecord as Cancellation
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, UserIdentityRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.workflow.context_retrieval_runtime import reconcile_context_retrievals_once
from apps.api.tests.test_context_retrieval_execution import retrieval, indexed, publication, documents, evidence_api
from apps.api.tests.test_context_retrieval_execution import queue, run, count, Call, Batch, Trace, Result
from apps.api.tests.test_semantic_evaluations_api import invoke, completed
from apps.api.app.application.system_image.context_retrieval_ports import CONTEXT_CANCEL_TOOL


def cancel(v, ident, **kwargs):
    return completed(invoke(v, CONTEXT_CANCEL_TOOL,
        {"project_id": v["project_id"], "invocation_id": ident}, **kwargs))


def delivered(ident):
    with session_scope() as session:
        return session.get(Cancellation, ident).delivered_at


def test_failed_cancel_rpc_is_durable_and_reconciled_idempotently(retrieval):
    v = retrieval
    ident = queue(v)
    v["workflow"].cancel.side_effect = RuntimeError("Temporal temporarily unreachable")
    assert "cancelled" in cancel(v, ident)["summary"]
    assert delivered(ident) is None
    assert (ident, v["project_id"]) in v["jobs"].repository.pending_cancellations()
    assert run(v, ident) == "cancelled" and count(v, Call) == count(v, Result) == 0
    v["workflow"].cancel.side_effect = None
    asyncio.run(reconcile_context_retrievals_once(v["workflow"], v["jobs"].repository))
    first = delivered(ident)
    assert first is not None
    calls = v["workflow"].cancel.await_count
    asyncio.run(reconcile_context_retrievals_once(v["workflow"], v["jobs"].repository))
    assert v["workflow"].cancel.await_count == calls and delivered(ident) == first
    with session_scope() as session:
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == ident)).all()
        assert sum(e.event_type == "system_image.context_retrieval.cancel_requested" for e in events) == 1
        assert sum(e.event_type == "system_image.context_retrieval.cancel_delivered" for e in events) == 1
        assert session.get(ToolInvocationRecord, ident).status == "cancelled"
    assert len(v["index_calls"]) == v["calls_before"]


def test_cancellation_record_and_terminal_command_rollback_together(retrieval, monkeypatch):
    v = retrieval
    ident = queue(v)
    repo = v["jobs"].repository
    original = repo._event
    def fail(session, project_id, invocation_id, state, ordinal=None):
        if state == "cancel_requested":
            raise RuntimeError("outbox write failed")
        return original(session, project_id, invocation_id, state, ordinal)
    monkeypatch.setattr(repo, "_event", fail)
    with pytest.raises(RuntimeError, match="outbox"):
        repo.finish(v["project_id"], ident, "cancelled", "fixture cancellation")
    with session_scope() as session:
        assert session.get(ToolInvocationRecord, ident).status == "running"
        assert session.get(Cancellation, ident) is None
    v["workflow"].cancel.assert_not_awaited()
    repo.finish(v["project_id"], ident, "failed", "fixture cleanup after rollback verification")


@pytest.mark.parametrize("cancel_first", [False, True])
def test_disabled_confirming_account_cannot_strand_or_block_admin_cancellation(retrieval, cancel_first):
    v = retrieval
    ident = queue(v)
    assert v["client"].put(f"/v1/projects/{v['project_id']}/members/{v['member']['id']}",
        headers=v["headers"], json={"role": "project_admin"}).status_code == 200
    with session_scope() as session:
        session.get(UserIdentityRecord, v["owner"]["id"]).status = "disabled"
    if cancel_first:
        assert "cancelled" in cancel(v, ident, headers=v["member_headers"])["summary"]
    assert run(v, ident) == ("cancelled" if cancel_first else "failed")
    assert count(v, Call) == count(v, Result) == 0


def test_paged_reconciliation_isolates_failed_jobs_and_reaches_later_pages(retrieval):
    v = retrieval
    ident = queue(v)
    prefix = "z-recovery-" + uuid4().hex
    ids = [f"{prefix}-{i:03d}" for i in range(105)]
    # Explicit durable-dispatch fixtures avoid 105 redundant source builds/HTTP confirmations.
    with session_scope() as session:
        template = session.get(ToolInvocationRecord, ident)
        body = {column.name: getattr(template, column.name) for column in ToolInvocationRecord.__table__.columns}
        for item in ids:
            session.add(ToolInvocationRecord(**{**body, "id": item, "idempotency_key": uuid4().hex}))
    started, cancelled = [], []
    async def start(item):
        started.append(item)
        if item == ids[0]:
            raise RuntimeError("one poisoned workflow")
        return item != ids[-1]
    async def stop(item):
        cancelled.append(item)
        if item == ids[1]:
            raise RuntimeError("cancellation endpoint temporarily unavailable")
    repo = v["jobs"].repository
    for item in ids[1:-1]:
        repo.finish(v["project_id"], item, "cancelled", "fixture cancellation")
    runtime = SimpleNamespace(start=start, cancel=stop)
    asyncio.run(reconcile_context_retrievals_once(runtime, repo))
    assert {ids[0], ids[-1]} <= set(started)
    assert set(ids[1:-1]) <= set(cancelled) and delivered(ids[-2]) is not None
    assert delivered(ids[1]) is None
    with session_scope() as session:
        assert session.get(ToolInvocationRecord, ids[0]).status == "running"
        assert session.get(ToolInvocationRecord, ids[-1]).status == "failed"
    # Retain over 100 running commands for the dispatch pagination assertion too.
    with session_scope() as session:
        for i in range(105, 210):
            session.add(ToolInvocationRecord(**{**body, "id": f"{prefix}-{i:03d}", "idempotency_key": uuid4().hex}))
    started.clear()
    asyncio.run(reconcile_context_retrievals_once(runtime, repo))
    assert {f"{prefix}-{i:03d}" for i in range(105, 210)} <= set(started)
    assert len(started) == len(set(started))
    for item in [ident, *ids, *[f"{prefix}-{i:03d}" for i in range(105, 210)]]:
        repo.finish(v["project_id"], item, "failed", "fixture cleanup after pagination verification")


def test_migration_backfills_legacy_cancel_and_blocks_destructive_downgrade(retrieval, monkeypatch):
    import importlib
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import text
    from apps.api.app.infrastructure.persistence.database import engine
    v = retrieval
    ident = queue(v)
    migration = importlib.import_module("apps.api.migrations.versions.0056_context_retrieval_cancel")
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("UPDATE tool_invocations SET status = 'cancelled' WHERE id = :id"), {"id": ident})
            connection.execute(text("DROP TABLE context_retrieval_cancellations"))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            row = connection.execute(text("SELECT project_id, delivered_at FROM context_retrieval_cancellations WHERE invocation_id = :id"), {"id": ident}).one()
            assert row.project_id == v["project_id"] and row.delivered_at is None
            with pytest.raises(RuntimeError, match="cannot downgrade"):
                migration.downgrade()
        finally:
            transaction.rollback()
    assert v["jobs"].repository.command(ident)[1] == "running"
    v["jobs"].repository.finish(v["project_id"], ident, "failed", "fixture cleanup after migration rollback")


@pytest.mark.skipif(not os.getenv("TEST_TEMPORAL_ADDRESS"), reason="requires explicit isolated Temporal task queue")
def test_real_temporal_cancel_recovery_stops_inflight_provider(retrieval, monkeypatch):
    from dataclasses import replace
    from temporalio.client import Client, WorkflowFailureError, WorkflowExecutionStatus
    from temporalio.worker import Worker
    from apps.api.app.infrastructure.workflow.context_retrieval_runtime import TemporalContextRetrievalRuntime, build_context_retrieval_activities
    from apps.api.app.infrastructure.workflow.nasus_context_retrieval_workflow import NasusContextRetrievalWorkflow
    from apps.api.app.infrastructure.config.agent_runtime_config import temporal_gateway_config_from_env
    v = retrieval
    ident = queue(v)
    monkeypatch.setenv("NASUS_AGENT_WORKFLOW_RUNTIME", "temporal")
    async def verify():
        entered, stopped = asyncio.Event(), asyncio.Event()
        async def stalled(*args):
            entered.set()
            try:
                await asyncio.sleep(120)
            except asyncio.CancelledError:
                stopped.set()
                raise
        monkeypatch.setattr(v["index_service"].provider, "embed", stalled)
        config = replace(temporal_gateway_config_from_env(), address=os.environ["TEST_TEMPORAL_ADDRESS"], task_queue="nasus-cancel-test-" + uuid4().hex)
        client = await Client.connect(config.address, namespace=config.namespace)
        runtime = TemporalContextRetrievalRuntime(config, client)
        repo = v["jobs"].repository
        async with Worker(client, task_queue=runtime.task_queue, workflows=[NasusContextRetrievalWorkflow], activities=build_context_retrieval_activities()):
            await runtime.start(ident)
            handle = client.get_workflow_handle(f"nasus-context-retrieval:{ident}")
            try:
                await asyncio.wait_for(entered.wait(), 30)
                v["workflow"].cancel.side_effect = RuntimeError("cancel RPC acknowledgement lost")
                with actor_scope(UserProfile.model_validate(v["owner"])):
                    assert await v["jobs"].cancel(v["project_id"], ident) == "cancelled"
                assert delivered(ident) is None
                # Only this test workflow belongs to this isolated Temporal queue.
                scoped = SimpleNamespace(pending=lambda **kw: [],
                    pending_cancellations=lambda **kw: [(ident, v["project_id"])] if kw.get("after_id") is None else [],
                    cancellation_delivered=repo.cancellation_delivered)
                await reconcile_context_retrievals_once(runtime, scoped)
                assert delivered(ident) is not None
                with pytest.raises(WorkflowFailureError):
                    await asyncio.wait_for(handle.result(), 30)
                assert (await handle.describe()).status == WorkflowExecutionStatus.CANCELED
                await asyncio.wait_for(stopped.wait(), 5)
            finally:
                await handle.cancel()
    asyncio.run(verify())
    assert count(v, Call) == 1 and count(v, Batch) == count(v, Trace) == count(v, Result) == 0
    assert run(v, ident) == "cancelled"
