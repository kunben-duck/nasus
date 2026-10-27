import importlib.util
from dataclasses import asdict
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import delete, event, func, insert, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.application.system_image.system_image_models import KnowledgeObject, KnowledgeCodeReference, RawAssetRecord
from apps.api.app.infrastructure.persistence.image_revision_models import ImageRevisionRecord as Image, ImageObjectMemberRecord as Member
from apps.api.app.infrastructure.persistence.object_provenance_models import (
    ObjectProvenanceNodeRecord as Node, ObjectProvenanceEdgeRecord as Edge, ImageObjectProvenanceRecord as Root,
)
from apps.api.app.infrastructure.persistence.object_provenance_projection_v1 import ObjectProvenanceProjectorV1
from apps.api.tests.test_code_entity_registry import registry, pg_repo
from apps.api.tests.test_image_revision_repository import image_repo, inputs, writer, freeze, drop_relation_provenance
from apps.api.tests.test_source_evidence_repository import captured
from apps.api.tests.test_code_entity_registry import register
from apps.api.app.infrastructure.persistence.code_entity_models import CodeEntityIdentityRecord, CodeEntityRevisionRecord
from apps.api.app.infrastructure.persistence.source_evidence_models import SourceEvidenceRecord, CodeEntityEvidenceRecord
from apps.api.app.infrastructure.persistence.source_snapshot_models import (
    SourceBindingRecord, SourceRevisionRecord, SourceManifestRecord, SourceManifestMemberRecord,
)


def evidenced_inputs(registry, tmp_path):
    _, _, _, _, source, units, graph = captured(registry, tmp_path)
    references = register(registry[0], source, units, graph)
    manifest = registry[1].freeze_manifest("project", [source], captured_at="now")
    objects = [KnowledgeObject(id="object-" + key, name=key, type="code", branch="Official",
        confidence="unknown", freshness="now", code_reference=KnowledgeCodeReference(**asdict(reference)))
        for key, reference in references.items()]
    return manifest, objects


def test_fixed_image_records_complete_source_entity_membership_and_shared_ancestors(image_repo, registry, tmp_path):
    manifest, objects = inputs(registry)
    service = writer(image_repo, tmp_path)
    first = freeze(service, manifest, objects)
    second = freeze(service, manifest, [o.model_copy(update={"name": "renamed"}) for o in objects], "second")
    sessions = image_repo[2]
    with sessions.begin() as session:
        assert ObjectProvenanceProjectorV1().backfill(session) == 0
        roots = session.scalars(select(Root)).all()
        assert len(roots) == 2
        nodes = session.scalars(select(Node)).all()
        assert sum(n.kind == "source" for n in nodes) == 1
        assert sum(n.kind == "manifest" for n in nodes) == 1
        assert sum(n.kind == "code" for n in nodes) == len(objects)
        assert sum(n.kind == "member" for n in nodes) == 2 * len(objects)
        assert sum(n.kind == "image_objects" for n in nodes) == 2
        root = next(n for n in nodes if n.node_key == roots[0].node_key)
        assert root.source_pins == [[manifest.members[0].binding_id, manifest.members[0].source_revision_id]]
        assert len(session.scalars(select(Edge).where(Edge.node_key == root.node_key)).all()) == len(objects) + 1
    image_repo[0].get("project", first.image_revision_id)
    image_repo[0].get("project", second.image_revision_id)


def test_populated_provenance_backfill_can_read_pre_tracked_ref_source_schema(image_repo, registry, tmp_path):
    manifest, objects = evidenced_inputs(registry, tmp_path)
    image = freeze(writer(image_repo, tmp_path), manifest, objects)
    engine = image_repo[2].kw["bind"]
    with engine.begin() as conn:
        before = conn.execute(select(Node.content_hash).order_by(Node.content_hash)).scalars().all()
        assert before
        conn.execute(text("ALTER TABLE source_bindings DROP COLUMN tracked_ref"))
        with Session(bind=conn) as session:
            assert ObjectProvenanceProjectorV1().backfill(session) == 0
        assert conn.execute(select(Node.content_hash).order_by(Node.content_hash)).scalars().all() == before
    image_repo[0].get("project", image.image_revision_id)


