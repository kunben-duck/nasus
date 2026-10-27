"""Canonical PG/MinIO RunPlan replay; model and target policy are specimens."""
from copy import deepcopy

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from apps.api.app.domain.quality_loop.run_plan import RunPlanIntegrityError
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.run_plan_models import RunPlanRecord as Plan
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_run_plans_api import (
    native_scripts, reviewed_plan_inputs, preview, submit, read, completed, count,
    base_evidence_api, evidence_api, documents, publication, design_scope, generation_result, mapping,
)


def test_original_pg_run_plan_fact_replays_without_repair_or_private_envelope(native_scripts, monkeypatch):
    v = native_scripts
    _, _, _, selection = reviewed_plan_inputs(v)
    response = preview(v, selection)
    assert response.status_code == 200, response.text
    command = completed(submit(v, response.json()["request"]))
    ident = command["result"]["object_refs"][0].split(":", 1)[1]
    original_plan = read(v, ident).json()
    with session_scope() as session:
        row = session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == ident,
            SSEEventOutboxRecord.event_type == "quality.run_plan.prepared"))
        original = deepcopy(row.event_payload)
    repository = EventOutboxRepository()
    def replay():
        return repository.list_after(stream_kind="conversation", stream_id=command["conversation_id"], after_event_id=None)
    before = count(v, Plan)
    original_calls = len(v["script_calls"])
    assert next(item.model_dump() for item in replay() if item.event_id == original["event_id"]) == original
    monkeypatch.setattr(EventOutboxRepository, "append", lambda *args, **kwargs: pytest.fail("replay must not append facts"))

    # The envelope and SQL selectors are changed together, so matching them is
    # insufficient: the original command/fact must reject the forged content.
    changes = [
        ("patch", {**original["patch"], "status": "executed"}),
        ("correlation_id", "other-project"), ("entity_type", "other-entity-type"),
        ("agent_goal_id", "other-goal"), ("occurred_at", "other-time"),
        ("payload", {"private_url": "s3://must-not-stream"}),
        ("query_keys", [["private-archive", v["project_id"]]]), ("mutation_kind", "replace"),
    ]
    for field, value in changes:
        changed = {**original, field: value}
        columns = {"event_payload": changed}
        if field in {"entity_type", "agent_goal_id", "occurred_at"}:
            columns[field] = value
        with session_scope() as session:
            session.execute(update(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_id == original["event_id"]).values(**columns))
        with pytest.raises(RunPlanIntegrityError):
            replay()
        with session_scope() as session:
            stored = session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_id == original["event_id"]))
            assert stored.event_payload == changed
            session.execute(update(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_id == original["event_id"]).values(
                event_payload=original, entity_type=original["entity_type"], agent_goal_id=original["agent_goal_id"],
                occurred_at=original["occurred_at"]))

    get = Session.get
    def missing(self, model, key, *args, **kwargs):
        return None if model is Plan and key == ident else get(self, model, key, *args, **kwargs)
    with monkeypatch.context() as scoped:
        scoped.setattr(Session, "get", missing)
        with pytest.raises(RunPlanIntegrityError):
            replay()
    assert count(v, Plan) == before and len(v["script_calls"]) == original_calls
    assert read(v, ident).json() == original_plan
    assert next(item.model_dump() for item in replay() if item.event_id == original["event_id"]) == original
