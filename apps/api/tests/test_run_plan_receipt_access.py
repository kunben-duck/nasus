"""Protocol authorization checks, not target execution or business gold."""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.agent.use_cases import AgentApplicationService
from apps.api.app.application.platform.events import PlatformEventApplicationService
from apps.api.app.application.platform.run_plan_receipts import RunPlanReceiptAccess
from apps.api.app.application.platform.source_refresh_receipts import SourceRefreshReceiptAccess
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolInvocationRequest, ToolResult
from apps.api.app.application.platform.tool_receipt_access import ToolReceiptAccess, require_receipt_access
from apps.api.app.application.quality_loop.run_plan_inputs import RunPlanCommandScope
from apps.api.app.application.quality_loop.run_plans import RunPlanApplicationService
from apps.api.app.domain.quality_loop.run_plan import RunPlanIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from apps.api.tests.test_run_plans import plan_inputs
from apps.api.tests.test_source_refresh_receipt_access import Sources, receipt as source_receipt
from apps.api.tests.test_tool_invocation_application_ports import build_service
from apps.api.tests.test_tool_invocation_runtime_ports import build_runtime, tool_definition
from apps.api.tests.test_platform_event_ports import conversation, event, RecordingStreams, RecordingProjection


def receipt(tool="quality.run_plan.prepare", status="completed"):
    *_, selection = plan_inputs()
    body = selection.model_dump(mode="json")
    body.update(idempotency_key="original-request", confirmed_by_user=True,
        confirmed_actor_id="owner", confirmed_at="2026-10-10T01:00:00+00:00")
    return ToolInvocation(id="original-plan", tool_id=tool, status=status,
        summary="Private target fixture description", input_payload=body,
        idempotency_key="original-request", idempotency_scope="actor:owner",
        idempotency_fingerprint="private-fingerprint",
        result=ToolResult(invocation_id="original-plan", status="completed", summary="Private preparation reason",
            object_refs=["run_plan:original"], evidence_refs=["private-evidence"]))


class Plans:
    def __init__(self):
        self.reads, self.batches = [], []
        self.error = None

    def require_command_inputs_access(self, scope):
        self.reads.append(scope)
        if self.error:
            raise self.error("private target origin and original-request")

    def require_command_inputs_access_many(self, scopes):
        self.batches.append(scopes)
        if self.error:
            raise self.error("private target origin and original-request")


@pytest.mark.parametrize("tool", ["quality.run_plan.prepare", "query.quality.run_plan_preview"])
@pytest.mark.parametrize("status", ["waiting_confirmation", "running", "completed", "failed"])
def test_every_receipt_status_uses_original_parent_pins_and_preserves_history(tool, status):
    command, plans = receipt(tool, status), Plans()
    original = deepcopy(command.model_dump())
    access = RunPlanReceiptAccess(plans)
    access.require_access(command)
    assert [item.model_dump(mode="json") for item in plans.reads] == [
        {key: command.input_payload[key] for key in RunPlanCommandScope.model_fields}]
    assert command.model_dump() == original and not plans.batches


@pytest.mark.parametrize("field,value", [("project_id", None), ("script_revision_id", ""),
    ("script_artifact_hash", "sha256:" + "A" * 64), ("review_revision_id", None), ("review_artifact_hash", "broken")])
def test_incomplete_parent_scope_is_rejected_without_authorizing_another_resource(field, value):
    command, plans = receipt(), Plans()
    command.input_payload[field] = value
    with pytest.raises(PlatformApplicationError) as denied:
        RunPlanReceiptAccess(plans).require_access(command)
    assert denied.value.status_code == 409 and plans.reads == plans.batches == []


@pytest.mark.parametrize("error,code", [(SourceAccessDenied, 403), (StaleSourceAccessScope, 403),
    (KeyError, 403), (RunPlanIntegrityError, 502), (RuntimeError, 503)])
def test_receipt_authorization_failures_are_sanitized(error, code):
    plans = Plans()
    plans.error = error
    for operation in (lambda: RunPlanReceiptAccess(plans).require_access(receipt()),
            lambda: RunPlanReceiptAccess(plans).require_batch_access((receipt(),))):
        with pytest.raises(PlatformApplicationError) as denied:
            operation()
        assert denied.value.status_code == code
        assert "private target" not in str(denied.value) and "original-request" not in str(denied.value)


