from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.platform.tool_invocations import (
    ToolInvocationApplicationService,
)
from apps.api.app.application.platform.tool_models import (
    AuditEvent,
    ToolDefinition,
    ToolInvocation,
    ToolInvocationRequest,
)


class ToolApplicationState:
    def __init__(self) -> None:
        self.tools = [
            ToolDefinition(
                tool_id="run.progress.get",
                label="Get run progress",
                tool_kind="query",
                scope="central",
                risk_level="low",
                confirmation_mode="none",
                description="Read current run progress.",
            )
        ]
        self.conversations = {
            "conversation_tool_app": SimpleNamespace(id="conversation_tool_app")
        }
        self.invocations: dict[str, ToolInvocation] = {}
        self.audit_events: list[AuditEvent] = []

    def list_tools(self):
        return tuple(self.tools)

    def get_conversation(self, conversation_id: str):
        return self.conversations[conversation_id]

    def get_invocation(self, invocation_id: str) -> ToolInvocation:
        return self.invocations[invocation_id]

    def list_invocations(self):
        return tuple(self.invocations.values())

    def list_audit_events(self):
        return tuple(self.audit_events)


class ToolExecutionRuntime:
    def __init__(self, state: ToolApplicationState) -> None:
        self.state = state
        self.created_payloads: list[ToolInvocationRequest] = []
        self.confirmed_ids: list[str] = []

    async def create(self, payload: ToolInvocationRequest) -> ToolInvocation:
        self.created_payloads.append(payload)
        invocation = ToolInvocation(
            id="tool_application_created",
            conversation_id=payload.conversation_id,
            tool_id=self.canonical_tool_id(payload.tool_id),
            status="completed",
            summary="Created through explicit runtime port.",
        )
        self.state.invocations[invocation.id] = invocation
        return invocation

    async def execute(self, invocation: ToolInvocation) -> ToolInvocation:
        return invocation

    async def gate_if_needed(self, invocation: ToolInvocation) -> bool:
        return False

    def tool_definition(self, tool_id: str) -> ToolDefinition | None:
        canonical = self.canonical_tool_id(tool_id)
        return next(
            (tool for tool in self.state.tools if tool.tool_id == canonical),
            None,
        )

    async def confirm(self, invocation_id: str) -> ToolInvocation:
        self.confirmed_ids.append(invocation_id)
        return self.state.invocations[invocation_id]

    def canonical_tool_id(self, tool_id: str) -> str:
        return {
            "query.run.status": "run.progress.get",
        }.get(tool_id, tool_id)


class ToolAccess:
    def __init__(self) -> None:
        self.conversations: list[str] = []
        self.invocations: list[str] = []
        self.denied_invocation_ids: set[str] = set()

    def require_conversation_access(self, conversation) -> None:
        self.conversations.append(conversation.id)

    def require_invocation_access(self, invocation: ToolInvocation) -> None:
        self.invocations.append(invocation.id)
        if invocation.id in self.denied_invocation_ids:
            raise PlatformApplicationError("tool_invocation_access_denied", "Access has been revoked.", 403)

    def can_access_invocation(self, invocation: ToolInvocation) -> bool:
        return invocation.id not in self.denied_invocation_ids

    def can_access_audit_event(self, event: AuditEvent) -> bool:
        return event.tool_invocation_id not in self.denied_invocation_ids


class ToolEvents:
    def __init__(self) -> None:
        self.statuses: list[tuple[str, str]] = []
        self.updates: list[dict[str, object]] = []

    async def emit_tool_status(
        self,
        invocation_id: str,
        status: str,
        summary: str,
        query_keys: list[list[str]],
        result=None,
    ) -> None:
        self.statuses.append((invocation_id, status))

    async def emit_tool_invocation_update(self, **payload) -> None:
        self.updates.append(payload)


def build_service():
    state = ToolApplicationState()
    runtime = ToolExecutionRuntime(state)
    access = ToolAccess()
    events = ToolEvents()
    service = ToolInvocationApplicationService(
        state=state,
        runtime=runtime,
        authorization=access,
        events=events,
    )
    return service, state, runtime, access, events


