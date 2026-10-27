import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import importlib
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.generation_execution_inputs import GENERATION_EXECUTION_PREVIEW_TOOL, GenerationExecutionSelection
from apps.api.app.application.quality_loop.generation_executor import GenerationOutcomeUnknown
from apps.api.app.application.quality_loop.generation_job_ports import GENERATION_RECOVER_TOOL, GENERATION_CANCEL_TOOL, GENERATION_JOB_QUERY_TOOL
from apps.api.app.infrastructure.persistence.generation_job_models import GenerationJobCancellationRecord as Cancellation
from apps.api.app.infrastructure.workflow.generation_runtime import reconcile_generation_jobs_once
from apps.api.app.application.quality_loop.test_design_results import GENERATION_TOOL, GenerationResultRequest, TestDesignResultIntegrityError
from apps.api.app.infrastructure.llm.test_design_model import HTTPTestDesignModel
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, LLMCallRecord, SSEEventOutboxRecord, UserIdentityRecord
from apps.api.app.infrastructure.persistence.generation_execution_models import GenerationCallReservationRecord as Reservation, GenerationNativeReplyRecord as Reply
from apps.api.app.infrastructure.persistence.test_design_result_models import TestDesignResultRecord as Result
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_test_design_scope_api import design_scope, submit
from apps.api.tests.test_test_design_generation_api import generation_request
from apps.api.tests.test_image_publications_api import publication
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_semantic_evaluations_api import completed, count, invoke, confirm
from apps.api.tests.test_semantic_link_model import native_reply, saved_config
from apps.api.tests.test_generation_executor import budget, policy
from apps.api.tests.test_test_design_generation import case_output


@pytest.fixture
def execution(design_scope, monkeypatch):
    v = design_scope
    completed(submit(v))
    selection, _ = generation_request(v)
    service = app.state.container.test_design_executor
    jobs = app.state.container.test_design_jobs
    workflow = SimpleNamespace(start=AsyncMock(return_value=True), cancel=AsyncMock())
    monkeypatch.setattr(jobs, "workflow", workflow)
    config = saved_config(config_id=uuid4().hex)
    encrypted = service.profiles.secrets.encrypt_api_key("native-test-design-fixture-key")
    service.profiles.repository.save_model_config(config, encrypted)
    monkeypatch.setattr(service.policies, "resolve", lambda binding: SimpleNamespace(policy=policy(binding), count=lambda *args: 32000))
    calls = []
    def handle(request):
        calls.append(request)
        prepared = json.loads(json.loads(request.content)["messages"][-1]["content"])
        return httpx.Response(200, json=native_reply("openai_compatible", json.dumps(case_output(prepared))))
    monkeypatch.setattr(service, "provider", HTTPTestDesignModel(transport=httpx.MockTransport(handle)))
    selection = GenerationExecutionSelection(**selection.model_dump(), model_config_id=config.config_id, budget=budget())
    with actor_scope(UserProfile.model_validate(v["owner"])):
        preview = service.preview(selection)
    v.update(executor=service, preview=preview, execution_request=GenerationResultRequest.model_validate(preview["request"]),
        selection=selection, native_calls=calls, jobs=jobs, workflow=workflow)
    return v


def seed(v, *, expired=False):
    ident = uuid4().hex
    when = datetime.now(timezone.utc) - timedelta(minutes=16 if expired else 0)
    with session_scope() as session:
        session.add(ToolInvocationRecord(id=ident, tool_id=GENERATION_TOOL, status="running", conversation_id=v["conversation"].json()["id"],
            summary="Confirmed native transport test fixture, NOT external model validation",
            input_payload={**v["execution_request"].model_dump(mode="json"), "confirmed_by_user": True,
                "confirmed_actor_id": v["owner"]["id"], "confirmed_at": when.isoformat()}))
    return ident


def execute(v, ident):
    with actor_scope(UserProfile.model_validate(v["owner"])):
        return asyncio.run(v["executor"].execute(v["execution_request"], invocation_id=ident))


def queued(v, tool=GENERATION_TOOL, payload=None):
    pending = invoke(v, tool, payload or v["preview"]["request"], key=uuid4().hex).json()
    assert pending["status"] == "waiting_confirmation"
    response = confirm(v, pending)
    assert response.status_code == 200 and response.json()["status"] == "running", response.text
    return pending["id"]


