from dataclasses import replace
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.app.application.system_image.context_extraction import ContextExtractionService
from apps.api.app.application.system_image.image_revision_queries import ImageRevisionQueryApplicationService
from apps.api.app.domain.system_image.code_alias import canonical_code_object_id, legacy_code_object_id
from apps.api.app.domain.system_image.source_access import SourceAccessScope
from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.infrastructure.persistence.code_alias_models import CodeObjectAliasRecord as Alias
from apps.api.app.infrastructure.persistence.code_alias_projection_v1 import CodeAliasProjectorV1
from apps.api.app.infrastructure.persistence.code_alias_repository import CodeObjectAliasRepository
from apps.api.app.infrastructure.persistence import code_entity_repository
from apps.api.app.infrastructure.persistence.code_entity_models import CodeEntityProviderBindingRecord as Mapping
from apps.api.app.infrastructure.persistence.code_entity_models import CodeEntityRevisionRecord as Revision
from apps.api.app.infrastructure.system_image.code_identity_normalization import attach_symbol_keys
from apps.api.tests.test_code_entity_registry import registry, pg_repo, capture, register
from apps.api.tests.test_code_symbol_identity import external
from apps.api.tests.test_image_revision_repository import image_repo, writer, freeze


def extract(registry, item, units, graph):
    return ContextExtractionService(SimpleNamespace(extract_text_units=lambda _: units),
        SimpleNamespace(analyze=lambda _: graph), code_entity_registry=registry[0].repository).extract(
        project_id=item.project_id, project_name="Identity test", baseline_id="baseline", sources=[item],
        version_id=None, captured_at="2026-10-07T00:00:00Z")


def test_new_object_ids_and_edges_survive_provider_replacement(registry):
    service, item, units, graph = capture(registry)
    first = extract(registry, item, units, graph)
    second = extract(registry, item, units, attach_symbol_keys(external(graph), graph))
    code_ids = {obj.id for obj in first.objects if obj.code_reference}
    assert code_ids and code_ids == {obj.id for obj in second.objects if obj.code_reference}
    assert all(obj.id == canonical_code_object_id(obj.code_reference.entity_id) for obj in second.objects if obj.code_reference)
    all_ids = {obj.id for obj in second.objects}
    assert all(edge.from_object_id in all_ids and edge.to_object_id in all_ids for edge in second.relationships)
    assert all(obj.id.startswith("CTX-") and obj.code_reference is None for obj in
        extract(registry, item, units, replace(graph, entities=tuple(replace(node, identity_status="ambiguous") for node in graph.entities))).objects)
    with registry[2]() as session:
        rows = session.scalars(select(Alias)).all()
        assert len(rows) == session.scalar(select(func.count()).select_from(Mapping))
        assert {row.canonical_object_id for row in rows} == code_ids


def test_line_changes_preserve_canonical_id_but_not_revision(registry):
    _, item, units, graph = capture(registry)
    first = extract(registry, item, units, graph)
    _, next_item, next_units, next_graph = capture(registry, "// changed\nclass A { void load(int renamed){} }\n", "b")
    second = extract(registry, next_item, next_units, next_graph)
    a = {obj.id: obj.code_reference for obj in first.objects if obj.code_reference}
    b = {obj.id: obj.code_reference for obj in second.objects if obj.code_reference}
    assert a.keys() == b.keys()
    assert all(a[ident].source_revision_id != b[ident].source_revision_id for ident in a)


def test_provider_only_alias_registration_rolls_back_when_outbox_fails(registry, monkeypatch):
    service, item, units, graph = capture(registry)
    first = register(service, item, units, graph)
    with registry[2]() as session:
        hashes = {row.content_hash for row in session.scalars(select(Alias))}
    replacement = attach_symbol_keys(external(graph), graph)
    append = code_entity_repository.EventOutboxRepository.append

    def fail(*args, **kwargs):
        raise RuntimeError("alias outbox unavailable")

    monkeypatch.setattr(code_entity_repository.EventOutboxRepository, "append", fail)
    with pytest.raises(RuntimeError, match="alias outbox unavailable"):
        register(service, item, units, replacement)
    with registry[2]() as session:
        assert {row.content_hash for row in session.scalars(select(Alias))} == hashes
        for model in (Alias, Mapping, Revision):
            assert session.scalar(select(func.count()).select_from(model)) == len(first)
    monkeypatch.setattr(code_entity_repository.EventOutboxRepository, "append", append)
    assert list(register(service, item, units, replacement).values()) == list(first.values())
    with registry[2]() as session:
        assert session.scalar(select(func.count()).select_from(Alias)) == len(first) * 2
        assert session.scalar(select(func.count()).select_from(Revision)) == len(first)