def test_read_audit_checks_all_nodes_and_edges_without_orm_identity_allocation(image_repo, registry, tmp_path):
    manifest, objects = inputs(registry)
    image = freeze(writer(image_repo, tmp_path), manifest, objects)
    with image_repo[2]() as session:
        projector = ObjectProvenanceProjectorV1()
        expected = projector.expected(session, session.get(Image, image.image_revision_id))
        loaded = []

        def loaded_instance(_session, instance):
            if isinstance(instance, (Node, Edge)):
                loaded.append(type(instance))

        event.listen(session, "loaded_as_persistent", loaded_instance)
        try:
            assert projector._compare(session, expected, write=False) == 0
        finally:
            event.remove(session, "loaded_as_persistent", loaded_instance)
        assert loaded == []
        assert not any(key[0] in {Node, Edge} for key in session.identity_map)
        assert any(node.parents for node in expected.values())


def test_native_audit_and_membership_read_do_not_allocate_source_orm_identities(image_repo, registry, tmp_path):
    manifest, objects = evidenced_inputs(registry, tmp_path)
    image = freeze(writer(image_repo, tmp_path), manifest, objects)
    native_models = (Member, CodeEntityIdentityRecord, CodeEntityRevisionRecord, SourceEvidenceRecord,
        CodeEntityEvidenceRecord, SourceBindingRecord, SourceRevisionRecord, SourceManifestRecord, SourceManifestMemberRecord)
    with image_repo[2]() as session:
        loaded = []

        def loaded_instance(_session, instance):
            if isinstance(instance, native_models):
                loaded.append(type(instance))

        event.listen(session, "loaded_as_persistent", loaded_instance)
        try:
            expected = ObjectProvenanceProjectorV1().expected(session, session.get(Image, image.image_revision_id))
            assert any(node.kind == "code" for node in expected.values())
            assert any(node.kind == "evidence" for node in expected.values())
            result, artifact_ref, bindings = image_repo[0]._get(session, "project", image.image_revision_id)
            assert result == image and artifact_ref and bindings == frozenset(m.binding_id for m in manifest.members)
        finally:
            event.remove(session, "loaded_as_persistent", loaded_instance)
        assert loaded == []
        assert not any(key[0] in native_models for key in session.identity_map)


@pytest.mark.parametrize("model,field", [(CodeEntityRevisionRecord, "payload"),
    (CodeEntityIdentityRecord, "symbol_key"), (SourceEvidenceRecord, "object_ref")])
def test_native_column_audit_autoflushes_and_rejects_pending_corruption(image_repo, registry, tmp_path, model, field):
    manifest, objects = evidenced_inputs(registry, tmp_path)
    image = freeze(writer(image_repo, tmp_path), manifest, objects)
    with image_repo[2]() as session:
        session.execute(text(f"ALTER TABLE {model.__tablename__} DISABLE TRIGGER USER"))
        image_row = session.get(Image, image.image_revision_id)
        row = session.scalars(select(model).where(model.project_id == "project")).first()
        assert row is not None
        value = getattr(row, field)
        setattr(row, field, {**value, "tampered": True} if type(value) is dict else value + "/tampered")
        assert row in session.dirty
        with pytest.raises(ImageRevisionIntegrityError, match="provenance"):
            ObjectProvenanceProjectorV1().expected(session, image_row)
        assert row not in session.dirty
        session.rollback()
    image_repo[0].get("project", image.image_revision_id)


def test_provenance_failure_rolls_back_candidate_members_outbox_and_new_nodes(image_repo, registry, tmp_path, monkeypatch):
    manifest, objects = inputs(registry)
    projector = ObjectProvenanceProjectorV1._compare

    def fail(self, session, nodes, *, write):
        projector(self, session, nodes, write=write)
        raise RuntimeError("provenance write failed")

    monkeypatch.setattr(ObjectProvenanceProjectorV1, "_compare", fail)
    with pytest.raises(RuntimeError, match="provenance write failed"):
        freeze(writer(image_repo, tmp_path), manifest, objects)
    with image_repo[2]() as session:
        for model in (Image, Member, Node, Edge, Root):
            assert session.scalar(select(func.count()).select_from(model)) == 0
    monkeypatch.setattr(ObjectProvenanceProjectorV1, "_compare", projector)
    assert freeze(writer(image_repo, tmp_path), manifest, objects)


