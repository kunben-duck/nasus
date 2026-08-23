from __future__ import annotations

from typing import Protocol

from .tool_models import AuditEvent, ToolInvocation


class ToolInvocationProjectionStatePort(Protocol):
    """Persistence boundary for the canonical ToolInvocation read projection."""

    def persist_and_project(self, invocation: ToolInvocation) -> None:
        ...


class AuditEventPersistencePort(Protocol):
    """Persistence boundary for append-only platform audit facts."""

    def persist_audit_event(self, event: AuditEvent) -> None:
        ...


__all__ = [
    "AuditEventPersistencePort",
    "ToolInvocationProjectionStatePort",
]