def test_alias_fk_and_immutability_protect_both_provider_and_entity_pins(registry):
    service, item, units, graph = capture(registry)
    register(service, item, units, graph)
    with registry[2]() as session:
        row = session.scalars(select(Alias)).first()
        values = {column.name: getattr(row, column.name) for column in row.__table__.columns}
        mapping = session.scalars(select(Mapping).where(Mapping.project_id == row.project_id,
            Mapping.extraction_digest == row.extraction_digest, Mapping.provider_node_hash == row.provider_node_hash)).first()
        mapping_values = {column.name: getattr(mapping, column.name) for column in mapping.__table__.columns}
    with registry[2].begin() as session:
        session.execute(insert(Mapping).values({**mapping_values, "extraction_digest": "sha256:" + "0" * 64}))
    with pytest.raises(IntegrityError, match="append-only"):
        with registry[2].begin() as session:
            session.execute(update(Alias).values(canonical_object_id="wrong"))
    for changed in ({"project_id": "foreign"}, {"entity_id": "071d553d-40f3-45c8-b8b9-8d67398c722d",
            "canonical_object_id": "CODE-071d553d-40f3-45c8-b8b9-8d67398c722d"}, {"entity_revision_id": "foreign"},
            {"legacy_object_id": "CTX-" + "0" * 16}):
        with pytest.raises(IntegrityError):
            with registry[2].begin() as session:
                session.execute(insert(Alias).values({**values, "extraction_digest": "sha256:" + "0" * 64, **changed}))