@pytest.mark.parametrize("corruption", ["missing_node", "missing_edge", "node_hash", "extra_edge", "missing_root"])
def test_existing_image_read_rejects_incomplete_or_corrupt_provenance(image_repo, registry, tmp_path, corruption):
    manifest, objects = inputs(registry)
    image = freeze(writer(image_repo, tmp_path), manifest, objects)
    with image_repo[2].begin() as session:
        for model in (Node, Edge, Root):
            session.execute(text(f"ALTER TABLE {model.__tablename__} DISABLE TRIGGER USER"))
        root_key = "image_objects:" + image.image_revision_id
        if corruption == "missing_edge":
            session.execute(delete(Edge).where(Edge.node_key == root_key))
        elif corruption == "missing_root":
            session.execute(delete(Root))
        elif corruption == "node_hash":
            session.execute(update(Node).where(Node.node_key == root_key).values(metadata_hash="sha256:" + "0" * 64))
        elif corruption == "missing_node":
            code = session.scalars(select(Node).where(Node.kind == "code")).first()
            session.execute(delete(Edge).where((Edge.node_key == code.node_key) | (Edge.parent_key == code.node_key)))
            session.execute(delete(Node).where(Node.node_key == code.node_key))
        else:
            source = session.scalars(select(Node).where(Node.kind == "source")).one()
            root = session.get(Node, ("project", root_key))
            session.execute(insert(Edge).values(project_id="project", node_key=root_key, parent_key=source.node_key,
                node_hash=root.content_hash, parent_hash=source.content_hash))
        with pytest.raises(ImageRevisionIntegrityError, match="provenance"):
            row = session.get(Image, image.image_revision_id)
            ObjectProvenanceProjectorV1().image(session, row, write=False)
        session.rollback()
    image_repo[0].get("project", image.image_revision_id)


def test_duplicate_freeze_cannot_return_a_successful_fact_with_missing_registry(image_repo, registry, tmp_path):
    manifest, objects = inputs(registry)
    service = writer(image_repo, tmp_path)
    first = freeze(service, manifest, objects)
    with image_repo[2].begin() as session:
        session.execute(text("ALTER TABLE image_object_provenance_roots DISABLE TRIGGER USER"))
        session.execute(delete(Root))
        session.execute(text("ALTER TABLE image_object_provenance_roots ENABLE TRIGGER USER"))
    with pytest.raises(ImageRevisionIntegrityError, match="provenance"):
        freeze(service, manifest, objects, "second")
    with image_repo[2]() as session:
        assert session.get(Image, first.image_revision_id)


def test_database_protects_append_only_nodes_edges_roots_and_cross_project_hash_pins(image_repo, registry, tmp_path):
    manifest, objects = inputs(registry)
    freeze(writer(image_repo, tmp_path), manifest, objects)
    for model in (Node, Edge, Root):
        for statement in (update(model).values(project_id="other"), delete(model)):
            with pytest.raises(IntegrityError, match="append-only"):
                with image_repo[2].begin() as session:
                    session.execute(statement)
    with image_repo[2]() as session:
        edge = session.scalars(select(Edge)).first()
        values = {col.name: getattr(edge, col.name) for col in edge.__table__.columns}
        original = session.get(Node, ("project", edge.node_key))
        fresh = {col.name: getattr(original, col.name) for col in original.__table__.columns}
    fresh.update(artifact_id="new-node", node_key=fresh["kind"] + ":new-node")
    with image_repo[2].begin() as session:
        session.execute(insert(Node).values(fresh))
    for changed in ({"project_id": "other"}, {"parent_hash": "sha256:" + "0" * 64}):
        with pytest.raises(IntegrityError):
            with image_repo[2].begin() as session:
                session.execute(insert(Edge).values({**values, "node_key": fresh["node_key"], **changed}))


class RollbackProbe(RuntimeError):
    pass


def drop_later_object_dependents(connection):
    drop_relation_provenance(connection)
    connection.execute(text("DROP TABLE system_image_context_provenance_anchors"))