def test_batch_deduplicates_original_scopes_without_reusing_an_access_grant():
    plans, first = Plans(), receipt()
    second = first.model_copy(update={"id": "another", "status": "waiting_confirmation"}, deep=True)
    access = RunPlanReceiptAccess(plans)
    access.require_batch_access((first, second))
    assert len(plans.batches) == 1 and len(plans.batches[0]) == 1 and not plans.reads
    plans.error = SourceAccessDenied
    with pytest.raises(PlatformApplicationError) as denied:
        access.require_batch_access((first, second))
    assert denied.value.status_code == 403 and len(plans.batches) == 2


@pytest.mark.parametrize("fault", ["missing_bulk", "oversized"])
def test_unavailable_or_oversized_batch_fails_before_reading_protected_parents(fault):
    plans, command = Plans(), receipt()
    commands = (command,)
    if fault == "missing_bulk":
        plans.require_command_inputs_access_many = None
    else:
        commands = tuple(command.model_copy(update={"input_payload": {**command.input_payload,
            "project_id": f"project-{index}"}}, deep=True) for index in range(129))
    with pytest.raises(PlatformApplicationError) as denied:
        RunPlanReceiptAccess(plans).require_batch_access(commands)
    assert denied.value.status_code == 503 and not plans.batches and not plans.reads


def test_broadcasts_omit_original_declarations_and_never_mutate_or_authorize_history():
    plans, command = Plans(), receipt()
    original = deepcopy(command.model_dump())
    view = RunPlanReceiptAccess(plans).broadcast_view(command)
    assert view.id == command.id and view.status == command.status
    assert view.input_payload == {} and view.result is None
    assert view.idempotency_key is view.idempotency_scope is view.idempotency_fingerprint is None
    assert view.summary == "Execution plan command status: completed."
    assert command.model_dump() == original and not plans.reads and not plans.batches


def require_public_receipt(value, original):
    assert value["id"] == original.id and value["status"] == original.status
    assert value["input_payload"] == {} and value["result"] is None
    assert value["summary"] == f"Execution plan command status: {original.status}."
    for field in ("idempotency_key", "idempotency_scope", "idempotency_fingerprint"):
        assert field not in value


@pytest.mark.parametrize("tool", ["quality.run_plan.prepare", "query.quality.run_plan_preview"])
@pytest.mark.parametrize("operation", ["ensure", "list", "get", "archive", "search"])
def test_every_conversation_discovery_exit_projects_plan_receipts_without_source_grants(tool, operation):
    command, plans = receipt(tool), Plans()
    original = conversation().model_copy(update={"tool_invocations": [command]}, deep=True)
    snapshot = deepcopy(original.model_dump())
    search = {"query": "Event", "conversations": [original], "message_hits": [], "related_links": []}
    manager = SimpleNamespace(ensure_conversation=lambda _: original, list_conversations=lambda **_: [original],
        get_conversation=lambda _: original, archive_conversation=lambda *_: original,
        search_conversations=lambda _: search)
    service = AgentApplicationService(conversations=manager, events=object(), explanations=object(), goals=object(),
        memory=object(), messages=object(), swarm=object(), tool_broadcast_view=RunPlanReceiptAccess(plans).broadcast_view)
    plans.error = SourceAccessDenied
    if operation == "ensure": result = service.ensure_conversation(None)
    elif operation == "list": result = service.list_conversations()[0]
    elif operation == "get": result = service.get_conversation(original.id)
    elif operation == "archive": result = service.archive_conversation(original.id, None)
    else: result = service.search_conversations("Event")["conversations"][0]
    require_public_receipt(result.tool_invocations[0].model_dump(), command)
    assert original.model_dump() == snapshot and not plans.reads and not plans.batches
    assert search["conversations"] == [original]


