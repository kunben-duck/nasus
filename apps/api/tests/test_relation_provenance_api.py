"""Native PG, canonical commands and archived source bytes; no external model calls."""
import importlib

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import delete, func, insert, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.context_pack_models import ContextPackRecord as Context
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.image_revision_models import ImageRevisionRecord as Image
from apps.api.app.infrastructure.persistence.relation_provenance_models import (
    RelationProvenanceNodeRecord as Node, RelationProvenanceEdgeRecord as Edge,
    ImageRelationProvenanceRecord as Root, ContextRelationProvenanceRecord as Anchor,
)
from apps.api.app.infrastructure.persistence.relation_provenance_projection_v1 import RelationProvenanceProjectorV1
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_semantic_review_api import semantic, documents, evidence_api, submit, completed
from apps.api.tests.test_semantic_membership_api import setup, freeze, child
from apps.api.tests.test_image_membership_api import setup_freeze, freeze as freeze_references, child as reference_child
from apps.api.tests.test_link_decisions_api import submit as review_reference
from apps.api.tests.test_context_packs_api import archive, read


def inventory(session, project):
    return tuple(tuple(tuple(row) for row in session.execute(select(*(getattr(model, c.name)
        for c in model.__table__.columns)).where(model.project_id == project)
        .order_by(*model.__table__.primary_key.columns))) for model in (Node, Edge, Root, Anchor))


def archive_image(v, image):
    url = f"{v['image_url']}/context-packs/preview"
    response = v["client"].get(url, headers=v["headers"], params={
        "image_revision_id": image["image_revision_id"], "image_artifact_hash": image["artifact_hash"]})
    assert response.status_code == 200, response.text
    done = completed(archive(v, response.json())[0])
    return read(v, done)


def verify_semantic_history(v):
    initial_calls = len(v["calls"])
    url, review, payload, original = setup(v)
    child_url, first = child(v, freeze(v, payload))
    context, context_url = archive_image(v, first["revision"])
    with session_scope() as session:
        image = session.get(Image, first["revision"]["image_revision_id"])
        projector = RelationProvenanceProjectorV1()
        nodes = projector.expected(session, image)
        assert projector.image(session, image, write=False) == 0
        assert {"semantic_evaluation", "semantic_assertion", "semantic_decision", "relation_member", "object_pin", "image_relations"}.issubset({n.kind for n in nodes.values()})
        assertion = nodes["semantic_assertion:" + original["assertion"]["assertion_id"]]
        assert sum(p.startswith("object_pin:member:") for p in assertion.parents) == 2
        assert sum(p.startswith("object_pin:evidence:") for p in assertion.parents) >= 2
        assert all(p in nodes for n in nodes.values() for p in n.parents)
        anchor = session.get(Anchor, (v["project_id"], context["metadata"]["context_id"]))
        assert anchor.image_relations_hash == nodes["image_relations:" + image.image_revision_id].content_hash
        assert projector.context(session, session.get(Context, anchor.context_id), write=False) == 0
        original_inventory = inventory(session, v["project_id"])
        assert projector.backfill(session) == 0
        assert inventory(session, v["project_id"]) == original_inventory
        graph_digest = snapshot_digest(sorted(n.content_hash for n in nodes.values()))
    completed(submit(v, {**review, "decision": "defer", "expected_previous_decision_id": payload["decision_ids"][0]}))
    current = v["client"].get(url, headers=v["headers"]).json()
    _, second = child(v, freeze(v, {**payload, "parent_revision_id": first["revision"]["image_revision_id"],
        "parent_artifact_hash": first["revision"]["artifact_hash"], "decision_ids": [current["head_decision_id"]]}))
    with session_scope() as session:
        old_nodes = RelationProvenanceProjectorV1().expected(session, session.get(Image, first["revision"]["image_revision_id"]))
        assert snapshot_digest(sorted(n.content_hash for n in old_nodes.values())) == graph_digest
        nodes = RelationProvenanceProjectorV1().expected(session, session.get(Image, second["revision"]["image_revision_id"]))
        assert sum(n.kind == "semantic_decision" for n in nodes.values()) == 2
        new_decision = nodes["semantic_decision:" + current["head_decision_id"]]
        assert "semantic_decision:" + original["head_decision_id"] in new_decision.parents
    assert v["client"].get(child_url, headers=v["headers"], params={"section": "semantic_assertion_members"}).json() == first
    assert v["client"].get(context_url, headers=v["headers"]).json()["context"] == context["context"]
    assert not context["current_use"]["generation_authorized"] and len(v["calls"]) == initial_calls + 1
    return {"first_image_id": first["revision"]["image_revision_id"], "next_image_id": second["revision"]["image_revision_id"],
        "original_graph_digest": graph_digest, "context_id": context["metadata"]["context_id"],
        "latest_decision_id": current["head_decision_id"],
        "fixed_rejection_retained": True, "later_defer_is_new_revision": True,
        "context_has_relation_anchor": True, "backfill_idempotent": True, "node_kinds": sorted({n.kind for n in nodes.values()})}


