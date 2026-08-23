from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ContextManager, Protocol

from ...application.agent.agent_models import ConversationSession
from ...application.platform.projection_ports import ToolInvocationProjectionStatePort
from ...application.platform.tool_models import ToolInvocation


@dataclass(frozen=True)
class ToolInvocationProjectionFacts:
    invocations: dict[str, ToolInvocation]
    conversations: dict[str, ConversationSession]


@dataclass(frozen=True)
class ToolInvocationProjectionAdapters:
    mutation_guard: Callable[[], ContextManager[Any]]
    persist_invocation: Callable[[ToolInvocation], None]
    persist_conversation: Callable[[ConversationSession], None]


class ToolInvocationProjectionRepository(Protocol):
    def upsert_tool_invocation(self, invocation: ToolInvocation) -> None:
        ...


class ProjectedToolInvocationProjectionState(ToolInvocationProjectionStatePort):
    """Compatibility-only projection with process-local conversation mirrors."""

    def __init__(
        self,
        facts: ToolInvocationProjectionFacts,
        adapters: ToolInvocationProjectionAdapters,
    ) -> None:
        self._facts = facts
        self._adapters = adapters

    def persist_and_project(self, invocation: ToolInvocation) -> None:
        with self._adapters.mutation_guard():
            self._facts.invocations[invocation.id] = invocation
        self._adapters.persist_invocation(invocation)
        self._project_in_conversation(invocation)

    def mirror_invocation(self, invocation: ToolInvocation) -> None:
        """Refresh compatibility reads without becoming the durable writer."""
        with self._adapters.mutation_guard():
            self._facts.invocations[invocation.id] = invocation
        self._project_in_conversation(invocation)

    def _project_in_conversation(self, invocation: ToolInvocation) -> None:
        conversation: ConversationSession | None = None
        with self._adapters.mutation_guard():
            if not invocation.conversation_id:
                return
            conversation = self._facts.conversations.get(invocation.conversation_id)
            if conversation is None:
                return
            existing_index = next(
                (
                    index
                    for index, current in enumerate(conversation.tool_invocations)
                    if current.id == invocation.id
                ),
                None,
            )
            if existing_index is None:
                conversation.tool_invocations.append(invocation)
            else:
                conversation.tool_invocations[existing_index] = invocation
        self._adapters.persist_conversation(conversation)


class SQLAlchemyToolInvocationProjectionState(ToolInvocationProjectionStatePort):
    """Persist the shared ToolInvocation projection directly in PostgreSQL.

    ConversationRepository assembles ``conversation.tool_invocations`` from
    rows keyed by ``conversation_id``. Persisting the invocation therefore
    updates both the canonical fact and every process' conversation read model
    without a second Conversation aggregate write or an in-process mirror.
    """

    def __init__(self, repository: ToolInvocationProjectionRepository) -> None:
        self._repository = repository

    def persist_and_project(self, invocation: ToolInvocation) -> None:
        self._repository.upsert_tool_invocation(invocation)


__all__ = [
    "ProjectedToolInvocationProjectionState",
    "SQLAlchemyToolInvocationProjectionState",
    "ToolInvocationProjectionAdapters",
    "ToolInvocationProjectionFacts",
    "ToolInvocationProjectionRepository",
]
