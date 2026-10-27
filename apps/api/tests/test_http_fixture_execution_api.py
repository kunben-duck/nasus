"""Real PG/MinIO worker composition; HTTP/build/health transports are specimens."""
import asyncio
import importlib
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, literal, select, text, update, delete
from sqlalchemy.exc import DBAPIError

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.http_fixture_execution import HttpFixtureExecutionSelection
from apps.api.app.application.quality_loop.http_fixture_commands import HttpFixtureCommandAuthority
from apps.api.app.application.quality_loop.http_fixture_history import HttpFixtureHistoryQuery
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.environment_observation_record import ENVIRONMENT_RECORD_TOOL
from apps.api.app.domain.quality_loop.http_fixture_grant import GRANT_TOOL, NATIVE_GRANT_SCHEMA
from apps.api.app.domain.quality_loop.http_fixture_recipe import RECIPE_TOOL
from apps.api.app.domain.quality_loop.http_fixture_command import FIXTURE_COMMAND_TOOL, FIXTURE_CANCEL_TOOL, FIXTURE_CANONICAL_DISPATCH_SCHEMA
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.domain.quality_loop.run_plan import RUN_PLAN_BINDING_SCHEMA
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, SSEEventOutboxRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.http_fixture_command_models import HttpFixtureCommandRecord, HttpFixtureDispatchCommandRecord
from apps.api.app.infrastructure.persistence.http_fixture_job_models import HttpFixtureCancellationRecord, HttpFixtureCancellationDeliveryRecord
from apps.api.app.infrastructure.persistence.http_fixture_preparation_models import HttpFixturePreparationRecord, HttpFixturePreparationBindingRecord
from apps.api.app.infrastructure.persistence.http_fixture_preparation_cancel_models import HttpFixturePreparationCancellationRecord, HttpFixturePreparationCancellationDeliveryRecord
from apps.api.app.infrastructure.persistence.http_fixture_dispatch_consent_models import HttpFixtureDispatchConsentRecord
from apps.api.app.infrastructure.persistence.http_fixture_grant_repository import HttpFixtureGrantRepository
from apps.api.app.infrastructure.persistence.http_fixture_history_repository import HttpFixtureHistoryRepository
from apps.api.app.infrastructure.persistence.http_fixture_journal_models import HttpFixtureDispatchRecord, HttpFixtureResultRecord
from apps.api.app.infrastructure.persistence.http_fixture_work_models import HttpFixtureDispatchOwnershipRecord, HttpFixtureWorkLeaseRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.runner.owned_target_environment import OwnedTargetEnvironmentInspector
from apps.api.app.infrastructure.runner.owned_target_health import OwnedTargetHealthInspector
from apps.api.app.infrastructure.workflow.http_fixture_runtime import reconcile_http_fixtures_once
from apps.api.tests.test_http_bindings import specimen
from apps.api.tests.test_http_fixtures import Runner, manifest
from apps.api.tests.test_owned_target_environment import Commands, spec
from apps.api.tests.test_owned_target_health import HealthCommands
from apps.api.tests.test_run_plan_builds_api import (
    base_evidence_api, evidence_api, documents, publication, design_scope, generation_result, mapping, native_scripts,
    prepared_binding, submit_binding, read_binding,
)
from apps.api.tests.test_run_plans_api import select_binding_scripts
from apps.api.tests.test_semantic_evaluations_api import completed, invoke, confirm


def journal_snapshot(project_id):
    models = (HttpFixtureDispatchRecord, HttpFixtureResultRecord, HttpFixtureDispatchOwnershipRecord,
        HttpFixtureDispatchConsentRecord, HttpFixtureWorkLeaseRecord, HttpFixtureCommandRecord, HttpFixtureDispatchCommandRecord)
    with session_scope() as session:
        result = {model.__tablename__: [deepcopy({c.name: getattr(row, c.name) for c in model.__table__.columns})
            for row in session.scalars(select(model).where(model.project_id == project_id)).all()] for model in models}
        identifiers = [value["claim_id"] for value in result[HttpFixtureDispatchRecord.__tablename__]]
        identifiers.extend(value["invocation_id"] for value in result[HttpFixtureCommandRecord.__tablename__])
        for model in (AuditEventRecord, SSEEventOutboxRecord):
            result[model.__tablename__] = [deepcopy({c.name: getattr(row, c.name) for c in model.__table__.columns})
                for row in session.scalars(select(model).where(model.entity_id.in_(identifiers))).all()]
        return result