def job(v, ident):
    return completed(invoke(v, GENERATION_JOB_QUERY_TOOL, {"project_id": v["project_id"], "invocation_id": ident}))["result"]["test_design_job"]


def command(v, ident):
    return v["client"].get(f"/v1/tool-invocations/{ident}", headers=v["headers"])


def test_internal_batch_planning_uses_real_pins_without_egress_or_persistence(execution):
    from apps.api.tests.test_generation_batches import responses_for

    v = execution
    planner = v["executor"].batch_planning
    before_calls = count(v, LLMCallRecord)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        planned = planner.prepare(v["selection"])
        assert planned.preview["input_digest"] == v["execution_request"].input_digest
        assert planned.preview["selection"] == v["selection"].model_dump(mode="json")
        assert len(planned.preview["source_binding_ids"]) == 3
        assert not planned.preview["generation_authorized"] and not planned.preview["execution_authorized"]
        assert "HTTP 400" not in json.dumps(planned.preview) and "native-test-design-fixture-key" not in repr(planned)
        result = planner.check_outputs(v["selection"], expected_planning_digest=planned.digest,
            responses=responses_for(planned.input, planned.plan))
        assert result["proposal"]["coverage"]["obligation_denominator"] == len(planned.input["obligations"])
        assert result["proposal"]["coverage"]["passed_count"] == 0
    assert count(v, Reservation) == count(v, Reply) == count(v, Result) == 0
    assert count(v, LLMCallRecord) == before_calls
    assert not v["native_calls"]


def test_internal_batch_checker_does_not_reuse_withdrawn_scope(execution):
    from apps.api.app.domain.quality_loop.test_design_scope import TestDesignScopeChanged
    from apps.api.tests.test_generation_batches import responses_for

    v = execution
    planner = v["executor"].batch_planning
    with actor_scope(UserProfile.model_validate(v["owner"])):
        planned = planner.prepare(v["selection"])
    completed(submit(v, {**v["scope_request"], "expected_previous_revision_id": v["selection"].scope_revision_id,
        "decision": "withdraw", "contract": None}))
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(TestDesignScopeChanged):
            planner.check_outputs(v["selection"], expected_planning_digest=planned.digest,
                responses=responses_for(planned.input, planned.plan))
    assert not v["native_calls"] and count(v, Reservation) == count(v, Result) == 0


def test_canonical_generation_requires_confirmation_and_archives_native_call_atomically(execution):
    v = execution
    preview = completed(invoke(v, GENERATION_EXECUTION_PREVIEW_TOOL, v["selection"].model_dump(mode="json")))
    assert preview["result"]["test_design_execution_preview"] == v["preview"]
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(preview["id"], v["project_id"]) == v["preview"]
    assert count(v, Reservation) == count(v, Reply) == count(v, Result) == 0 and not v["native_calls"]
    pending = invoke(v, GENERATION_TOOL, {**v["preview"]["request"], "confirmed_by_user": True}, key=uuid4().hex).json()
    assert pending["status"] == "waiting_confirmation" and not v["native_calls"]
    accepted = confirm(v, pending)
    assert accepted.status_code == 200 and accepted.json()["status"] == "running" and not v["native_calls"]
    assert asyncio.run(v["jobs"].run(pending["id"])) == "completed"
    done = completed(command(v, pending["id"]))
    assert len(v["native_calls"]) == 1 and count(v, Reservation) == count(v, Reply) == count(v, Result) == 1
    assert completed(confirm(v, pending))["id"] == done["id"] and len(v["native_calls"]) == 1
    result_id = done["result"]["object_refs"][0].split(":", 1)[1]
    response = v["client"].get(f"/v1/projects/{v['project_id']}/quality/test-design-results/{result_id}", headers=v["headers"])
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["result"]["request"] == v["preview"]["request"] and value["result"]["status"] == "draft"
    assert value["result"]["proposal"]["coverage"]["passed_count"] == 0
    with session_scope() as session:
        calls = session.scalars(select(LLMCallRecord).where(LLMCallRecord.tool_invocation_id == done["id"])).all()
        assert len(calls) == 1 and calls[0].outcome == "success" and calls[0].usage_source == "provider"
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_payload["correlation_id"].as_string() == v["project_id"],
            SSEEventOutboxRecord.event_type.in_(["quality.test_design.call_reserved", "quality.test_design.reply_archived"]))).all()
        assert len(events) == 2 and all("HTTP 400" not in json.dumps(row.event_payload) for row in events)
    assert "native-test-design-fixture-key" not in response.text and "artifact_ref" not in response.text
    for model in (Reservation, Reply):
        for statement in (delete(model), update(model).values(project_id="forged")):
            with pytest.raises(IntegrityError, match="append-only"):
                with session_scope() as session:
                    session.execute(statement.where(model.project_id == v["project_id"]))
    import importlib
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from apps.api.app.infrastructure.persistence.database import engine
    migration = importlib.import_module("apps.api.migrations.versions.0059_generation_execution")
    with engine.begin() as connection:
        original = migration.op
        try:
            migration.op = Operations(MigrationContext.configure(connection))
            with pytest.raises(RuntimeError, match="cannot downgrade"):
                migration.downgrade()
        finally:
            migration.op = original


