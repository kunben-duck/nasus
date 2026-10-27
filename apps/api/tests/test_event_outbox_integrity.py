"""Pure envelope specimens; these do not prove persisted business ancestry."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.tool_models import EventPayload
from apps.api.app.domain.quality_loop.run_plan import RunPlanIntegrityError
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxIntegrityError, EventOutboxRepository
from apps.api.app.infrastructure.persistence.run_plan_event_integrity import verify_run_plan_event_envelope


def event():
    return EventPayload(event_id="original-event", event_type="agent.goal.updated", occurred_at="2026-10-10T00:00:00+00:00",
        correlation_id="project", conversation_id="conversation", agent_goal_id="goal", swarm_run_id="swarm",
        entity_type="agent_goal", entity_id="goal", entity_version=7, mutation_kind="patch", patch={"status": "running"})


def row(value):
    fields = ("event_id", "event_type", "occurred_at", "conversation_id", "agent_goal_id", "swarm_run_id",
        "entity_type", "entity_id", "entity_version")
    return SSEEventOutboxRecord(sequence=value.entity_version, retention_until="2026-10-17T00:00:00+00:00",
        event_payload=value.model_dump(), **{key: getattr(value, key) for key in fields})


def test_original_envelope_round_trip_is_read_only():
    value = event()
    stored = row(value)
    before = deepcopy(stored.event_payload)
    assert EventOutboxRepository._read_event(None, stored) == value
    assert stored.event_payload == before


@pytest.mark.parametrize("field,value", [
    ("event_id", "other-event"), ("event_type", "quality.run_plan.prepared"), ("occurred_at", "other-time"),
    ("conversation_id", "other-conversation"), ("agent_goal_id", "other-goal"), ("swarm_run_id", "other-swarm"),
    ("entity_type", "run_plan"), ("entity_id", "other-entity"), ("entity_version", 8),
    ("entity_version", True), ("entity_version", "7"), ("unexpected_private_data", "must-not-stream"),
])
def test_payload_cannot_relabel_or_rebind_the_stored_envelope(field, value):
    stored = row(event())
    stored.event_payload[field] = value
    before = deepcopy(stored.event_payload)
    with pytest.raises(EventOutboxIntegrityError):
        EventOutboxRepository._read_event(None, stored)
    assert stored.event_payload == before


@pytest.mark.parametrize("value", [0, -1, True, 8])
def test_sequence_must_be_the_original_positive_integer(value):
    stored = row(event())
    stored.sequence = value
    with pytest.raises(EventOutboxIntegrityError):
        EventOutboxRepository._read_event(None, stored)


def fact_envelope():
    return event().model_copy(update={"event_type": "quality.run_plan.prepared", "entity_type": "run_plan",
        "entity_id": "plan", "swarm_run_id": None, "mutation_kind": "append", "snapshot_hint": True,
        "query_keys": [["run-plans", "project"]], "patch": {"status": "prepared"}})


def verify_envelope(value):
    command = SimpleNamespace(conversation_id="conversation", input_payload={"agent_goal_id": "goal"})
    session = SimpleNamespace(get=lambda model, ident: command if ident == "invocation" else None)
    stored = SimpleNamespace(invocation_id="invocation", project_id="project", recorded_at=event().occurred_at)
    verify_run_plan_event_envelope(session, value, stored, entity_type="run_plan", query_key="run-plans")


def test_metadata_fact_has_only_the_original_command_attribution():
    verify_envelope(fact_envelope())


@pytest.mark.parametrize("field,value", [
    ("entity_type", "run_plan_observations"), ("correlation_id", "other-project"), ("occurred_at", "new-time"),
    ("conversation_id", "other-conversation"), ("agent_goal_id", "other-goal"), ("mutation_kind", "replace"),
    ("snapshot_hint", False), ("query_keys", [["private-archive", "project"]]),
    ("payload", {"private_url": "must-not-stream"}), ("tool_invocation_id", "other-invocation"),
    ("agent_step_id", "step"), ("swarm_run_id", "swarm"), ("assignment_id", "assignment"),
    ("task_id", "task"), ("run_id", "run"),
])
def test_metadata_fact_cannot_add_private_payload_or_inherit_other_context(field, value):
    with pytest.raises(RunPlanIntegrityError):
        verify_envelope(fact_envelope().model_copy(update={field: value}))
