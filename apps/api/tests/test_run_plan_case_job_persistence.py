"""Actual lifecycle adapter rules with explicit sessions; no actual PostgreSQL proof."""
from copy import deepcopy
from datetime import timedelta
import importlib
import io
from types import SimpleNamespace

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import MetaData, Table

from apps.api.app.application.quality_loop.run_plan_case_jobs import RunPlanCaseJobTarget
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.run_plan_case_execution import CASE_CANCEL_TOOL, RunPlanCaseExecutionInvalid, RunPlanCaseWorkBusy
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.run_plan_case_job_models import RunPlanCaseJobCancellationRecord as Cancellation, RunPlanCaseJobCancellationDeliveryRecord as Delivery
from apps.api.app.infrastructure.persistence.run_plan_case_cancellation_journal import RunPlanCaseCancellationJournal
from apps.api.app.infrastructure.persistence.run_plan_case_execution_repository import PostgresRunPlanCaseExecutionRepository as Cases
from apps.api.app.infrastructure.persistence.run_plan_case_execution_models import RunPlanCaseClaimRecord as Claim, RunPlanCaseOutcomeRecord as Outcome
from apps.api.app.infrastructure.persistence.run_plan_case_job_repository import RunPlanCaseJobRepository as Repository
from apps.api.tests.test_run_plan_case_preparation import preparing


@pytest.fixture
def lifecycle(preparing, monkeypatch):
    v = preparing
    v.claim()
    v.target = RunPlanCaseJobTarget(project_id=v.scope.project_id, invocation_id=v.command.id)
    v.control = SimpleNamespace(id="independent-case-cancel", tool_id=CASE_CANCEL_TOOL, status="running", revision=1,
        conversation_id=None, input_payload={**v.target.model_dump(mode="json"), "confirmed_by_user": True,
            "confirmed_actor_id": "other-current-admin", "confirmed_at": v.session.now.isoformat()})
    v.rows[(ToolInvocationRecord, v.control.id)] = v.control
    scalar = v.session.scalar
    def query_value(query):
        if query.column_descriptions[0].get("entity") is ToolInvocationRecord:
            return v.rows.get((ToolInvocationRecord, query.compile().params["id_1"]))
        return scalar(query)
    v.session.scalar = query_value
    monkeypatch.setattr(Repository, "_event", staticmethod(lambda _session, command, **_: v.events.append(command.status)))
    import apps.api.app.infrastructure.persistence.run_plan_case_job_repository as module
    from contextlib import contextmanager
    @contextmanager
    def opened(): yield v.session
    monkeypatch.setattr(module, "session_scope", opened)
    v.jobs = Repository()
    v.cancel = lambda: v.jobs.cancel(v.target, control_id=v.control.id, actor_id="other-current-admin", require_current=lambda: None)
    return v


@pytest.mark.parametrize("bound", [False, True])
def test_independent_cancel_fences_original_preparation_or_work_before_delivery(lifecycle, bound):
    v = lifecycle
    if bound: v.acquire()
    assert v.cancel() == "cancelled"
    value = v.rows[(Cancellation, v.command.id)].payload
    assert value["actor_id"] == "other-current-admin" and value["control_id"] == v.control.id
    assert value["command_digest"] == v.current_scope().command_digest
    assert v.jobs.command(v.target)["status"] == "cancelled"
    assert v.jobs.command(v.target)["scope"] is not None if bound else v.jobs.command(v.target)["scope"] is None
    assert (Delivery, v.command.id) not in v.rows
    if bound: assert Cases._cancelled(v.session, v.current_scope()) is True
    before = len(v.added)
    v.jobs.cancellation_delivered(v.command.id)
    v.jobs.cancellation_delivered(v.command.id)
    assert len(v.added) == before + 1
    assert v.rows[(Delivery, v.command.id)].payload["cancellation_digest"] == acceptance_digest(value)
    with pytest.raises(RunPlanCaseExecutionInvalid): v.acquire()


