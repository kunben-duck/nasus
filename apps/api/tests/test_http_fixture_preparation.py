"""Actual preparation policies/adapters with explicit session/transport specimens."""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects.postgresql import dialect

from apps.api.app.application.platform.actor_context import current_user
from apps.api.app.application.platform.runtime import ToolInvocationRuntime
from apps.api.app.application.platform.tool_handlers.query_input import query_payload
from apps.api.app.application.quality_loop.http_fixture_jobs import HttpFixtureJobApplicationService
from apps.api.app.application.quality_loop.http_fixture_work import HttpFixtureWorkBusy
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixture_command import FALSE_AUTHORITIES
from apps.api.app.domain.quality_loop.http_fixture_preparation import PREPARATION_SCHEMA, PREPARATION_MARKER, verify_preparation
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.infrastructure.persistence import http_fixture_job_repository as jobs_adapter
from apps.api.app.infrastructure.persistence import conversation_repository as conversation_adapter
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.http_fixture_command_models import HttpFixtureCommandRecord as Intent
from apps.api.app.infrastructure.persistence.http_fixture_preparation_models import HttpFixturePreparationRecord as Preparation, HttpFixturePreparationBindingRecord as Binding
from apps.api.app.infrastructure.persistence.http_fixture_preparation_repository import HttpFixturePreparationJournal as Journal
from apps.api.app.infrastructure.persistence.http_fixture_work_models import HttpFixtureWorkLeaseRecord as Lease
from apps.api.tests.test_http_fixture_commands import command_specimen
from apps.api.tests.test_http_fixture_native_grants import native_grant, spec
from apps.api.tests.test_http_fixture_jobs import application_specimen


@pytest.fixture
def preparing(command_specimen, monkeypatch):
    v = command_specimen
    v.rows.pop((Intent, v.command.id))
    v.session.added.clear()
    v.events.clear()
    v.command.revision, v.command.conversation_id = 0, None
    v.command.result_payload, v.command.summary = None, ""
    add = v.session.add
    def record(row):
        add(row)
        if isinstance(row, (Preparation, Binding)):
            v.rows[(type(row), row.invocation_id)] = row
    v.session.add = record
    @contextmanager
    def session_scope(): yield v.session
    monkeypatch.setattr(jobs_adapter, "session_scope", session_scope)
    monkeypatch.setattr(conversation_adapter, "session_scope", session_scope)
    v.outbox = []
    monkeypatch.setattr(jobs_adapter.EventOutboxRepository, "append", lambda _self, value, **_: v.outbox.append(value))
    v.repository = jobs_adapter.HttpFixtureJobRepository()
    def claim(changes=None):
        if changes:
            v.command.input_payload = {**v.command.input_payload, **changes}
        Journal().record(v.session, v.command)
        v.authority = v.repository._authority(v.command)
        return v.rows[(Preparation, v.command.id)].payload
    v.claim = claim
    return v


def test_preparation_pins_whole_confirmed_input_without_target_or_coverage_authority(preparing):
    v = preparing
    receipt = v.claim()
    assert receipt["request_digest"] == v.authority.request_digest
    assert receipt["actor_id"] == v.inputs.consent.actor_id
    assert receipt["confirmed_at"] == v.command.input_payload["confirmed_at"]
    assert receipt["recorded_at"] == v.session.now.isoformat()
    assert all(receipt[key] is False for key in FALSE_AUTHORITIES)
    assert set(receipt) == {"schema", "invocation_id", "project_id", "request_digest", "actor_id", "confirmed_at", "recorded_at", *FALSE_AUTHORITIES}
    assert (Intent, v.command.id) not in v.rows and not v.events and not v.outbox
    assert v.repository.delivery(v.command.id) == {"status": "running", "bound": False, "authority": v.authority}


def test_production_composite_preserves_existing_fixture_claim_protocol(preparing):
    from apps.api.app.infrastructure.persistence.tool_claim_journal import ToolClaimJournal
    v = preparing
    ToolClaimJournal().record(v.session, v.command)
    receipt = v.rows[(Preparation, v.command.id)].payload
    assert v.command.input_payload[PREPARATION_MARKER] == PREPARATION_SCHEMA
    assert "case_claim_protocol" not in v.command.input_payload
    assert receipt["request_digest"] == v.repository._authority(v.command).request_digest
    assert v.repository.delivery(v.command.id)["bound"] is False
    assert len(v.session.added) == 1 and not v.outbox


@pytest.mark.parametrize("change", ["input", "actor", "confirmation", "missing_actor", "marker", "missing_receipt",
    "receipt_bytes", "project", "recorded_before", "recorded_expired", "naive", "authority"])