@pytest.fixture
def composed_fixture_execution(native_scripts, spec, monkeypatch):
    v = native_scripts
    select_binding_scripts(v)
    owned = replace(spec, project_id=v["project_id"])
    environment = {"environment_id": owned.environment_id, "kind": "local", "base_url": "http://127.0.0.1:8080",
        "inventory_hash": owned.digest, "isolation": "Original instance and transport protocol specimen"}
    def recipe(declaration):
        value = {**manifest(), **{key: declaration[key] for key in ("case_id", "preconditions_digest", "setup", "cleanup")}}
        value["setup_steps"][-1]["value_json"] = '"EXPLICIT_INDEPENDENT_EXPECTED"'
        return value
    v = prepared_binding(v, monkeypatch, environment=environment, fixture_recipe=recipe,
        policy_revision=RUN_PLAN_BINDING_SCHEMA)
    bound = completed(submit_binding(v))
    binding_id = bound["result"]["object_refs"][0].split(":", 1)[1]
    binding = read_binding(v, binding_id).json()
    plan = v["original_plan"]
    request = {"project_id": v["project_id"], "run_plan_id": plan["metadata"]["run_plan_id"],
        "run_plan_artifact_hash": plan["metadata"]["artifact_hash"], "build_binding_id": binding_id,
        "build_binding_artifact_hash": binding["metadata"]["artifact_hash"]}
    commands, health_commands = Commands(owned), HealthCommands(owned)
    commands.body = health_commands.body = binding["metadata"]["target_artifact_hash"][7:].encode() + b"  /app/target.jar\n"
    class Environment:
        def policy_digest(self, project, ident, *, require_work):
            assert (project, ident) == (owned.project_id, owned.environment_id)
            require_work()
            return owned.digest
        def inspect(self, project, ident, digest, *, require_work):
            assert (project, ident) == (owned.project_id, owned.environment_id)
            return OwnedTargetEnvironmentInspector(owned, command=commands).inspect(digest, require_work=require_work)
        def inspect_health(self, project, ident, digest, *, require_work):
            assert (project, ident) == (owned.project_id, owned.environment_id)
            return OwnedTargetHealthInspector(owned, command=health_commands).inspect(digest, require_work=require_work)
    monkeypatch.setattr(app.state.container.run_plan_environments, "environments", Environment())
    monkeypatch.setattr(app.state.container.run_plan_environment_health, "health", Environment())
    environment_record = completed(confirm(v, invoke(v, ENVIRONMENT_RECORD_TOOL, request, key=uuid4().hex).json()))
    env_metadata = environment_record["result"]["run_plan_environment_record"]["metadata"]
    registered = completed(confirm(v, invoke(v, RECIPE_TOOL, {
        **{key: request[key] for key in ("project_id", "run_plan_id", "run_plan_artifact_hash")},
        "manifest": v["fixture_manifest"]}, key=uuid4().hex).json()))
    recipe_metadata = registered["result"]["http_fixture_recipe"]["metadata"]
    consent = {"project_id": v["project_id"], "recipe_id": recipe_metadata["record_id"],
        "recipe_artifact_hash": recipe_metadata["artifact_hash"], "attempt_id": "composed-" + uuid4().hex,
        "operation": "setup", "timeout_ms": 10000, "policy_revision": NATIVE_GRANT_SCHEMA,
        "environment_record_id": env_metadata["record_id"], "environment_record_artifact_hash": env_metadata["artifact_hash"]}
    def grant(operation):
        saved = completed(confirm(v, invoke(v, GRANT_TOOL, {**consent, "operation": operation}, key=uuid4().hex).json()))
        metadata = saved["result"]["http_fixture_grant"]["metadata"]
        return HttpFixtureExecutionSelection(project_id=v["project_id"], grant_id=metadata["record_id"],
            grant_digest=metadata["grant_digest"], operation=operation)
    chosen = grant("setup")
    executor = app.state.container.http_fixture_execution
    runner = Runner()
    runner.payload = lambda command: (specimen(command, states=["passed", "passed", "passed", "failed"], status="failed")
        if command.metadata["fixture_phase"] == "setup" else specimen(command))
    monkeypatch.setattr(executor.runtimes, "runner", runner)
    actor = UserProfile.model_validate(v["owner"])
    return SimpleNamespace(v=v, executor=executor, runner=runner, actor=actor, chosen=chosen,
        grant=grant, environment_metadata=env_metadata)