def test_migration_backfills_populated_images_atomically_and_refuses_destructive_downgrade(image_repo, registry, tmp_path):
    manifest, objects = inputs(registry)
    image = freeze(writer(image_repo, tmp_path), manifest, objects)
    path = Path(__file__).resolve().parents[1] / "migrations/versions/0070_object_provenance.py"
    spec = importlib.util.spec_from_file_location("provenance_backfill", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with pytest.raises(RollbackProbe), image_repo[2].kw["bind"].begin() as conn:
        before = conn.scalar(select(func.count()).select_from(Node))
        drop_later_object_dependents(conn)
        for model in (Root, Edge, Node):
            model.__table__.drop(conn)
        conn.execute(text("DROP FUNCTION nasus_reject_object_provenance_mutation()"))
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
        assert conn.scalar(select(func.count()).select_from(Node)) == before
        with pytest.raises(RuntimeError, match="Cannot discard"):
            migration.downgrade()
        raise RollbackProbe()
    image_repo[0].get("project", image.image_revision_id)


def test_native_bad_pin_during_backfill_rolls_back_ddl_and_partial_graph(image_repo, registry, tmp_path):
    manifest, objects = inputs(registry)
    image = freeze(writer(image_repo, tmp_path), manifest, objects)
    path = Path(__file__).resolve().parents[1] / "migrations/versions/0070_object_provenance.py"
    spec = importlib.util.spec_from_file_location("provenance_failed_backfill", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = image_repo[2].kw["bind"]
    with engine.connect() as conn:
        before = conn.scalar(select(func.count()).select_from(Node))
    with pytest.raises(ImageRevisionIntegrityError):
        with engine.begin() as conn:
            drop_later_object_dependents(conn)
            for model in (Root, Edge, Node):
                model.__table__.drop(conn)
            conn.execute(text("DROP FUNCTION nasus_reject_object_provenance_mutation()"))
            conn.execute(text("ALTER TABLE image_revisions DISABLE TRIGGER USER"))
            conn.execute(update(Image).values(object_count=999))
            migration.op = Operations(MigrationContext.configure(conn))
            migration.upgrade()
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(Node)) == before
    image_repo[0].get("project", image.image_revision_id)


def test_complete_registration_exceeds_batch_size_and_keeps_failed_pending_sources(image_repo, registry, tmp_path, monkeypatch):
    manifest, objects = inputs(registry)
    from apps.api.tests.test_source_snapshot_repository import source, artifact, indexed
    code = indexed(source(), artifact("a"))
    optional = [RawAssetRecord(id="optional-" + status, project_id="project", source_type="us_doc",
        source_uri="unavailable-" + status, ingestion_status=status) for status in ("failed", "pending")]
    manifest = registry[1].freeze_manifest("project", [code, *optional], captured_at="now")
    objects.extend(KnowledgeObject(id=f"legacy-{i:04}", name="Unverified legacy observation", type="code",
        branch="Official", confidence="unknown", freshness="now") for i in range(540))
    image = freeze(writer(image_repo, tmp_path), manifest, objects)
    with image_repo[2].begin() as session:
        expected = ObjectProvenanceProjectorV1().expected(session, session.get(Image, image.image_revision_id))
        assert sum(n.kind == "member" for n in expected.values()) == len(objects) > 540
        root = expected["image_objects:" + image.image_revision_id]
        assert len(root.parents) == len(objects) + 1 and len(root.source_pins) == 1
        assert len(manifest.members) == 3 and {m.status for m in manifest.members} == {"captured", "failed", "pending"}
        assert ObjectProvenanceProjectorV1().backfill(session) == 0
        assert session.scalar(select(func.count()).select_from(Node)) == len(expected)
        from apps.api.app.domain.system_image.object_provenance import ObjectProvenanceNode
        getter = ObjectProvenanceNode.content_hash.fget
        calls = {}

        def counted(node):
            calls[node.key] = calls.get(node.key, 0) + 1
            return getter(node)

        with monkeypatch.context() as patch:
            patch.setattr(ObjectProvenanceNode, "content_hash", property(counted))
            ObjectProvenanceProjectorV1()._compare(session, expected, write=False)
        assert set(calls) == set(expected) and max(calls.values()) == 1
    image_repo[0].get("project", image.image_revision_id)