@pytest.mark.parametrize("tool", ["quality.run_plan.prepare", "query.quality.run_plan_preview"])
def test_fresh_conversation_events_drop_private_explicit_payload_and_patch_before_publication(tool):
    command, plans, streams = receipt(tool), Plans(), RecordingStreams()
    snapshot = deepcopy(command.model_dump())
    service = PlatformEventApplicationService(streams, SimpleNamespace(get_tool_invocation=lambda _: command),
        RecordingProjection(), tool_broadcast_view=RunPlanReceiptAccess(plans).broadcast_view)
    patch = {"status": command.status, "input_payload": command.input_payload, "summary": command.summary}
    explicit = {"tool_invocation": command.model_dump(), "private_target": command.input_payload}
    asyncio.run(service.push_event("conversation_event_port", "tool.invocation.updated", "tool_invocation", command.id,
        "replace", patch, [["conversation", "conversation_event_port"]], payload=explicit))
    published = streams.events[0]
    expected_patch = {"status": command.status, "summary": f"Execution plan command status: {command.status}.", "tool_id": tool}
    assert published.patch == published.payload["patch"] == expected_patch
    assert set(published.payload) == {"patch", "tool_invocation"}
    require_public_receipt(published.payload["tool_invocation"], command)
    assert command.model_dump() == snapshot and patch["input_payload"] == command.input_payload
    assert "private_target" in explicit and not plans.reads and not plans.batches


@pytest.mark.parametrize("tool", ["quality.run_plan.prepare", "query.quality.run_plan_preview"])
@pytest.mark.parametrize("stream", ["conversation", "goal", "swarm"])
def test_all_event_replays_project_historical_plan_receipts_without_mutation_or_current_entities(tool, stream):
    command, plans = receipt(tool), Plans()
    original = event().model_copy(update={"tool_invocation_id": command.id, "entity_id": command.id,
        "patch": {"summary": command.summary, "input_payload": command.input_payload},
        "payload": {"tool_invocation": command.model_dump(), "private_target": command.input_payload}}, deep=True)
    snapshot = deepcopy(original.model_dump())
    calls = []
    class Replays(RecordingStreams):
        async def _replay(self, ident, cursor):
            calls.append((ident, cursor))
            yield original
            yield None
        stream_conversation_events = stream_goal_events = stream_swarm_events = _replay
    service = PlatformEventApplicationService(Replays(), object(), object(),
        tool_broadcast_view=RunPlanReceiptAccess(plans).broadcast_view)
    plans.error = SourceAccessDenied
    async def collect():
        return [item async for item in getattr(service, f"stream_{stream}_events")("original-stream", "old-cursor")]
    items = asyncio.run(collect())
    assert len(items) == 2 and items[1] is None and calls == [("original-stream", "old-cursor")]
    projected = items[0]
    expected_patch = {"status": command.status, "summary": f"Execution plan command status: {command.status}.", "tool_id": tool}
    assert projected.patch == projected.payload["patch"] == expected_patch
    assert set(projected.payload) == {"patch", "tool_invocation"}
    require_public_receipt(projected.payload["tool_invocation"], command)
    for field in ("event_id", "entity_id", "entity_version", "occurred_at", "query_keys"):
        assert getattr(projected, field) == getattr(original, field)
    assert original.model_dump() == snapshot and not plans.reads and not plans.batches


def test_composition_keeps_original_source_policy_and_does_not_touch_other_commands():
    sources, plans = Sources(), Plans()
    access = ToolReceiptAccess(SourceRefreshReceiptAccess(sources), RunPlanReceiptAccess(plans))
    command, ingestion = receipt(), source_receipt()
    require_receipt_access(access, command)
    require_receipt_access(access, ingestion)
    access.require_batch_access((command, ingestion))
    assert len(plans.reads) == len(plans.batches) == 1 and len(sources.reads) == 2
    for original in (command, ingestion):
        assert access.broadcast_view(original).input_payload == {}
    unrelated = command.model_copy(update={"tool_id": "run.progress.get"}, deep=True)
    require_receipt_access(access, unrelated)
    assert access.broadcast_view(unrelated) is unrelated
    assert len(plans.reads) == 1


@pytest.mark.parametrize("port", [None, "source_only", "empty_composition"])
def test_project_membership_and_unrelated_resource_ports_cannot_authorize_plans(port):
    resource = None if port is None else SourceRefreshReceiptAccess(Sources()) if port == "source_only" else ToolReceiptAccess()
    with pytest.raises(PlatformApplicationError) as denied:
        require_receipt_access(resource, receipt())
    assert denied.value.status_code == 503