def test_changed_or_missing_preparation_is_rejected_without_repair(preparing, change):
    v = preparing
    v.claim()
    row = v.rows[(Preparation, v.command.id)]
    if change in {"input", "actor", "confirmation", "missing_actor", "marker"}:
        key = {"input": "agent_goal_id", "actor": "confirmed_actor_id", "confirmation": "confirmed_at",
            "missing_actor": "confirmed_actor_id", "marker": PREPARATION_MARKER}[change]
        v.command.input_payload[key] = None if change == "missing_actor" else "changed"
    elif change == "missing_receipt": v.rows.pop((Preparation, v.command.id))
    elif change == "receipt_bytes": row.content_hash = acceptance_digest("not-the-original")
    else:
        value = deepcopy(row.payload)
        if change == "project": value["project_id"] = row.project_id = "other"
        elif change == "recorded_before": value["recorded_at"] = row.recorded_at = (v.session.now - timedelta(seconds=1)).isoformat()
        elif change == "recorded_expired": value["recorded_at"] = row.recorded_at = (v.session.now + timedelta(seconds=901)).isoformat()
        elif change == "naive": value["recorded_at"] = row.recorded_at = v.session.now.replace(tzinfo=None).isoformat()
        else: value["execution_authorized"] = True
        row.payload, row.content_hash = value, acceptance_digest(value)
    before = len(v.session.added)
    with pytest.raises(HttpFixtureInvalid): v.repository.delivery(v.command.id)
    with pytest.raises(HttpFixtureInvalid): v.repository.failure_command(v.command.id)
    assert len(v.session.added) == before and v.command.status == "running" and not v.outbox


@pytest.mark.parametrize("actor", [None, "", True, "bad\x00actor", "x" * 129])
def test_claim_cannot_treat_missing_or_invalid_actor_as_independent_confirmation(preparing, actor):
    with pytest.raises(HttpFixtureInvalid): preparing.claim({"confirmed_actor_id": actor})
    assert (Preparation, preparing.command.id) not in preparing.rows


def test_binding_receipt_is_exact_and_repeated_binding_only_verifies_original_history(preparing):
    v = preparing
    prep = v.claim()
    intent = v.repository.bind(v.inputs, v.authority, require_current=lambda: None)
    binding = v.rows[(Binding, v.command.id)].payload
    assert binding["preparation_digest"] == acceptance_digest(prep)
    assert binding["intent_digest"] == acceptance_digest(intent)
    assert binding["recorded_at"] == intent["recorded_at"]
    assert all(binding[key] is False for key in FALSE_AUTHORITIES)
    before = len(v.session.added)
    assert v.repository.bind(v.inputs, v.authority, require_current=lambda: None) == intent
    assert len(v.session.added) == before
    assert v.repository.delivery(v.command.id)["bound"] is True


@pytest.mark.parametrize("missing", ["intent", "binding", "preparation", "marker", "binding_bytes"])
def test_bound_history_loss_never_becomes_new_preparation_or_legacy_rebinding(preparing, missing):
    v = preparing
    v.claim()
    v.repository.bind(v.inputs, v.authority, require_current=lambda: None)
    if missing == "marker": v.command.input_payload.pop(PREPARATION_MARKER)
    elif missing == "binding_bytes": v.rows[(Binding, v.command.id)].content_hash = acceptance_digest("changed")
    else: v.rows.pop(({"intent": Intent, "binding": Binding, "preparation": Preparation}[missing], v.command.id))
    before = len(v.session.added)
    with pytest.raises(HttpFixtureInvalid): v.repository.delivery(v.command.id)
    with pytest.raises(HttpFixtureInvalid): v.repository.bind(v.inputs, v.authority, require_current=lambda: None)
    with pytest.raises(HttpFixtureInvalid): v.repository.finish(v.authority, "failed")
    assert len(v.session.added) == before and not v.outbox and v.command.status == "running"


def test_legacy_unbound_command_is_not_automatically_promoted(preparing):
    v = preparing
    with pytest.raises(HttpFixtureInvalid, match="legacy unbound"): v.repository.delivery(v.command.id)
    assert not any(model in {Preparation, Binding} for model, _ in v.rows)


@pytest.mark.parametrize("malformed", [{"operation": "invented"}, {"grant_digest": "invalid"}, {"unexpected": "field"}])
def test_invalid_unbound_selection_can_fail_under_original_lock_without_inventing_intent(preparing, malformed):
    v = preparing
    v.claim(malformed)
    with pytest.raises(ValueError): v.repository.command(v.command.id)
    status, authority = v.repository.failure_command(v.command.id)
    assert status == "running" and authority == v.authority
    assert v.repository.finish(authority, "failed") == "failed"
    assert v.command.id in v.session.locks and v.command.revision == 1
    assert len(v.outbox) == 1 and v.command.result_payload["http_fixture_job"] is None
    assert (Intent, v.command.id) not in v.rows and (Binding, v.command.id) not in v.rows
    assert v.repository.finish(authority, "failed") == "failed" and len(v.outbox) == 1


