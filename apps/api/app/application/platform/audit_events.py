from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from .projection_ports import AuditEventPersistencePort
from .tool_models import AuditEvent


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PlatformAuditApplicationService:
    """Platform audit event write use cases."""

    def __init__(self, persistence: AuditEventPersistencePort) -> None:
        self._persistence = persistence

    def record_audit_event(self, event: AuditEvent) -> None:
        self._persistence.persist_audit_event(event)

    def record_agent_goal_audit_event(
        self,
        goal: Any,
        *,
        action: str,
        status: str | None = None,
        summary: str,
        actor: str = "agent",
        actor_kind: str = "agent",
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        object_refs: List[str] = []
        if goal.project_id:
            object_refs.append(f"project:{goal.project_id}")
        if goal.us_id:
            object_refs.append(f"us:{goal.us_id}")

        event_metadata: Dict[str, Any] = {
            "workflow_id": goal.workflow_id,
            "autonomy_level": goal.autonomy_level,
            "max_steps": goal.max_steps,
            "steps_completed": goal.steps_completed,
            "pause_reason": goal.pause_reason,
        }
        if metadata:
            event_metadata.update(metadata)

        self.record_audit_event(
            AuditEvent(
                id=f"audit_{uuid4().hex[:12]}",
                occurred_at=_now_iso(),
                actor=actor,
                actor_kind=actor_kind,  # type: ignore[arg-type]
                action=action,
                entity_type="agent_goal",
                entity_id=goal.id,
                status=status or goal.status,  # type: ignore[arg-type]
                summary=summary,
                conversation_id=goal.conversation_id,
                agent_goal_id=goal.id,
                object_refs=object_refs,
                metadata=event_metadata,
            )
        )
