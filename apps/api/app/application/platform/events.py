from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from .event_ports import (
    PlatformEventEntityReaderPort,
    PlatformEventStreamPort,
    ToolInvocationEventProjectionPort,
)
from .tool_models import EventPayload, ToolResult


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


class PlatformEventApplicationService:
    """Platform SSE/outbox event publication use cases."""

    def __init__(
        self,
        streams: PlatformEventStreamPort,
        entities: PlatformEventEntityReaderPort,
        tool_projection: ToolInvocationEventProjectionPort,
    ) -> None:
        self.streams = streams
        self.entities = entities
        self.tool_projection = tool_projection

    def _agent_goal_or_none(self, goal_id: str):
        return self.entities.get_agent_goal(goal_id)

    def _tool_invocation_or_none(self, invocation_id: str):
        try:
            return self._tool_invocation(invocation_id)
        except KeyError:
            return None

    def _tool_invocation(self, invocation_id: str):
        return self.entities.get_tool_invocation(invocation_id)

    def _agent_swarm(self, swarm_id: str):
        return self.entities.get_agent_swarm(swarm_id)

    async def push_event(
        self,
        conversation_id: str,
        event_type: str,
        entity_type: str,
        entity_id: str,
        mutation_kind: str,
        patch: Dict[str, Any],
        query_keys: List[List[str]],
        *,
        snapshot_hint: bool = False,
        payload: Dict[str, Any] | None = None,
    ) -> None:
        event_id = f"evt_{uuid4().hex[:10]}"
        event = EventPayload(
            event_id=event_id,
            event_type=event_type,
            occurred_at=_now_iso(),
            correlation_id=str(
                patch.get("correlation_id")
                or patch.get("tool_invocation_id")
                or patch.get("agent_goal_id")
                or event_id
            ),
            conversation_id=conversation_id,
            tool_invocation_id=entity_id if entity_type == "tool_invocation" else _optional_str(patch.get("tool_invocation_id")),
            agent_goal_id=entity_id if entity_type == "agent_goal" else _optional_str(patch.get("agent_goal_id")),
            agent_step_id=_optional_str(patch.get("agent_step_id")),
            swarm_run_id=entity_id if entity_type == "agent_swarm" else _optional_str(patch.get("swarm_run_id")),
            assignment_id=_optional_str(patch.get("assignment_id")),
            task_id=entity_id if entity_type == "task" else _optional_str(patch.get("task_id")),
            run_id=entity_id if entity_type == "run" else _optional_str(patch.get("run_id")),
            entity_type=entity_type,
            entity_id=entity_id,
            entity_version=0,
            mutation_kind=mutation_kind,  # type: ignore[arg-type]
            patch=patch,
            query_keys=query_keys,
            snapshot_hint=snapshot_hint,
            payload=self.event_payload(entity_type, entity_id, patch, payload),
        )
        await self.streams.publish_conversation_event(conversation_id, event)

    async def push_goal_event(
        self,
        goal_id: str,
        event_type: str,
        mutation_kind: str,
        patch: Dict[str, Any],
        query_keys: List[List[str]],
        *,
        snapshot_hint: bool = False,
        payload: Dict[str, Any] | None = None,
    ) -> None:
        goal = self._agent_goal_or_none(goal_id)
        effective_query_keys = [list(key) for key in query_keys]
        if goal:
            conversation_query_key = ["conversation", goal.conversation_id]
            if conversation_query_key not in effective_query_keys:
                effective_query_keys.append(conversation_query_key)
        event_id = f"evt_{uuid4().hex[:10]}"
        event = EventPayload(
            event_id=event_id,
            event_type=event_type,
            occurred_at=_now_iso(),
            correlation_id=str(patch.get("correlation_id") or patch.get("tool_invocation_id") or goal_id),
            conversation_id=goal.conversation_id if goal else _optional_str(patch.get("conversation_id")),
            tool_invocation_id=_optional_str(patch.get("tool_invocation_id")),
            agent_goal_id=goal_id,
            agent_step_id=_optional_str(patch.get("agent_step_id")),
            swarm_run_id=_optional_str(patch.get("swarm_run_id")),
            assignment_id=_optional_str(patch.get("assignment_id")),
            task_id=_optional_str(patch.get("task_id")),
            run_id=_optional_str(patch.get("run_id")),
            entity_type="agent_goal",
            entity_id=goal_id,
            entity_version=0,
            mutation_kind=mutation_kind,  # type: ignore[arg-type]
            patch=patch,
            query_keys=effective_query_keys,
            snapshot_hint=snapshot_hint,
            payload=self.event_payload("agent_goal", goal_id, patch, payload),
        )
        await self.streams.publish_goal_event(goal_id, event)

    def event_payload(
        self,
        entity_type: str,
        entity_id: str,
        patch: Dict[str, Any],
        payload: Dict[str, Any] | None,
    ) -> Dict[str, Any]:
        if payload is not None:
            return payload
        if entity_type == "agent_goal":
            goal = self._agent_goal_or_none(entity_id)
            if goal is not None:
                return {"patch": patch, "agent_goal": goal.model_dump()}
        if entity_type == "agent_swarm":
            try:
                return {"patch": patch, "agent_swarm": self._agent_swarm(entity_id).model_dump()}
            except KeyError:
                return patch
        if entity_type == "tool_invocation":
            invocation = self._tool_invocation_or_none(entity_id)
            if invocation is not None:
                return {"patch": patch, "tool_invocation": invocation.model_dump()}
        return patch

    async def emit_tool_status(
        self,
        invocation_id: str,
        status: str,
        summary: str,
        query_keys: List[List[str]],
        result: ToolResult | None = None,
    ) -> None:
        invocation = self._tool_invocation(invocation_id)
        invocation.status = status  # type: ignore[assignment]
        invocation.summary = summary
        if result is not None:
            invocation.result = result
        self.tool_projection.persist_and_project(invocation)

        if invocation.conversation_id:
            await self.push_event(
                invocation.conversation_id,
                "tool.invocation.updated",
                "tool_invocation",
                invocation.id,
                "replace",
                {
                    "status": invocation.status,
                    "summary": invocation.summary,
                    "tool_id": invocation.tool_id,
                },
                query_keys,
            )

    async def emit_tool_invocation_update(
        self,
        *,
        conversation_id: str,
        invocation: Any,
        summary: str | None = None,
    ) -> None:
        await self.push_event(
            conversation_id,
            "tool.invocation.updated",
            "tool_invocation",
            invocation.id,
            "replace",
            {
                "status": invocation.status,
                "summary": summary or invocation.summary,
                "tool_id": invocation.tool_id,
            },
            [["conversation", conversation_id]],
        )

    async def stream_conversation_events(self, conversation_id: str, last_event_id: str | None = None):
        async for event in self.streams.stream_conversation_events(conversation_id, last_event_id):
            yield event

    async def stream_goal_events(self, goal_id: str, last_event_id: str | None = None):
        async for event in self.streams.stream_goal_events(goal_id, last_event_id):
            yield event

    async def stream_swarm_events(self, swarm_id: str, last_event_id: str | None = None):
        if last_event_id is None:
            yield self.swarm_snapshot_event(swarm_id)
        async for event in self.streams.stream_swarm_events(swarm_id, last_event_id):
            yield event

    def swarm_snapshot_event(self, swarm_id: str) -> EventPayload:
        swarm = self._agent_swarm(swarm_id)
        entity_version = self.streams.latest_entity_version(
            entity_type="agent_swarm",
            entity_id=swarm_id,
        )
        return EventPayload(
            event_id=f"evt_{uuid4().hex[:10]}",
            event_type="agent.swarm.snapshot",
            occurred_at=_now_iso(),
            correlation_id=swarm_id,
            conversation_id=swarm.conversation_id,
            agent_goal_id=swarm.parent_goal_id,
            swarm_run_id=swarm_id,
            entity_type="agent_swarm",
            entity_id=swarm_id,
            entity_version=entity_version,
            mutation_kind="replace",
            patch={"status": swarm.status, "result_summary": swarm.result_summary},
            query_keys=[["conversation", swarm.conversation_id], ["agent-swarm", swarm_id]],
            snapshot_hint=True,
            payload={"agent_swarm": swarm.model_dump()},
        )