def test_semantic_dependencies_and_context_pin_do_not_follow_new_review_heads(semantic):
    verify_semantic_history(semantic)


def test_references_and_semantics_share_native_sources_without_conflating_relationships(semantic):
    v = semantic
    payload, review, endpoint = setup_freeze(v)
    _, first = reference_child(v, freeze_references(v, payload))
    completed(review_reference(v, {**review, "decision": "defer", "expected_previous_decision_id": payload["decision_ids"][0]}))
    head = v["client"].get(endpoint, headers=v["headers"]).json()["head_decision_id"]
    _, next_reference = reference_child(v, freeze_references(v, {**payload,
        "parent_revision_id": first["revision"]["image_revision_id"], "parent_artifact_hash": first["revision"]["artifact_hash"],
        "decision_ids": [head]}))
    _, _, semantic_payload, _ = setup(v)
    _, mixed = child(v, freeze(v, {**semantic_payload,
        "parent_revision_id": next_reference["revision"]["image_revision_id"], "parent_artifact_hash": next_reference["revision"]["artifact_hash"]}))
    with session_scope() as session:
        nodes = RelationProvenanceProjectorV1().expected(session, session.get(Image, mixed["revision"]["image_revision_id"]))
        kinds = [n.kind for n in nodes.values()]
        assert kinds.count("reference_decision") == 2 and kinds.count("semantic_decision") == 1
        assert kinds.count("relation_member") == 2
        assert set(kinds).issuperset({"reference_proposal", "reference_assertion", "semantic_evaluation", "semantic_assertion"})
        root = nodes["image_relations:" + mixed["revision"]["image_revision_id"]]
        assert len(root.parents) == 3
        assert RelationProvenanceProjectorV1().backfill(session) == 0


@pytest.fixture
def frozen(semantic):
    v = semantic
    _, _, payload, _ = setup(v)
    url, view = child(v, freeze(v, payload))
    return v, url, view


@pytest.mark.parametrize("mutation", ["node", "edge"])
def test_corrupt_relation_graph_is_hidden_and_restored_without_touching_old_facts(frozen, mutation):
    v, url, view = frozen
    with session_scope() as session:
        root = session.get(Root, (v["project_id"], view["revision"]["image_revision_id"]))
        model = Node if mutation == "node" else Edge
        row = session.scalars(select(model).where(model.project_id == v["project_id"], model.node_key == root.node_key)).first()
        values = {c.name: getattr(row, c.name) for c in model.__table__.columns}
        predicate = [getattr(model, c.name) == values[c.name] for c in model.__table__.primary_key]
        session.execute(text(f"ALTER TABLE {model.__tablename__} DISABLE TRIGGER USER"))
        if mutation == "node":
            session.execute(update(model).where(*predicate).values(metadata_hash="sha256:" + "0" * 64))
        else:
            session.execute(delete(model).where(*predicate))
        session.execute(text(f"ALTER TABLE {model.__tablename__} ENABLE TRIGGER USER"))
    try:
        response = v["client"].get(url, headers=v["headers"], params={"section": "semantic_assertion_members"})
        assert response.status_code == 502 and "items" not in response.json(), response.text
        assert v["client"].get(url).status_code == 401
        assert v["client"].get(url, headers=v["member_headers"]).status_code == 403
    finally:
        with session_scope() as session:
            session.execute(text(f"ALTER TABLE {model.__tablename__} DISABLE TRIGGER USER"))
            if mutation == "node":
                session.execute(update(model).where(*predicate).values(metadata_hash=values["metadata_hash"]))
            else:
                session.execute(insert(model).values(values))
            session.execute(text(f"ALTER TABLE {model.__tablename__} ENABLE TRIGGER USER"))
    assert v["client"].get(url, headers=v["headers"], params={"section": "semantic_assertion_members"}).json() == view