def test_project_history_pg_discovers_pending_and_cancelled_originals_without_effects(composed_fixture_execution, monkeypatch):
    """Actual persisted ancestry/filtering; workflow delivery remains an explicit double."""
    fixture, delivered = composed_fixture_execution, []
    v = fixture.v
    jobs = app.state.container.http_fixture_jobs
    class Workflow:
        async def start(self, ident): delivered.append(("start", ident)); return True
        async def cancel(self, ident): delivered.append(("cancel", ident))
    monkeypatch.setattr(jobs, "workflow", Workflow())
    with actor_scope(fixture.actor):
        original = jobs.grants.history_request(v["project_id"], fixture.chosen.grant_id)
    waiting_grant = invoke(v, GRANT_TOOL, original.model_dump(mode="json"), key=uuid4().hex)
    assert waiting_grant.status_code == 200 and waiting_grant.json()["status"] == "waiting_confirmation"
    waiting_execute = invoke(v, FIXTURE_COMMAND_TOOL, fixture.chosen.model_dump(mode="json"), key=uuid4().hex)
    assert waiting_execute.status_code == 200 and waiting_execute.json()["status"] == "waiting_confirmation"
    execute_id = waiting_execute.json()["id"]
    base = f"/v1/projects/{v['project_id']}/quality/http-fixture-operations"
    def pages():
        result, after, total = [], "", None
        for _ in range(10):
            response = v["client"].get(base, params={"limit": 1, "after_id": after}, headers=v["headers"])
            assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store", response.text
            page = response.json()
            assert total is None or total == page["total"]
            total = page["total"]
            result.extend(page["items"])
            if page["next_after_id"] is None: break
            assert page["next_after_id"] > after
            after = page["next_after_id"]
        else: pytest.fail("fixture history pagination failed to terminate")
        assert len(result) == total and len({item["invocation_id"] for item in result}) == total
        return {item["invocation_id"]: item for item in result}
    before = journal_snapshot(v["project_id"])
    pending = pages()
    assert pending[execute_id]["status"] == pending[waiting_grant.json()["id"]]["status"] == "waiting_confirmation"
    pending_observation = v["client"].get(base + "/" + execute_id + "/observation", headers=v["headers"])
    assert pending_observation.status_code == 200 and pending_observation.json()["state"] == "not_confirmed"
    assert pending_observation.json()["job"] is None and pending_observation.json()["expected_phases"] == []
    assert journal_snapshot(v["project_id"]) == before and not fixture.runner.commands and not delivered
    # Confirm only the original execute command; the transport double starts no target activity.
    assert confirm(v, waiting_execute.json()).status_code == 200
    assert delivered == [("start", execute_id)]
    control = invoke(v, FIXTURE_CANCEL_TOOL, {"project_id": v["project_id"], "invocation_id": execute_id}, key=uuid4().hex)
    assert control.status_code == 200 and control.json()["status"] == "waiting_confirmation", control.text
    assert confirm(v, control.json()).status_code == 200
    assert delivered == [("start", execute_id), ("cancel", execute_id)]
    before = journal_snapshot(v["project_id"])
    history = pages()
    assert history[execute_id]["status"] == "cancelled"
    assert history[control.json()["id"]]["original_execution_id"] == execute_id
    assert history[control.json()["id"]]["stage"] == "cancel" and history[control.json()["id"]]["status"] == "completed"
    response = v["client"].get(base + "/" + execute_id, headers=v["headers"])
    assert response.status_code == 200 and response.json() == history[execute_id]
    observed = v["client"].get(base + "/" + control.json()["id"] + "/observation", headers=v["headers"])
    assert observed.status_code == 200 and observed.headers["cache-control"] == "private, no-store", observed.text
    assert observed.json()["execution"] == history[execute_id]
    assert observed.json()["selected"] == history[control.json()["id"]]
    assert observed.json()["state"] == "not_dispatched" and observed.json()["job"]["phases"][0]["state"] == "not_dispatched"
    assert observed.json()["business_coverage_verified"] is False and observed.json()["baseline_restored"] is False
    assert not fixture.runner.commands and journal_snapshot(v["project_id"]) == before
    assert v["client"].get(base, headers=v["member_headers"]).status_code == 403
    with actor_scope(fixture.actor):
        scope = jobs.grants.authorization.scope(v["project_id"])
        visible = HttpFixtureHistoryRepository().list_history(HttpFixtureHistoryQuery(project_id=v["project_id"], limit=5),
            binding_ids=tuple(sorted(scope.binding_ids)))
        hidden = HttpFixtureHistoryRepository().list_history(HttpFixtureHistoryQuery(project_id=v["project_id"], limit=5), binding_ids=())
        assert visible["total"] == len(history) and hidden["total"] == 0 and hidden["items"] == hidden["lookahead"] == []
        with pytest.raises(KeyError): HttpFixtureHistoryRepository().read_history(v["project_id"], execute_id, binding_ids=())
    with session_scope() as session:
        assert session.get_bind().dialect.name == "postgresql"
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
        assert session.scalars(select(HttpFixtureDispatchRecord).where(HttpFixtureDispatchRecord.project_id == v["project_id"])).all() == []


