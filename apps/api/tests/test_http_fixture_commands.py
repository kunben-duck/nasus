"""Explicit command/session specimens; not PG locking or native-target evidence."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.http_fixture_commands import HttpFixtureCommandAuthority
from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureLifecycleApplicationService
from apps.api.app.application.quality_loop.http_fixture_work import fixture_work_identity
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixture_command import (
    FIXTURE_COMMAND_TOOL, FIXTURE_COMMAND_SCHEMA, FIXTURE_DISPATCH_COMMAND_SCHEMA,
    FIXTURE_CANONICAL_DISPATCH_SCHEMA, FALSE_AUTHORITIES, verify_fixture_command,
)
from apps.api.app.domain.quality_loop.http_fixture_grant import grant_metadata
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.infrastructure.persistence import http_fixture_command_repository as adapter
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.http_fixture_command_models import (
    HttpFixtureCommandRecord as Intent, HttpFixtureDispatchCommandRecord as Binding,
)
from apps.api.app.infrastructure.persistence.http_fixture_grant_models import HttpFixtureGrantRecord as Grant
from apps.api.app.infrastructure.persistence.http_fixture_journal_models import HttpFixtureDispatchRecord as Dispatch
from apps.api.tests.test_http_fixture_execution import selection
from apps.api.tests.test_http_fixture_native_grants import native_grant, spec


ORIGINAL_EVENT_WRITER = adapter.HttpFixtureCommandRepository._event


def snapshot():
    now = datetime(2026, 10, 13, tzinfo=timezone.utc)
    request = {"project_id": "project", "grant_id": "original-grant", "grant_digest": acceptance_digest("grant"), "operation": "setup"}
    value = {"id": "original-command", "tool_id": FIXTURE_COMMAND_TOOL, "status": "running",
        "input_payload": {**request, "confirmed_by_user": True, "confirmed_actor_id": "admin", "confirmed_at": now.isoformat()}}
    digest = acceptance_digest({"tool_id": value["tool_id"], "input_payload": value["input_payload"]})
    return value, request, digest, now


@pytest.mark.parametrize("change", ["id", "tool", "status", "confirmation", "actor", "time", "naive", "future", "expired",
    "selection", "runtime_metadata", "digest"])
def test_original_command_rejects_changed_input_actor_confirmation_and_terminal_state(change):
    value, request, digest, now = snapshot()
    if change == "id": value["id"] = "another"
    elif change == "tool": value["tool_id"] = "quality.http_fixture.authorize"
    elif change == "status": value["status"] = "cancelled"
    elif change == "confirmation": value["input_payload"]["confirmed_by_user"] = 1
    elif change == "actor": value["input_payload"]["confirmed_actor_id"] = "another"
    elif change == "time": value["input_payload"]["confirmed_at"] = "not-time"
    elif change == "naive": value["input_payload"]["confirmed_at"] = now.replace(tzinfo=None).isoformat()
    elif change == "future": now -= timedelta(seconds=1)
    elif change == "expired": now += timedelta(seconds=901)
    elif change == "selection": value["input_payload"]["operation"] = "cleanup"
    elif change == "runtime_metadata": value["input_payload"]["agent_goal_id"] = "another-goal"
    else: digest = acceptance_digest("another-command")
    with pytest.raises(HttpFixtureInvalid):
        verify_fixture_command(value, request, invocation_id="original-command", request_digest=digest, actor_id="admin", now=now)


@pytest.mark.parametrize("status", ["running", "completed", "failed", "cancelled"])
def test_history_retains_original_confirmation_after_termination_without_renewal(status):
    value, request, digest, now = snapshot()
    value["status"] = status
    assert verify_fixture_command(value, request, invocation_id=value["id"], request_digest=digest,
        actor_id="admin", historical=True) == now
    assert "execution_authorized" not in value


@pytest.mark.parametrize("actor", [None, "", True, "bad\x00actor", "x" * 129])
def test_equal_but_invalid_confirmation_actors_never_establish_original_command_authority(actor):
    value, request, _, now = snapshot()
    value["input_payload"]["confirmed_actor_id"] = actor
    digest = acceptance_digest({"tool_id": value["tool_id"], "input_payload": value["input_payload"]})
    with pytest.raises(HttpFixtureInvalid):
        verify_fixture_command(value, request, invocation_id=value["id"], request_digest=digest,
            actor_id=actor, historical=True)


@pytest.mark.parametrize("changes", [{"invocation_id": True}, {"invocation_id": "bad\x00identity"},
    {"invocation_id": "x" * 129}, {"request_digest": "bad"}, {"execution_authorized": True}])
def test_worker_authority_is_only_an_exact_invocation_and_full_input_digest(changes):
    with pytest.raises(ValueError):
        HttpFixtureCommandAuthority.model_validate({"invocation_id": "original", "request_digest": acceptance_digest("input"), **changes})


class SessionSpecimen:
    def __init__(self, rows, now):
        self.rows, self.now, self.locks, self.added = rows, now, [], []
    def get(self, model, ident): return self.rows.get((model, ident))
    def scalar(self, query):
        entity = query.column_descriptions[0].get("entity")
        if entity is ToolInvocationRecord:
            command = self.rows.get((ToolInvocationRecord, query.compile().params["id_1"]))
            if query._for_update_arg is not None: self.locks.append(command.id)
            return command
        if entity is Intent:
            return next((row for (model, _id), row in self.rows.items() if model is Intent), None)
        if entity is Dispatch:
            return next((row for (model, _id), row in self.rows.items() if model is Dispatch), None)
        return self.now
    def add(self, row):
        self.added.append(row)
        if isinstance(row, Intent): self.rows[(Intent, row.invocation_id)] = row
        if isinstance(row, Binding): self.rows[(Binding, row.claim_id)] = row
    def flush(self): pass


@pytest.fixture
def command_specimen(native_grant, monkeypatch):
    v = native_grant
    chosen = selection(v)
    inputs = v.service.execution_inputs(chosen, live=True)
    original = grant_metadata(v.state["issued"][chosen.grant_id])
    now = datetime.now(timezone.utc)
    payload = {**chosen.model_dump(mode="json"), "confirmed_by_user": True,
        "confirmed_actor_id": inputs.consent.actor_id, "confirmed_at": now.isoformat(), "idempotency_key": "original-key"}
    command = ToolInvocationRecord(id="fixture-execution-command", tool_id=FIXTURE_COMMAND_TOOL, status="running", input_payload=payload)
    authority = HttpFixtureCommandAuthority(invocation_id=command.id,
        request_digest=acceptance_digest({"tool_id": command.tool_id, "input_payload": command.input_payload}))
    grant_command = SimpleNamespace(status="completed")
    rows = {(ToolInvocationRecord, command.id): command,
        (ToolInvocationRecord, original["invocation_id"]): grant_command,
        (Grant, chosen.grant_id): SimpleNamespace(invocation_id=original["invocation_id"])}
    session = SessionSpecimen(rows, now)
    @contextmanager
    def session_scope(): yield session
    monkeypatch.setattr(adapter, "session_scope", session_scope)
    monkeypatch.setattr(adapter.HttpFixtureGrantRepository, "_verify", staticmethod(lambda *args: deepcopy(original)))
    monkeypatch.setattr(adapter.HttpFixtureGrantRepository, "_request", staticmethod(lambda *args: v.request))
    monkeypatch.setattr(adapter.HttpFixtureGrantRepository, "_parents", staticmethod(lambda *args: inputs.parent.model_dump(mode="json")))
    monkeypatch.setattr(adapter.HttpFixtureGrantRepository, "require_live_in_session", lambda *args, **kwargs: deepcopy(original))
    monkeypatch.setattr(adapter.TestDesignResultRepository, "_project_scope", staticmethod(lambda *args: None))
    monkeypatch.setattr(adapter.TestDesignScopeRepository, "_lock", staticmethod(lambda *args: None))
    monkeypatch.setattr(adapter.PostgresHttpFixtureWorkRepository, "_actor_current", staticmethod(lambda *args: None))
    events = []
    monkeypatch.setattr(adapter.HttpFixtureCommandRepository, "_event", staticmethod(lambda session, value: events.append(deepcopy(value))))
    repository = adapter.HttpFixtureCommandRepository()
    value = repository.bind(inputs, authority, require_current=lambda: None)
    return SimpleNamespace(inputs=inputs, authority=authority, command=command, grant_command=grant_command,
        rows=rows, session=session, repository=repository, value=value, events=events, original=original)


def test_binding_replays_only_original_bytes_and_uses_the_journal_command_lock(command_specimen):
    v = command_specimen
    before = deepcopy(v.value)
    assert v.repository.bind(v.inputs, v.authority, require_current=lambda: None) == before
    assert len(v.events) == 1 and v.session.locks == [v.command.id, v.command.id]
    assert v.value["schema"] == FIXTURE_COMMAND_SCHEMA
    assert all(v.value[key] is False for key in FALSE_AUTHORITIES)
    fence = v.repository.fence(v.inputs, v.authority)
    command = HttpFixtureLifecycleApplicationService._command(v.inputs.scope, "setup", ())
    fence.require(v.session, v.inputs.scope, "setup", command)
    assert v.session.locks[-1] == v.command.id
    assert fence.command_pin(v.session, v.inputs.scope, "setup") == {
        **v.authority.model_dump(mode="json"), "intent_digest": acceptance_digest(before)}


def test_one_original_grant_cannot_be_reused_by_a_second_confirmed_command(command_specimen):
    v = command_specimen
    second = ToolInvocationRecord(id="second-command", tool_id=FIXTURE_COMMAND_TOOL, status="running",
        input_payload=deepcopy(v.command.input_payload))
    v.rows[(ToolInvocationRecord, second.id)] = second
    authority = HttpFixtureCommandAuthority(invocation_id=second.id, request_digest=v.authority.request_digest)
    with pytest.raises(HttpFixtureInvalid, match="another canonical command"):
        v.repository.bind(v.inputs, authority, require_current=lambda: None)
    assert len(v.events) == 1 and (Intent, second.id) not in v.rows


def test_private_dispatch_cannot_bypass_a_bound_command(command_specimen):
    v = command_specimen
    with pytest.raises(HttpFixtureInvalid, match="fall back to private dispatch"):
        adapter.require_private_fixture_work(v.session, v.inputs.scope, "setup")
    assert len(v.events) == 1


def test_new_binding_cannot_adopt_a_previously_dispatched_private_or_unknown_phase(command_specimen):
    v = command_specimen
    v.rows.pop((Intent, v.command.id))
    v.rows[(Dispatch, "old-private-claim")] = SimpleNamespace(status="reserved")
    with pytest.raises(HttpFixtureInvalid, match="already dispatched"):
        v.repository.bind(v.inputs, v.authority, require_current=lambda: None)
    assert (Intent, v.command.id) not in v.rows and len(v.events) == 1


@pytest.mark.parametrize("key,value", [("base_url", "https://example.com"), ("owner_id", "client-selected"),
    ("execution_authorized", True), ("timeout_ms", 120000), ("result", {"passed": True})])
def test_even_rehashed_confirmed_input_cannot_add_runtime_or_authority_fields(command_specimen, key, value):
    v = command_specimen
    v.command.input_payload[key] = value
    changed = v.authority.model_copy(update={"request_digest": acceptance_digest({
        "tool_id": v.command.tool_id, "input_payload": v.command.input_payload})})
    with pytest.raises(HttpFixtureInvalid, match="unverified execution selection"):
        v.repository._canonical(v.session, changed, v.inputs.selection, v.inputs.consent.actor_id)


def test_original_command_event_and_audit_use_public_dto_contracts_and_replay_without_work(command_specimen, monkeypatch):
    from apps.api.app.application.platform.tool_models import AuditEvent
    from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord
    v = command_specimen
    events = []
    monkeypatch.setattr(adapter.EventOutboxRepository, "append", lambda self, event, **kwargs: events.append(event))
    ORIGINAL_EVENT_WRITER(v.session, v.value)
    audit = next(row for row in v.session.added if isinstance(row, AuditEventRecord))
    AuditEvent.model_validate({**{c.name: getattr(audit, c.name) for c in audit.__table__.columns if c.name != "metadata"},
        "metadata": audit.event_metadata})
    assert audit.status == "recorded" and audit.tool_invocation_id == v.command.id
    v.command.status = "cancelled"
    v.repository.verify_event(v.session, events[0])
    changed = events[0].model_copy(update={"patch": {**events[0].patch, "passed_count": 1}})
    with pytest.raises(HttpFixtureInvalid): v.repository.verify_event(v.session, changed)


@pytest.mark.parametrize("version", [1, 17, 2147483648])
def test_command_fact_accepts_assigned_outbox_sequence_without_promoting_execution(command_specimen, monkeypatch, version):
    v, events = command_specimen, []
    monkeypatch.setattr(adapter.EventOutboxRepository, "append", lambda self, event, **kwargs: events.append(event))
    ORIGINAL_EVENT_WRITER(v.session, v.value)
    assigned = events[0].model_copy(update={"entity_version": version})
    v.repository.verify_event(v.session, assigned)
    assert assigned.patch == {key: v.value[key] for key in ("project_id", "invocation_id")}
    assert all(v.value[key] is False for key in FALSE_AUTHORITIES)


@pytest.mark.parametrize("version", [True, -1, "17"])
def test_command_fact_rejects_untyped_or_negative_sequence(command_specimen, monkeypatch, version):
    v, events = command_specimen, []
    monkeypatch.setattr(adapter.EventOutboxRepository, "append", lambda self, event, **kwargs: events.append(event))
    ORIGINAL_EVENT_WRITER(v.session, v.value)
    with pytest.raises(HttpFixtureInvalid):
        v.repository.verify_event(v.session, events[0].model_copy(update={"entity_version": version}))


@pytest.mark.parametrize("change", ["cancelled", "completed", "failed", "input", "metadata", "actor", "missing", "grant_terminal"])
def test_terminated_or_changed_command_is_fenced_before_dispatch_or_result_commit(command_specimen, change):
    v = command_specimen
    if change in {"cancelled", "completed", "failed"}: v.command.status = change
    elif change == "input": v.command.input_payload["operation"] = "cleanup"
    elif change == "metadata": v.command.input_payload["agent_goal_id"] = "another-goal"
    elif change == "actor": v.command.input_payload["confirmed_actor_id"] = "another-actor"
    elif change == "missing": v.rows.pop((Intent, v.command.id))
    else: v.grant_command.status = "failed"
    before = len(v.session.added)
    with pytest.raises(HttpFixtureInvalid): v.repository.require(v.inputs, v.authority)
    fence = v.repository.fence(v.inputs, v.authority)
    command = HttpFixtureLifecycleApplicationService._command(v.inputs.scope, "setup", ())
    with pytest.raises(HttpFixtureInvalid): fence.require(v.session, v.inputs.scope, "setup", command)
    assert len(v.session.added) == before and len(v.events) == 1


@pytest.mark.parametrize("field,value", [("scope_digest", acceptance_digest("other")), ("actor_id", "other"),
    ("grant_digest", acceptance_digest("other")), ("operation", "cleanup"), ("work_id", "another"),
    ("execution_authorized", 1), ("recorded_at", "2030-01-01T00:00:00+00:00"), ("native_environment", {}), ("parent", {})])
def test_rehashed_binding_cannot_change_its_original_consent_parent_or_authority(command_specimen, field, value):
    v = command_specimen
    row = v.rows[(Intent, v.command.id)]
    row.payload[field] = value
    if field in row.__table__.columns: setattr(row, field, value)
    row.content_hash = acceptance_digest(row.payload)
    with pytest.raises(HttpFixtureInvalid): v.repository._verify(v.session, row)


def dispatch_specimen(v, monkeypatch):
    scope = v.inputs.scope
    pin = {**v.authority.model_dump(mode="json"), "intent_digest": acceptance_digest(v.value)}
    dispatch = {"schema": FIXTURE_CANONICAL_DISPATCH_SCHEMA, "claim_id": "original-claim", "project_id": scope.project_id,
        "actor_id": v.inputs.consent.actor_id, "scope": asdict(scope), "phase": "setup", "recorded_at": v.value["recorded_at"],
        "canonical_command": pin, "operation_consent": v.inputs.consent.pin,
        "work_ownership": {"work_id": fixture_work_identity(scope, "setup"), "owner_id": "original-worker", "epoch": 1}}
    v.rows[(Dispatch, dispatch["claim_id"])] = SimpleNamespace(content_hash=acceptance_digest(dispatch))
    # Ancestry/lease/consent transport checks have their own actual adapter tests.
    monkeypatch.setattr(adapter, "verify_dispatch_ownership", lambda *args: {"owner_id": "original-worker"})
    monkeypatch.setattr(adapter, "verify_dispatch_consent", lambda *args: v.inputs.consent.pin)
    fence = v.repository.fence(v.inputs, v.authority)
    fence.claim(v.session, dispatch)
    return dispatch, fence


def test_dispatch_binding_preserves_original_command_after_cancel_without_allowing_adoption(command_specimen, monkeypatch):
    v = command_specimen
    dispatch, fence = dispatch_specimen(v, monkeypatch)
    v.command.status = "cancelled"
    before = deepcopy(dispatch)
    assert adapter.verify_dispatch_command(v.session, dispatch)["schema"] == FIXTURE_DISPATCH_COMMAND_SCHEMA
    fence.complete(v.session, dispatch)
    command = HttpFixtureLifecycleApplicationService._command(v.inputs.scope, "setup", ())
    with pytest.raises(HttpFixtureInvalid): fence.require(v.session, v.inputs.scope, "setup", command)
    assert dispatch == before
    other = v.repository.fence(v.inputs, v.authority.model_copy(update={"invocation_id": "other-command"}))
    with pytest.raises(HttpFixtureInvalid): other.complete(v.session, dispatch)
    with pytest.raises(HttpFixtureInvalid): fence.complete(v.session, {**dispatch, "claim_id": "private-phase"})


@pytest.mark.parametrize("change", ["missing", "stripped-marker", "schema", "pin", "scope", "phase", "actor", "intent", "request", "authority", "columns"])
def test_rehashed_dispatch_link_cannot_downgrade_or_rebind_original_ancestry(command_specimen, monkeypatch, change):
    v = command_specimen
    dispatch, _fence = dispatch_specimen(v, monkeypatch)
    row = v.rows[(Binding, dispatch["claim_id"])]
    if change == "missing": v.rows.pop((Binding, dispatch["claim_id"]))
    elif change == "stripped-marker":
        v.rows.pop((Binding, dispatch["claim_id"]))
        dispatch.pop("canonical_command")
        dispatch["schema"] = "nasus.http-fixture-dispatch.v3"
    elif change == "schema": dispatch["schema"] = "nasus.http-fixture-dispatch.v3"
    elif change == "pin": dispatch["canonical_command"]["invocation_id"] = "another"
    elif change == "scope": dispatch["scope"]["attempt_id"] = "another"
    elif change == "phase": dispatch["phase"] = "cleanup:session"
    elif change == "actor": dispatch["actor_id"] = "another"
    elif change == "intent": row.payload["intent_digest"] = acceptance_digest("another")
    elif change == "request": row.payload["request_digest"] = acceptance_digest("another")
    elif change == "authority": row.payload["business_coverage_verified"] = True
    else: row.invocation_id = "another"
    row.payload["dispatch_digest"] = acceptance_digest(dispatch)
    if change != "columns":
        for key in set(row.__table__.columns.keys()) - {"payload", "content_hash"}: setattr(row, key, row.payload[key])
    row.content_hash = acceptance_digest(row.payload)
    with pytest.raises(HttpFixtureInvalid): adapter.verify_dispatch_command(v.session, dispatch)


@pytest.mark.parametrize("schema", ["nasus.http-fixture-dispatch.v1", "nasus.http-fixture-dispatch.v2", "nasus.http-fixture-dispatch.v3"])
def test_legacy_dispatch_never_acquires_a_canonical_command_link(schema):
    dispatch = {"schema": schema, "claim_id": "legacy"}
    session = SimpleNamespace(get=lambda *args: None)
    assert adapter.verify_dispatch_command(session, dispatch) is None
    dispatch["canonical_command"] = {"invocation_id": "invented"}
    with pytest.raises(HttpFixtureInvalid): adapter.verify_dispatch_command(session, dispatch)


@pytest.mark.parametrize("missing", ["both", "work", "consent"])
def test_command_marker_cannot_replace_either_original_dispatch_gate(monkeypatch, missing):
    from apps.api.app.infrastructure.persistence import http_fixture_journal_repository as journal
    monkeypatch.setattr(journal, "engine", SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    options = {"command_fence": object(), "work_fence": object(), "consent_fence": object()}
    if missing in {"both", "work"}: options["work_fence"] = None
    if missing in {"both", "consent"}: options["consent_fence"] = None
    with pytest.raises(HttpFixtureInvalid, match="cannot bypass"):
        journal.PostgresHttpFixtureDispatchJournal(object(), object(), actor_id="admin", **options)
