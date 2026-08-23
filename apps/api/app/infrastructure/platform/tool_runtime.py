from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Callable, Mapping, MutableMapping, Protocol, Sequence

from ...application.platform.tool_models import ToolDefinition, ToolInvocation


@dataclass(frozen=True)
class ToolInvocationRuntimeProjectionState:
    invocations: MutableMapping[str, ToolInvocation]


@dataclass(frozen=True)
class ToolInvocationRuntimeAdapters:
    projection_lock: Callable[[], AbstractContextManager[Any]]
    persist_invocation: Callable[[ToolInvocation], None]


class ToolInvocationRuntimeRepository(Protocol):
    def create_tool_invocation(
        self,
        invocation: ToolInvocation,
    ) -> ToolInvocation: ...

    def get_tool_invocation(
        self,
        invocation_id: str,
    ) -> ToolInvocation | None: ...

    def load_tool_invocations(self) -> list[ToolInvocation]: ...

    def find_idempotent_tool_invocation(
        self,
        *,
        idempotency_scope: str,
        tool_id: str,
        idempotency_key: str,
    ) -> ToolInvocation | None: ...

    def claim_tool_invocation_for_execution(
        self,
        invocation_id: str,
        *,
        expected_statuses: tuple[str, ...],
        input_updates: dict | None = None,
    ) -> ToolInvocation | None: ...

    def upsert_tool_invocation(self, invocation: ToolInvocation) -> None: ...


class ProjectedToolInvocationRuntimeState:
    """Compatibility runtime state for isolated tests and migration paths."""

    def __init__(
        self,
        state: ToolInvocationRuntimeProjectionState,
        adapters: ToolInvocationRuntimeAdapters,
    ) -> None:
        self._state = state
        self._adapters = adapters

    def create_invocation(self, invocation: ToolInvocation) -> ToolInvocation:
        with self._adapters.projection_lock():
            if invocation.idempotency_scope and invocation.idempotency_key:
                existing = self._find_idempotent_invocation_unlocked(
                    idempotency_scope=invocation.idempotency_scope,
                    tool_id=invocation.tool_id,
                    idempotency_key=invocation.idempotency_key,
                )
                if existing is not None:
                    return existing
            self._state.invocations[invocation.id] = invocation
        self._adapters.persist_invocation(invocation)
        return invocation

    def get_invocation(self, invocation_id: str) -> ToolInvocation:
        with self._adapters.projection_lock():
            return self._state.invocations[invocation_id]

    def list_invocations(self) -> list[ToolInvocation]:
        with self._adapters.projection_lock():
            return list(self._state.invocations.values())

    def find_idempotent_invocation(
        self,
        *,
        idempotency_scope: str,
        tool_id: str,
        idempotency_key: str,
    ) -> ToolInvocation | None:
        with self._adapters.projection_lock():
            return self._find_idempotent_invocation_unlocked(
                idempotency_scope=idempotency_scope,
                tool_id=tool_id,
                idempotency_key=idempotency_key,
            )

    def claim_for_execution(
        self,
        invocation_id: str,
        *,
        expected_statuses: tuple[str, ...],
        input_updates: dict[str, Any] | None = None,
    ) -> ToolInvocation | None:
        with self._adapters.projection_lock():
            current = self._state.invocations[invocation_id]
            if current.status not in expected_statuses:
                return None
            claimed = current.model_copy(deep=True)
            claimed.status = "running"
            claimed.input_payload.update(input_updates or {})
            claimed.revision += 1
            self._state.invocations[invocation_id] = claimed
        self._adapters.persist_invocation(claimed)
        return claimed

    def persist_invocation(self, invocation: ToolInvocation) -> None:
        self._adapters.persist_invocation(invocation)

    def _find_idempotent_invocation_unlocked(
        self,
        *,
        idempotency_scope: str,
        tool_id: str,
        idempotency_key: str,
    ) -> ToolInvocation | None:
        return next(
            (
                invocation
                for invocation in self._state.invocations.values()
                if invocation.tool_id == tool_id
                and (
                    invocation.idempotency_scope == idempotency_scope
                    or (
                        invocation.idempotency_scope is None
                        and invocation.conversation_id
                        and idempotency_scope
                        == f"conversation:{invocation.conversation_id}"
                    )
                )
                and (
                    invocation.idempotency_key == idempotency_key
                    or invocation.input_payload.get("idempotency_key")
                    == idempotency_key
                )
            ),
            None,
        )


class SQLAlchemyToolInvocationRuntimeState:
    """PostgreSQL-backed command state for cross-process tool execution."""

    def __init__(
        self,
        *,
        repository: ToolInvocationRuntimeRepository,
        mirror_invocation: Callable[[ToolInvocation], None] | None = None,
    ) -> None:
        self._repository = repository
        self._mirror_invocation = mirror_invocation or (lambda invocation: None)

    def create_invocation(self, invocation: ToolInvocation) -> ToolInvocation:
        created = self._repository.create_tool_invocation(invocation)
        self._mirror_invocation(created)
        return created

    def get_invocation(self, invocation_id: str) -> ToolInvocation:
        invocation = self._repository.get_tool_invocation(invocation_id)
        if invocation is None:
            raise KeyError(invocation_id)
        return invocation

    def list_invocations(self) -> list[ToolInvocation]:
        return self._repository.load_tool_invocations()

    def find_idempotent_invocation(
        self,
        *,
        idempotency_scope: str,
        tool_id: str,
        idempotency_key: str,
    ) -> ToolInvocation | None:
        return self._repository.find_idempotent_tool_invocation(
            idempotency_scope=idempotency_scope,
            tool_id=tool_id,
            idempotency_key=idempotency_key,
        )

    def claim_for_execution(
        self,
        invocation_id: str,
        *,
        expected_statuses: tuple[str, ...],
        input_updates: dict[str, Any] | None = None,
    ) -> ToolInvocation | None:
        claimed = self._repository.claim_tool_invocation_for_execution(
            invocation_id,
            expected_statuses=expected_statuses,
            input_updates=input_updates,
        )
        if claimed is not None:
            self._mirror_invocation(claimed)
        return claimed

    def persist_invocation(self, invocation: ToolInvocation) -> None:
        self._repository.upsert_tool_invocation(invocation)
        self._mirror_invocation(invocation)


class StaticToolCatalogRuntimeAdapter:
    """Immutable lookup adapter for the versioned first-party tool catalog."""

    def __init__(self, tools: Sequence[ToolDefinition]) -> None:
        self._tools: Mapping[str, ToolDefinition] = {tool.tool_id: tool for tool in tools}

    def tool_definition(self, tool_id: str) -> ToolDefinition | None:
        return self._tools.get(tool_id)


__all__ = [
    "ProjectedToolInvocationRuntimeState",
    "SQLAlchemyToolInvocationRuntimeState",
    "StaticToolCatalogRuntimeAdapter",
    "ToolInvocationRuntimeAdapters",
    "ToolInvocationRuntimeProjectionState",
    "ToolInvocationRuntimeRepository",
]
