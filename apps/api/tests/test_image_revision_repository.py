from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, replace
import importlib.util
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import delete, func, insert, select, update, text
from sqlalchemy.exc import IntegrityError

from apps.api.app.application.system_image.image_candidates import ImageCandidateApplicationService
from apps.api.app.application.system_image.system_image_models import KnowledgeObject, KnowledgeCodeReference
from apps.api.app.domain.system_image.image_revision import ImageRevisionConflict, ImageRevisionIntegrityError
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.persistence import image_revision_repository as module
from apps.api.app.infrastructure.persistence import image_read_snapshot as snapshot_module
from apps.api.app.infrastructure.persistence.image_revision_models import (
    ImageRevisionRecord, ImageObjectMemberRecord, ImageRevisionInvocationRecord,
)
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.source_evidence_models import SourceEvidenceRecord, CodeEntityEvidenceRecord
from apps.api.app.infrastructure.persistence.code_entity_models import CodeEntityRevisionRecord
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage, ObjectStorageConfig
from apps.api.app.infrastructure.system_image.image_artifacts import ArchivedImageArtifacts
from apps.api.tests.test_code_entity_registry import registry, pg_repo, capture, register


def context_provenance_prerequisites():
    # Image-only repository tests have no context facts, but the production
    # relation migration still requires the real context FK contracts.
    from apps.api.app.infrastructure.persistence.context_pack_models import ContextPackRecord
    from apps.api.app.infrastructure.persistence.derivation_registry_models import (
        DerivationRegistryRecord, DerivationRegistryEdgeRecord, ContextQueryScopeRecord, ContextQuerySourceRecord,
    )
    from apps.api.app.infrastructure.persistence.context_provenance_models import ContextProvenanceAnchorRecord
    return (ContextPackRecord, DerivationRegistryRecord, DerivationRegistryEdgeRecord,
        ContextQueryScopeRecord, ContextQuerySourceRecord, ContextProvenanceAnchorRecord)


def drop_relation_provenance(connection):
    for table in ("system_image_context_relation_anchors", "image_relation_provenance_roots",
            "image_relation_provenance_edges", "image_relation_provenance_nodes"):
        connection.execute(text(f"DROP TABLE {table}"))
    connection.execute(text("DROP FUNCTION nasus_reject_relation_provenance_mutation()"))


