from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ContextManager, Protocol

from ...application.platform.projection_ports import AuditEventPersistencePort
from ...application.platform.tool_models import AuditEvent


@dataclass(frozen=True)
class AuditEventProjectionFacts:
    audit_events: dict[str, AuditEvent]


@dataclass(frozen=True)
class AuditEventPersistenceAdapters:
    mutation_guard: Callable[[], ContextManager[Any]]
    persist_audit_event: Callable[[AuditEvent], None]


class AuditEventRepository(Protocol):
    def append_audit_event(self, event: AuditEvent) -> None:
        ...


class ProjectedAuditEventPersistence(AuditEventPersistencePort):
    """Compatibility-only audit persistence with an in-process mirror."""

    def __init__(
        self,
        facts: AuditEventProjectionFacts,
        adapters: AuditEventPersistenceAdapters,
    ) -> None:
        self._facts = facts
        self._adapters = adapters

    def persist_audit_event(self, event: AuditEvent) -> None:
        with self._adapters.mutation_guard():
            self._facts.audit_events[event.id] = event
        self._adapters.persist_audit_event(event)


class SQLAlchemyAuditEventPersistence(AuditEventPersistencePort):
    """Persist append-only audit facts directly in the shared database."""

    def __init__(self, repository: AuditEventRepository) -> None:
        self._repository = repository

    def persist_audit_event(self, event: AuditEvent) -> None:
        self._repository.append_audit_event(event)


__all__ = [
    "AuditEventPersistenceAdapters",
    "AuditEventProjectionFacts",
    "AuditEventRepository",
    "ProjectedAuditEventPersistence",
    "SQLAlchemyAuditEventPersistence",
]