@pytest.mark.parametrize("command_mode", ["private", "original-command", "cancelled-command"])
def test_composed_worker_keeps_original_failed_oracle_and_read_only_history(composed_fixture_execution, monkeypatch, command_mode):
    fixture = composed_fixture_execution
    v, executor, runner, actor = fixture.v, fixture.executor, fixture.runner, fixture.actor
    chosen, grant, env_metadata = fixture.chosen, fixture.grant, fixture.environment_metadata
    def command_options(selection):
        if command_mode == "private": return {}
        # Explicit canonical-record specimen, not the public Tool runtime.
        # Public registration alone does not turn this into dispatch evidence.
        ident = str(uuid4())
        payload = {**selection.model_dump(mode="json"), "confirmed_by_user": True,
            "confirmed_actor_id": actor.id, "confirmed_at": datetime.now(timezone.utc).isoformat()}
        with session_scope() as session:
            session.add(ToolInvocationRecord(id=ident, tool_id=FIXTURE_COMMAND_TOOL, status="running",
                conversation_id=v["conversation"].json()["id"], input_payload=payload,
                summary="Original command provenance protocol specimen"))
        return {"command_authority": HttpFixtureCommandAuthority(invocation_id=ident,
            request_digest=acceptance_digest({"tool_id": FIXTURE_COMMAND_TOOL, "input_payload": payload}))}
    setup_options = command_options(chosen)
    if command_mode == "cancelled-command":
        original_payload = runner.payload
        def cancelled_payload(command):
            response = original_payload(command)
            with session_scope() as session:
                row = session.scalar(select(ToolInvocationRecord).where(
                    ToolInvocationRecord.id == setup_options["command_authority"].invocation_id).with_for_update())
                row.status = "cancelled"
            return response
        runner.payload = cancelled_payload
        with actor_scope(actor):
            with pytest.raises(HttpFixtureInvalid):
                asyncio.run(executor.execute(chosen, require_current=lambda: None, **setup_options))
            before = journal_snapshot(v["project_id"])
            assert len(before[HttpFixtureDispatchRecord.__tablename__]) == len(before[HttpFixtureDispatchCommandRecord.__tablename__]) == 1
            assert before[HttpFixtureResultRecord.__tablename__] == [] and len(runner.commands) == 1
            assert executor.read(chosen, require_current=lambda: None)[0][1].execution is None
            with pytest.raises(HttpFixtureInvalid):
                asyncio.run(executor.execute(chosen, require_current=lambda: None, **setup_options))
            assert journal_snapshot(v["project_id"]) == before and len(runner.commands) == 1
        return
    with actor_scope(actor):
        prepared = asyncio.run(executor.execute(chosen, require_current=lambda: None, **setup_options))
        assert prepared.execution.result.status == "failed" and prepared.receipt["failed_assertion_count"] == 1
        assert len(runner.commands) == 1 and runner.commands[0].steps[-1]["value_json"] == '"EXPLICIT_INDEPENDENT_EXPECTED"'
        assert runner.commands[0].metadata["fixture_scope"]["inventory_hash"] == env_metadata["inventory_hash"]
        before = journal_snapshot(v["project_id"])
        record = before[HttpFixtureDispatchRecord.__tablename__][0]["payload"]
        assert record["schema"] == (FIXTURE_CANONICAL_DISPATCH_SCHEMA if setup_options else "nasus.http-fixture-dispatch.v3")
        if setup_options:
            assert record["canonical_command"]["invocation_id"] == setup_options["command_authority"].invocation_id
            assert len(before[HttpFixtureCommandRecord.__tablename__]) == len(before[HttpFixtureDispatchCommandRecord.__tablename__]) == 1
        assert record["operation_consent"]["grant_id"] == chosen.grant_id
        assert len(before[HttpFixtureDispatchOwnershipRecord.__tablename__]) == len(before[HttpFixtureDispatchConsentRecord.__tablename__]) == 1
        assert len(before[AuditEventRecord.__tablename__]) == len(before[SSEEventOutboxRecord.__tablename__]) == (3 if setup_options else 2)
        assert before[HttpFixtureResultRecord.__tablename__][0]["status"] == "failed"
        with monkeypatch.context() as expired:
            expired.setattr(HttpFixtureGrantRepository, "_clock", staticmethod(lambda: literal(datetime.now(timezone.utc) + timedelta(hours=1))))
            history = executor.read(chosen, require_current=lambda: None)
            assert history[0][0] == "setup" and history[0][1].execution.result_body == prepared.execution.result_body
            assert journal_snapshot(v["project_id"]) == before and len(runner.commands) == 1
            with pytest.raises(PermissionError):
                asyncio.run(executor.execute(chosen, require_current=lambda: None, **setup_options))
            assert journal_snapshot(v["project_id"]) == before and len(runner.commands) == 1
    cleanup_selection = grant("cleanup")
    cleanup_options = command_options(cleanup_selection)
    with actor_scope(actor):
        cleaned = asyncio.run(executor.execute(cleanup_selection, require_current=lambda: None, **cleanup_options))
        assert cleaned.cleanup_verified and len(runner.commands) == 2
        assert runner.commands[1].steps[0]["path"] == "/sessions/session_original/close"
        assert not cleaned.business_coverage_verified and not cleaned.baseline_restored and not cleaned.execution_authorized
        before = journal_snapshot(v["project_id"])
        history = executor.read(cleanup_selection, require_current=lambda: None)
        assert [phase for phase, _record in history] == ["setup", "cleanup:session"]
        assert journal_snapshot(v["project_id"]) == before and len(runner.commands) == 2
        assert all(row["payload"][key] is False for row in before[HttpFixtureResultRecord.__tablename__]
            for key in ("execution_authorized", "canonical_execution_committed", "business_coverage_verified", "baseline_restored"))