@pytest.mark.parametrize("terminal", ["cancelled", "failed", "completed"])
def test_preparation_failure_never_reopens_or_overwrites_original_terminal_state(preparing, terminal):
    v = preparing
    v.claim({"operation": "invalid"})
    v.command.status = terminal
    assert v.repository.failure_command(v.command.id) == (terminal, v.authority)
    assert v.repository.finish(v.authority, "failed") == terminal
    assert not v.outbox and v.command.revision == 0


def test_expired_original_confirmation_is_not_renewed_by_delivery_or_failure(preparing):
    v = preparing
    receipt = deepcopy(v.claim())
    v.session.now += timedelta(seconds=901)
    with pytest.raises(HttpFixtureInvalid, match="not fresh"): v.repository.execution(v.command.id)
    assert v.repository.finish(v.authority, "failed") == "failed"
    assert v.rows[(Preparation, v.command.id)].payload == receipt
    assert v.command.input_payload["confirmed_at"] == receipt["confirmed_at"]


def test_termination_rechecks_binding_and_live_lease_when_prepare_wins_the_lock(preparing):
    v = preparing
    v.claim()
    original = v.session.scalar
    raced = []
    def scalar(query):
        if query.column_descriptions[0].get("entity") is ToolInvocationRecord and not raced:
            raced.append(True)
            intent = v.repository.bind(v.inputs, v.authority, require_current=lambda: None)
            v.rows[(Lease, intent["work_id"])] = SimpleNamespace(expires_at=v.session.now + timedelta(seconds=30))
        return original(query)
    v.session.scalar = scalar
    with pytest.raises(HttpFixtureWorkBusy): v.repository.finish(v.authority, "failed")
    assert raced and v.repository.delivery(v.command.id)["bound"] is True
    assert v.command.status == "running" and not v.outbox


def test_preparation_journal_is_noop_for_other_tools(preparing):
    v = preparing
    v.command.tool_id = "run.start"
    before = deepcopy(v.command.input_payload)
    Journal().record(v.session, v.command)
    assert v.command.input_payload == before and not v.session.added


def test_unbound_preparation_cannot_be_completed_without_original_observations(preparing):
    v = preparing
    v.claim()
    with pytest.raises(HttpFixtureInvalid, match="complete durable original observations"):
        v.repository.finish(v.authority, "completed")
    assert v.command.status == "running" and not v.outbox


def test_claim_journal_uses_same_locked_session_before_flush_and_dto(preparing, monkeypatch):
    v = preparing
    v.command.status = "waiting_confirmation"
    calls = []
    class JournalPort:
        def record(self, session, row):
            assert session is v.session and row is v.command and row.status == "running"
            assert row.id in session.locks
            calls.append("journal")
            Journal().record(session, row)
    v.session.flush = lambda: calls.append("flush")
    repository = conversation_adapter.ConversationRepository(tool_claim_journal=JournalPort())
    monkeypatch.setattr(repository, "_to_tool_invocation", lambda row: calls.append("dto") or row)
    claimed = repository.claim_tool_invocation_for_execution(v.command.id, expected_statuses=("waiting_confirmation",))
    assert claimed is v.command and calls == ["journal", "flush", "dto"]
    assert v.repository.delivery(claimed.id)["bound"] is False
    assert repository.claim_tool_invocation_for_execution(claimed.id, expected_statuses=("waiting_confirmation",)) is None
    assert calls == ["journal", "flush", "dto"]


def test_client_cannot_inject_or_keep_server_owned_preparation_marker():
    value = {"project_id": "project", PREPARATION_MARKER: PREPARATION_SCHEMA, "confirmed_actor_id": "forged"}
    assert ToolInvocationRuntime._sanitize_client_input(value) == {"project_id": "project"}
    assert query_payload(value) == {"project_id": "project"}


