from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence

from ...application.agent.agent_models import ConversationSession
from ...application.platform.tool_models import (
    AuditEvent,
    ToolDefinition,
    ToolInvocation,
)


class ToolInvocationFactRepository(Protocol):
    def get_conversation(self, conversation_id: str) -> ConversationSession | None: ...

    def get_tool_invocation(self, invocation_id: str) -> ToolInvocation | None: ...

    def find_idempotent_tool_invocation(
        self, *, idempotency_scope: str, tool_id: str, idempotency_key: str,
    ) -> ToolInvocation | None: ...

    def load_tool_invocations(self) -> list[ToolInvocation]: ...

    def load_audit_events(self) -> list[AuditEvent]: ...


@dataclass(frozen=True)
class ToolInvocationApplicationProjectionState:
    tools: Sequence[ToolDefinition]
    conversations: Mapping[str, ConversationSession]
    invocations: Mapping[str, ToolInvocation]
    audit_events: Mapping[str, AuditEvent]


@dataclass(frozen=True)
class ToolInvocationApplicationProjectionAdapters:
    projection_lock: Callable[[], AbstractContextManager[Any]]


class ProjectedToolInvocationApplicationState:
    """Thread-safe read projection for ToolInvocation application use cases."""

    def __init__(
        self,
        state: ToolInvocationApplicationProjectionState,
        adapters: ToolInvocationApplicationProjectionAdapters,
    ) -> None:
        self._state = state
        self._adapters = adapters

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._state.tools)

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        with self._adapters.projection_lock():
            return self._state.conversations[conversation_id]

    def get_invocation(self, invocation_id: str) -> ToolInvocation:
        with self._adapters.projection_lock():
            return self._state.invocations[invocation_id]

    def list_invocations(self) -> list[ToolInvocation]:
        with self._adapters.projection_lock():
            return list(self._state.invocations.values())

    def find_idempotent_invocation(
        self, *, idempotency_scope: str, tool_id: str, idempotency_key: str,
    ) -> ToolInvocation | None:
        with self._adapters.projection_lock():
            matches = [item for item in self._state.invocations.values()
                if item.idempotency_scope == idempotency_scope and item.tool_id == tool_id
                and item.idempotency_key == idempotency_key]
            if len(matches) > 1:
                raise ValueError("non-unique original command")
            return matches[0] if matches else None

    def list_audit_events(self) -> list[AuditEvent]:
        with self._adapters.projection_lock():
            return list(self._state.audit_events.values())


class SQLAlchemyToolInvocationApplicationState:
    """Read ToolInvocation and audit facts from the durable shared store.

    Agent workflows execute in a separate Temporal worker process. Reading
    query facts from an API-local projection would therefore miss committed
    worker updates until a manual hydration cycle runs.
    """

    def __init__(
        self,
        *,
        tools: Sequence[ToolDefinition],
        repository: ToolInvocationFactRepository,
    ) -> None:
        self._tools = tuple(tools)
        self._repository = repository

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools)

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        conversation = self._repository.get_conversation(conversation_id)
        if conversation is None:
            raise KeyError(conversation_id)
        return conversation

    def get_invocation(self, invocation_id: str) -> ToolInvocation:
        invocation = self._repository.get_tool_invocation(invocation_id)
        if invocation is None:
            raise KeyError(invocation_id)
        return invocation

    def list_invocations(self) -> list[ToolInvocation]:
        return self._repository.load_tool_invocations()

    def find_idempotent_invocation(
        self, *, idempotency_scope: str, tool_id: str, idempotency_key: str,
    ) -> ToolInvocation | None:
        return self._repository.find_idempotent_tool_invocation(
            idempotency_scope=idempotency_scope, tool_id=tool_id, idempotency_key=idempotency_key,
        )

    def list_audit_events(self) -> list[AuditEvent]:
        return self._repository.load_audit_events()


__all__ = [
    "ProjectedToolInvocationApplicationState",
    "SQLAlchemyToolInvocationApplicationState",
    "ToolInvocationFactRepository",
    "ToolInvocationApplicationProjectionAdapters",
    "ToolInvocationApplicationProjectionState",
]