def test_create_rechecks_resource_access_before_returning_a_completed_command():
    service, state, runtime, access, _ = build_service()
    checked = []

    def denied(invocation):
        checked.append(invocation.id)
        raise PlatformApplicationError("source_access_denied", "Source is not available.", 403)

    service._read_resources = SimpleNamespace(require_access=denied)
    with pytest.raises(PlatformApplicationError) as raised:
        asyncio.run(service.create_tool_invocation(ToolInvocationRequest(tool_id="system_image.sources.ingest")))
    assert raised.value.status_code == 403
    assert checked == ["tool_application_created"]
    assert len(runtime.created_payloads) == 1
    assert state.invocations["tool_application_created"].status == "completed"
    assert access.invocations == ["tool_application_created"]


def test_create_cannot_return_a_completed_source_receipt_without_resource_authorization():
    service, state, runtime, _, _ = build_service()
    with pytest.raises(PlatformApplicationError) as raised:
        asyncio.run(service.create_tool_invocation(ToolInvocationRequest(tool_id="system_image.sources.ingest")))
    assert raised.value.status_code == 503
    assert len(runtime.created_payloads) == 1
    assert state.invocations["tool_application_created"].status == "completed"


@pytest.mark.parametrize("tool_id", ["quality.run_plan.prepare", "query.quality.run_plan_preview"])
def test_run_plan_receipt_reads_fail_closed_without_original_source_authorization(tool_id, monkeypatch):
    service, state, _, _, _ = build_service()
    command = ToolInvocation(id="original-plan-command", tool_id=tool_id, status="waiting_confirmation",
        summary="Original private plan", input_payload={"project_id": "project", "idempotency_key": "request"},
        idempotency_scope="actor:owner", idempotency_key="request")
    state.invocations[command.id] = command
    monkeypatch.setattr(state, "find_idempotent_invocation", lambda **_: command, raising=False)
    for read in (
        lambda: service.get_tool_invocation(command.id),
        lambda: service.resolve_owned_tool_invocation(actor_id="owner", project_id="project", tool_id=tool_id, request_key="request"),
    ):
        with pytest.raises(PlatformApplicationError) as denied:
            read()
        assert denied.value.status_code == 503
    with pytest.raises(PlatformApplicationError) as unavailable:
        service.list_tool_invocations(tool_id=tool_id)
    assert unavailable.value.status_code == 503


def test_original_request_resolution_uses_the_owner_scope_not_a_command_list(monkeypatch):
    service, state, runtime, access, _ = build_service()
    command = ToolInvocation(id="original", tool_id="run.progress.get", status="completed",
        summary="Original receipt", idempotency_scope="actor:owner", idempotency_key="request",
        input_payload={"project_id": "project", "idempotency_key": "request"})
    lookups = []

    def find(**scope):
        lookups.append(scope)
        return command

    monkeypatch.setattr(state, "find_idempotent_invocation", find, raising=False)
    monkeypatch.setattr(state, "list_invocations", lambda: pytest.fail("must not scan commands"))
    monkeypatch.setattr(state, "list_audit_events", lambda: pytest.fail("must not sort command history"))
    resolved = service.resolve_owned_tool_invocation(actor_id="owner", project_id="project",
        tool_id="query.run.status", request_key="request")
    assert resolved is command
    assert lookups == [{"idempotency_scope": "actor:owner", "tool_id": "run.progress.get", "idempotency_key": "request"}]
    assert access.invocations == ["original"]
    assert not runtime.created_payloads and not runtime.confirmed_ids


@pytest.mark.parametrize("fault", ["missing", "other_actor", "other_project", "other_tool", "other_key", "input_key"])
def test_original_request_resolution_never_returns_a_substituted_scope(monkeypatch, fault):
    service, state, runtime, access, _ = build_service()
    command = ToolInvocation(id="original", tool_id="run.progress.get", status="completed",
        summary="Original receipt", idempotency_scope="actor:owner", idempotency_key="request",
        input_payload={"project_id": "project", "idempotency_key": "request"})
    if fault == "other_actor":
        command.idempotency_scope = "actor:someone-else"
    elif fault == "other_project":
        command.input_payload["project_id"] = "other"
    elif fault == "other_tool":
        command.tool_id = "other"
    elif fault == "other_key":
        command.idempotency_key = "other"
    elif fault == "input_key":
        command.input_payload["idempotency_key"] = "other"
    monkeypatch.setattr(state, "find_idempotent_invocation", lambda **_: None if fault == "missing" else command, raising=False)
    assert service.resolve_owned_tool_invocation(actor_id="owner", project_id="project",
        tool_id="query.run.status", request_key="request") is None
    assert access.invocations == []
    assert not runtime.created_payloads and not runtime.confirmed_ids


