"""Canonical writes, PG integrity, no read-time repairs and unchanged historical facts."""
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.tool_models import EventPayload
from apps.api.app.domain.system_image.publication import PUBLICATION_REVIEW_TOOL, ROLLBACK_TOOL, PublicationIntegrityError, PublicationChanged
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.image_publication_models import ImagePublicationRecord, ImagePublicationReviewRecord, ImagePublicationHeadRecord
from apps.api.app.infrastructure.persistence.publication_provenance_models import (
    PublicationProvenanceRecord as Anchor, PublicationProvenanceDependencyRecord as Edge,
    ContextPublicationDependencyRecord as ContextAnchor,
)
from apps.api.app.infrastructure.persistence.publication_provenance_projection_v1 import PublicationProvenanceProjectorV1
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_image_publications_api import publication, history, inspect, review, review_request, publish_request
from apps.api.tests.test_image_rollbacks_api import rollback, rollback_review
from apps.api.tests.test_published_image_reads import publish
from apps.api.tests.test_published_context_packs import request_for, preview_response, advance
from apps.api.tests.test_context_packs_api import archive, read
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_semantic_evaluations_api import invoke, confirm, completed


def values(row):
    return deepcopy({c.name: getattr(row, c.name) for c in row.__table__.columns})


def inventory(v):
    with session_scope() as session:
        return {model.__tablename__: [values(row) for row in session.scalars(select(model).where(
            model.project_id == v["project_id"]).order_by(*model.__table__.primary_key.columns))]
            for model in (Anchor, Edge, ContextAnchor, ImagePublicationRecord, ImagePublicationReviewRecord)}


def erase_edges(v, ident):
    with session_scope() as session:
        rows = [values(row) for row in session.scalars(select(Edge).where(Edge.project_id == v["project_id"], Edge.fact_id == ident))]
        session.execute(text("ALTER TABLE image_publication_dependencies DISABLE TRIGGER immutable_image_publication_dependencies"))
        session.execute(delete(Edge).where(Edge.project_id == v["project_id"], Edge.fact_id == ident))
        session.execute(text("ALTER TABLE image_publication_dependencies ENABLE TRIGGER immutable_image_publication_dependencies"))
    assert rows
    return rows


def restore_edges(rows):
    with session_scope() as session:
        session.execute(insert(Edge), rows)


def test_publication_ancestry_is_atomic_append_only_and_backfill_keeps_facts(publication):
    v = publication
    approval, _ = review(v, review_request(v, decision="reject"))
    accepted, _ = review(v)
    completed(invoke(v, "baseline.promote", publish_request(v, accepted)))
    head = history(v)["head"]
    before = inventory(v)
    assert len(before[Anchor.__tablename__]) == 3
    assert len(before[Edge.__tablename__]) == 2
    with session_scope() as session:
        parent = session.get(Anchor, (v["project_id"], "review", approval))
        child = session.get(Anchor, (v["project_id"], "review", accepted))
        edge = session.get(Edge, (v["project_id"], "review", accepted, "previous_review"))
        assert edge.parent_hash == parent.content_hash and edge.fact_hash == child.content_hash
        PublicationProvenanceProjectorV1().backfill(session)
    assert inventory(v) == before
    for model in (Anchor, Edge):
        for statement in (delete(model), update(model).values(**({"metadata_hash": "bad"} if model is Anchor else {"parent_hash": "bad"}))):
            with pytest.raises(IntegrityError, match="append-only"):
                with session_scope() as session:
                    session.execute(statement.where(model.project_id == v["project_id"]))
    assert history(v)["head"] == head


def test_read_and_new_decision_do_not_repair_missing_predecessor_edges(publication):
    v = publication
    review(v, review_request(v, decision="reject"))
    approval, _ = review(v)
    completed(invoke(v, "baseline.promote", publish_request(v, approval)))
    head = history(v)["head"]
    target = {**v["target"], "expected_head_id": head["publication_id"]}
    pending = invoke(v, PUBLICATION_REVIEW_TOOL, review_request(v, target=target), key=uuid4().hex).json()
    before = inventory(v)
    erased = erase_edges(v, head["publication_id"])
    try:
        response = v["client"].get(v["publication_url"], params={"baseline_id": head["baseline_id"]}, headers=v["headers"])
        assert response.status_code == 502, response.text
        assert confirm(v, pending).json()["status"] == "failed"
        broken = inventory(v)
        assert broken[Anchor.__tablename__] == before[Anchor.__tablename__]
        assert broken[ImagePublicationRecord.__tablename__] == before[ImagePublicationRecord.__tablename__]
        assert broken[ImagePublicationReviewRecord.__tablename__] == before[ImagePublicationReviewRecord.__tablename__]
        assert len(broken[Edge.__tablename__]) == len(before[Edge.__tablename__]) - len(erased)
    finally:
        restore_edges(erased)
    assert history(v)["head"] == head