@pytest.mark.parametrize("fault", ["tool", "actor", "target", "extra", "not_confirmed", "expired", "future", "naive"])
def test_invalid_cancel_never_fences_original_or_creates_request(lifecycle, fault):
    v = lifecycle
    if fault == "tool": v.control.tool_id = "quality.http_fixture.cancel"
    elif fault == "actor": v.control.input_payload["confirmed_actor_id"] = "other"
    elif fault == "target": v.control.input_payload["invocation_id"] = "other"
    elif fault == "extra": v.control.input_payload["scope_digest"] = v.current_scope().digest
    elif fault == "not_confirmed": v.control.input_payload["confirmed_by_user"] = 1
    elif fault == "expired": v.session.now += timedelta(seconds=901)
    elif fault == "future": v.session.now -= timedelta(seconds=1)
    else: v.control.input_payload["confirmed_at"] = v.session.now.replace(tzinfo=None).isoformat()
    before = len(v.added)
    with pytest.raises(RunPlanCaseExecutionInvalid): v.cancel()
    assert v.command.status == "running" and len(v.added) == before and not v.events


@pytest.mark.parametrize("fault", ["receipt", "control", "control_state", "marker", "delivery_hash", "delivery_ancestor"])
def test_original_cancel_history_loss_cannot_be_repaired_or_rebound(lifecycle, fault):
    v = lifecycle
    v.cancel()
    v.jobs.cancellation_delivered(v.command.id)
    if fault == "receipt": v.rows.pop((Cancellation, v.command.id))
    elif fault == "control": v.control.input_payload["confirmed_actor_id"] = "changed"
    elif fault == "control_state": v.control.status = "waiting_confirmation"
    elif fault == "marker": v.command.input_payload.pop("case_claim_protocol")
    elif fault == "delivery_hash": v.rows[(Delivery, v.command.id)].content_hash = acceptance_digest("changed")
    else:
        row = v.rows[(Delivery, v.command.id)]
        row.cancellation_digest = acceptance_digest("other")
        row.payload = {**row.payload, "cancellation_digest": row.cancellation_digest}
        row.content_hash = acceptance_digest(row.payload)
    before = len(v.added)
    with pytest.raises(RunPlanCaseExecutionInvalid): v.jobs.command(v.target)
    assert len(v.added) == before and v.command.status == "cancelled"


def test_completed_control_and_old_cancel_time_do_not_renew_execution_consent(lifecycle):
    v = lifecycle
    v.cancel()
    receipt = deepcopy(v.rows[(Cancellation, v.command.id)].payload)
    v.control.status = "completed"
    v.session.now += timedelta(days=5)
    assert RunPlanCaseCancellationJournal.verify(v.session, v.command) == receipt
    v.jobs.cancellation_delivered(v.command.id)
    assert v.rows[(Cancellation, v.command.id)].payload == receipt


def test_unbound_failure_is_terminal_without_inventing_work_and_late_finish_preserves_cancel(lifecycle):
    v = lifecycle
    digest = v.current_scope().command_digest
    assert v.jobs.finish(v.command.id, digest, "failed") == "failed"
    assert v.command.result_payload["status"] == "failed"
    before = len(v.events)
    assert v.jobs.finish(v.command.id, digest, "failed") == "failed" and len(v.events) == before


def test_failed_finalization_waits_for_original_live_worker_then_preserves_claims(lifecycle):
    v = lifecycle
    v.acquire()
    digest = v.current_scope().command_digest
    with pytest.raises(RunPlanCaseWorkBusy): v.jobs.finish(v.command.id, digest, "failed")
    assert v.command.status == "running"
    v.session.now += timedelta(seconds=91)
    assert v.jobs.finish(v.command.id, digest, "failed") == "failed"


@pytest.mark.parametrize("history", [None, {}, {"state": {"state": "observed"}, "observations": []}])
def test_completion_cannot_import_a_worker_return_flag_without_complete_original_work(lifecycle, history):
    v = lifecycle
    with pytest.raises(RunPlanCaseExecutionInvalid):
        v.jobs.finish(v.command.id, v.current_scope().command_digest, "completed", history=history, require_access=lambda: None)
    assert v.command.status == "running" and not v.events


