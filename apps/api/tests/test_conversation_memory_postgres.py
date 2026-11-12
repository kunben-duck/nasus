"""Run through scripts/test-api-postgres.py; never touch developer records."""
import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete

from apps.api.tests.test_semantic_conversation_memory import Model, add_turn
from apps.api.app.application.agent.agent_models import ConversationSession, ConversationSummaryCheckpoint
from apps.api.app.application.agent.semantic_memory import SemanticConversationMemory
from apps.api.app.infrastructure.persistence.conversation_memory_repository import ConversationMemoryRepository
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import ConversationMemoryJobRecord, ConversationRecord, ConversationMessageRecord, ConversationSummaryCheckpointRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository


@pytest.fixture
def durable():
    if engine.dialect.name != "postgresql":
        pytest.skip("isolated PostgreSQL required")
    ident = "memory-test-" + uuid4().hex
    conversation = ConversationSession(id=ident, session_id=ident, title="Memory", space_type="build", space_id=ident)
    repository, jobs, model = ConversationRepository(), ConversationMemoryRepository(), Model()
    repository.upsert_conversation(conversation)
    for _ in range(8):
        add_turn(conversation, "约束：不自动发布候选")
    for message in conversation.messages:
        repository.append_message(ident, message)
    async def publish(*args):
        pass
    service = SemanticConversationMemory(jobs=jobs, model=model, conversation=repository.get_conversation,
        checkpoints=repository.load_summary_checkpoints, guard=lambda _: "scope-one", publish=publish)
    yield service, conversation, repository, jobs, model
    with session_scope() as session:
        for cls in (ConversationMemoryJobRecord, ConversationSummaryCheckpointRecord, ConversationMessageRecord):
            session.execute(delete(cls).where(cls.conversation_id == ident))
        session.execute(delete(ConversationRecord).where(ConversationRecord.id == ident))


def test_job_and_semantic_checkpoint_survive_new_repository_instances(durable):
    service, conversation, repository, jobs, model = durable
    job = service.schedule(conversation)
    assert job["id"] in ConversationMemoryRepository().pending()
    service.jobs = ConversationMemoryRepository()
    result = asyncio.run(service.run(job["id"]))
    assert result["status"] == "completed", result["reason"]
    checkpoint = service.valid_checkpoint(repository.get_conversation(conversation.id))
    assert checkpoint.memory_payload["format_version"] == 2
    assert checkpoint.memory_payload["digest"]["constraints"][0]["refs"] == ["message:m0"]
    # A stale foreground writer must not erase the background checkpoint pointer.
    repository.upsert_conversation(conversation)
    assert repository.get_conversation(conversation.id).latest_summary_checkpoint_id == checkpoint.id
    asyncio.run(service.run(job["id"]))
    assert model.calls == 1
    events = EventOutboxRepository().list_after(stream_kind="conversation", stream_id=conversation.id, after_event_id=None)
    assert [e.event_type for e in events] == ["conversation.summary.updated"]
    assert events[0].patch["latest_summary_checkpoint_id"] == checkpoint.id
    assert ["agent-memory"] in events[0].query_keys


def test_outbox_failure_rolls_back_checkpoint_and_retries_without_losing_originals(durable, monkeypatch):
    service, conversation, repository, jobs, _ = durable
    job = service.schedule(conversation)
    original = EventOutboxRepository.append
    def fail(*args, **kwargs):
        raise RuntimeError("temporary storage failure")
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    first = asyncio.run(service.run(job["id"]))
    assert first["status"] == "pending"
    assert service.valid_checkpoint(repository.get_conversation(conversation.id)) is None
    monkeypatch.setattr(EventOutboxRepository, "append", original)
    second = asyncio.run(service.run(job["id"]))
    assert second["status"] == "completed"
    assert second["reason"] == ""
    assert len(repository.get_conversation(conversation.id).messages) == 16


def test_stale_parent_cannot_replace_newer_checkpoint(durable):
    service, conversation, repository, jobs, model = durable
    first = service.schedule(conversation)
    second = dict(first, id=first["id"] + "-competing")
    jobs.enqueue(second)
    asyncio.run(service.run(first["id"]))
    claimed = jobs.claim(second["id"])
    stale = ConversationSummaryCheckpoint(id="stale", conversation_id=conversation.id, summary_text="stale",
        created_at=datetime.now(timezone.utc).isoformat(), memory_payload={"format_version": 2})
    assert jobs.commit(claimed, stale) is False
    assert jobs.get(second["id"])["status"] == "superseded"
    assert repository.get_conversation(conversation.id).latest_summary_checkpoint_id != "stale"


def test_expired_lease_fences_previous_attempt(durable):
    service, conversation, _, jobs, _ = durable
    job = service.schedule(conversation)
    first_attempt = jobs.claim(job["id"])
    assert jobs.claim(job["id"]) is None
    with session_scope() as session:
        session.get(ConversationMemoryJobRecord, job["id"]).lease_until = "2000-01-01"
    assert job["id"] in ConversationMemoryRepository().pending()
    second_attempt = ConversationMemoryRepository().claim(job["id"])
    assert second_attempt["attempts"] == 2
    checkpoint = ConversationSummaryCheckpoint(id="expired", conversation_id=conversation.id,
        summary_text="expired", created_at=datetime.now(timezone.utc).isoformat())
    assert jobs.commit(first_attempt, checkpoint) is False
    jobs.fail(job["id"], "summary_model_unavailable", first_attempt["attempts"])
    assert jobs.get(job["id"])["status"] == "running"
    jobs.fail(job["id"], "summary_model_unavailable", second_attempt["attempts"])
    assert jobs.get(job["id"])["status"] == "failed"


def test_legacy_rows_round_trip_with_empty_semantic_payload(durable):
    _, conversation, repository, _, _ = durable
    checkpoint = ConversationSummaryCheckpoint(id="legacy-" + conversation.id, conversation_id=conversation.id,
        summary_text="Legacy truncated content", created_at="2020-01-01")
    repository.upsert_summary_checkpoint(checkpoint)
    restored = next(c for c in ConversationRepository().load_summary_checkpoints() if c.id == checkpoint.id)
    assert restored.memory_payload == {}
