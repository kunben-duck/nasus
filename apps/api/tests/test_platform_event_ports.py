from __future__ import annotations

import asyncio
from collections import defaultdict
from threading import RLock
from types import SimpleNamespace

from apps.api.app.application.agent.agent_models import ConversationSession
from apps.api.app.application.platform.audit_events import PlatformAuditApplicationService
from apps.api.app.application.platform.event_streams import (
    PlatformEventStreamApplicationService,
)
from apps.api.app.application.platform.events import PlatformEventApplicationService
from apps.api.app.application.platform.tool_models import (
    AuditEvent,
    EventPayload,
    ToolInvocation,
    ToolResult,
)
from apps.api.app.application.platform.tool_projection import (
    ToolInvocationProjectionApplicationService,
)
from apps.api.app.infrastructure.platform.audit_persistence import (
    SQLAlchemyAuditEventPersistence,
)
from apps.api.app.infrastructure.platform.event_runtime import (
    CallablePlatformEventEntityReader,
    EventStreamWakeUpState,
    PlatformEventEntityAdapters,
    SSEWakeUpBuffer,
)
from apps.api.app.infrastructure.platform.tool_projection import (
    ProjectedToolInvocationProjectionState,
    ToolInvocationProjectionAdapters,
    ToolInvocationProjectionFacts,
)


def invocation(invocation_id: str = "tool_event_port") -> ToolInvocation:
    return ToolInvocation(
        id=invocation_id,
        conversation_id="conversation_event_port",
        tool_id="run.progress.get",
        status="running",
        summary="Running",
    )


def conversation() -> ConversationSession:
    return ConversationSession(
        id="conversation_event_port",
        session_id="session_event_port",
        title="Event port",
        space_type="project",
        space_id="project_event_port",
        project_id="project_event_port",
    )


def event(event_id: str = "event_port") -> EventPayload:
    return EventPayload(
        event_id=event_id,
        event_type="tool.invocation.updated",
        occurred_at="2026-01-01T00:00:00+00:00",
        correlation_id="tool_event_port",
        conversation_id="conversation_event_port",
        tool_invocation_id="tool_event_port",
        agent_goal_id="goal_event_port",
        swarm_run_id="swarm_event_port",
        entity_type="tool_invocation",
        entity_id="tool_event_port",
        entity_version=0,
        mutation_kind="replace",
        patch={"status": "completed"},
    )


def test_projection_and_sql_audit_ports_persist_without_application_store() -> None:
    lock = RLock()
    invocations: dict[str, ToolInvocation] = {}
    conversations = {"conversation_event_port": conversation()}
    persisted_invocations: list[str] = []
    persisted_conversations: list[str] = []
    projection = ToolInvocationProjectionApplicationService(
        ProjectedToolInvocationProjectionState(
            ToolInvocationProjectionFacts(
                invocations=invocations,
                conversations=conversations,
            ),
            ToolInvocationProjectionAdapters(
                mutation_guard=lambda: lock,
                persist_invocation=lambda item: persisted_invocations.append(item.id),
                persist_conversation=lambda item: persisted_conversations.append(item.id),
            ),
        )
    )
    tool = invocation()

    projection.persist_and_project(tool)
    tool.summary = "Updated"
    projection.persist_and_project(tool)

    assert invocations == {tool.id: tool}
    assert conversations["conversation_event_port"].tool_invocations == [tool]
    assert persisted_invocations == [tool.id, tool.id]
    assert persisted_conversations == [
        "conversation_event_port",
        "conversation_event_port",
    ]

    class RecordingAuditRepository:
        def __init__(self) -> None:
            self.events: list[AuditEvent] = []

        def append_audit_event(self, item: AuditEvent) -> None:
            self.events.append(item)

    audit_repository = RecordingAuditRepository()
    audit = PlatformAuditApplicationService(
        SQLAlchemyAuditEventPersistence(audit_repository)
    )
    audit_event = AuditEvent(
        id="audit_event_port",
        occurred_at="2026-01-01T00:00:00+00:00",
        actor="system",
        action="tool.invocation.updated",
        entity_type="tool_invocation",
        entity_id=tool.id,
        summary="Updated",
    )

    audit.record_audit_event(audit_event)

    assert audit_repository.events == [audit_event]


class RecordingOutbox:
    def __init__(self) -> None:
        self.events: list[EventPayload] = []

    def append(self, item: EventPayload) -> EventPayload:
        item.entity_version = len(self.events) + 1
        self.events.append(item)
        return item

    def list_after(self, **_kwargs) -> list[EventPayload]:
        return []

    def latest_entity_version(self, *, entity_type: str, entity_id: str) -> int:
        return max(
            (
                item.entity_version
                for item in self.events
                if item.entity_type == entity_type and item.entity_id == entity_id
            ),
            default=0,
        )