def test_backfill_audits_every_existing_provider_mapping_and_is_idempotent(registry):
    service, item, units, graph = capture(registry)
    register(service, item, units, graph)
    register(service, item, units, attach_symbol_keys(external(graph), graph))
    engine = registry[2].kw["bind"]
    path = Path(__file__).resolve().parents[1] / "migrations/versions/0069_code_object_aliases.py"
    spec = importlib.util.spec_from_file_location("alias_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as conn:
        before = conn.scalar(select(func.count()).select_from(Alias))
        conn.execute(text("DROP TABLE code_object_aliases"))
        conn.execute(text("DROP FUNCTION nasus_reject_code_alias_mutation()"))
        conn.execute(text("ALTER TABLE code_entity_revisions DROP CONSTRAINT uq_code_alias_revision_pin"))
        conn.execute(text("ALTER TABLE code_entity_provider_bindings DROP CONSTRAINT uq_code_alias_mapping_pin"))
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
        assert conn.scalar(select(func.count()).select_from(Alias)) == before
    with registry[2].begin() as session:
        assert CodeAliasProjectorV1().backfill(session) == 0
    with engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        with pytest.raises(RuntimeError, match="Cannot discard"):
            migration.downgrade()


def test_populated_alias_backfill_can_read_pre_tracked_ref_source_schema(registry):
    service, item, units, graph = capture(registry)
    register(service, item, units, graph)
    engine = registry[2].kw["bind"]
    with engine.begin() as conn:
        before = conn.execute(select(Alias.content_hash).order_by(Alias.content_hash)).scalars().all()
        assert before
        conn.execute(text("ALTER TABLE source_bindings DROP COLUMN tracked_ref"))
        with Session(bind=conn) as session:
            assert CodeAliasProjectorV1().backfill(session) == 0
        assert conn.execute(select(Alias.content_hash).order_by(Alias.content_hash)).scalars().all() == before


def test_backfill_rejects_mapping_corruption_without_creating_aliases(registry):
    service, item, units, graph = capture(registry)
    register(service, item, units, graph)
    with registry[2].begin() as session:
        session.execute(text("ALTER TABLE code_entity_provider_bindings DISABLE TRIGGER immutable_code_entity_provider_bindings"))
        session.execute(update(Mapping).values(provider_node_id="corrupt-node"))
        with pytest.raises(ImageRevisionIntegrityError, match="audit"):
            CodeAliasProjectorV1().backfill(session)
        # The intentional corruption is rolled back with its private test transaction.
        session.rollback()


def test_failed_migration_rolls_back_backfill_and_ddl(registry):
    service, item, units, graph = capture(registry)
    register(service, item, units, graph)
    engine = registry[2].kw["bind"]
    path = Path(__file__).resolve().parents[1] / "migrations/versions/0069_code_object_aliases.py"
    spec = importlib.util.spec_from_file_location("failed_alias_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.connect() as conn:
        before = conn.scalar(select(func.count()).select_from(Alias))
        last = conn.execute(select(Mapping.provider_node_hash).order_by(
            Mapping.project_id.desc(), Mapping.binding_id.desc(), Mapping.source_revision_id.desc(),
            Mapping.extraction_digest.desc(), Mapping.provider_node_hash.desc())).scalar()
        assert before > 1
    with pytest.raises(ImageRevisionIntegrityError, match="audit"):
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE code_object_aliases"))
            conn.execute(text("DROP FUNCTION nasus_reject_code_alias_mutation()"))
            conn.execute(text("ALTER TABLE code_entity_revisions DROP CONSTRAINT uq_code_alias_revision_pin"))
            conn.execute(text("ALTER TABLE code_entity_provider_bindings DROP CONSTRAINT uq_code_alias_mapping_pin"))
            conn.execute(text("ALTER TABLE code_entity_provider_bindings DISABLE TRIGGER immutable_code_entity_provider_bindings"))
            conn.execute(update(Mapping).where(Mapping.provider_node_hash == last).values(provider_node_id="corrupt-node"))
            migration.op = Operations(MigrationContext.configure(conn))
            migration.upgrade()
    with registry[2].begin() as session:
        assert session.scalar(select(func.count()).select_from(Alias)) == before
        assert CodeAliasProjectorV1().backfill(session) == 0
    with pytest.raises(IntegrityError, match="append-only"):
        with registry[2].begin() as session:
            session.execute(update(Alias).values(canonical_object_id="wrong"))


def test_frozen_alias_resolution_preserves_historical_ids_and_never_jumps_source_revisions(image_repo, registry, tmp_path):
    service, item, units, graph = capture(registry)
    extracted = extract(registry, item, units, graph)
    by_entity = {ref.entity_id: legacy_code_object_id(item.project_id, item.id, node_id)
                 for node_id, ref in register(service, item, units, graph).items()}
    legacy = [obj.model_copy(update={"id": by_entity[obj.code_reference.entity_id]})
              for obj in extracted.objects if obj.code_reference]
    manifest = registry[1].freeze_manifest(item.project_id, [item], captured_at="now")
    archive = writer(image_repo, tmp_path)
    old = freeze(archive, manifest, legacy, "legacy-image")
    new = freeze(archive, manifest, [obj for obj in extracted.objects if obj.code_reference], "canonical-image")
    scope = SourceAccessScope(item.project_id, "reviewer", "viewer", 0,
        frozenset(member.binding_id for member in manifest.members), frozenset({item.id}), "test-scope", False)
    authorization = SimpleNamespace(scope=lambda _: scope, require_current=lambda _: None)
    queries = ImageRevisionQueryApplicationService(image_repo[0], archive.artifacts, authorization,
        code_aliases=CodeObjectAliasRepository())
    registered = next(obj for obj in extracted.objects if obj.code_reference)
    old_id = by_entity[registered.code_reference.entity_id]
    first = queries.resolve_code_object(item.project_id, old.image_revision_id, registered.id)
    second = queries.resolve_code_object(item.project_id, new.image_revision_id, old_id)
    assert first.frozen_object_id == old_id and second.frozen_object_id == registered.id
    assert first.entity_revision_id == second.entity_revision_id
    assert queries.read(item.project_id, old.image_revision_id).items[0]["id"].startswith("CTX-")
    assert CodeObjectAliasRepository().find_in_image("foreign", old.image_revision_id, registered.id) == ()
    _, changed_item, changed_units, changed_graph = capture(registry, "// moved\nclass A { void load(int x){} }\n", "b")
    extract(registry, changed_item, changed_units, changed_graph)
    assert queries.resolve_code_object(item.project_id, old.image_revision_id, registered.id) == first