@pytest.mark.parametrize("mutation", ["missing", "content_hash"])
def test_context_read_rejects_missing_or_corrupt_relation_anchor_and_reauthorizes(frozen, mutation):
    v, _, image = frozen
    view, url = archive_image(v, image["revision"])
    ident = view["metadata"]["context_id"]
    predicate = (Anchor.project_id == v["project_id"], Anchor.context_id == ident)
    with session_scope() as session:
        row = session.get(Anchor, (v["project_id"], ident))
        values = {column.name: getattr(row, column.name) for column in Anchor.__table__.columns}
        session.execute(text("ALTER TABLE system_image_context_relation_anchors DISABLE TRIGGER USER"))
        if mutation == "missing":
            session.execute(delete(Anchor).where(*predicate))
        else:
            session.execute(update(Anchor).where(*predicate).values(content_hash="sha256:" + "0" * 64))
        session.execute(text("ALTER TABLE system_image_context_relation_anchors ENABLE TRIGGER USER"))
    try:
        response = v["client"].get(url, headers=v["headers"])
        assert response.status_code == 502, response.text
        assert response.json()["detail"]["error"]["code"] == "context_integrity_failed"
        assert "metadata" not in response.json() and "context" not in response.json()
        assert v["client"].get(url).status_code == 401
        assert v["client"].get(url, headers=v["member_headers"]).status_code == 403
    finally:
        with session_scope() as session:
            session.execute(text("ALTER TABLE system_image_context_relation_anchors DISABLE TRIGGER USER"))
            if mutation == "missing":
                session.execute(insert(Anchor).values(values))
            else:
                session.execute(update(Anchor).where(*predicate).values(content_hash=values["content_hash"]))
            session.execute(text("ALTER TABLE system_image_context_relation_anchors ENABLE TRIGGER USER"))
    assert v["client"].get(url, headers=v["headers"]).json() == view


def test_projection_failure_rolls_back_candidate_relation_graph_and_fact_outbox(semantic, monkeypatch):
    v = semantic
    _, _, payload, _ = setup(v)
    with session_scope() as session:
        before = inventory(session, v["project_id"])
        image_count = session.scalar(select(func.count()).select_from(Image).where(Image.project_id == v["project_id"]))
    project_event = RelationProvenanceProjectorV1.project_event
    def fail(self, session, event):
        project_event(self, session, event)
        if event.event_type == "system_image.candidate.frozen":
            raise ImageRevisionIntegrityError("injected relation graph failure")
    monkeypatch.setattr(RelationProvenanceProjectorV1, "project_event", fail)
    assert freeze(v, payload).json()["status"] == "failed"
    with session_scope() as session:
        assert inventory(session, v["project_id"]) == before
        assert session.scalar(select(func.count()).select_from(Image).where(Image.project_id == v["project_id"])) == image_count
        assert session.scalar(select(func.count()).select_from(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.event_payload["correlation_id"].as_string() == v["project_id"],
            SSEEventOutboxRecord.event_type == "system_image.candidate.frozen")) == image_count