@pytest.fixture
def image_repo(registry, monkeypatch):
    _, snapshots, sessions = registry
    path = Path(__file__).resolve().parents[1] / "migrations/versions/0038_image_candidates.py"
    spec = importlib.util.spec_from_file_location("image_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    document_path = path.parent / "0042_source_documents.py"
    document_spec = importlib.util.spec_from_file_location("document_migration", document_path)
    documents = importlib.util.module_from_spec(document_spec)
    document_spec.loader.exec_module(documents)
    review_migrations = []
    for name in ("0043_reference_links", "0044_link_decisions", "0045_image_review_membership", "0046_requirement_components",
                 "0047_semantic_evaluations", "0048_semantic_reviews", "0049_semantic_membership"):
        review_spec = importlib.util.spec_from_file_location(name, path.parent / f"{name}.py")
        review = importlib.util.module_from_spec(review_spec)
        review_spec.loader.exec_module(review)
        review_migrations.append(review)
    provenance_spec = importlib.util.spec_from_file_location("object_provenance_migration", path.parent / "0070_object_provenance.py")
    provenance = importlib.util.module_from_spec(provenance_spec)
    provenance_spec.loader.exec_module(provenance)
    relation_spec = importlib.util.spec_from_file_location("relation_provenance_migration", path.parent / "0072_relation_provenance.py")
    relations = importlib.util.module_from_spec(relation_spec)
    relation_spec.loader.exec_module(relations)
    with sessions.kw["bind"].begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
        conn.execute(text("CREATE TABLE knowledge_objects (id VARCHAR PRIMARY KEY)"))
        documents.op = Operations(MigrationContext.configure(conn))
        documents.upgrade()
        ToolInvocationRecord.__table__.create(conn)
        for review in review_migrations:
            review.op = Operations(MigrationContext.configure(conn))
            review.upgrade()
        provenance.op = Operations(MigrationContext.configure(conn))
        provenance.upgrade()
        for model in context_provenance_prerequisites():
            model.__table__.create(conn)
        relations.op = Operations(MigrationContext.configure(conn))
        relations.upgrade()

    @contextmanager
    def scope():
        with sessions.begin() as session:
            yield session

    monkeypatch.setattr(module, "session_scope", scope)
    monkeypatch.setattr(snapshot_module, "_session_factory", lambda: sessions)
    yield module.ImageRevisionRepository(), snapshots, sessions
    with sessions() as session:
        original_revisions = session.scalar(select(func.count()).select_from(CodeEntityRevisionRecord))
    with sessions.kw["bind"].begin() as conn:
        # This entire schema is private to the test, not a production downgrade.
        drop_relation_provenance(conn)
        for model in reversed(context_provenance_prerequisites()):
            model.__table__.drop(conn)
        for table in ("image_object_provenance_roots", "image_object_provenance_edges", "image_object_provenance_nodes"):
            conn.execute(text(f"DROP TABLE {table}"))
        conn.execute(text("DROP FUNCTION nasus_reject_object_provenance_mutation()"))
        for review in reversed(review_migrations):
            review.op = Operations(MigrationContext.configure(conn))
            review.downgrade()
        ToolInvocationRecord.__table__.drop(conn)
        documents.op = Operations(MigrationContext.configure(conn))
        documents.downgrade()
        migration.op = Operations(MigrationContext.configure(conn))
        migration.downgrade()
        conn.execute(text("DROP TABLE knowledge_objects"))
        assert conn.scalar(select(func.count()).select_from(CodeEntityRevisionRecord)) == original_revisions
        migration.upgrade()
        assert conn.scalar(select(func.count()).select_from(ImageRevisionRecord)) == 0
        migration.downgrade()


def inputs(registry, seed="a", source_id="source"):
    service, source, units, result = capture(registry, seed=seed, source_id=source_id)
    registered = register(service, source, units, result)
    manifest = registry[1].freeze_manifest(source.project_id, [source], captured_at="now")
    objects = [KnowledgeObject(id=f"object-{key}", name=key, type="code", branch="Official", confidence="0.8",
        freshness="now", code_reference=KnowledgeCodeReference(**asdict(ref))) for key, ref in registered.items()]
    return manifest, objects


def writer(image_repo, tmp_path):
    archive = ArchivedImageArtifacts(ObjectStorage(ObjectStorageConfig(None, "images", None, None, "local", tmp_path)))
    return ImageCandidateApplicationService(archive, image_repo[0])


def freeze(service, manifest, objects, invocation="invocation"):
    return service.freeze(manifest, "baseline", objects=objects, relationships=[], invocation_id=invocation, recorded_at="now")


def test_candidate_pins_all_members_and_retries_record_invocation_without_duplicate_event(image_repo, registry, tmp_path):
    manifest, objects = inputs(registry)
    service = writer(image_repo, tmp_path)
    first = freeze(service, manifest, objects)
    assert freeze(service, manifest, objects, "second-invocation") == first
    repo, _, sessions = image_repo
    header, ref, bindings = repo.get("project", first.image_revision_id)
    payload = service.artifacts.read("project", ref, header.artifact_hash)
    assert header == first and bindings == {manifest.members[0].binding_id}
    # This identity fixture has no archived bytes; do not invent verified evidence.
    assert len(payload["members"]) == len(objects) and all(item["evidence_ids"] == [] for item in payload["members"])
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(ImageRevisionRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ImageObjectMemberRecord)) == len(objects)
        assert session.scalar(select(func.count()).select_from(ImageRevisionInvocationRecord)) == 2
        events = session.scalars(select(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.event_type == "system_image.candidate.frozen")).all()
        assert len(events) == 1 and "object-" not in str(events[0].event_payload)
    assert repo.list("project", binding_ids=bindings, after_id="", limit=1) == [first]
    assert not repo.list("project", binding_ids=frozenset(), after_id="", limit=1)
    assert not repo.list("other", binding_ids=bindings, after_id="", limit=1)
    with pytest.raises(KeyError):
        repo.get("other", first.image_revision_id)
    for model in (ImageRevisionRecord, ImageObjectMemberRecord, ImageRevisionInvocationRecord):
        for statement in (update(model).values(project_id="changed"), delete(model)):
            with pytest.raises(IntegrityError, match="append-only"):
                with sessions.begin() as session:
                    session.execute(statement)