def test_original_request_resolution_rechecks_current_resource_access(monkeypatch):
    service, state, _, access, _ = build_service()
    command = ToolInvocation(id="original", tool_id="run.progress.get", status="completed",
        summary="Original receipt", idempotency_scope="actor:owner", idempotency_key="request",
        input_payload={"project_id": "project", "idempotency_key": "request"})
    access.denied_invocation_ids.add(command.id)
    monkeypatch.setattr(state, "find_idempotent_invocation", lambda **_: command, raising=False)
    with pytest.raises(PlatformApplicationError) as denied:
        service.resolve_owned_tool_invocation(actor_id="owner", project_id="project",
            tool_id="query.run.status", request_key="request")
    assert denied.value.status_code == 403


@pytest.mark.parametrize("field,value", [("actor_id", ""), ("project_id", " project"),
    ("tool_id", "bad\x00tool"), ("request_key", "request\x7f"), ("request_key", "x" * 129)])
def test_original_request_resolution_validates_before_reading(monkeypatch, field, value):
    service, state, _, _, _ = build_service()
    monkeypatch.setattr(state, "find_idempotent_invocation", lambda **_: pytest.fail("invalid lookup must not read"), raising=False)
    values = {"actor_id": "owner", "project_id": "project", "tool_id": "query.run.status", "request_key": "request"}
    values[field] = value
    with pytest.raises(PlatformApplicationError) as invalid:
        service.resolve_owned_tool_invocation(**values)
    assert invalid.value.status_code == 422


def test_create_and_confirm_use_explicit_runtime_and_access_ports() -> None:
    service, _, runtime, access, _ = build_service()

    invocation = asyncio.run(
        service.create_tool_invocation(
            ToolInvocationRequest(
                conversation_id="conversation_tool_app",
                tool_id="query.run.status",
            )
        )
    )
    confirmed = asyncio.run(service.confirm_tool_invocation(invocation.id))

    assert access.conversations == ["conversation_tool_app"]
    assert access.invocations == [invocation.id, invocation.id, invocation.id]
    assert runtime.created_payloads[0].tool_id == "query.run.status"
    assert runtime.confirmed_ids == [invocation.id]
    assert confirmed.id == invocation.id
    assert confirmed.tool_id == "run.progress.get"


def test_create_rechecks_receipt_access_after_runtime_execution(monkeypatch) -> None:
    service, state, runtime, access, _ = build_service()
    create = runtime.create

    async def revoke_after_create(payload):
        invocation = await create(payload)
        access.denied_invocation_ids.add(invocation.id)
        return invocation

    monkeypatch.setattr(runtime, "create", revoke_after_create)
    with pytest.raises(PlatformApplicationError) as denied:
        asyncio.run(service.create_tool_invocation(ToolInvocationRequest(tool_id="query.run.status")))

    assert denied.value.status_code == 403
    assert list(state.invocations) == ["tool_application_created"]
    assert state.invocations["tool_application_created"].status == "completed"
    assert access.invocations == ["tool_application_created"]


def test_confirmation_rechecks_access_without_rewriting_the_completed_fact(monkeypatch) -> None:
    service, state, runtime, access, _ = build_service()
    invocation = asyncio.run(service.create_tool_invocation(ToolInvocationRequest(tool_id="query.run.status")))
    confirm = runtime.confirm

    async def revoke_after_confirm(invocation_id):
        result = await confirm(invocation_id)
        access.denied_invocation_ids.add(invocation_id)
        return result

    monkeypatch.setattr(runtime, "confirm", revoke_after_confirm)
    snapshot = invocation.model_dump(mode="json")
    with pytest.raises(PlatformApplicationError) as denied:
        asyncio.run(service.confirm_tool_invocation(invocation.id))

    assert denied.value.status_code == 403
    assert runtime.confirmed_ids == [invocation.id]
    assert state.invocations[invocation.id].model_dump(mode="json") == snapshot
    assert access.invocations == [invocation.id, invocation.id, invocation.id]