def test_list_final_recheck_rejects_a_revocation_after_individual_plan_reads():
    service, state, _, _, _ = build_service()
    plans, command = Plans(), receipt()
    state.invocations[command.id] = command
    service._read_resources = ToolReceiptAccess(RunPlanReceiptAccess(plans))
    original = plans.require_command_inputs_access
    def revoked(scope):
        original(scope)
        plans.error = SourceAccessDenied
    plans.require_command_inputs_access = revoked
    with pytest.raises(PlatformApplicationError) as denied:
        service.list_tool_invocations(tool_id=command.tool_id)
    assert denied.value.status_code == 403 and len(plans.reads) == len(plans.batches) == 1


def test_runtime_confirmation_and_idempotent_replay_reauthorize_without_consuming_the_command():
    definition = tool_definition(confirmation_mode="user_confirm").model_copy(update={"tool_id": "quality.run_plan.prepare"})
    plans = Plans()
    runtime, state, audit, _, _, executions = build_runtime(tool=definition,
        replay_resources=ToolReceiptAccess(RunPlanReceiptAccess(plans)))
    payload = ToolInvocationRequest(tool_id=definition.tool_id, input=receipt().input_payload, idempotency_key="original-request")
    pending = asyncio.run(runtime.create(payload))
    assert pending.status == "waiting_confirmation" and not executions
    before = deepcopy(pending.model_dump()), len(audit.events)
    plans.error = SourceAccessDenied
    with pytest.raises(PlatformApplicationError) as denied:
        asyncio.run(runtime.confirm(pending.id))
    assert denied.value.status_code == 403
    with pytest.raises(PlatformApplicationError) as denied:
        asyncio.run(runtime.create(payload))
    assert denied.value.status_code == 403
    assert (state.get_invocation(pending.id).model_dump(), len(audit.events)) == before and not executions


def application():
    draft, review, sources, selection = plan_inputs()
    calls = []
    class Authorization:
        revoked = False
        def scope(self, project_id):
            calls.append(("scope", project_id))
            return SimpleNamespace(project_id=project_id)
        def require_current(self, access):
            calls.append(("current", access.project_id))
            if self.revoked:
                raise SourceAccessDenied("private source revoked")
    class OriginalSources:
        @contextmanager
        def verified_read_session(self):
            calls.append(("begin", "original"))
            try:
                yield
            finally:
                calls.append(("end", "original"))
        def run_plan_sources(self, prepared):
            calls.append(("sources", prepared["project_id"]))
            return sources
    def read_script(project, ident):
        calls.append(("script", ident))
        return draft
    def read_review(project, ident):
        calls.append(("review", ident))
        return review
    auth = Authorization()
    app = RunPlanApplicationService(SimpleNamespace(read=read_script), SimpleNamespace(read=read_review),
        OriginalSources(), auth, object(), object())
    scope = RunPlanCommandScope.model_validate({key: selection.model_dump(mode="json")[key] for key in RunPlanCommandScope.model_fields})
    return app, auth, scope, draft, review, sources, calls


def test_application_receipt_read_keeps_historical_pins_and_never_compiles_or_writes():
    app, auth, scope, draft, review, _, calls = application()
    draft["current_use"]["input_current"] = review["current_use"]["review_complete"] = False
    app.require_command_inputs_access(scope)
    assert calls == [("scope", scope.project_id), ("begin", "original"), ("script", scope.script_revision_id),
        ("review", scope.review_revision_id), ("sources", scope.project_id), ("current", scope.project_id), ("end", "original")]
    auth.revoked = True
    with pytest.raises(SourceAccessDenied):
        app.require_command_inputs_access(scope)


@pytest.mark.parametrize("fault", ["script_hash", "review_hash", "review_parent", "source_project", "image_hash"])
def test_application_rejects_substituted_original_parents_or_source_inventory(fault):
    app, _, scope, draft, review, sources, _ = application()
    if fault == "script_hash": draft["metadata"]["artifact_hash"] = "sha256:" + "f" * 64
    elif fault == "review_hash": review["revision"]["artifact_hash"] = "sha256:" + "f" * 64
    elif fault == "review_parent": review["revision"]["script_revision_id"] = "unrelated"
    elif fault == "source_project": sources["project_id"] = "unrelated"
    else: sources["image_artifact_hash"] = "sha256:" + "f" * 64
    with pytest.raises(RunPlanIntegrityError):
        app.require_command_inputs_access(scope)