def test_new_inputs_do_not_redirect_history_and_moving_head_during_archive_rejects_commit(image_repo, registry, tmp_path, monkeypatch):
    old_manifest, old_objects = inputs(registry)
    service = writer(image_repo, tmp_path)
    first = freeze(service, old_manifest, old_objects)
    _, ref, _ = image_repo[0].get("project", first.image_revision_id)
    old_payload = service.artifacts.read("project", ref, first.artifact_hash)
    new_manifest, new_objects = inputs(registry, seed="b")
    original_put = service.artifacts.put

    def race(project_id, payload):
        archived = original_put(project_id, payload)
        inputs(registry, seed="c")
        return archived

    monkeypatch.setattr(service.artifacts, "put", race)
    with pytest.raises(ImageRevisionConflict, match="inputs changed"):
        freeze(service, new_manifest, new_objects)
    with image_repo[2]() as session:
        assert session.scalar(select(func.count()).select_from(ImageRevisionRecord)) == 1
    assert service.artifacts.read("project", ref, first.artifact_hash) == old_payload
    monkeypatch.setattr(service.artifacts, "put", original_put)
    newest_manifest, newest_objects = inputs(registry, seed="c")
    assert freeze(service, newest_manifest, newest_objects).image_revision_id != first.image_revision_id


def test_outbox_failure_rolls_back_candidate_members_and_invocation(image_repo, registry, tmp_path, monkeypatch):
    manifest, objects = inputs(registry)
    service = writer(image_repo, tmp_path)

    def fail(*args, **kwargs):
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(module.EventOutboxRepository, "append", fail)
    with pytest.raises(RuntimeError, match="outbox unavailable"):
        freeze(service, manifest, objects)
    with image_repo[2]() as session:
        for model in (ImageRevisionRecord, ImageObjectMemberRecord, ImageRevisionInvocationRecord):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_database_rejects_cross_project_entity_and_manifest_membership(image_repo, registry, tmp_path):
    manifest, objects = inputs(registry)
    freeze(writer(image_repo, tmp_path), manifest, objects)
    with image_repo[2]() as session:
        row = session.scalars(select(ImageObjectMemberRecord)).first()
        values = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    for field in ("project_id", "manifest_id", "binding_id", "entity_id", "source_revision_id", "entity_revision_id"):
        with pytest.raises(IntegrityError):
            with image_repo[2].begin() as session:
                session.execute(insert(ImageObjectMemberRecord).values(**{**values, "object_id": "forged", field: "foreign"}))


def test_forged_evidence_is_rejected_and_fixed_members_ignore_later_evidence(image_repo, registry, tmp_path, monkeypatch):
    manifest, objects = inputs(registry)
    service = writer(image_repo, tmp_path)
    reference = objects[0].code_reference

    def append_evidence():
        evidence_id = str(uuid4())
        with image_repo[2].begin() as session:
            values = dict(project_id=manifest.project_id,
                binding_id=manifest.members[0].binding_id, source_revision_id=reference.source_revision_id,
                relative_path="sample.java", start_line=1, end_line=1,
                precision="exact", file_hash="sha256:" + "a" * 64, snippet_hash="sha256:" + "a" * 64,
                object_ref="s3://fixture/raw", decoder_version="utf8", extractor_version=evidence_id)
            session.add(SourceEvidenceRecord(evidence_id=evidence_id, identity_hash=snapshot_digest(values), captured_at="now", **values))
            session.flush()
            session.add(CodeEntityEvidenceRecord(entity_revision_id=reference.entity_revision_id, evidence_id=evidence_id,
                project_id=manifest.project_id, binding_id=manifest.members[0].binding_id,
                source_revision_id=reference.source_revision_id))
        return evidence_id

    before = append_evidence()
    first = freeze(service, manifest, objects)
    later = append_evidence()
    _, ref, _ = service.repository.get("project", first.image_revision_id)
    old = service.artifacts.read("project", ref, first.artifact_hash)
    member = next(item for item in old["members"] if item["entity_revision_id"] == reference.entity_revision_id)
    assert member["evidence_ids"] == [before] and later not in str(old)
    second = freeze(service, manifest, objects)
    assert second.image_revision_id != first.image_revision_id
    original_pin = service.repository.pin_evidence

    def forged(project_id, members):
        pinned = original_pin(project_id, members)
        return (replace(pinned[0], evidence_ids=("foreign-evidence",)), *pinned[1:])

    monkeypatch.setattr(service.repository, "pin_evidence", forged)
    with pytest.raises(ImageRevisionIntegrityError, match="outside its code member"):
        freeze(service, manifest, objects)
    # Reads must never ask the current evidence index to rebuild old membership.
    _, ref, _ = service.repository.get("project", first.image_revision_id)
    assert "foreign-evidence" not in str(service.artifacts.read("project", ref, first.artifact_hash))