def test_confirmation_denied_before_runtime_does_not_execute() -> None:
    service, state, runtime, access, _ = build_service()
    invocation = asyncio.run(service.create_tool_invocation(ToolInvocationRequest(tool_id="query.run.status")))
    access.denied_invocation_ids.add(invocation.id)
    snapshot = invocation.model_dump(mode="json")
    with pytest.raises(PlatformApplicationError):
        asyncio.run(service.confirm_tool_invocation(invocation.id))

    assert runtime.confirmed_ids == []
    assert state.invocations[invocation.id].model_dump(mode="json") == snapshot


def test_query_filters_canonical_tool_id_authorization_and_created_time() -> None:
    service, state, _, access, _ = build_service()
    visible = ToolInvocation(
        id="tool_visible",
        conversation_id="conversation_tool_app",
        tool_id="run.progress.get",
        status="completed",
        summary="Visible",
        input_payload={"agent_goal_id": "goal_visible"},
    )
    hidden = ToolInvocation(
        id="tool_hidden",
        conversation_id="conversation_tool_app",
        tool_id="run.progress.get",
        status="completed",
        summary="Hidden",
        input_payload={"agent_goal_id": "goal_visible"},
    )
    state.invocations = {hidden.id: hidden, visible.id: visible}
    access.denied_invocation_ids.add(hidden.id)
    state.audit_events.extend(
        [
            AuditEvent(
                id="audit_hidden",
                occurred_at="2026-01-02T00:00:00+00:00",
                actor="system",
                action="tool.invocation.created",
                entity_type="tool_invocation",
                entity_id=hidden.id,
                summary="Created",
                tool_invocation_id=hidden.id,
            ),
            AuditEvent(
                id="audit_visible",
                occurred_at="2026-01-01T00:00:00+00:00",
                actor="system",
                action="tool.invocation.created",
                entity_type="tool_invocation",
                entity_id=visible.id,
                summary="Created",
                tool_invocation_id=visible.id,
            ),
        ]
    )

    invocations = service.list_tool_invocations(
        conversation_id="conversation_tool_app",
        agent_goal_id="goal_visible",
        tool_id="query.run.status",
        status="completed",
    )
    audits = service.list_audit_events(agent_goal_id=None)

    assert [item.id for item in invocations] == [visible.id]
    assert [event.id for event in audits] == ["audit_visible"]


def test_status_and_update_events_use_the_event_port() -> None:
    service, state, _, _, events = build_service()
    invocation = ToolInvocation(
        id="tool_event",
        conversation_id="conversation_tool_app",
        tool_id="run.progress.get",
        status="running",
        summary="Running",
    )
    state.invocations[invocation.id] = invocation

    asyncio.run(
        service.emit_tool_status(
            invocation.id,
            "completed",
            "Completed",
            [["conversation", "conversation_tool_app"]],
        )
    )
    asyncio.run(
        service.emit_tool_invocation_update(
            conversation_id="conversation_tool_app",
            invocation=invocation,
            summary="Updated",
        )
    )

    assert events.statuses == [(invocation.id, "completed")]
    assert events.updates == [
        {
            "conversation_id": "conversation_tool_app",
            "invocation": invocation,
            "summary": "Updated",
        }
    ]


@pytest.mark.parametrize("field", ["conversation_id", "agent_goal_id", "tool_id", "status"])
def test_scoped_invocation_query_does_not_authorize_unrelated_history(monkeypatch, field):
    service, state, _, access, _ = build_service()
    matching = ToolInvocation(id="match", conversation_id="conversation_tool_app", tool_id="run.progress.get",
        status="completed", summary="Matching", input_payload={"agent_goal_id": "goal_selected"})
    denied = matching.model_copy(update={"id": "denied"}, deep=True)
    unrelated = matching.model_copy(update={"id": "unrelated"}, deep=True)
    if field == "agent_goal_id":
        unrelated.input_payload["agent_goal_id"] = "another_goal"
    else:
        setattr(unrelated, field, {"conversation_id": "another_conversation", "tool_id": "another.tool",
            "status": "running"}[field])
    state.invocations = {item.id: item for item in (unrelated, denied, matching)}
    access.denied_invocation_ids.add(denied.id)
    checked, authorize = [], access.can_access_invocation

    def scoped(item):
        checked.append(item.id)
        assert item.id != unrelated.id, "Unrelated history must not trigger source or artifact verification"
        return authorize(item)

    monkeypatch.setattr(access, "can_access_invocation", scoped)
    value = {"conversation_id": "conversation_tool_app", "agent_goal_id": "goal_selected",
        "tool_id": "query.run.status", "status": "completed"}[field]
    assert [item.id for item in service.list_tool_invocations(**{field: value})] == [matching.id]
    assert checked == [denied.id, matching.id]


