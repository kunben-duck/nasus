import asyncio
from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.case_approval_event_access import CaseApprovalEventAccess
from apps.api.app.application.platform.event_streams import PlatformEventStreamApplicationService
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.platform.tool_models import EventPayload
from apps.api.app.domain.quality_loop.case_approval import CASE_APPROVAL_EVENT
from apps.api.app.domain.system_image.source_access import SourceAccessDenied


def original_event():
    return EventPayload(event_id="event", event_type=CASE_APPROVAL_EVENT, occurred_at="2026-10-13T00:00:00+00:00",
        correlation_id="project", entity_type="test_design_case_approval", entity_id="revision", entity_version=1,
        conversation_id="conversation", mutation_kind="append", patch={"project_id": "project", "revision_id": "revision", "status": "approved"},
        query_keys=[["test-design-case-approvals", "project"]], snapshot_hint=True)


def access_ports():
    service = SimpleNamespace(read=lambda *_: {"revision": {"invocation_id": "command", "status": "approved"}})
    commands = SimpleNamespace(get_invocation=lambda _: SimpleNamespace(conversation_id="conversation", input_payload={}))
    return CaseApprovalEventAccess(service, commands)


def test_event_replay_rechecks_original_source_access_even_when_conversation_is_visible():
    policy, event = access_ports(), original_event()
    assert policy.can_access(event)
    def deny(*_):
        raise SourceAccessDenied("current source access withdrawn")
    policy.application.read = deny
    assert not policy.can_access(event)
    assert policy.can_access(event.model_copy(update={"event_type": "unrelated.event"}))


@pytest.mark.parametrize("fault", ["project", "revision", "body", "status", "conversation", "query"])
def test_event_substitution_or_extra_source_body_is_not_hidden_as_an_empty_stream(fault):
    policy, event = access_ports(), original_event()
    if fault == "project": event.patch["project_id"] = "foreign"
    elif fault == "revision": event.patch["revision_id"] = "foreign"
    elif fault == "body": event.patch["source_text"] = "untrusted private document"
    elif fault == "status": event.patch["status"] = "withdrawn"
    elif fault == "conversation": event.conversation_id = "foreign"
    else: event.query_keys = []
    with pytest.raises(PlatformApplicationError) as error:
        policy.can_access(event)
    assert error.value.status_code == 502


def test_stream_authorizer_advances_denied_cursor_but_never_yields_denied_event():
    event = original_event()
    safe = event.model_copy(update={"event_id": "safe", "event_type": "safe.event"})
    calls = []
    def list_after(**arguments):
        calls.append(arguments["after_event_id"])
        return [event, safe]
    state = PlatformEventStreamApplicationService(SimpleNamespace(list_after=list_after), SimpleNamespace(conversation_queue=lambda _: asyncio.Queue()),
        poll_seconds=.05, heartbeat_seconds=1, authorize_event=lambda value: value.event_type != CASE_APPROVAL_EVENT)
    async def observe():
        stream = state.stream_conversation_events("conversation", "cursor")
        try:
            assert (await stream.__anext__()).event_id == "safe"
        finally:
            await stream.aclose()
    asyncio.run(observe())
    assert calls == ["cursor"]


def test_stream_does_not_downgrade_failed_verification_to_denial():
    event = original_event()
    def failed(_):
        raise RuntimeError("verification offline")
    state = PlatformEventStreamApplicationService(SimpleNamespace(list_after=lambda **_: [event]), SimpleNamespace(conversation_queue=lambda _: asyncio.Queue()),
        poll_seconds=.05, heartbeat_seconds=1, authorize_event=failed)
    async def observe():
        stream = state.stream_conversation_events("conversation")
        with pytest.raises(RuntimeError, match="verification offline"):
            await stream.__anext__()
        await stream.aclose()
    asyncio.run(observe())