@pytest.mark.parametrize("cancel_cleanup", [False, True])
def test_public_fixture_tool_dispatch_and_cancel_keep_original_pg_commands(composed_fixture_execution, monkeypatch, cancel_cleanup):
    """Actual public ToolRuntime, PG and MinIO; Temporal/target transports are doubles."""
    fixture = composed_fixture_execution
    v, runner = fixture.v, fixture.runner
    jobs = app.state.container.http_fixture_jobs
    workflow_calls = []
    async def start(ident): workflow_calls.append(("start", ident)); return True
    async def cancel(ident): workflow_calls.append(("cancel", ident))
    monkeypatch.setattr(jobs.workflow, "start", start)
    monkeypatch.setattr(jobs.workflow, "cancel", cancel)

    def dispatch(selection):
        key = uuid4().hex
        request = selection.model_dump(mode="json")
        pending = invoke(v, FIXTURE_COMMAND_TOOL, request, key=key)
        assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
        assert len(runner.commands) == (0 if selection.operation == "setup" else 1)
        response = confirm(v, pending.json())
        assert response.status_code == 200 and response.json()["status"] == "running", response.text
        ident = response.json()["id"]
        with session_scope() as session:
            preparation = session.get(HttpFixturePreparationRecord, ident)
            binding = session.get(HttpFixturePreparationBindingRecord, ident)
            intent = session.get(HttpFixtureCommandRecord, ident)
            assert preparation is not None and binding is not None and intent is not None
            assert binding.preparation_digest == preparation.content_hash and binding.intent_digest == intent.content_hash
            assert preparation.request_digest == intent.request_digest
        assert workflow_calls[-1] == ("start", ident)
        replay = invoke(v, FIXTURE_COMMAND_TOOL, request, key=key)
        assert replay.status_code == 200 and replay.json()["id"] == ident, replay.text
        assert workflow_calls.count(("start", ident)) == 1
        return ident

    def read(ident):
        response = v["client"].get(f"/v1/projects/{v['project_id']}/quality/http-fixture-executions/{ident}", headers=v["headers"])
        assert response.status_code == 200 and response.headers["Cache-Control"] == "private, no-store", response.text
        result = response.json()
        assert result["invocation_id"] == ident and all(result[key] is False for key in
            ("execution_authorized", "canonical_execution_committed", "business_coverage_verified", "baseline_restored"))
        return result

    original = dispatch(fixture.chosen)
    initial = read(original)
    assert initial["status"] == "running" and [item["state"] for item in initial["phases"]] == ["not_dispatched"]
    assert not runner.commands
    with actor_scope(fixture.actor):
        assert asyncio.run(jobs.run(original)) == "completed"
        assert asyncio.run(jobs.run(original)) == "completed"
    observed = read(original)
    assert observed["status"] == "completed" and observed["phases"][0]["state"] == "observed"
    assert observed["phases"][0]["result_status"] == "failed" and len(runner.commands) == 1
    assert runner.commands[0].steps[-1]["value_json"] == '"EXPLICIT_INDEPENDENT_EXPECTED"'

    # Another command cannot adopt the original grant/work, even after completion.
    duplicate = invoke(v, FIXTURE_COMMAND_TOOL, fixture.chosen.model_dump(mode="json"), key=uuid4().hex)
    rejected = confirm(v, duplicate.json())
    assert rejected.status_code == 200 and rejected.json()["status"] == "failed", rejected.text
    assert read(original) == observed and len(runner.commands) == 1
    assert workflow_calls == [("start", original)]

    cleanup = dispatch(fixture.grant("cleanup"))
    if cancel_cleanup:
        control = invoke(v, FIXTURE_CANCEL_TOOL, {"project_id": v["project_id"], "invocation_id": cleanup}, key=uuid4().hex)
        assert control.status_code == 200 and control.json()["status"] == "waiting_confirmation", control.text
        completed(confirm(v, control.json()))
        cancelled = read(cleanup)
        assert cancelled["status"] == "cancelled" and cancelled["cancellation_requested"] and cancelled["cancellation_delivered"]
        assert [item["state"] for item in cancelled["phases"]] == ["not_dispatched"]
        with actor_scope(fixture.actor):
            assert asyncio.run(jobs.run(cleanup)) == asyncio.run(jobs.fail(cleanup)) == "cancelled"
        assert read(cleanup) == cancelled and workflow_calls[-1] == ("cancel", cleanup)
        assert len(runner.commands) == 1
        with session_scope() as session:
            assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
            for model in (HttpFixtureCancellationRecord, HttpFixtureCancellationDeliveryRecord,
                    HttpFixturePreparationRecord, HttpFixturePreparationBindingRecord):
                for statement in (update(model).where(model.invocation_id == cleanup).values(content_hash="changed"),
                        delete(model).where(model.invocation_id == cleanup)):
                    with pytest.raises(DBAPIError):
                        with session.begin_nested(): session.execute(statement)
                assert session.get(model, cleanup) is not None
            migration = importlib.import_module("apps.api.migrations.versions.0115_fixture_job_cancellations")
            with Operations.context(MigrationContext.configure(session.connection())):
                with pytest.raises(RuntimeError, match="Cannot discard populated"):
                    migration.downgrade()
            assert all(inspect(session.connection()).has_table(model.__tablename__) for model in
                (HttpFixtureCancellationRecord, HttpFixtureCancellationDeliveryRecord))
        assert read(cleanup) == cancelled
    else:
        with actor_scope(fixture.actor): assert asyncio.run(jobs.run(cleanup)) == "completed"
        cleaned = read(cleanup)
        assert cleaned["status"] == "completed" and [item["state"] for item in cleaned["phases"]] == ["observed"]
        assert runner.commands[-1].steps[0]["path"] == "/sessions/session_original/close" and len(runner.commands) == 2


