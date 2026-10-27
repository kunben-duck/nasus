"""Actual canonical PG/MinIO binding and replay; no native target execution claim."""
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from apps.api.app.main import app
from apps.api.app.domain.quality_loop.http_fixture_command import FIXTURE_COMMAND_TOOL, FALSE_AUTHORITIES
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxIntegrityError, EventOutboxRepository
from apps.api.app.infrastructure.persistence.http_fixture_command_models import HttpFixtureCommandRecord
from apps.api.app.infrastructure.persistence.http_fixture_preparation_models import HttpFixturePreparationBindingRecord
from apps.api.app.infrastructure.persistence.http_fixture_journal_models import HttpFixtureDispatchRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_http_fixture_execution_api import (
    base_evidence_api, evidence_api, documents, publication, design_scope, generation_result, mapping,
    native_scripts, spec, composed_fixture_execution,
)
from apps.api.tests.test_semantic_evaluations_api import invoke, confirm, count


BOUND_EVENT = "quality.http_fixture.command_bound"


def test_fixture_bound_fact_uses_outbox_sequence_and_rolls_back_invalid_event(composed_fixture_execution, monkeypatch):
    fixture = composed_fixture_execution
    value, jobs, delivered = fixture.v, app.state.container.http_fixture_jobs, []
    assert engine.dialect.name == "postgresql"
    with session_scope() as session:
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
    async def start(ident):
        delivered.append(ident)
        return True
    monkeypatch.setattr(jobs.workflow, "start", start)
    append = EventOutboxRepository.append

    def altered(outbox, event, **kwargs):
        if event.event_type == BOUND_EVENT:
            event = event.model_copy(update={"patch": {**event.patch, "passed_count": 1}})
        return append(outbox, event, **kwargs)

    def dispatch():
        pending = invoke(value, FIXTURE_COMMAND_TOOL, fixture.chosen.model_dump(mode="json"), key=uuid4().hex)
        assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation"
        result = confirm(value, pending.json())
        assert result.status_code == 200
        return result.json()

    monkeypatch.setattr(EventOutboxRepository, "append", altered)
    failed = dispatch()
    assert failed["status"] == "failed" and not delivered and not fixture.runner.commands
    with session_scope() as session:
        assert session.get(HttpFixtureCommandRecord, failed["id"]) is None
        assert session.get(HttpFixturePreparationBindingRecord, failed["id"]) is None
        assert session.scalar(select(AuditEventRecord).where(
            AuditEventRecord.entity_id == failed["id"], AuditEventRecord.action == BOUND_EVENT)) is None
        assert session.scalar(select(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.entity_id == failed["id"], SSEEventOutboxRecord.event_type == BOUND_EVENT)) is None
    monkeypatch.setattr(EventOutboxRepository, "append", append)
    bound = dispatch()
    assert bound["status"] == "running" and delivered == [bound["id"]]
    with session_scope() as session:
        intent = session.get(HttpFixtureCommandRecord, bound["id"])
        preparation = session.get(HttpFixturePreparationBindingRecord, bound["id"])
        assert intent is not None and preparation is not None and preparation.intent_digest == intent.content_hash
        assert all(intent.payload[key] is False for key in FALSE_AUTHORITIES)
        row = session.scalar(select(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.entity_id == bound["id"], SSEEventOutboxRecord.event_type == BOUND_EVENT))
        assert type(row.sequence) is int and row.entity_version == row.sequence > 0
        original = deepcopy(row.event_payload)
        event = EventOutboxRepository._read_event(session, row)
        assert event.entity_version == row.sequence
        assert event.patch == {"project_id": value["project_id"], "invocation_id": bound["id"]}
        for mutation, error in (("sequence", EventOutboxIntegrityError), ("coverage", HttpFixtureInvalid)):
            changed = deepcopy(original)
            if mutation == "sequence":
                changed["entity_version"] += 1
            else:
                changed["patch"]["passed_count"] = 1
            transaction = session.begin_nested()
            try:
                row.event_payload = changed
                session.flush()
                session.expire(row)
                with pytest.raises(error):
                    EventOutboxRepository._read_event(session, row)
            finally:
                transaction.rollback()
            session.expire(row)
            assert row.event_payload == original
            assert EventOutboxRepository._read_event(session, row).entity_version == row.sequence
    assert count(value, HttpFixtureDispatchRecord) == 0 and not fixture.runner.commands
