"""Read-port specimens; Java/PG/MinIO verification is tested separately."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.agent.use_cases import AgentApplicationService
from apps.api.app.application.platform.events import PlatformEventApplicationService
from apps.api.app.application.platform.native_build_receipts import NativeBuildReceiptAccess, NATIVE_BUILD_RECEIPT_TOOLS
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.application.platform.tool_receipt_access import require_receipt_access
from apps.api.app.application.quality_loop.native_build_inputs import NativeBuildCommand, NativeBuildSelection, NativeBuildTarget
from apps.api.app.application.quality_loop.native_builds import NativeBuildApplicationService
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_native_build import request_value
from apps.api.tests.test_platform_event_ports import conversation, event, RecordingStreams, RecordingProjection


HASH = "sha256:" + "a" * 64


def invocation(tool):
    value = {"project_id": "project", "image_revision_id": "image", "image_artifact_hash": HASH,
        "binding_id": "binding", "source_revision_id": "revision", "artifact_path": "target/app.jar"}
    if tool == "quality.native_build.prepare":
        value.update(request_digest=HASH, operator_policy_digest=HASH, source_scope_digest=HASH)
    elif tool in {"query.quality.native_build", "quality.native_build.cancel"}:
        value = {"project_id": "project", "invocation_id": "original-build"}
    return ToolInvocation(id="original", tool_id=tool, status="waiting_confirmation", summary="private build detail",
        input_payload={**value, "idempotency_key": "private-key"}, idempotency_key="private-key",
        result=ToolResult(invocation_id="original", status="completed", summary="private original output"))


@pytest.mark.parametrize("tool", sorted(NATIVE_BUILD_RECEIPT_TOOLS))
def test_native_original_read_batch_and_broadcast_preserve_scope_and_hide_private_data(tool):
    calls = []
    port = SimpleNamespace(require_receipt_inputs_access=lambda scope: calls.append(scope),
        require_receipt_inputs_access_many=lambda scopes: calls.append(scopes))
    value, access = invocation(tool), NativeBuildReceiptAccess(port)
    original = deepcopy(value.model_dump())
    access.require_access(value)
    access.require_batch_access((value, value.model_copy(update={"id": "replay"}, deep=True)))
    assert len(calls) == 2 and len(calls[1]) == 1 and calls[0] == calls[1][0]
    if isinstance(calls[0], NativeBuildSelection):
        assert calls[0].expected_artifact_hash is None
    projected = access.broadcast_view(value)
    assert projected.input_payload == {} and projected.result is None and projected.idempotency_key is None
    assert projected.summary == "Native build command status: waiting_confirmation."
    assert "private" not in str(projected.model_dump()) and value.model_dump() == original


@pytest.mark.parametrize("tool", sorted(NATIVE_BUILD_RECEIPT_TOOLS))
@pytest.mark.parametrize("fault,status", [(SourceAccessDenied("private revoked source"), 403),
    (ValueError("private corrupt artifact"), 502), (RuntimeError("private unavailable port"), 503)])
def test_native_original_scope_errors_are_sanitized_in_single_and_batch_reads(tool, fault, status):
    def fail(*args):
        raise fault
    access = NativeBuildReceiptAccess(SimpleNamespace(require_receipt_inputs_access=fail,
        require_receipt_inputs_access_many=fail))
    for operation in (lambda: access.require_access(invocation(tool)), lambda: access.require_batch_access((invocation(tool),))):
        with pytest.raises(PlatformApplicationError) as failure:
            operation()
        assert failure.value.status_code == status and "private" not in str(failure.value)


@pytest.mark.parametrize("tool", sorted(NATIVE_BUILD_RECEIPT_TOOLS))
def test_native_receipt_missing_policy_or_port_fails_closed_and_invalid_original_scope_is_rejected(tool):
    value = invocation(tool)
    for operation in (lambda: require_receipt_access(None, value),
                      lambda: NativeBuildReceiptAccess(object()).require_access(value),
                      lambda: NativeBuildReceiptAccess(object()).require_batch_access((value,))):
        with pytest.raises(PlatformApplicationError) as missing:
            operation()
        assert missing.value.status_code == 503
    value.input_payload.pop("project_id")
    with pytest.raises(PlatformApplicationError) as invalid:
        NativeBuildReceiptAccess(object()).require_access(value)
    assert invalid.value.status_code == 409


def test_native_receipt_application_reads_original_bytes_without_operator_or_dispatch_and_checks_final_acl(request_value):
    calls = []
    revoked = False
    def current(scope):
        if revoked:
            raise SourceAccessDenied("revoked after original source read")
    access = SimpleNamespace(require_binding=lambda ident: calls.append(("binding", ident)))
    authorization = SimpleNamespace(scope=lambda project: access, require_current=current)
    sources = SimpleNamespace(read=lambda **selection: calls.append(("source", selection)) or request_value.source)
    service = NativeBuildApplicationService(sources, authorization, object(), object(), object())
    pin = request_value.source.pin
    selection = NativeBuildSelection(project_id=pin.project_id, image_revision_id=pin.image_revision_id,
        image_artifact_hash=pin.image_artifact_hash, binding_id=pin.binding_id, source_revision_id=pin.source_revision_id,
        artifact_path=request_value.artifact_path)
    command = NativeBuildCommand(**selection.model_dump(mode="json"), request_digest=request_value.digest,
        operator_policy_digest=HASH, source_scope_digest=HASH)
    service.require_receipt_inputs_access_many((selection, command))
    assert len([value for value in calls if value[0] == "source"]) == 2
    with pytest.raises(ValueError, match="original command source differs"):
        service.require_receipt_inputs_access(command.model_copy(update={"request_digest": HASH}))
    def late_revoke(**selection):
        nonlocal revoked
        revoked = True
        return request_value.source
    sources.read = late_revoke
    with pytest.raises(SourceAccessDenied):
        service.require_receipt_inputs_access(command)


def test_native_receipt_target_uses_original_read_port_not_preview_or_rebuild():
    calls = []
    original = SimpleNamespace()
    authorization = SimpleNamespace(scope=lambda project: original, require_current=lambda scope: calls.append(("current", scope)))
    service = NativeBuildApplicationService(object(), authorization, object(), object(), object())
    service.read = lambda project, ident: calls.append(("read", project, ident))
    service.require_receipt_inputs_access(NativeBuildTarget(project_id="project", invocation_id="original-build"))
    assert calls == [("read", "project", "original-build"), ("current", original)]


def test_native_receipt_batch_cannot_silently_truncate():
    value = invocation("query.quality.native_build")
    access = NativeBuildReceiptAccess(SimpleNamespace(require_receipt_inputs_access_many=lambda values: pytest.fail("truncated batch dispatched")))
    commands = [value.model_copy(update={"input_payload": {"project_id": "project", "invocation_id": f"build-{i}"}}, deep=True) for i in range(129)]
    with pytest.raises(PlatformApplicationError) as too_many:
        access.require_batch_access(commands)
    assert too_many.value.status_code == 503


@pytest.mark.parametrize("tool", sorted(NATIVE_BUILD_RECEIPT_TOOLS))
@pytest.mark.parametrize("operation", ["ensure", "list", "get", "archive", "search"])
def test_native_conversation_discovery_is_lifecycle_only_without_authorizing_source_read(tool, operation):
    command = invocation(tool)
    original = conversation().model_copy(update={"tool_invocations": [command]}, deep=True)
    snapshot = deepcopy(original.model_dump())
    manager = SimpleNamespace(ensure_conversation=lambda _: original, list_conversations=lambda **_: [original],
        get_conversation=lambda _: original, archive_conversation=lambda *_: original,
        search_conversations=lambda _: {"conversations": [original]})
    service = AgentApplicationService(conversations=manager, events=object(), explanations=object(), goals=object(),
        memory=object(), messages=object(), swarm=object(), tool_broadcast_view=NativeBuildReceiptAccess(object()).broadcast_view)
    if operation == "ensure":
        result = service.ensure_conversation(None)
    elif operation == "list":
        result = service.list_conversations()[0]
    elif operation == "get":
        result = service.get_conversation(original.id)
    elif operation == "archive":
        result = service.archive_conversation(original.id, None)
    else:
        result = service.search_conversations("Event")["conversations"][0]
    projected = result.tool_invocations[0]
    assert projected.input_payload == {} and projected.result is None and projected.idempotency_key is None
    assert projected.summary == f"Native build command status: {command.status}."
    assert original.model_dump() == snapshot


@pytest.mark.parametrize("tool", sorted(NATIVE_BUILD_RECEIPT_TOOLS))
def test_native_fresh_event_removes_explicit_private_payload_before_publication(tool):
    command, streams = invocation(tool), RecordingStreams()
    original = deepcopy(command.model_dump())
    service = PlatformEventApplicationService(streams, SimpleNamespace(get_tool_invocation=lambda _: command),
        RecordingProjection(), tool_broadcast_view=NativeBuildReceiptAccess(object()).broadcast_view)
    asyncio.run(service.push_event("conversation_event_port", "tool.invocation.updated", "tool_invocation", command.id,
        "replace", {"status": command.status, "input_payload": command.input_payload, "summary": command.summary}, [],
        payload={"tool_invocation": original, "private_build_detail": command.input_payload}))
    published = streams.events[0]
    assert published.patch == {"status": command.status, "summary": f"Native build command status: {command.status}.", "tool_id": tool}
    assert published.payload["patch"] == published.patch and set(published.payload) == {"patch", "tool_invocation"}
    assert published.payload["tool_invocation"]["input_payload"] == {} and published.payload["tool_invocation"]["result"] is None
    assert command.model_dump() == original and "private" not in str(published.model_dump())


@pytest.mark.parametrize("tool", sorted(NATIVE_BUILD_RECEIPT_TOOLS))
@pytest.mark.parametrize("stream", ["conversation", "goal", "swarm"])
def test_native_historical_outbox_projection_does_not_need_current_entities_or_mutate_archives(tool, stream):
    command = invocation(tool)
    original = event().model_copy(update={"tool_invocation_id": command.id, "entity_id": command.id,
        "patch": {"summary": command.summary, "input_payload": command.input_payload},
        "payload": {"tool_invocation": command.model_dump(), "private_build_detail": command.input_payload}}, deep=True)
    snapshot = deepcopy(original.model_dump())
    class Replays(RecordingStreams):
        async def replay(self, ident, cursor):
            assert (ident, cursor) == ("original-stream", "old-cursor")
            yield original
            yield None
        stream_conversation_events = stream_goal_events = stream_swarm_events = replay
    service = PlatformEventApplicationService(Replays(), object(), object(),
        tool_broadcast_view=NativeBuildReceiptAccess(object()).broadcast_view)
    async def collect():
        return [value async for value in getattr(service, f"stream_{stream}_events")("original-stream", "old-cursor")]
    values = asyncio.run(collect())
    assert len(values) == 2 and values[1] is None
    projected = values[0]
    assert projected.patch == {"status": command.status, "summary": f"Native build command status: {command.status}.", "tool_id": tool}
    assert projected.payload["patch"] == projected.patch and set(projected.payload) == {"patch", "tool_invocation"}
    assert projected.payload["tool_invocation"]["input_payload"] == {} and projected.payload["tool_invocation"]["result"] is None
    assert projected.event_id == original.event_id and projected.entity_version == original.entity_version
    assert "private" not in str(projected.model_dump()) and original.model_dump() == snapshot
