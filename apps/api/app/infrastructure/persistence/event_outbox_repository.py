from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db_models import SSEEventOutboxRecord
from .unit_of_work import session_scope
from ...application.platform.event_ports import EventStreamKind
from ...application.platform.tool_models import EventPayload


class EventOutboxIntegrityError(ValueError):
    """Persisted events are not a second authority for business facts."""


class EventOutboxRepository:
    """Durable SSE event log used for replay and multi-instance polling."""

    def __init__(self) -> None:
        self._retention_days = max(1, int(os.getenv("NASUS_SSE_RETENTION_DAYS", "7")))

    def append(
        self,
        event: EventPayload,
        *,
        session: Session | None = None,
    ) -> EventPayload:
        if session is not None:
            return self._append_in_session(session, event)
        with session_scope() as owned_session:
            return self._append_in_session(owned_session, event)

    def _append_in_session(
        self,
        session: Session,
        event: EventPayload,
    ) -> EventPayload:
        retention_until = (
            datetime.now(timezone.utc) + timedelta(days=self._retention_days)
        ).isoformat()
        record = SSEEventOutboxRecord(
            event_id=event.event_id,
            event_type=event.event_type,
            occurred_at=event.occurred_at,
            conversation_id=event.conversation_id,
            agent_goal_id=event.agent_goal_id,
            swarm_run_id=event.swarm_run_id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            entity_version=0,
            event_payload={},
            retention_until=retention_until,
        )
        session.add(record)
        session.flush()
        event.entity_version = record.sequence
        record.entity_version = record.sequence
        record.event_payload = event.model_dump()
        self._verify_run_plan_fact(session, event)
        from .derivation_registry_projection import DerivationRegistryProjector
        DerivationRegistryProjector().project_event(session, event)
        from .object_provenance_projection_v1 import ObjectProvenanceProjectorV1
        ObjectProvenanceProjectorV1().project_event(session, event)
        from .context_provenance_projection_v1 import ContextProvenanceProjectorV1
        ContextProvenanceProjectorV1().project_event(session, event)
        from .relation_provenance_projection_v1 import RelationProvenanceProjectorV1
        RelationProvenanceProjectorV1().project_event(session, event)
        from .relation_fact_provenance_v1 import RelationFactProvenanceProjectorV1
        RelationFactProvenanceProjectorV1().project_event(session, event)
        from .authority_provenance_projection_v1 import AuthorityProvenanceProjectorV1
        AuthorityProvenanceProjectorV1().project_event(session, event)
        from .context_authority_projection_v1 import ContextAuthorityProjectorV1
        ContextAuthorityProjectorV1().project_event(session, event)
        from .publication_provenance_projection_v1 import PublicationProvenanceProjectorV1
        PublicationProvenanceProjectorV1().project_event(session, event)
        from .retrieval_provenance_projection_v1 import RetrievalProvenanceProjectorV1
        RetrievalProvenanceProjectorV1().project_event(session, event)
        from .automation_provenance_v1 import AutomationProvenanceProjectorV1
        AutomationProvenanceProjectorV1().project_event(session, event)
        return event

    def list_after(
        self,
        *,
        stream_kind: EventStreamKind,
        stream_id: str,
        after_event_id: str | None,
        limit: int = 500,
        initial_replay_limit: int = 500,
    ) -> list[EventPayload]:
        stream_column = self._stream_column(stream_kind)
        with session_scope() as session:
            if after_event_id:
                cursor = session.scalar(
                    select(SSEEventOutboxRecord.sequence).where(
                        SSEEventOutboxRecord.event_id == after_event_id,
                        stream_column == stream_id,
                    )
                )
                cursor_sequence = int(cursor or 0)
            else:
                latest = session.scalar(
                    select(func.max(SSEEventOutboxRecord.sequence)).where(
                        stream_column == stream_id
                    )
                )
                cursor_sequence = max(0, int(latest or 0) - initial_replay_limit)

            rows = session.scalars(
                select(SSEEventOutboxRecord)
                .where(
                    stream_column == stream_id,
                    SSEEventOutboxRecord.sequence > cursor_sequence,
                )
                .order_by(SSEEventOutboxRecord.sequence)
                .limit(limit)
            ).all()
            # Verify the complete page before yielding any event. Replay never
            # invokes write-side projectors to repair missing business facts.
            return [self._read_event(session, row) for row in rows]

    @classmethod
    def _read_event(cls, session: Session, row: SSEEventOutboxRecord) -> EventPayload:
        try:
            event = EventPayload.model_validate(row.event_payload, strict=True)
        except (TypeError, ValueError):
            raise EventOutboxIntegrityError("persisted event payload is invalid") from None
        fields = (
            "event_id", "event_type", "occurred_at", "conversation_id",
            "agent_goal_id", "swarm_run_id", "entity_type", "entity_id", "entity_version",
        )
        if (type(row.event_payload) is not dict
                or set(row.event_payload) - set(EventPayload.model_fields)
                or any(getattr(event, key) != getattr(row, key) for key in fields)
                or type(row.sequence) is not int or row.sequence <= 0
                or type(row.entity_version) is not int or row.entity_version != row.sequence):
            raise EventOutboxIntegrityError("persisted event envelope differs from its outbox row")
        cls._verify_run_plan_fact(session, event)
        return event

    @staticmethod
    def _verify_run_plan_fact(session: Session, event: EventPayload) -> None:
        from .run_plan_repository import RunPlanRepository
        from .run_plan_build_repository import RunPlanBuildRepository
        from .run_plan_observation_repository import RunPlanObservationRepository
        from .environment_observation_repository import EnvironmentObservationRepository
        from .environment_health_repository import EnvironmentHealthRepository
        from .http_locator_repository import HttpLocatorRepository
        from .http_fixture_recipe_repository import HttpFixtureRecipeRepository
        from .http_fixture_grant_repository import HttpFixtureGrantRepository
        from .http_fixture_command_repository import HttpFixtureCommandRepository
        from .http_fixture_job_repository import HttpFixtureJobRepository

        RunPlanRepository.verify_event(session, event)
        RunPlanBuildRepository.verify_event(session, event)
        RunPlanObservationRepository.verify_event(session, event)
        EnvironmentObservationRepository.verify_event(session, event)
        EnvironmentHealthRepository.verify_event(session, event)
        HttpLocatorRepository.verify_event(session, event)
        HttpFixtureRecipeRepository.verify_event(session, event)
        HttpFixtureGrantRepository.verify_event(session, event)
        HttpFixtureCommandRepository.verify_event(session, event)
        HttpFixtureJobRepository.verify_event(session, event)

    def latest_entity_version(self, *, entity_type: str, entity_id: str) -> int:
        with session_scope() as session:
            version = session.scalar(
                select(func.max(SSEEventOutboxRecord.entity_version)).where(
                    SSEEventOutboxRecord.entity_type == entity_type,
                    SSEEventOutboxRecord.entity_id == entity_id,
                )
            )
        return int(version or 0)

    @staticmethod
    def _stream_column(stream_kind: EventStreamKind):
        if stream_kind == "conversation":
            return SSEEventOutboxRecord.conversation_id
        if stream_kind == "goal":
            return SSEEventOutboxRecord.agent_goal_id
        if stream_kind == "swarm":
            return SSEEventOutboxRecord.swarm_run_id
        raise ValueError(f"Unsupported event stream kind: {stream_kind}")


__all__ = ["EventOutboxRepository", "EventOutboxIntegrityError", "EventStreamKind"]
