"""Explicit transaction specimens, not actual PG/Temporal/target execution evidence."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects.postgresql import dialect

from apps.api.app.application.platform.runtime import ToolInvocationRuntime
from apps.api.app.application.platform.tool_handlers.query_input import query_payload
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.run_plan_case_execution import RunPlanCaseExecutionInvalid, execution_roster
from apps.api.app.domain.quality_loop.run_plan_case_preparation import (
    CASE_PREPARATION_SCHEMA, CASE_PREPARATION_BINDING_SCHEMA, CASE_PREPARATION_MARKER, FALSE_AUTHORITIES,
    verify_case_preparation,
)
from apps.api.app.infrastructure.persistence import conversation_repository as conversation_adapter
from apps.api.app.infrastructure.persistence import run_plan_case_execution_repository as execution_adapter
from apps.api.app.infrastructure.persistence import run_plan_case_preparation_repository as preparation_adapter
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.run_plan_case_execution_models import RunPlanCaseWorkRecord as Work, RunPlanCaseLeaseRecord as Lease
from apps.api.app.infrastructure.persistence.run_plan_case_preparation_models import RunPlanCasePreparationRecord as Preparation, RunPlanCasePreparationBindingRecord as Binding
from apps.api.app.infrastructure.persistence.run_plan_case_preparation_repository import RunPlanCasePreparationJournal as Journal
from apps.api.app.infrastructure.persistence.tool_claim_journal import ToolClaimJournal
from apps.api.tests.test_run_plan_case_execution import inputs


@pytest.fixture
def preparing(monkeypatch):
    plan, scope, snapshot, now = inputs()
    command = SimpleNamespace(**snapshot, revision=0, conversation_id=None)
    rows, added, events = {(ToolInvocationRecord, command.id): command}, [], []
    session = SimpleNamespace(now=now, flushes=0)
    session.get = lambda model, ident: rows.get((model, ident))
    def add(row):
        added.append(row)
        ident = row.work_id if isinstance(row, (Work, Lease)) else row.invocation_id
        rows[(type(row), ident)] = row
    session.add = add
    def flush(): session.flushes += 1
    session.flush = flush
    def scalar(query):
        entity = query.column_descriptions[0].get("entity")
        if entity is ToolInvocationRecord: return command
        if entity is Lease: return rows.get((Lease, scope.work_id))
        return session.now
    session.scalar = scalar
    @contextmanager
    def opened(): yield session
    monkeypatch.setattr(preparation_adapter, "session_scope", opened)
    monkeypatch.setattr(execution_adapter, "session_scope", opened)
    monkeypatch.setattr(conversation_adapter, "session_scope", opened)
    monkeypatch.setattr(execution_adapter.PostgresRunPlanCaseExecutionRepository, "_actor", staticmethod(lambda *_: None))
    monkeypatch.setattr(execution_adapter.TestDesignScopeRepository, "_lock", staticmethod(lambda *_: None))
    monkeypatch.setattr(execution_adapter.PostgresRunPlanCaseExecutionRepository, "_event",
        staticmethod(lambda *args: events.append(args[-1])))
    def claim():
        Journal().record(session, command)
        return deepcopy(rows[(Preparation, command.id)].payload)
    def current_scope():
        return replace(scope, command_digest=acceptance_digest({"tool_id": command.tool_id, "input_payload": command.input_payload}))
    def acquire():
        prepared = current_scope()
        return execution_adapter.PostgresRunPlanCaseExecutionRepository().acquire(prepared,
            execution_roster(plan, prepared), "worker-owner", require_current=lambda: None)
    return SimpleNamespace(plan=plan, scope=scope, command=command, session=session, rows=rows, added=added,
        events=events, claim=claim, current_scope=current_scope, acquire=acquire,
        repository=preparation_adapter.RunPlanCasePreparationRepository())


def test_original_claim_pins_full_command_and_seven_setup_pins_without_execution_authority(preparing):
    v = preparing
    receipt = v.claim()
    assert receipt["command_digest"] == v.current_scope().command_digest
    assert receipt["selection_digest"] == acceptance_digest(v.scope.selection)
    assert receipt["confirmed_at"] == receipt["recorded_at"] == v.session.now.isoformat()
    assert v.command.input_payload[CASE_PREPARATION_MARKER] == CASE_PREPARATION_SCHEMA
    assert len(v.command.input_payload["fixture_setups"]) == 7
    assert all(receipt[key] is False for key in FALSE_AUTHORITIES)
    assert set(v.rows) == {(ToolInvocationRecord, v.command.id), (Preparation, v.command.id)}
    result = v.repository.delivery(v.command.id)
    assert result["bound"] is False and result["status"] == "running"
    assert all(result[key] is False for key in FALSE_AUTHORITIES)
    assert not {"selection", "scope", "input_payload", "artifact_ref", "fixtures"} & set(result)
    assert not v.events


@pytest.mark.parametrize("fault", ["missing_actor", "invalid_actor", "not_confirmed", "expired", "future", "naive",
    "client_marker", "unexpected_field", "invalid_hash", "duplicate_case", "duplicate_setup", "bool_timeout", "terminal"])
def test_invalid_claim_never_marks_protocol_or_adds_a_receipt(preparing, fault):
    v, payload = preparing, preparing.command.input_payload
    if fault == "missing_actor": payload.pop("confirmed_actor_id")
    elif fault == "invalid_actor": payload["confirmed_actor_id"] = "bad\x00actor"
    elif fault == "not_confirmed": payload["confirmed_by_user"] = 1
    elif fault == "expired": v.session.now += timedelta(seconds=901)
    elif fault == "future": v.session.now -= timedelta(seconds=1)
    elif fault == "naive": payload["confirmed_at"] = v.session.now.replace(tzinfo=None).isoformat()
    elif fault == "client_marker": payload[CASE_PREPARATION_MARKER] = CASE_PREPARATION_SCHEMA
    elif fault == "unexpected_field": payload["verified"] = True
    elif fault == "invalid_hash": payload["plan_digest"] = "invalid"
    elif fault in {"duplicate_case", "duplicate_setup"}:
        key = "case_id" if fault == "duplicate_case" else "invocation_id"
        payload["fixture_setups"][1][key] = payload["fixture_setups"][0][key]
    elif fault == "bool_timeout": payload["timeout_ms"] = True
    else: v.command.status = "completed"
    before = deepcopy(v.command.input_payload)
    with pytest.raises(RunPlanCaseExecutionInvalid): v.claim()
    assert v.command.input_payload == before and not v.added


@pytest.mark.parametrize("fault", ["input", "actor", "confirmation", "marker", "missing_receipt", "column", "hash",
    "authority", "extra", "recorded_before", "recorded_expired", "recorded_naive"])
def test_history_corruption_or_downgrade_is_rejected_without_repair(preparing, fault):
    v = preparing
    v.claim()
    row = v.rows[(Preparation, v.command.id)]
    if fault == "input": v.command.input_payload["agent_goal_id"] = "changed"
    elif fault == "actor": v.command.input_payload["confirmed_actor_id"] = "other"
    elif fault == "confirmation": v.command.input_payload["confirmed_at"] = (v.session.now + timedelta(seconds=1)).isoformat()
    elif fault == "marker": v.command.input_payload.pop(CASE_PREPARATION_MARKER)
    elif fault == "missing_receipt": v.rows.pop((Preparation, v.command.id))
    elif fault == "column": row.run_id = "other"
    elif fault == "hash": row.content_hash = acceptance_digest("changed")
    else:
        value = deepcopy(row.payload)
        if fault == "authority": value["execution_authorized"] = True
        elif fault == "extra": value["live"] = True
        else:
            observed = v.session.now + timedelta(seconds=-1 if fault == "recorded_before" else 901)
            if fault == "recorded_naive": observed = v.session.now.replace(tzinfo=None)
            value["recorded_at"] = row.recorded_at = observed.isoformat()
        row.payload, row.content_hash = value, acceptance_digest(value)
    before = len(v.added)
    with pytest.raises(RunPlanCaseExecutionInvalid): v.repository.delivery(v.command.id)
    assert len(v.added) == before and not v.events and v.command.status == "running"


def test_first_work_acquisition_binds_original_preparation_in_same_session(preparing):
    v = preparing
    receipt = v.claim()
    lease = v.acquire()
    work = v.rows[(Work, lease.work_id)]
    binding = v.rows[(Binding, v.command.id)].payload
    assert binding["schema"] == CASE_PREPARATION_BINDING_SCHEMA
    assert binding["preparation_digest"] == acceptance_digest(receipt)
    assert binding["work_digest"] == work.content_hash and binding["work_id"] == lease.work_id
    assert len(work.roster) == len(work.scope["selection"]["fixture_setups"]) == 7
    assert all(binding[key] is False for key in FALSE_AUTHORITIES)
    before = len(v.added)
    assert v.repository.delivery(v.command.id)["bound"] is True
    assert Journal.verify(v.session, v.command) == receipt
    assert len(v.added) == before
    assert v.events == ["quality.run_plan.case_work_recorded"]


@pytest.mark.parametrize("fault", ["work", "binding", "preparation", "work_hash", "binding_hash", "work_actor", "work_roster",
    "binding_work", "binding_time", "binding_authority"])
def test_bound_history_loss_is_not_new_unbound_work_or_a_new_legacy_attempt(preparing, fault):
    v = preparing
    v.claim()
    lease = v.acquire()
    if fault in {"work", "binding", "preparation"}:
        model, ident = (Work, lease.work_id) if fault == "work" else (Binding if fault == "binding" else Preparation, v.command.id)
        v.rows.pop((model, ident))
    elif fault.startswith("work_"):
        row = v.rows[(Work, lease.work_id)]
        if fault == "work_hash": row.content_hash = acceptance_digest("changed")
        else:
            if fault == "work_actor": row.scope = {**row.scope, "actor_id": "other"}
            else: row.roster = row.roster[:-1]
            row.content_hash = acceptance_digest({"schema": "nasus.run-plan-case-work.v1",
                **{key: getattr(row, key) for key in row.__table__.columns.keys() if key != "content_hash"}})
    else:
        row = v.rows[(Binding, v.command.id)]
        if fault == "binding_hash": row.content_hash = acceptance_digest("changed")
        else:
            value = deepcopy(row.payload)
            if fault == "binding_work": value["work_id"] = row.work_id = "other"
            elif fault == "binding_time": value["recorded_at"] = row.recorded_at = (v.session.now - timedelta(seconds=1)).isoformat()
            else: value["execution_authorized"] = True
            row.payload, row.content_hash = value, acceptance_digest(value)
    before = len(v.added)
    with pytest.raises(RunPlanCaseExecutionInvalid): v.repository.delivery(v.command.id)
    assert len(v.added) == before and v.command.status == "running"


@pytest.mark.parametrize("terminal", ["completed", "failed", "cancelled"])
def test_old_terminal_history_remains_readable_but_cannot_acquire_or_renew_consent(preparing, terminal):
    v = preparing
    receipt = v.claim()
    v.acquire()
    v.command.status = terminal
    v.session.now += timedelta(days=2)
    before = len(v.added)
    assert v.repository.delivery(v.command.id)["status"] == terminal
    assert Journal.verify(v.session, v.command) == receipt
    with pytest.raises(RunPlanCaseExecutionInvalid): v.acquire()
    assert len(v.added) == before and v.command.input_payload["confirmed_at"] == receipt["confirmed_at"]


def test_old_receipt_is_not_a_fresh_execution_approval(preparing):
    v = preparing
    v.claim()
    v.session.now += timedelta(seconds=901)
    assert v.repository.delivery(v.command.id)["bound"] is False
    with pytest.raises(RunPlanCaseExecutionInvalid): v.acquire()
    assert not v.events


def test_legacy_command_is_not_backfilled_into_recoverable_preparation(preparing):
    v = preparing
    assert Journal.verify(v.session, v.command) is None
    with pytest.raises(RunPlanCaseExecutionInvalid, match="legacy"): v.repository.delivery(v.command.id)
    assert not v.added


def test_reserved_marker_is_not_client_input_but_stays_in_the_full_command_digest():
    payload = {"project_id": "original", CASE_PREPARATION_MARKER: CASE_PREPARATION_SCHEMA, "confirmed_actor_id": "actor"}
    assert ToolInvocationRuntime._sanitize_client_input(payload) == {"project_id": "original"}
    assert query_payload(payload) == {"project_id": "original"}
    assert acceptance_digest(payload) != acceptance_digest(query_payload(payload))


def test_composed_claim_hook_records_before_flush_in_original_conversation_transaction(preparing):
    v = preparing
    v.command.status = "waiting_confirmation"
    runtime = conversation_adapter.ConversationRepository(tool_claim_journal=ToolClaimJournal())
    monkeypatch_result = lambda row: SimpleNamespace(id=row.id, status=row.status, input_payload=deepcopy(row.input_payload))
    runtime._to_tool_invocation = monkeypatch_result
    result = runtime.claim_tool_invocation_for_execution(v.command.id, expected_statuses=("waiting_confirmation",))
    assert result.status == "running" and result.input_payload[CASE_PREPARATION_MARKER] == CASE_PREPARATION_SCHEMA
    assert v.command.revision == 1 and v.session.flushes == 1
    assert len(v.added) == 1 and isinstance(v.added[0], Preparation)
    assert runtime.claim_tool_invocation_for_execution(v.command.id, expected_statuses=("waiting_confirmation",)) is None
    assert len(v.added) == 1


def test_composite_does_not_replace_fixture_receipts_or_mark_unrelated_tools(preparing, monkeypatch):
    v, calls = preparing, []
    journal = ToolClaimJournal()
    monkeypatch.setattr(journal.journals[0], "record", lambda session, command: calls.append((session, command)))
    journal.record(v.session, v.command)
    assert calls == [(v.session, v.command)] and len(v.added) == 1
    v.command = SimpleNamespace(tool_id="query.project.summary", input_payload={})
    journal.record(v.session, v.command)
    assert len(v.added) == 1 and CASE_PREPARATION_MARKER not in v.command.input_payload


def test_discovery_is_bounded_metadata_only_and_never_takes_locks_or_writes(preparing):
    v, queries = preparing, []
    def scalars(query):
        queries.append(str(query.compile(dialect=dialect(), compile_kwargs={"literal_binds": True})))
        assert query._for_update_arg is None
        return SimpleNamespace(all=lambda: ["original-a", "original-b"])
    v.session.scalars = scalars
    assert v.repository.pending(after_id="previous", limit=2) == ("original-a", "original-b")
    assert "running" in queries[0] and "previous" in queries[0] and "LIMIT 2" in queries[0]
    assert "ORDER BY quality_run_plan_case_preparations.invocation_id" in queries[0]
    assert not v.added and not v.events


@pytest.mark.parametrize("limit", [True, 0, -1, 101, 1.5, "10", None])
def test_invalid_discovery_limit_is_rejected_before_opening_session(preparing, limit):
    with pytest.raises(RunPlanCaseExecutionInvalid): preparing.repository.pending(limit=limit)


def test_domain_receipt_cannot_pin_a_selection_different_from_the_original_command(preparing):
    v = preparing
    value = v.claim()
    other = {**deepcopy(v.scope.selection), "run_id": "other-run"}
    value["run_id"], value["selection_digest"] = "other-run", acceptance_digest(other)
    with pytest.raises(RunPlanCaseExecutionInvalid): verify_case_preparation(Journal.snapshot(v.command), other, value)