def test_public_unbound_preparation_survives_transport_failure_and_recovers_same_command(composed_fixture_execution, monkeypatch):
    """Public claim + actual PG/MinIO; explicit Temporal/target transport doubles."""
    fixture = composed_fixture_execution
    v, jobs, runner = fixture.v, app.state.container.http_fixture_jobs, fixture.runner
    calls = []
    async def start(ident): calls.append(ident); return True
    monkeypatch.setattr(jobs.workflow, "start", start)
    pending = invoke(v, FIXTURE_COMMAND_TOOL, fixture.chosen.model_dump(mode="json"), key=uuid4().hex)
    assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
    ident = pending.json()["id"]
    def unavailable(*args): raise RuntimeError("explicit transient preparation failure before binding")
    with monkeypatch.context() as outage:
        outage.setattr(jobs, "_prepare", unavailable)
        response = confirm(v, pending.json())
    assert response.status_code == 200 and response.json()["status"] == "running", response.text
    assert not calls and not runner.commands
    with session_scope() as session:
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
        command = session.get(ToolInvocationRecord, ident)
        original_payload = deepcopy(command.input_payload)
        receipt = deepcopy(session.get(HttpFixturePreparationRecord, ident).payload)
        assert session.get(HttpFixtureCommandRecord, ident) is None
        assert session.get(HttpFixturePreparationBindingRecord, ident) is None
    with monkeypatch.context() as readonly:
        def forbidden(*args, **kwargs): pytest.fail("unbound preparation must not open a target execution archive")
        readonly.setattr(jobs.execution, "read", forbidden)
        response = v["client"].get(f"/v1/projects/{v['project_id']}/quality/http-fixture-executions/{ident}", headers=v["headers"])
    assert response.status_code == 200 and response.headers["Cache-Control"] == "private, no-store", response.text
    assert response.json()["schema"] == "nasus.http-fixture-job.v2" and response.json()["phase"] == "preparing"
    assert response.json()["preparation_digest"] == acceptance_digest(receipt) and response.json()["intent_digest"] is None
    assert not response.json()["phases"] and response.json()["target_observation_verified"] is False
    assert asyncio.run(jobs.deliver(ident)) == "running"
    assert calls == [ident] and not runner.commands
    with session_scope() as session:
        command = session.get(ToolInvocationRecord, ident)
        assert command.input_payload == original_payload
        assert session.get(HttpFixturePreparationRecord, ident).payload == receipt
        assert session.get(HttpFixturePreparationBindingRecord, ident).intent_digest == session.get(HttpFixtureCommandRecord, ident).content_hash
    with actor_scope(fixture.actor): assert asyncio.run(jobs.run(ident)) == "completed"
    assert len(runner.commands) == 1 and runner.commands[0].steps[-1]["value_json"] == '"EXPLICIT_INDEPENDENT_EXPECTED"'
    assert asyncio.run(jobs.deliver(ident)) == "completed" and calls == [ident]


