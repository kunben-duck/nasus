"""Actual disposable PG replay and corruption checks; no target execution."""
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from apps.api.app.application.platform.tool_models import EventPayload
from apps.api.app.domain.quality_loop.run_plan import RunPlanIntegrityError
from apps.api.app.domain.quality_loop.run_plan_observations import RunPlanObservationInvalid
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxIntegrityError, EventOutboxRepository
from apps.api.app.infrastructure.persistence.run_plan_models import RunPlanRecord
from apps.api.app.infrastructure.persistence.run_plan_build_models import RunPlanBuildRecord
from apps.api.app.infrastructure.persistence.run_plan_observation_models import RunPlanObservationRecord, RunPlanCaseObservationRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope


@pytest.fixture
def outbox():
    assert engine.dialect.name == "postgresql", "run via the isolated PostgreSQL harness"
    ident = uuid4().hex
    repository = EventOutboxRepository()
    def make(index, conversation=None):
        return EventPayload(event_id="replay-event-" + uuid4().hex, event_type="agent.goal.updated",
            occurred_at="2026-10-10T00:00:00+00:00", correlation_id=ident, conversation_id=conversation or ident,
            agent_goal_id="goal-" + ident, swarm_run_id="swarm-" + ident, entity_type="agent_goal", entity_id=ident,
            entity_version=0, mutation_kind="patch", patch={"steps_completed": index})
    first = repository.append(make(1))
    second = repository.append(make(2))
    return repository, ident, first, second, make


def replay(repository, ident, **kwargs):
    return repository.list_after(stream_kind="conversation", stream_id=ident, after_event_id=kwargs.pop("after_event_id", None), **kwargs)


def stored(ident):
    with session_scope() as session:
        value = session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_id == ident))
        return deepcopy(value.event_payload)


def test_order_cursor_all_streams_and_foreign_cursor_preserve_original_events(outbox):
    repository, ident, first, second, make = outbox
    foreign = repository.append(make(3, conversation="other-" + ident))
    for kind, key in (("conversation", ident), ("goal", "goal-" + ident), ("swarm", "swarm-" + ident)):
        values = repository.list_after(stream_kind=kind, stream_id=key, after_event_id=first.event_id)
        assert values[0] == second
    assert replay(repository, ident, after_event_id=foreign.event_id) == [first, second]
    assert replay(repository, ident, after_event_id="missing-cursor") == [first, second]
    assert replay(repository, ident, initial_replay_limit=1) == [second]
    assert replay(repository, ident, limit=1) == [first]
    assert stored(first.event_id) == first.model_dump() and stored(second.event_id) == second.model_dump()


@pytest.mark.parametrize("field,value", [
    ("event_id", "other-event"), ("event_type", "quality.run_plan.prepared"), ("occurred_at", "other-time"),
    ("conversation_id", "other-conversation"), ("agent_goal_id", "other-goal"), ("swarm_run_id", "other-swarm"),
    ("entity_type", "run_plan"), ("entity_id", "other-entity"), ("entity_version", True),
    ("entity_version", "7"), ("unexpected_private_data", "must-not-stream"),
])
def test_committed_envelope_corruption_discards_whole_page_and_is_not_repaired(outbox, monkeypatch, field, value):
    repository, ident, first, second, _ = outbox
    changed = second.model_dump()
    changed[field] = value
    with session_scope() as session:
        session.execute(update(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_id == second.event_id)
            .values(event_payload=changed))
    monkeypatch.setattr(EventOutboxRepository, "append", lambda *args, **kwargs: pytest.fail("replay must not write"))
    with pytest.raises(EventOutboxIntegrityError):
        replay(repository, ident)
    assert stored(second.event_id) == changed and stored(first.event_id) == first.model_dump()


@pytest.mark.parametrize("kind,entity,error", [
    ("quality.run_plan.prepared", "run_plan", RunPlanIntegrityError),
    ("quality.run_plan.build_bound", "run_plan_build", RunPlanIntegrityError),
    ("quality.run_plan.observations_recorded", "run_plan_observations", RunPlanObservationInvalid),
])
def test_self_consistent_event_without_original_fact_cannot_stream_or_create_fact(outbox, monkeypatch, kind, entity, error):
    repository, ident, _, second, _ = outbox
    changed = second.model_copy(update={"event_type": kind, "entity_type": entity, "entity_id": "missing-" + uuid4().hex,
        "mutation_kind": "append", "snapshot_hint": True, "payload": {}})
    with session_scope() as session:
        session.execute(update(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_id == second.event_id).values(
            event_type=kind, entity_type=entity, entity_id=changed.entity_id, event_payload=changed.model_dump()))
        before = [session.scalar(select(func.count()).select_from(model)) for model in (
            RunPlanRecord, RunPlanBuildRecord, RunPlanObservationRecord, RunPlanCaseObservationRecord)]
    monkeypatch.setattr(EventOutboxRepository, "append", lambda *args, **kwargs: pytest.fail("replay must not write"))
    with pytest.raises(error):
        replay(repository, ident)
    assert stored(second.event_id) == changed.model_dump()
    with session_scope() as session:
        assert [session.scalar(select(func.count()).select_from(model)) for model in (
            RunPlanRecord, RunPlanBuildRecord, RunPlanObservationRecord, RunPlanCaseObservationRecord)] == before