@pytest.mark.parametrize("field", ["conversation_id", "tool_invocation_id", "agent_goal_id"])
def test_scoped_audit_query_does_not_authorize_unrelated_history(monkeypatch, field):
    service, state, _, access, _ = build_service()
    matching = AuditEvent(id="match", occurred_at="2026-01-01T00:00:00+00:00", actor="system",
        action="tool.invocation.created", entity_type="tool_invocation", entity_id="tool_selected",
        summary="Matching", conversation_id="conversation_tool_app", tool_invocation_id="tool_selected",
        agent_goal_id="goal_selected")
    denied = matching.model_copy(update={"id": "denied", "tool_invocation_id": "tool_denied"}, deep=True)
    if field == "tool_invocation_id":
        denied.tool_invocation_id = matching.tool_invocation_id
    unrelated = matching.model_copy(update={"id": "unrelated", field: "another_scope"}, deep=True)
    state.audit_events = [unrelated, denied, matching]
    state.invocations[matching.tool_invocation_id] = ToolInvocation(id=matching.tool_invocation_id,
        tool_id="run.progress.get", status="completed", summary="Selected command")
    checked = []

    def scoped(event):
        checked.append(event.id)
        assert event.id != unrelated.id, "Unrelated audit history must not trigger evidence verification"
        return event.id != denied.id

    monkeypatch.setattr(access, "can_access_audit_event", scoped)
    assert [event.id for event in service.list_audit_events(**{field: getattr(matching, field)})] == [matching.id]
    assert checked == [denied.id, matching.id]


def test_audit_events_with_missing_commands_do_not_bypass_resource_authorization():
    service, state, _, _, _ = build_service()
    state.audit_events = [AuditEvent(id="missing", occurred_at="2026-01-01T00:00:00+00:00",
        actor="system", action="tool.invocation.completed", entity_type="tool_invocation",
        entity_id="missing-command", tool_invocation_id="missing-command", summary="Private command")]
    assert service.list_audit_events() == []


def test_audit_reads_recheck_the_source_resource_port_after_project_access(monkeypatch):
    service, state, _, _, _ = build_service()
    command = ToolInvocation(id="original", tool_id="system_image.sources.ingest", status="completed",
        summary="Refreshed", input_payload={"source_ids": ["private-source"]})
    state.invocations[command.id] = command
    state.audit_events = [AuditEvent(id="private", occurred_at="2026-01-01T00:00:00+00:00", actor="system",
        action="tool.invocation.completed", entity_type="tool_invocation", entity_id=command.id,
        tool_invocation_id=command.id, object_refs=["raw_asset:private-source"], summary="Private receipt")]
    with pytest.raises(PlatformApplicationError) as unavailable:
        service.list_audit_events(tool_invocation_id=command.id)
    assert unavailable.value.status_code == 503
    checked = []

    def require(invocation):
        checked.append(invocation.id)
        raise PlatformApplicationError("source_receipt_access_denied", "Receipt is unavailable.", 403)

    service._read_resources = SimpleNamespace(require_access=require)
    assert service.list_audit_events(tool_invocation_id=command.id) == [] and checked == [command.id]
    monkeypatch.setattr(service._read_resources, "require_access", lambda _: None)
    with pytest.raises(PlatformApplicationError) as unavailable:
        service.list_audit_events(tool_invocation_id=command.id)
    assert unavailable.value.status_code == 503
    service._read_resources.require_batch_access = lambda _: None
    assert [event.id for event in service.list_audit_events(tool_invocation_id=command.id)] == ["private"]