def test_0120_fixed_migration_preserves_exact_parents_and_append_only_contract(monkeypatch):
    migration = importlib.import_module("apps.api.migrations.versions.0120_run_plan_case_jobs")
    stream = io.StringIO()
    with Operations.context(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": stream})):
        migration.upgrade()
    sql = stream.getvalue()
    assert migration.down_revision == "0119_run_plan_case_preparations" and len(migration.revision) <= 32
    assert sql.count("EXECUTE FUNCTION nasus_reject_image_revision_mutation()") == 2
    assert "REFERENCES quality_run_plan_case_preparations" in sql and "REFERENCES tool_invocations" in sql
    assert "INSERT INTO" not in sql
    tables = {}
    class Capture:
        def create_table(self, name, *parts): tables[name] = Table(name, MetaData(), *parts)
        def execute(self, _sql): pass
    monkeypatch.setattr(migration, "op", Capture())
    migration.upgrade()
    for model in (Cancellation, Delivery):
        original, generated = tables[model.__tablename__], model.__table__
        shape = lambda table: {(item.name, str(item.type), item.nullable, item.primary_key) for item in table.columns}
        fks = lambda table: {(tuple(item.column_keys), tuple(element.target_fullname for element in item.elements))
            for item in table.foreign_key_constraints}
        assert shape(original) == shape(generated) and fks(original) == fks(generated)


@pytest.mark.parametrize("fault", [None, "missing_case", "changed_observation", "wrong_state", "revoked"])
def test_completion_requires_all_seven_original_native_observations_and_bookended_access(lifecycle, fault):
    from apps.api.app.application.quality_loop.run_plan_case_execution import RunPlanCaseExecutionApplicationService
    from apps.api.app.domain.quality_loop.run_plan_case_execution import execution_roster
    from apps.api.app.infrastructure.runner.http_fixture_verifier import OwnedHttpFixtureObservationVerifier
    from apps.api.tests.test_run_plan_case_execution import Runner
    v = lifecycle
    lease = v.acquire()
    add = v.session.add
    def record(row):
        if isinstance(row, (Claim, Outcome)):
            v.added.append(row)
            v.rows[(type(row), row.claim_id)] = row
        else: add(row)
    v.session.add = record
    def scalars(query):
        model = query.column_descriptions[0]["entity"]
        return SimpleNamespace(all=lambda: [row for (kind, _id), row in v.rows.items() if kind is model])
    v.session.scalars = scalars
    scope, runner = lease.scope, Runner()
    worker = RunPlanCaseExecutionApplicationService(runner, OwnedHttpFixtureObservationVerifier(), Cases(), None)
    jobs, observations = worker._commands(v.plan, scope), []
    for case in execution_roster(v.plan, scope):
        claim = Cases().claim(lease, case, require_current=lambda: None)
        job, command = jobs[case["case_id"]]
        native = runner.execute_owned_http(command, environment_id=scope.environment_id,
            artifact_hash=scope.target_artifact_hash, inventory_hash=scope.inventory_hash, require_work=lambda: None)
        observed = worker._observation(v.plan, scope, job, command, native)
        Cases().complete(lease, claim, artifact_ref="private://" + case["case_id"], artifact_hash=acceptance_digest(case),
            observation=observed, require_current=lambda: None)
        observations.append(observed)
    state, _outcomes = v.jobs._facts(v.session, scope)
    history = dict(state=state, observations=observations, historical_not_live=True)
    if fault == "missing_case": history["observations"] = history["observations"][:-1]
    elif fault == "changed_observation": history["observations"][0]["observation_digest"] = acceptance_digest("changed")
    elif fault == "wrong_state": history["state"] = {**state, "observed_case_count": 0}
    reads = []
    def access():
        reads.append(True)
        if fault == "revoked": raise PermissionError("source revoked before finalization")
    if fault is None:
        assert v.jobs.finish(v.command.id, scope.command_digest, "completed", history=history, require_access=access) == "completed"
        assert len(reads) == 2 and v.command.result_payload["summary"].startswith("All original case observations")
        assert "observations" not in v.command.result_payload
    else:
        with pytest.raises((RunPlanCaseExecutionInvalid, PermissionError)):
            v.jobs.finish(v.command.id, scope.command_digest, "completed", history=history, require_access=access)
        assert v.command.status == "running"
    assert len(runner.commands) == state["case_count"] == state["observed_case_count"] == 7