def test_draft_transaction_failure_recovers_archived_reply_without_new_provider_egress(execution, monkeypatch):
    v = execution
    ident = seed(v)
    original = v["executor"].results.repository.record
    def fail(*args, **kwargs):
        raise RuntimeError("injected draft transaction failure")
    monkeypatch.setattr(v["executor"].results.repository, "record", fail)
    with pytest.raises(RuntimeError, match="draft transaction failure"):
        execute(v, ident)
    assert count(v, Reservation) == count(v, Reply) == 1 and count(v, Result) == 0 and len(v["native_calls"]) == 1
    monkeypatch.setattr(v["executor"].results.repository, "record", original)
    assert execute(v, ident)["status"] == "draft" and count(v, Result) == 1 and len(v["native_calls"]) == 1


def test_terminal_failure_requires_explicit_recovery_and_never_resends(execution, monkeypatch):
    v = execution
    original = v["executor"].results.repository.record
    def fail(*args, **kwargs):
        raise RuntimeError("injected canonical finalization failure")
    monkeypatch.setattr(v["executor"].results.repository, "record", fail)
    ident = queued(v)
    with pytest.raises(RuntimeError, match="finalization failure"):
        asyncio.run(v["jobs"].run(ident))
    assert asyncio.run(v["jobs"].fail(ident)) == "failed"
    assert count(v, Reservation) == count(v, Reply) == 1 and count(v, Result) == 0
    monkeypatch.setattr(v["executor"].results.repository, "record", original)
    assert confirm(v, {"id": ident}).json()["status"] == "failed"
    with pytest.raises(TestDesignResultIntegrityError, match="canonical"):
        execute(v, ident)
    assert len(v["native_calls"]) == 1 and count(v, Result) == 0
    state = job(v, ident)
    assert state["status"] == "failed" and state["reply_archived"] and not state["provider_outcome_unknown"]
    recovery_id = queued(v, GENERATION_RECOVER_TOOL, state["recovery_request"])
    assert len(v["native_calls"]) == 1
    async def unexpected_failure(*args):
        raise
    monkeypatch.setattr(v["jobs"], "fail", unexpected_failure)
    assert asyncio.run(v["jobs"].run(recovery_id)) == "completed"
    result_id = completed(command(v, recovery_id))["result"]["object_refs"][0].split(":", 1)[1]
    response = v["client"].get(f"/v1/projects/{v['project_id']}/quality/test-design-results/{result_id}", headers=v["headers"])
    assert response.status_code == 200, response.text
    payload = response.json()["result"]
    assert payload["schema"] == "nasus.test-design-result.v2" and payload["recovery_invocation_id"] == recovery_id
    assert payload["invocation_id"] == ident and payload["proposal"]["coverage"]["passed_count"] == 0
    assert command(v, ident).json()["status"] == "failed" and count(v, Result) == 1 and len(v["native_calls"]) == 1
    assert asyncio.run(v["jobs"].run(recovery_id)) == "completed" and len(v["native_calls"]) == 1