@pytest.mark.parametrize("cancel_transport_down", [False, True])
def test_public_preparation_cancel_is_durable_before_rpc_and_never_creates_execution_history(
        composed_fixture_execution, monkeypatch, cancel_transport_down):
    """Actual public commands/PG/MinIO; explicit Temporal and target doubles."""
    fixture = composed_fixture_execution
    v, jobs, runner = fixture.v, app.state.container.http_fixture_jobs, fixture.runner
    target_path = f"/v1/projects/{v['project_id']}/quality/http-fixture-executions/"
    calls = []
    async def start(_): pytest.fail("cancelled preparation must never start its workflow")
    async def cancel(ident):
        calls.append(ident)
        if cancel_transport_down: raise RuntimeError("explicit unavailable cancellation transport")
    monkeypatch.setattr(jobs.workflow, "start", start)
    monkeypatch.setattr(jobs.workflow, "cancel", cancel)
    key = uuid4().hex
    pending = invoke(v, FIXTURE_COMMAND_TOOL, fixture.chosen.model_dump(mode="json"), key=key)
    assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
    ident = pending.json()["id"]
    def unavailable(*args): raise RuntimeError("explicit preparation outage before intent binding")
    with monkeypatch.context() as outage:
        outage.setattr(jobs, "_prepare", unavailable)
        response = confirm(v, pending.json())
    assert response.status_code == 200 and response.json()["status"] == "running", response.text
    with session_scope() as session:
        original = deepcopy(session.get(ToolInvocationRecord, ident).input_payload)
        preparation = deepcopy(session.get(HttpFixturePreparationRecord, ident).payload)
    def forbidden(*args, **kwargs): pytest.fail("preparation observation/cancel must not open target history")
    monkeypatch.setattr(jobs.execution, "read", forbidden)
    control = invoke(v, FIXTURE_CANCEL_TOOL, {"project_id": v["project_id"], "invocation_id": ident}, key=uuid4().hex)
    assert control.status_code == 200 and control.json()["status"] == "waiting_confirmation", control.text
    completed(confirm(v, control.json()))
    response = v["client"].get(target_path + ident, headers=v["headers"])
    assert response.status_code == 200 and response.headers["Cache-Control"] == "private, no-store", response.text
    observed = response.json()
    assert observed["status"] == "cancelled" and observed["phase"] == "preparation_cancelled"
    assert observed["intent_digest"] is None and observed["preparation_digest"] == acceptance_digest(preparation)
    assert observed["cancellation_requested"] and observed["cancellation_delivered"] is not cancel_transport_down
    assert not observed["phases"] and observed["target_observation_verified"] is False
    assert all(observed[field] is False for field in
        ("execution_authorized", "canonical_execution_committed", "business_coverage_verified", "baseline_restored"))
    assert calls == [ident] and not runner.commands
    assert asyncio.run(jobs.deliver(ident)) == asyncio.run(jobs.fail(ident)) == "cancelled"
    replay = invoke(v, FIXTURE_COMMAND_TOOL, fixture.chosen.model_dump(mode="json"), key=key)
    assert replay.status_code == 200 and replay.json()["id"] == ident and replay.json()["status"] == "cancelled", replay.text
    if cancel_transport_down:
        assert (ident, v["project_id"]) in jobs.repository.pending_cancellations()
        cancel_transport_down = False
        # Restrict this transport specimen to the current test's original task;
        # actual pending queries and delivery writes still use PostgreSQL.
        own_pending = SimpleNamespace(pending=lambda **_: [],
            pending_cancellations=lambda **kwargs: [row for row in jobs.repository.pending_cancellations(**kwargs) if row[0] == ident],
            cancellation_delivered=jobs.repository.cancellation_delivered)
        asyncio.run(reconcile_http_fixtures_once(jobs.workflow, own_pending, jobs=jobs))
        assert len(calls) == 2
        response = v["client"].get(target_path + ident, headers=v["headers"])
        assert response.status_code == 200 and response.json()["cancellation_delivered"] is True, response.text
    with session_scope() as session:
        assert session.get(ToolInvocationRecord, ident).input_payload == original
        assert session.get(HttpFixturePreparationRecord, ident).payload == preparation
        record = session.get(HttpFixturePreparationCancellationRecord, ident)
        assert record.control_id == control.json()["id"] and record.preparation_digest == acceptance_digest(preparation)
        assert session.get(HttpFixturePreparationCancellationDeliveryRecord, ident).cancellation_digest == record.content_hash
        assert session.get(HttpFixtureCommandRecord, ident) is None and session.get(HttpFixturePreparationBindingRecord, ident) is None
        assert session.get(HttpFixtureCancellationRecord, ident) is None
        assert session.scalars(select(HttpFixtureDispatchRecord).where(HttpFixtureDispatchRecord.project_id == v["project_id"])).all() == []
        assert session.scalars(select(HttpFixtureResultRecord).where(HttpFixtureResultRecord.project_id == v["project_id"])).all() == []
    assert not runner.commands