def test_projection_failure_rolls_back_native_review_approval_audit_and_outbox(publication, monkeypatch):
    v = publication
    pending = invoke(v, PUBLICATION_REVIEW_TOOL, review_request(v), key=uuid4().hex).json()
    before = inventory(v)
    original = EventOutboxRepository.append
    def fail(self, event, **kwargs):
        if event.event_type == "system_image.publication.reviewed":
            # The native fact and its complete new registration already exist in this transaction.
            session = kwargs["session"]
            assert session.get(Anchor, (v["project_id"], "review", event.entity_id)) is not None
            raise PublicationIntegrityError("injected publication outbox failure")
        return original(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    assert confirm(v, pending).json()["status"] == "failed"
    assert inventory(v) == before
    with session_scope() as session:
        assert session.scalar(select(AuditEventRecord.id).where(AuditEventRecord.action == "system_image.publication.reviewed",
            AuditEventRecord.tool_invocation_id == pending["id"])) is None
        events = session.scalars(select(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.event_type == "system_image.publication.reviewed")).all()
        assert not any(event.event_payload.get("tool_invocation_id") == pending["id"] for event in events)


def test_rollback_graph_pins_original_source_review_and_superseded_head(rollback):
    v = rollback
    before = inventory(v)
    request = rollback_review(v)
    completed(invoke(v, ROLLBACK_TOOL, request))
    head = history(v)["head"]
    after = inventory(v)
    for table in (ImagePublicationRecord.__tablename__, ImagePublicationReviewRecord.__tablename__, Anchor.__tablename__):
        original = {tuple(row[k] for k in ("project_id", "publication_id" if table == ImagePublicationRecord.__tablename__ else
            "review_id" if table == ImagePublicationReviewRecord.__tablename__ else "fact_id")): row for row in before[table]}
        actual = {tuple(row[k] for k in ("project_id", "publication_id" if table == ImagePublicationRecord.__tablename__ else
            "review_id" if table == ImagePublicationReviewRecord.__tablename__ else "fact_id")): row for row in after[table]}
        assert all(actual[key] == value for key, value in original.items())
    edges = {row["relation"]: row for row in after[Edge.__tablename__] if row["fact_id"] == head["publication_id"]}
    assert set(edges) == {"approval", "previous_publication", "rollback_source"}
    assert edges["rollback_source"]["parent_id"] == v["old_publication"]["publication_id"]
    assert edges["previous_publication"]["parent_id"] == v["new_publication"]["publication_id"]
    review_edges = {row["relation"]: row for row in after[Edge.__tablename__] if row["fact_id"] == head["approval_id"]}
    assert set(review_edges) == {"expected_head", "rollback_source"}
    assert not head["quality_generation_authorized"] and not head["release_authorized"]


def test_context_dependency_stays_pinned_and_missing_registration_is_not_recreated(publication):
    v = publication
    head = publish(v)
    view = preview_response(v, request_for(v, head)).json()
    response, _ = archive(v, view)
    done = completed(response)
    initial, url = read(v, done)
    ident = initial["metadata"]["context_id"]
    before = inventory(v)
    assert len(before[ContextAnchor.__tablename__]) == 1
    pin = before[ContextAnchor.__tablename__][0]
    assert pin["publication_id"] == head["publication_id"] and pin["context_metadata_hash"]
    advance(v, head)
    assert inventory(v)[ContextAnchor.__tablename__] == before[ContextAnchor.__tablename__]
    assert v["client"].get(url, headers=v["headers"]).json()["current_use"]["stale"]
    with session_scope() as session:
        session.execute(text("ALTER TABLE context_publication_dependencies DISABLE TRIGGER immutable_context_publication_dependencies"))
        session.execute(delete(ContextAnchor).where(ContextAnchor.project_id == v["project_id"], ContextAnchor.context_id == ident))
        session.execute(text("ALTER TABLE context_publication_dependencies ENABLE TRIGGER immutable_context_publication_dependencies"))
    try:
        response = v["client"].get(url, headers=v["headers"])
        assert response.status_code == 502, response.text
        assert not inventory(v)[ContextAnchor.__tablename__]
    finally:
        with session_scope() as session:
            session.execute(insert(ContextAnchor), pin)
    after = v["client"].get(url, headers=v["headers"])
    assert after.status_code == 200 and after.json()["context"] == initial["context"]


def test_publication_http_reads_share_one_complete_image_audit_only_within_request(publication, monkeypatch):
    from apps.api.app.infrastructure.persistence.object_provenance_projection_v1 import ObjectProvenanceProjectorV1
    from apps.api.app.infrastructure.persistence.object_provenance_models import ObjectProvenanceEdgeRecord as ObjectEdge
    from apps.api.app.infrastructure.persistence.image_read_snapshot import current_image_read_snapshot
    v = publication
    head = publish(v)
    target = {**v["target"], "expected_head_id": head["publication_id"]}
    original, audits = ObjectProvenanceProjectorV1.image, []
    def counted(self, session, value, **kwargs):
        if value.project_id == v["project_id"]:
            assert current_image_read_snapshot()[0] is session
            assert session.scalar(text("SHOW transaction_read_only")) == "on"
            audits.append(value.image_revision_id)
        return original(self, session, value, **kwargs)
    monkeypatch.setattr(ObjectProvenanceProjectorV1, "image", counted)
    for expected, operation in enumerate((lambda: history(v), lambda: history(v),
            lambda: inspect(v, target), lambda: inspect(v, target)), 1):
        operation()
        assert len(audits) == expected
        assert current_image_read_snapshot() is None
    key = "image_objects:" + head["image_revision_id"]
    with session_scope() as session:
        edges = [values(row) for row in session.scalars(select(ObjectEdge).where(
            ObjectEdge.project_id == v["project_id"], ObjectEdge.node_key == key))]
        assert edges
        session.execute(text("ALTER TABLE image_object_provenance_edges DISABLE TRIGGER USER"))
        session.execute(delete(ObjectEdge).where(ObjectEdge.project_id == v["project_id"], ObjectEdge.node_key == key))
        session.execute(text("ALTER TABLE image_object_provenance_edges ENABLE TRIGGER USER"))
    try:
        response = v["client"].get(v["publication_url"], headers=v["headers"], params={"baseline_id": head["baseline_id"]})
        assert response.status_code == 502, response.text
        assert len(audits) == 5 and current_image_read_snapshot() is None
    finally:
        with session_scope() as session:
            session.execute(insert(ObjectEdge), edges)
    assert history(v)["head"] == head and len(audits) == 6


def test_current_publication_is_live_even_inside_one_immutable_read_snapshot(publication):
    v = publication
    original = publish(v)
    current = advance(v, original)
    service = v["publication_service"]
    def select_head(value):
        with session_scope() as session:
            row = session.get(ImagePublicationHeadRecord, (v["project_id"], original["baseline_id"]))
            row.publication_id, row.sequence = value["publication_id"], value["sequence"]
    select_head(original)
    try:
        with actor_scope(UserProfile.model_validate(v["owner"])):
            with service.images.verified_read_session():
                before = service.pin(v["project_id"], original["publication_id"], require_current=True)
                select_head(current)
                with pytest.raises(PublicationChanged, match="head changed"):
                    service.pin(v["project_id"], original["publication_id"], require_current=True)
                assert service.pin(v["project_id"], original["publication_id"], require_current=False) == before
    finally:
        select_head(current)
    assert history(v)["head"] == current


def test_event_replay_verifies_exact_native_fact_without_repairing_dependencies(publication):
    v = publication
    head = publish(v)
    before = inventory(v)
    with session_scope() as session:
        source = session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == head["publication_id"],
            SSEEventOutboxRecord.event_type == "system_image.publication.published"))
        event = EventPayload.model_validate(deepcopy(source.event_payload))
    for changes in ({"correlation_id": "another-project"}, {"tool_invocation_id": "another-command"},
            {"occurred_at": "another-time"}, {"patch": {**event.patch, "sequence": head["sequence"] + 1}},
            {"event_type": "system_image.publication.rolled_back"}):
        with pytest.raises(PublicationIntegrityError):
            with session_scope() as session:
                PublicationProvenanceProjectorV1().project_event(session, event.model_copy(update=changes))
    erased = erase_edges(v, head["publication_id"])
    replay = event.model_copy(update={"event_id": str(uuid4())})
    try:
        with pytest.raises(PublicationIntegrityError):
            EventOutboxRepository().append(replay)
        broken = inventory(v)
        assert broken[Anchor.__tablename__] == before[Anchor.__tablename__]
        assert broken[ImagePublicationRecord.__tablename__] == before[ImagePublicationRecord.__tablename__]
        assert len(broken[Edge.__tablename__]) == len(before[Edge.__tablename__]) - len(erased)
        with session_scope() as session:
            assert session.scalar(select(SSEEventOutboxRecord.event_id).where(SSEEventOutboxRecord.event_id == replay.event_id)) is None
    finally:
        restore_edges(erased)
    assert inventory(v) == before