def test_concurrent_execution_of_same_call_never_duplicates_model_request(execution):
    v = execution
    ident = seed(v)
    def attempt(_):
        try:
            return execute(v, ident)
        except GenerationOutcomeUnknown:
            return "reserved"
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(attempt, range(2)))
    assert any(isinstance(value, dict) for value in values)
    assert len(v["native_calls"]) == 1 and count(v, Reservation) == count(v, Reply) == count(v, Result) == 1


def test_expired_confirmation_and_changed_policy_do_not_reserve_or_send(execution, monkeypatch):
    v = execution
    with pytest.raises(ValueError, match="confirmation expired"):
        execute(v, seed(v, expired=True))
    original = v["executor"].policies.resolve
    monkeypatch.setattr(v["executor"].policies, "resolve", lambda binding: SimpleNamespace(policy=policy(binding, revision="new"), count=lambda *args: 32000))
    with pytest.raises(ValueError, match="consent changed"):
        execute(v, seed(v))
    monkeypatch.setattr(v["executor"].policies, "resolve", original)
    assert not v["native_calls"] and count(v, Reservation) == count(v, Reply) == count(v, Result) == 0


def test_reply_outbox_failure_retains_unknown_reservation_without_half_receipt(execution, monkeypatch):
    v = execution
    original = EventOutboxRepository.append
    def fail(self, event, **kwargs):
        if event.event_type == "quality.test_design.reply_archived":
            raise RuntimeError("injected native reply outbox failure")
        return original(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    ident = seed(v)
    with pytest.raises(RuntimeError, match="outbox failure"):
        execute(v, ident)
    assert count(v, Reservation) == 1 and count(v, Reply) == count(v, Result) == 0
    with pytest.raises(GenerationOutcomeUnknown):
        execute(v, ident)
    assert len(v["native_calls"]) == 1
    with session_scope() as session:
        calls = session.scalars(select(LLMCallRecord).where(LLMCallRecord.tool_invocation_id == ident)).all()
        assert len(calls) == 1 and calls[0].outcome == "error" and calls[0].input_token_count == 123


@pytest.mark.parametrize("phase", ["provider_return", "artifact_written"])
@pytest.mark.parametrize("dependency", ["account", "model", "source", "scope"])
def test_changed_authority_blocks_native_receipt_and_never_resends(execution, monkeypatch, phase, dependency):
    v = execution
    def change():
        if dependency == "account":
            with session_scope() as session:
                session.get(UserIdentityRecord, v["owner"]["id"]).status = "disabled"
        elif dependency == "model":
            profiles = v["executor"].profiles
            config = profiles.repository.get_model_config(v["selection"].model_config_id)
            profiles.repository.save_model_config(config.model_copy(update={"model_name": "changed-model"}),
                profiles.secrets.encrypt_api_key("changed-generation-fixture-key"))
        elif dependency == "scope":
            completed(submit(v, {**v["scope_request"], "expected_previous_revision_id": v["execution_request"].scope_revision_id,
                "decision": "withdraw", "contract": None}))
        else:
            from apps.api.app.domain.system_image.source_access import SourceAccessRule
            from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
            repository = SourceAccessRepository()
            snapshot = repository.load_snapshot(v["project_id"])
            repository.set_policy(v["project_id"], snapshot.bindings[0].binding_id, SourceAccessRule("restricted"),
                expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="generation-source-revocation")
    if phase == "provider_return":
        original = v["executor"].provider.generate
        async def changed(*args, **kwargs):
            reply = await original(*args, **kwargs)
            change()
            return reply
        monkeypatch.setattr(v["executor"].provider, "generate", changed)
    else:
        original = v["executor"].artifacts.put
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            change()
            return result
        monkeypatch.setattr(v["executor"].artifacts, "put", changed)
    ident = seed(v)
    with pytest.raises((PermissionError, ValueError)):
        execute(v, ident)
    assert len(v["native_calls"]) == 1 and count(v, Reservation) == 1 and count(v, Reply) == count(v, Result) == 0
    with pytest.raises((PermissionError, GenerationOutcomeUnknown)):
        execute(v, ident)
    assert len(v["native_calls"]) == 1
    with session_scope() as session:
        calls = session.scalars(select(LLMCallRecord).where(LLMCallRecord.tool_invocation_id == ident)).all()
        assert len(calls) == 1 and calls[0].outcome == "error"


def test_lost_dispatch_ack_reconciles_original_job_without_egress(execution):
    v = execution
    v["workflow"].start.side_effect = RuntimeError("acknowledgement lost")
    ident = queued(v)
    assert not v["native_calls"] and count(v, Reservation) == 0
    noise = [f"000_dispatch_specimen_{uuid4().hex}_{i:03d}" for i in range(105)]
    with session_scope() as session:
        original = session.get(ToolInvocationRecord, ident)
        session.add_all([ToolInvocationRecord(id=key, tool_id=GENERATION_TOOL, status="running",
            summary="Pagination transport specimen; never executes a model",
            input_payload=dict(original.input_payload)) for key in noise])
    try:
        repository = v["jobs"].repository
        assert (ident, v["project_id"]) not in repository.pending()
        with session_scope() as session:
            expected = session.execute(select(ToolInvocationRecord.id,
                ToolInvocationRecord.input_payload["project_id"].as_string()).where(
                    ToolInvocationRecord.tool_id.in_((GENERATION_TOOL, GENERATION_RECOVER_TOOL)),
                    ToolInvocationRecord.status == "running").order_by(ToolInvocationRecord.id)).all()
        found, after_id = [], None
        while True:
            page = repository.pending(after_id=after_id)
            if not page:
                break
            assert len(page) <= 100 and (after_id is None or page[0][0] > after_id)
            found.extend(page)
            after_id = page[-1][0]
        assert found == [tuple(row) for row in expected]
        assert (ident, v["project_id"]) in found
        v["workflow"].start.side_effect = None
        v["workflow"].start.reset_mock()
        asyncio.run(reconcile_generation_jobs_once(v["workflow"], repository))
        assert [args.args[0] for args in v["workflow"].start.await_args_list] == [row[0] for row in found]
        assert command(v, ident).json()["status"] == "running" and not v["native_calls"]
        assert asyncio.run(v["jobs"].run(ident)) == "completed"
        assert len(v["native_calls"]) == 1
    finally:
        with session_scope() as session:
            session.execute(delete(ToolInvocationRecord).where(ToolInvocationRecord.id.in_(noise)))


def test_durable_cancel_before_egress_blocks_commit_and_retries_delivery(execution):
    v = execution
    ident = queued(v)
    v["workflow"].cancel.side_effect = RuntimeError("cancel RPC unavailable")
    pending = invoke(v, GENERATION_CANCEL_TOOL, {"project_id": v["project_id"], "invocation_id": ident}, key=uuid4().hex).json()
    assert pending["status"] == "waiting_confirmation" and command(v, ident).json()["status"] == "running"
    assert "cancelled" in completed(confirm(v, pending))["summary"]
    assert asyncio.run(v["jobs"].run(ident)) == "cancelled" and not v["native_calls"]
    with session_scope() as session:
        assert session.get(Cancellation, ident).delivered_at is None
    v["workflow"].cancel.side_effect = None
    asyncio.run(reconcile_generation_jobs_once(v["workflow"], v["jobs"].repository))
    with session_scope() as session:
        assert session.get(Cancellation, ident).delivered_at is not None
    calls = v["workflow"].cancel.await_count
    asyncio.run(reconcile_generation_jobs_once(v["workflow"], v["jobs"].repository))
    assert v["workflow"].cancel.await_count == calls and count(v, Result) == count(v, Reply) == count(v, Reservation) == 0


def test_cancel_after_atomic_result_keeps_completed_draft(execution):
    v = execution
    ident = queued(v)
    execute(v, ident)
    assert command(v, ident).json()["status"] == "running" and count(v, Result) == 1
    pending = invoke(v, GENERATION_CANCEL_TOOL, {"project_id": v["project_id"], "invocation_id": ident}, key=uuid4().hex).json()
    assert "completed" in completed(confirm(v, pending))["summary"]
    assert command(v, ident).json()["status"] == "completed" and count(v, Cancellation) == 0
    assert count(v, Result) == 1 and len(v["native_calls"]) == 1
    v["workflow"].cancel.assert_not_awaited()


def test_current_admin_can_cancel_disabled_actor_without_inheriting_recovery(execution):
    v = execution
    ident = queued(v)
    assert v["client"].put(f"/v1/projects/{v['project_id']}/members/{v['member']['id']}", headers=v["headers"],
        json={"role": "project_admin"}).status_code == 200
    with session_scope() as session:
        session.get(UserIdentityRecord, v["owner"]["id"]).status = "disabled"
    state = completed(invoke(v, GENERATION_JOB_QUERY_TOOL, {"project_id": v["project_id"], "invocation_id": ident},
        headers=v["member_headers"]))["result"]["test_design_job"]
    assert state["recovery_request"] is None
    pending = invoke(v, GENERATION_CANCEL_TOOL, {"project_id": v["project_id"], "invocation_id": ident},
        headers=v["member_headers"], key=uuid4().hex).json()
    assert pending["status"] == "waiting_confirmation"
    response = v["client"].post(f"/v1/tool-invocations/{pending['id']}/confirm", headers=v["member_headers"])
    assert "cancelled" in completed(response)["summary"]
    assert asyncio.run(v["jobs"].run(ident)) == "cancelled" and not v["native_calls"]


@pytest.mark.parametrize("mutation", ["unknown", "response_hash", "scope_withdrawn"])
def test_explicit_recovery_rejects_unknown_or_changed_dependencies(execution, monkeypatch, mutation):
    v = execution
    ident = queued(v)
    original = v["executor"].results.repository.record
    def fail(*args, **kwargs):
        raise RuntimeError("draft persistence unavailable")
    monkeypatch.setattr(v["executor"].results.repository, "record", fail)
    if mutation == "unknown":
        async def disconnected(*args, **kwargs):
            raise RuntimeError("provider connection lost")
        monkeypatch.setattr(v["executor"].provider, "generate", disconnected)
    with pytest.raises(RuntimeError):
        asyncio.run(v["jobs"].run(ident))
    assert asyncio.run(v["jobs"].fail(ident)) == "failed"
    monkeypatch.setattr(v["executor"].results.repository, "record", original)
    state = job(v, ident)
    if mutation == "unknown":
        assert state["provider_outcome_unknown"] and state["recovery_request"] is None
        request = {"project_id": v["project_id"], "invocation_id": ident,
            "request_hash": "sha256:" + "0" * 64, "reply_artifact_hash": "sha256:" + "0" * 64, "response_hash": "sha256:" + "0" * 64}
    else:
        request = state["recovery_request"]
        if mutation == "response_hash":
            request = {**request, "response_hash": "sha256:" + "0" * 64}
        else:
            completed(submit(v, {**v["scope_request"], "expected_previous_revision_id": v["execution_request"].scope_revision_id,
                "decision": "withdraw", "contract": None}))
    calls = len(v["native_calls"])
    pending = invoke(v, GENERATION_RECOVER_TOOL, request, key=uuid4().hex).json()
    assert pending["status"] == "waiting_confirmation"
    response = confirm(v, pending)
    assert response.status_code == 200, response.text
    if response.json()["status"] == "running":
        assert asyncio.run(v["jobs"].run(pending["id"])) == "failed"
    else:
        assert response.json()["status"] == "failed"
    assert count(v, Result) == 0 and len(v["native_calls"]) == calls


@pytest.mark.skipif(not os.getenv("TEST_TEMPORAL_ADDRESS"), reason="requires explicit isolated Temporal task queue")
def test_real_temporal_retries_draft_commit_by_replaying_one_native_reply(execution, monkeypatch):
    from dataclasses import replace
    from temporalio.client import Client
    from temporalio.worker import Worker
    from apps.api.app.infrastructure.config.agent_runtime_config import temporal_gateway_config_from_env
    from apps.api.app.infrastructure.workflow.generation_runtime import TemporalGenerationRuntime, build_generation_activities
    from apps.api.app.infrastructure.workflow.nasus_generation_workflow import NasusTestDesignGenerationWorkflow
    v = execution
    ident = queued(v)
    original = v["executor"].results.repository.record
    attempts = []
    def first_failure(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("private draft fixture; must not enter Temporal failure text")
        return original(*args, **kwargs)
    monkeypatch.setattr(v["executor"].results.repository, "record", first_failure)
    monkeypatch.setenv("NASUS_AGENT_WORKFLOW_RUNTIME", "temporal")
    async def verify():
        config = replace(temporal_gateway_config_from_env(), address=os.environ["TEST_TEMPORAL_ADDRESS"],
            task_queue="nasus-generation-test-" + uuid4().hex)
        client = await Client.connect(config.address, namespace=config.namespace)
        runtime = TemporalGenerationRuntime(config, client)
        async with Worker(client, task_queue=runtime.task_queue, workflows=[NasusTestDesignGenerationWorkflow],
                activities=build_generation_activities()):
            assert await runtime.start(ident)
            handle = client.get_workflow_handle("nasus-test-design-generation:" + ident)
            assert await asyncio.wait_for(handle.result(), 180) == "completed"
            assert not await runtime.start(ident)
            history = str(await handle.fetch_history())
            assert "private draft fixture" not in history and "native-test-design-fixture-key" not in history
    asyncio.run(verify())
    assert len(attempts) == 2 and len(v["native_calls"]) == 1 and count(v, Reservation) == count(v, Reply) == count(v, Result) == 1
    assert command(v, ident).json()["status"] == "completed"


@pytest.mark.skipif(not os.getenv("TEST_TEMPORAL_ADDRESS"), reason="requires explicit isolated Temporal task queue")
def test_real_temporal_cancellation_stops_inflight_generation_without_resend(execution, monkeypatch):
    from dataclasses import replace
    from temporalio.client import Client, WorkflowFailureError, WorkflowExecutionStatus
    from temporalio.worker import Worker
    from apps.api.app.infrastructure.config.agent_runtime_config import temporal_gateway_config_from_env
    from apps.api.app.infrastructure.workflow.generation_runtime import TemporalGenerationRuntime, build_generation_activities
    from apps.api.app.infrastructure.workflow.nasus_generation_workflow import NasusTestDesignGenerationWorkflow
    v = execution
    ident = queued(v)
    monkeypatch.setenv("NASUS_AGENT_WORKFLOW_RUNTIME", "temporal")
    async def verify():
        entered, stopped = asyncio.Event(), asyncio.Event()
        async def stalled(*args, **kwargs):
            entered.set()
            try:
                await asyncio.sleep(120)
            except asyncio.CancelledError:
                stopped.set()
                raise
        monkeypatch.setattr(v["executor"].provider, "generate", stalled)
        config = replace(temporal_gateway_config_from_env(), address=os.environ["TEST_TEMPORAL_ADDRESS"],
            task_queue="nasus-generation-cancel-test-" + uuid4().hex)
        client = await Client.connect(config.address, namespace=config.namespace)
        runtime = TemporalGenerationRuntime(config, client)
        async with Worker(client, task_queue=runtime.task_queue, workflows=[NasusTestDesignGenerationWorkflow],
                activities=build_generation_activities()):
            assert await runtime.start(ident)
            handle = client.get_workflow_handle("nasus-test-design-generation:" + ident)
            try:
                await asyncio.wait_for(entered.wait(), 60)
                v["workflow"].cancel.side_effect = RuntimeError("cancellation acknowledgement lost")
                pending = await asyncio.to_thread(invoke, v, GENERATION_CANCEL_TOOL,
                    {"project_id": v["project_id"], "invocation_id": ident}, key=uuid4().hex)
                assert pending.json()["status"] == "waiting_confirmation"
                assert "cancelled" in completed(await asyncio.to_thread(confirm, v, pending.json()))["summary"]
                repository = v["jobs"].repository
                scoped = SimpleNamespace(pending=lambda **kw: [],
                    pending_cancellations=lambda **kw: [(ident, v["project_id"])] if kw.get("after_id") is None else [],
                    cancellation_delivered=repository.cancellation_delivered)
                await reconcile_generation_jobs_once(runtime, scoped)
                with pytest.raises(WorkflowFailureError):
                    await asyncio.wait_for(handle.result(), 30)
                assert (await handle.describe()).status == WorkflowExecutionStatus.CANCELED
                await asyncio.wait_for(stopped.wait(), 5)
            finally:
                await handle.cancel()
    asyncio.run(verify())
    assert count(v, Reservation) == 1 and count(v, Reply) == count(v, Result) == 0
    assert asyncio.run(v["jobs"].run(ident)) == "cancelled"
