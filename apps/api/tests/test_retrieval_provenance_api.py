"""Real PostgreSQL facts and canonical writes; HTTP embeddings are explicit fixtures."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.infrastructure.persistence.frozen_index_models import (
    FrozenIndexReservationRecord as Reservation, FrozenIndexGenerationRecord as Generation,
    FrozenIndexDocumentRecord as Document, FrozenRetrievalRecord as Trace,
)
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.main import app
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.tool_handlers.query_input import query_payload
from apps.api.app.application.system_image.context_pack_inputs import ContextCompileInput
from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.persistence.context_pack_models import ContextPackRecord as Context
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord as Command, SSEEventOutboxRecord as Outbox
from apps.api.app.infrastructure.persistence.image_revision_models import ImageObjectMemberRecord as Member
from apps.api.app.infrastructure.persistence.document_projection_models import SourceDocumentRevisionRecord as SourceDocument
from apps.api.app.infrastructure.persistence.retrieval_provenance_models import (
    RetrievalProvenanceRecord as Anchor, IndexDocumentDependencyRecord as DocumentEdge,
    ContextRetrievalDependencyRecord as ContextEdge,
)
from apps.api.app.infrastructure.persistence.retrieval_provenance_projection_v1 import RetrievalProvenanceProjectorV1
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_frozen_indexes_api import indexed, build
from apps.api.tests.test_indexed_context_packs_api import recalled, response
from apps.api.tests.test_image_publications_api import publication
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_context_packs_api import archive, read
from apps.api.tests.test_semantic_evaluations_api import completed, invoke, confirm, count
from apps.api.app.application.system_image.index_inputs import INDEX_BUILD_TOOL


def values(row):
    return deepcopy({c.name: getattr(row, c.name) for c in row.__table__.columns})


def inventory(v):
    with session_scope() as session:
        return {model.__tablename__: [values(row) for row in session.scalars(select(model).where(
            model.project_id == v["project_id"]).order_by(*model.__table__.primary_key.columns))]
            for model in (Anchor, DocumentEdge, ContextEdge, Reservation, Generation, Trace)}


def erase(v, model, predicate):
    with session_scope() as session:
        saved = [values(row) for row in session.scalars(select(model).where(model.project_id == v["project_id"], predicate))]
        session.execute(text(f"ALTER TABLE {model.__tablename__} DISABLE TRIGGER USER"))
        session.execute(delete(model).where(model.project_id == v["project_id"], predicate))
        session.execute(text(f"ALTER TABLE {model.__tablename__} ENABLE TRIGGER USER"))
    assert saved
    return saved


def restore(model, rows):
    with session_scope() as session:
        session.execute(insert(model), rows)


def test_all_index_documents_and_context_trace_bindings_have_immutable_dependency_pins(recalled):
    v = recalled
    done = completed(archive(v, response(v).json())[0])
    initial, url = read(v, done)
    before = inventory(v)
    assert len(before[Anchor.__tablename__]) == 3
    assert len(before[DocumentEdge.__tablename__]) == count(v, Document)
    assert len(before[ContextEdge.__tablename__]) == len(v["context_request"]["retrieval_bindings"])
    roots = {row["kind"]: row for row in before[Anchor.__tablename__]}
    assert roots["generation"]["parent_hash"] == roots["reservation"]["content_hash"]
    assert roots["retrieval"]["parent_hash"] == roots["generation"]["content_hash"]
    assert all(edge["generation_hash"] == roots["generation"]["content_hash"]
        and edge["member_key"].startswith("member:" + v["index_head"]["image_revision_id"] + "/")
        for edge in before[DocumentEdge.__tablename__])
    assert all(edge["retrieval_hash"] == roots["retrieval"]["content_hash"] for edge in before[ContextEdge.__tablename__])
    calls = len(v["index_calls"])
    with session_scope() as session:
        RetrievalProvenanceProjectorV1().backfill(session)
    assert inventory(v) == before and len(v["index_calls"]) == calls
    assert v["client"].get(url, headers=v["headers"]).json() == initial
    for model in (Anchor, DocumentEdge, ContextEdge):
        for statement in (delete(model), update(model).values(project_id="foreign")):
            with pytest.raises(IntegrityError, match="append-only"):
                with session_scope() as session:
                    session.execute(statement.where(model.project_id == v["project_id"]))


def test_missing_index_member_dependency_is_never_repaired_by_reads_or_new_retrieval(recalled):
    v = recalled
    before = inventory(v)
    edge = before[DocumentEdge.__tablename__][0]
    removed = erase(v, DocumentEdge, DocumentEdge.document_id == edge["document_id"])
    try:
        url = v["image_url"] + "/indexes/" + edge["generation_id"]
        result = v["client"].get(url, headers=v["headers"])
        assert result.status_code == 502 and "documents" not in result.json()
        assert response(v).status_code == 502
        assert inventory(v)[Anchor.__tablename__] == before[Anchor.__tablename__]
        assert count(v, DocumentEdge) == len(before[DocumentEdge.__tablename__]) - 1
    finally:
        restore(DocumentEdge, removed)
    assert inventory(v) == before


def test_missing_context_trace_link_fails_closed_without_changing_old_archive(recalled):
    v = recalled
    archived, payload = archive(v, response(v).json())
    done = completed(archived)
    initial, url = read(v, done)
    before = inventory(v)
    removed = erase(v, ContextEdge, ContextEdge.context_id == initial["metadata"]["context_id"])
    try:
        result = v["client"].get(url, headers=v["headers"])
        assert result.status_code == 502 and "context" not in result.json()
        assert count(v, ContextEdge) == 0
        assert inventory(v)[Anchor.__tablename__] == before[Anchor.__tablename__]
        with session_scope() as session:
            session.get(Command, done["id"]).status = "running"
        with actor_scope(UserProfile.model_validate(v["owner"])), pytest.raises(ImageRevisionIntegrityError):
            app.state.container.context_packs.compile(ContextCompileInput.model_validate(payload),
                invocation_id=done["id"], recorded_at="retry")
        assert count(v, ContextEdge) == 0 and inventory(v)[Anchor.__tablename__] == before[Anchor.__tablename__]
    finally:
        with session_scope() as session:
            session.get(Command, done["id"]).status = done["status"]
        restore(ContextEdge, removed)
    assert v["client"].get(url, headers=v["headers"]).json() == initial


@pytest.mark.parametrize("target_kind", ["code_entity", "test_case"])
def test_context_registration_cannot_bind_non_ac_members_even_with_valid_trace(recalled, target_kind):
    v = recalled
    done = completed(archive(v, response(v).json())[0])
    initial, _ = read(v, done)
    before = inventory(v)
    removed = erase(v, ContextEdge, ContextEdge.context_id == initial["metadata"]["context_id"])
    try:
        with session_scope() as session:
            transaction = session.begin_nested()
            try:
                query = select(Member.object_id).where(Member.project_id == v["project_id"],
                    Member.image_revision_id == v["index_head"]["image_revision_id"])
                if target_kind == "code_entity":
                    query = query.where(Member.kind == target_kind)
                else:
                    query = query.join(SourceDocument, Member.document_revision_id == SourceDocument.document_revision_id)
                    query = query.where(SourceDocument.kind == target_kind)
                target = session.scalar(query.limit(1))
                assert target is not None
                command = session.get(Command, done["id"])
                command.input_payload = {**command.input_payload, "retrieval_bindings": {target: v["trace_id"]}}
                request = ContextCompileInput.model_validate({key: value for key, value in query_payload(command.input_payload).items()
                    if key not in {"confirmed_by_user", "confirmed_at"}})
                row = session.get(Context, initial["metadata"]["context_id"])
                proposed = SimpleNamespace(**{**values(row), "request_hash": snapshot_digest(request.model_dump(mode="json"))})
                with pytest.raises(ImageRevisionIntegrityError):
                    RetrievalProvenanceProjectorV1().context(session, proposed, write=True)
            finally:
                transaction.rollback()
        assert count(v, ContextEdge) == 0
    finally:
        restore(ContextEdge, removed)
    assert inventory(v) == before


@pytest.mark.parametrize("field", ["entity_version", "patch", "mutation_kind"])
def test_context_and_trace_dependency_commit_is_atomic_when_event_metadata_is_wrong(recalled, monkeypatch, field):
    v = recalled
    before = inventory(v)
    original = RetrievalProvenanceProjectorV1.project_event
    def corrupt(self, session, event):
        if event.event_type == "system_image.context.compiled":
            sequence = session.scalar(select(Outbox.sequence).where(Outbox.event_id == event.event_id))
            assert event.entity_version == sequence and sequence > 1
            assert session.scalar(select(ContextEdge).where(ContextEdge.context_id == event.entity_id)) is not None
            if field == "entity_version":
                event.entity_version = sequence + 1
            elif field == "patch":
                event.patch = {**event.patch, "readiness": "forged"}
            else:
                event.mutation_kind = "replace"
        return original(self, session, event)
    monkeypatch.setattr(RetrievalProvenanceProjectorV1, "project_event", corrupt)
    response_, _ = archive(v, response(v).json())
    assert response_.json()["status"] == "failed"
    assert count(v, Context) == count(v, ContextEdge) == 0
    assert inventory(v) == before


@pytest.mark.parametrize("stage", ["reserved", "completed"])
def test_registration_and_native_index_write_roll_back_with_outbox_failure(indexed, monkeypatch, stage):
    v = indexed
    original = EventOutboxRepository.append
    def fail(self, event, **kwargs):
        if event.event_type == "system_image.index." + stage:
            kind = "reservation" if stage == "reserved" else "generation"
            assert kwargs["session"].get(Anchor, (v["project_id"], kind, event.entity_id)) is not None
            raise RuntimeError("injected index event failure")
        return original(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    pending = invoke(v, INDEX_BUILD_TOOL, v["index_request"]).json()
    assert confirm(v, pending).json()["status"] == "failed"
    assert count(v, Generation) == count(v, Document) == count(v, DocumentEdge) == 0
    assert count(v, Reservation) == count(v, Anchor) == (0 if stage == "reserved" else 1)
    assert len(v["index_calls"]) == (0 if stage == "reserved" else v["index_preview"]["max_model_calls"])


def test_dependency_fk_rejects_wrong_hash_even_with_valid_member_id(recalled):
    v = recalled
    before = inventory(v)
    with pytest.raises(IntegrityError, match="foreign key"):
        with session_scope() as session:
            session.execute(text("ALTER TABLE image_index_document_dependencies DISABLE TRIGGER USER"))
            session.execute(update(DocumentEdge).where(DocumentEdge.project_id == v["project_id"])
                .values(member_hash="sha256:" + "0" * 64))
    assert inventory(v) == before