def test_database_hash_pins_cross_project_foreign_keys_and_append_only(frozen):
    v, _, _ = frozen
    for model in (Node, Edge, Root):
        with pytest.raises(IntegrityError, match="append-only"), session_scope() as session:
            session.execute(delete(model).where(model.project_id == v["project_id"]))
    with session_scope() as session:
        row = session.scalars(select(Node).where(Node.project_id == v["project_id"], Node.kind == "object_pin")).first()
        values = {c.name: getattr(row, c.name) for c in Node.__table__.columns}
    for changes in ({"project_id": "foreign"}, {"object_node_hash": "sha256:" + "0" * 64,
            "artifact_hash": "sha256:" + "0" * 64}, {"object_node_key": "member:missing",
            "artifact_id": "member:missing", "node_key": "object_pin:member:missing"}):
        with pytest.raises(IntegrityError, match="foreign key"), session_scope() as session:
            session.execute(text("ALTER TABLE image_relation_provenance_nodes DISABLE TRIGGER USER"))
            session.execute(text("ALTER TABLE image_relation_provenance_edges DISABLE TRIGGER USER"))
            session.execute(delete(Edge).where(Edge.project_id == v["project_id"],
                (Edge.node_key == values["node_key"]) | (Edge.parent_key == values["node_key"])))
            session.execute(delete(Node).where(Node.project_id == v["project_id"], Node.node_key == values["node_key"]))
            session.execute(insert(Node).values({**values, **changes}))


class RollbackProbe(RuntimeError):
    pass


def reset_relations(scoped_op):
    assert engine.url.database.startswith("nasus_test_")
    assert scoped_op.get_bind().in_transaction()
    # Future additive indexes do not exist at the 0071 migration floor.
    # Remove them explicitly inside this rolled-back probe, never with CASCADE.
    for name in ("0078_retrieval_provenance", "0077_publication_provenance"):
        future = importlib.import_module("apps.api.migrations.versions." + name)
        for table in reversed(future.TABLES):
            scoped_op.drop_table(table)
    migration = importlib.import_module("apps.api.migrations.versions.0072_relation_provenance")
    for table in reversed(migration.TABLES):
        scoped_op.drop_table(table)
    scoped_op.execute("DROP FUNCTION nasus_reject_relation_provenance_mutation()")
    return migration


def test_populated_migration_is_idempotent_and_preserves_original_context_and_members(frozen, monkeypatch):
    v, url, view = frozen
    context, context_url = archive_image(v, view["revision"])
    with session_scope() as session:
        before = inventory(session, v["project_id"])
        old = session.get(Context, context["metadata"]["context_id"]).content_hash
    with pytest.raises(RollbackProbe), engine.begin() as connection:
        scoped_op = Operations(MigrationContext.configure(connection))
        migration = reset_relations(scoped_op)
        monkeypatch.setattr(migration, "op", scoped_op)
        migration.upgrade()
        with Session(bind=connection) as session:
            assert inventory(session, v["project_id"]) == before
            assert session.get(Context, context["metadata"]["context_id"]).content_hash == old
        with pytest.raises(RuntimeError, match="Cannot discard"):
            migration.downgrade()
        raise RollbackProbe()
    assert v["client"].get(url, headers=v["headers"], params={"section": "semantic_assertion_members"}).json() == view
    assert v["client"].get(context_url, headers=v["headers"]).json() == context


def test_wrong_existing_decision_hash_aborts_entire_backfill_and_ddl(frozen, monkeypatch):
    v, url, view = frozen
    from apps.api.app.infrastructure.persistence.semantic_review_models import SemanticDecisionRecord
    with pytest.raises(ImageRevisionIntegrityError), engine.begin() as connection:
        scoped_op = Operations(MigrationContext.configure(connection))
        migration = reset_relations(scoped_op)
        monkeypatch.setattr(migration, "op", scoped_op)
        connection.execute(text("ALTER TABLE image_semantic_decisions DISABLE TRIGGER USER"))
        connection.execute(update(SemanticDecisionRecord).where(SemanticDecisionRecord.project_id == v["project_id"])
            .values(content_hash="sha256:" + "0" * 64))
        migration.upgrade()
    assert v["client"].get(url, headers=v["headers"], params={"section": "semantic_assertion_members"}).json() == view


def test_ddl_and_orm_columns_match_exactly():
    inspector = inspect(engine)
    for model in (Node, Edge, Root, Anchor):
        columns = inspector.get_columns(model.__tablename__)
        assert [v["name"] for v in columns] == list(model.__table__.columns.keys())
        for actual, expected in zip(columns, model.__table__.columns):
            assert actual["nullable"] == expected.nullable
            assert actual["type"]._type_affinity is expected.type._type_affinity