@pytest.mark.parametrize("extra_business_field", [False, True])
def test_agent_tool_budget_strips_only_protocol_envelope_and_pins_complete_original_input(monkeypatch, extra_business_field):
    from apps.api.app.infrastructure.persistence.build_tool_budget_repository import BuildToolBudgetRepository
    from apps.api.app.infrastructure.persistence.image_plan_phase_repository import ImagePlanPhaseRepository
    from apps.api.app.domain.system_image.build_plan import BuildPlanIntegrityError
    request = {"project_id": "project", "grant_id": "original-grant", "operation": "setup"}
    goal = SimpleNamespace(id="goal", conversation_id="conversation", status="running", steps=[{
        "id": "step", "phase": "acting", "status": "pending", "selected_tool_id": "quality.http_fixture.execute",
        "tool_input_payload": request}])
    invocation = SimpleNamespace(id="original", tool_id="quality.http_fixture.execute", conversation_id=goal.conversation_id,
        initiator_surface="agent_loop", initiator_actor="agent", idempotency_key="agent-goal:goal:step:step:attempt:0",
        input_payload={**request, PREPARATION_MARKER: PREPARATION_SCHEMA, "agent_loop_iteration_id": "goal:step:0"})
    monkeypatch.setattr(conversation_adapter.ConversationRepository, "_to_goal", staticmethod(lambda row: row))
    monkeypatch.setattr(ImagePlanPhaseRepository, "scope_in_session", staticmethod(lambda *args: (None, 0)))
    if extra_business_field:
        invocation.input_payload["unapproved_target"] = "another-target"
        with pytest.raises(BuildPlanIntegrityError): BuildToolBudgetRepository._work_key(None, goal, invocation)
    else:
        assert BuildToolBudgetRepository._work_key(None, goal, invocation) == "goal:step:0"
        pinned = BuildToolBudgetRepository._input_digest(invocation)
        invocation.input_payload.pop(PREPARATION_MARKER)
        assert BuildToolBudgetRepository._input_digest(invocation) != pinned


def test_pending_inventory_includes_new_unbound_claims_and_bound_legacy_not_all_old_running_commands(preparing):
    v = preparing
    v.claim()
    queries = []
    v.session.scalars = lambda query: queries.append(query) or [v.command]
    assert v.repository.pending(after_id="earlier", limit=105) == [(v.command.id, v.inputs.selection.project_id)]
    compiled = queries[0].compile(dialect=dialect())
    sql = str(compiled)
    assert "LEFT OUTER JOIN quality_http_fixture_commands" in sql and "LEFT OUTER JOIN quality_http_fixture_preparations" in sql
    assert "tool_invocations.id >" in sql and "ORDER BY tool_invocations.id" in sql
    assert queries[0]._limit_clause.value == 100
    assert PREPARATION_SCHEMA in compiled.params.values() and PREPARATION_MARKER in compiled.params.values()


def test_unbound_delivery_prepares_as_original_actor_and_only_then_starts_same_workflow(application_specimen):
    v = application_specimen
    v.jobs.repository.delivery = lambda _: {"status": v.state["status"], "bound": v.state["bound"], "authority": v.authority}
    original = v.jobs.repository.bind
    def bind(*args, **kwargs):
        assert current_user().id == v.actor.id
        return original(*args, **kwargs)
    v.jobs.repository.bind = bind
    assert asyncio.run(v.jobs.deliver(v.authority.invocation_id)) == "running"
    assert v.calls.index("bind") < v.calls.index("workflow-start") and "execute" not in v.calls


@pytest.mark.parametrize("fault", [HttpFixtureInvalid("original confirmation expired"), PermissionError("revoked")])
def test_invalid_unbound_preparation_fails_original_without_dispatch(application_specimen, fault):
    v = application_specimen
    v.jobs.repository.delivery = lambda _: {"status": "running", "bound": v.state["bound"], "authority": v.authority}
    def execution(_): raise fault
    v.jobs.repository.execution = execution
    assert asyncio.run(v.jobs.deliver(v.authority.invocation_id)) == "failed"
    assert v.calls == ["finish:failed"]


def test_transient_unbound_preparation_remains_running_for_same_id_redelivery(application_specimen):
    v = application_specimen
    v.jobs.repository.delivery = lambda _: {"status": "running", "bound": v.state["bound"], "authority": v.authority}
    original = v.jobs.repository.execution
    def unavailable(_): raise RuntimeError("database temporarily unavailable")
    v.jobs.repository.execution = unavailable
    with pytest.raises(RuntimeError): asyncio.run(v.jobs.deliver(v.authority.invocation_id))
    assert v.state["status"] == "running" and not v.calls
    v.jobs.repository.execution = original
    assert asyncio.run(v.jobs.deliver(v.authority.invocation_id)) == "running"
    assert v.calls.count("bind") == 1 and v.calls.count("workflow-start") == 1


def test_terminal_command_delivery_never_reprepares_or_starts_workflow(application_specimen):
    v = application_specimen
    v.jobs.repository.delivery = lambda _: {"status": "cancelled", "bound": False, "authority": v.authority}
    assert asyncio.run(v.jobs.deliver(v.authority.invocation_id)) == "cancelled" and not v.calls


def test_cancellation_after_preparation_is_rechecked_before_starting_workflow(application_specimen):
    v = application_specimen
    original = v.jobs.repository.bind
    def bind(*args, **kwargs):
        original(*args, **kwargs)
        v.state["status"] = "cancelled"
    v.jobs.repository.bind = bind
    # The post-bind current check observes cancellation, and termination keeps
    # it cancelled instead of reopening the command or starting its workflow.
    assert asyncio.run(v.jobs.deliver(v.authority.invocation_id)) == "cancelled"
    assert "workflow-start" not in v.calls