@pytest.mark.parametrize("endpoint", ["invocations", "audit"])
def test_receipt_batch_authorization_runs_after_history_reads_and_propagates_denial(endpoint):
    service, state, _, _, _ = build_service()
    command = ToolInvocation(id="private", tool_id="system_image.sources.ingest", status="completed", summary="Original")
    state.invocations[command.id] = command
    state.audit_events = [AuditEvent(id="audit", occurred_at="2026-01-01T00:00:00+00:00", actor="system",
        action="tool.invocation.created", entity_type="tool_invocation", entity_id=command.id,
        tool_invocation_id=command.id, summary="Private receipt")]
    reads = []

    def individual(item):
        reads.append(("individual", item.id))

    def batch(items):
        assert [("individual", command.id)] == reads
        assert [item.id for item in items] == [command.id]
        raise PlatformApplicationError("source_receipt_access_denied", "Source receipt is not available.", 403)

    service._read_resources = SimpleNamespace(require_access=individual, require_batch_access=batch)
    read = service.list_tool_invocations if endpoint == "invocations" else service.list_audit_events
    with pytest.raises(PlatformApplicationError) as denied:
        read()
    assert denied.value.status_code == 403


@pytest.mark.parametrize("endpoint", ["invocations", "audit"])
def test_damaged_authorized_receipt_aborts_history_instead_of_hiding_it(endpoint):
    service, state, _, _, _ = build_service()
    for ident in ("valid", "damaged"):
        state.invocations[ident] = ToolInvocation(id=ident, tool_id="system_image.sources.ingest",
            status="completed", summary="Original")
        state.audit_events.append(AuditEvent(id="audit_" + ident, occurred_at="2026-01-01T00:00:00+00:00",
            actor="system", action="tool.invocation.created", entity_type="tool_invocation", entity_id=ident,
            tool_invocation_id=ident, summary="Original receipt"))
    reads = []
    def require(invocation):
        reads.append(invocation.id)
        if invocation.id == "damaged":
            raise PlatformApplicationError("receipt_integrity_failed", "Original receipt cannot be verified.", 502)
    def batch(_):
        pytest.fail("a damaged cohort cannot reach successful final authorization")
    service._read_resources = SimpleNamespace(require_access=require, require_batch_access=batch)
    read = service.list_tool_invocations if endpoint == "invocations" else service.list_audit_events
    with pytest.raises(PlatformApplicationError) as invalid: read()
    assert invalid.value.status_code == 502 and reads == ["valid", "damaged"]


def test_invocation_sort_reads_creation_history_once_and_preserves_earliest_time(monkeypatch):
    service, state, _, _, _ = build_service()
    for ident in ("later", "early", "missing"):
        state.invocations[ident] = ToolInvocation(id=ident, tool_id="run.progress.get", status="completed", summary=ident)
    for ident, invocation_id, occurred_at in (
        ("late_creation", "later", "2026-01-02T00:00:00+00:00"),
        ("early_repeat", "early", "2026-01-03T00:00:00+00:00"),
        ("early_original", "early", "2026-01-01T00:00:00+00:00"),
        ("non_creation", "missing", "2025-01-01T00:00:00+00:00"),
    ):
        state.audit_events.append(AuditEvent(id=ident, occurred_at=occurred_at, actor="system", entity_type="tool_invocation",
            entity_id=invocation_id, action="tool.invocation.completed" if ident == "non_creation" else "tool.invocation.created",
            tool_invocation_id=invocation_id, summary="Audit"))
    original, reads = state.list_audit_events, []

    def history():
        reads.append(True)
        return original()

    monkeypatch.setattr(state, "list_audit_events", history)
    assert [item.id for item in service.list_tool_invocations()] == ["early", "later", "missing"]
    assert len(reads) == 1
    assert service.list_tool_invocations(status="failed") == []
    assert len(reads) == 1


def test_unscoped_queries_authorize_all_records_and_recheck_revocation():
    service, state, _, access, _ = build_service()
    for ident in ("first", "second"):
        state.invocations[ident] = ToolInvocation(id=ident, tool_id="run.progress.get", status="completed", summary=ident)
        state.audit_events.append(AuditEvent(id=f"audit_{ident}", occurred_at="2026-01-01T00:00:00+00:00",
            actor="system", action="tool.invocation.created", entity_type="tool_invocation", entity_id=ident,
            tool_invocation_id=ident, summary="Audit"))
    assert len(service.list_tool_invocations()) == len(service.list_audit_events()) == 2
    access.denied_invocation_ids.add("first")
    assert [item.id for item in service.list_tool_invocations()] == ["second"]
    assert [item.id for item in service.list_audit_events()] == ["audit_second"]