def test_event_stream_persists_before_fanout_and_updates_projection_version() -> None:
    lock = RLock()
    queues = {
        "conversation": {},
        "goal": {},
        "swarm": {},
    }
    versions: dict[str, int] = defaultdict(int)
    buffer = SSEWakeUpBuffer(
        EventStreamWakeUpState(
            conversation_queues=queues["conversation"],
            goal_queues=queues["goal"],
            swarm_queues=queues["swarm"],
            entity_versions=versions,
        ),
        lambda: lock,
    )
    outbox = RecordingOutbox()
    streams = PlatformEventStreamApplicationService(
        outbox,
        buffer,
        poll_seconds=0.05,
        heartbeat_seconds=1,
    )
    payload = event()

    asyncio.run(streams.publish_conversation_event("conversation_event_port", payload))

    assert outbox.events == [payload]
    assert payload.entity_version == 1
    assert versions["tool_invocation:tool_event_port"] == 1
    assert list(queues["conversation"]["conversation_event_port"]._queue) == [payload]
    assert list(queues["goal"]["goal_event_port"]._queue) == [payload]
    assert list(queues["swarm"]["swarm_event_port"]._queue) == [payload]
    assert streams.latest_entity_version(
        entity_type="tool_invocation",
        entity_id="tool_event_port",
    ) == 1


class RecordingStreams:
    def __init__(self) -> None:
        self.events: list[EventPayload] = []

    async def publish_conversation_event(
        self,
        _conversation_id: str,
        payload: EventPayload,
    ) -> None:
        self.events.append(payload)

    async def publish_goal_event(self, _goal_id: str, payload: EventPayload) -> None:
        self.events.append(payload)

    async def stream_conversation_events(self, *_args, **_kwargs):
        if False:
            yield None

    async def stream_goal_events(self, *_args, **_kwargs):
        if False:
            yield None

    async def stream_swarm_events(self, *_args, **_kwargs):
        if False:
            yield None

    def latest_entity_version(self, *, entity_type: str, entity_id: str) -> int:
        assert (entity_type, entity_id) == ("agent_swarm", "swarm_event_port")
        return 7


class RecordingProjection:
    def __init__(self) -> None:
        self.invocations: list[ToolInvocation] = []

    def persist_and_project(self, item: ToolInvocation) -> None:
        self.invocations.append(item)


def test_platform_events_read_entities_and_project_tool_status_through_ports() -> None:
    tool = invocation()
    goal = SimpleNamespace(
        id="goal_event_port",
        conversation_id="conversation_event_port",
        model_dump=lambda: {"id": "goal_event_port", "status": "running"},
    )
    swarm = SimpleNamespace(
        id="swarm_event_port",
        conversation_id="conversation_event_port",
        parent_goal_id="goal_event_port",
        status="completed",
        result_summary="Merged",
        model_dump=lambda: {"id": "swarm_event_port", "status": "completed"},
    )
    streams = RecordingStreams()
    projection = RecordingProjection()
    events = PlatformEventApplicationService(
        streams,
        CallablePlatformEventEntityReader(
            PlatformEventEntityAdapters(
                get_agent_goal=lambda goal_id: goal if goal_id == goal.id else None,
                get_tool_invocation=lambda invocation_id: (
                    tool if invocation_id == tool.id else (_ for _ in ()).throw(KeyError(invocation_id))
                ),
                get_agent_swarm=lambda swarm_id: (
                    swarm if swarm_id == swarm.id else (_ for _ in ()).throw(KeyError(swarm_id))
                ),
            )
        ),
        projection,
    )
    result = ToolResult(
        invocation_id=tool.id,
        status="completed",
        summary="Completed",
    )

    asyncio.run(
        events.emit_tool_status(
            tool.id,
            "completed",
            "Completed",
            [["conversation", "conversation_event_port"]],
            result,
        )
    )
    snapshot = events.swarm_snapshot_event(swarm.id)

    assert tool.status == "completed"
    assert tool.result == result
    assert projection.invocations == [tool]
    assert streams.events[0].payload["tool_invocation"]["id"] == tool.id
    assert streams.events[0].payload["tool_invocation"]["status"] == "completed"
    assert snapshot.entity_version == 7
    assert snapshot.payload == {
        "agent_swarm": {"id": "swarm_event_port", "status": "completed"}
    }
