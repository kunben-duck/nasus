from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.application.system_image.code_entity_registry import legacy_code_object_id
from apps.api.app.application.system_image.evidence_queries import EvidenceQueryApplicationService
from apps.api.app.application.system_image.system_image_models import RawAssetRecord
from apps.api.app.domain.system_image.evidence import EvidenceIntegrityError, EvidenceLocationUnavailable
from apps.api.app.infrastructure.persistence.source_evidence_models import SourceEvidenceRecord, CodeEntityEvidenceRecord
from apps.api.app.infrastructure.persistence.source_evidence_repository import SourceEvidenceRepository
from apps.api.app.infrastructure.persistence import code_entity_repository
from apps.api.app.infrastructure.persistence.code_entity_models import CodeEntityRevisionRecord, CodeEntityProviderBindingRecord
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord
from apps.api.app.infrastructure.system_image.evidence_source_reader import ArchivedEvidenceSourceReader
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.tests.test_source_snapshot_archive import _ingestion
from apps.api.tests.test_code_entity_registry import registry, pg_repo, register
from apps.api.tests.test_source_evidence import Authorization
from apps.api.tests.test_code_structural_identity import CONTROLLERS


def captured(registry, tmp_path, text="def run():\n    return 'old'\n", source_id="source"):
    service, snapshots, sessions = registry
    path = tmp_path / (source_id + ".py")
    path.write_text(text)
    ingestion = _ingestion(tmp_path)
    source = RawAssetRecord(id=source_id, project_id="project", source_type="code", source_uri=str(path))
    result = ingestion.ingest(source)
    source = source.model_copy(update={"content_ref": result.content_ref, "content_hash": result.content_hash, "ingestion_status": "indexed"})
    revision = snapshots.record_capture(source, result.snapshot, captured_at="2026-09-09")
    units = ingestion.extract_text_units(source)
    graph = TreeSitterCodeIntelligenceAdapter().analyze(units)
    register(service, source, units, graph)
    node = next(item for item in graph.entities if item.name == "run")
    object_id = legacy_code_object_id(source.project_id, source.id, node.provider_node_id)
    repo = SourceEvidenceRepository()
    evidence = repo.list_for_alias("project", revision, object_id)
    assert len(evidence) == 1
    app = EvidenceQueryApplicationService(repo, ArchivedEvidenceSourceReader(ingestion.snapshots.storage), Authorization(), Authorization())
    return app, evidence[0], ingestion, path, source, units, graph


def test_evidence_idempotence_and_old_revision_reads_after_source_deleted(registry, tmp_path):
    app, old, ingestion, path, source, units, graph = captured(registry, tmp_path)
    register(registry[0], source, units, graph)
    _, new, _, _, _, _, _ = captured(registry, tmp_path, "# changed\ndef run():\n    return 'new'\n")
    path.unlink()
    assert app.read("project", old.evidence_id).content == "def run():\n    return 'old'\n"
    assert app.read("project", new.evidence_id).content == "def run():\n    return 'new'\n"
    assert old.source_revision_id != new.source_revision_id
    with registry[2]() as session:
        assert session.scalar(select(func.count()).select_from(SourceEvidenceRecord)) == 4


def test_tampered_object_is_rejected_even_after_successful_read(registry, tmp_path):
    app, evidence, ingestion, _, _, _, _ = captured(registry, tmp_path)
    assert app.read("project", evidence.evidence_id).integrity == "verified"
    key = evidence.object_ref.split("/", 3)[3]
    ingestion.snapshots.storage.put_bytes(key, b"stolen-data\n")
    with pytest.raises(EvidenceIntegrityError):
        app.read("project", evidence.evidence_id)


def test_manifest_rewrite_is_rejected_before_raw_read(registry, tmp_path):
    app, evidence, ingestion, _, source, _, _ = captured(registry, tmp_path)
    payload = ingestion.snapshots.storage.get_json(source.content_ref)
    payload["files"][0]["content_ref"] = "local-object://other/private-secret"
    ingestion.snapshots.storage.put_json(source.content_ref.split("/", 3)[3], payload)
    with pytest.raises(EvidenceIntegrityError):
        app.read("project", evidence.evidence_id)


def test_manifest_reuse_is_session_local_but_raw_files_and_authorization_stay_live(registry, tmp_path, monkeypatch):
    app, evidence, ingestion, _, _, _, _ = captured(registry, tmp_path)
    reads = []
    original = app.reader.archive.read_manifest

    def read_manifest(*args, **kwargs):
        reads.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(app.reader.archive, "read_manifest", read_manifest)
    with app.verified_read_session():
        for _ in range(3):
            assert app.read("project", evidence.evidence_id).integrity == "verified"
        assert len(reads) == 1
        app.source_authorization.allowed = False
        with pytest.raises(PermissionError):
            app.read("project", evidence.evidence_id)
        app.source_authorization.allowed = True
        ingestion.snapshots.storage.put_bytes(evidence.object_ref.split("/", 3)[3], b"tampered\n")
        with pytest.raises(EvidenceIntegrityError):
            app.read("project", evidence.evidence_id)
    with pytest.raises(EvidenceIntegrityError):
        app.read("project", evidence.evidence_id)
    assert len(reads) == 2


def test_manifest_cache_binds_source_hash_and_is_reset_after_exception(registry, tmp_path, monkeypatch):
    app, evidence, _, _, _, _, _ = captured(registry, tmp_path)
    target = app.repository.get("project", evidence.evidence_id)
    original = app.reader.archive.read_manifest
    reads = []

    def read_manifest(*args, **kwargs):
        reads.append(kwargs["manifest_hash"])
        return original(*args, **kwargs)

    monkeypatch.setattr(app.reader.archive, "read_manifest", read_manifest)
    with pytest.raises(EvidenceIntegrityError):
        with app.verified_read_session():
            app.reader.read(target)
            app.reader.read(replace(target, manifest_hash="sha256:" + "0" * 64))
    app.reader.read(target)
    assert reads == [target.manifest_hash, "sha256:" + "0" * 64, target.manifest_hash]


def test_cross_project_reads_and_links_cannot_cross_scope(registry, tmp_path):
    _, evidence, _, _, _, _, _ = captured(registry, tmp_path)
    repo = SourceEvidenceRepository()
    with pytest.raises(KeyError):
        repo.get("foreign", evidence.evidence_id)
    with pytest.raises(KeyError):
        repo.list_for_alias("foreign", evidence.source_revision_id, "object")
    with registry[2]() as session:
        row = session.get(SourceEvidenceRecord, evidence.evidence_id)
        values = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    with pytest.raises(IntegrityError):
        with registry[2].begin() as session:
            session.execute(insert(SourceEvidenceRecord).values({**values, "evidence_id": "foreign", "project_id": "foreign"}))
    with registry[2]() as session:
        link = session.scalars(select(CodeEntityEvidenceRecord)).first()
        values = {column.name: getattr(link, column.name) for column in link.__table__.columns}
    with pytest.raises(IntegrityError):
        with registry[2].begin() as session:
            session.execute(insert(CodeEntityEvidenceRecord).values({**values, "entity_revision_id": "foreign"}))


@pytest.mark.parametrize("model", [SourceEvidenceRecord, CodeEntityEvidenceRecord])
@pytest.mark.parametrize("operation", ["update", "delete"])
def test_history_is_append_only(registry, tmp_path, model, operation):
    captured(registry, tmp_path)
    with pytest.raises(IntegrityError, match="append-only"):
        with registry[2].begin() as session:
            session.execute(update(model).values(project_id="foreign") if operation == "update" else delete(model))


def test_approximate_evidence_is_preserved_but_not_falsely_located(registry, tmp_path):
    app, exact, _, _, source, units, graph = captured(registry, tmp_path)
    node = next(item for item in graph.entities if item.name == "run")
    alias = legacy_code_object_id(source.project_id, source.id, node.provider_node_id)
    old = register(registry[0], source, units, graph)[node.provider_node_id]
    graph = replace(graph, entities=tuple(replace(item, location_precision="approximate") for item in graph.entities))
    new = register(registry[0], source, units, graph)[node.provider_node_id]
    assert old.entity_revision_id != new.entity_revision_id
    repo = SourceEvidenceRepository()
    assert repo.list_for_alias("project", exact.source_revision_id, alias, entity_revision_id=old.entity_revision_id) == [exact]
    approximate = repo.list_for_alias("project", exact.source_revision_id, alias, entity_revision_id=new.entity_revision_id)
    assert len(approximate) == 1 and approximate[0].locator.precision == "approximate"
    with registry[2]() as session:
        row = session.scalars(select(SourceEvidenceRecord).where(SourceEvidenceRecord.precision == "approximate")).first()
        evidence_id = row.evidence_id
        assert row.snippet_hash is None
    with pytest.raises(EvidenceLocationUnavailable):
        app.read("project", evidence_id)


def test_evidence_and_links_roll_back_with_registration_outbox(registry, tmp_path, monkeypatch):
    _, _, _, _, source, units, graph = captured(registry, tmp_path)
    models = (SourceEvidenceRecord, CodeEntityEvidenceRecord, CodeEntityRevisionRecord,
              CodeEntityProviderBindingRecord, SSEEventOutboxRecord)
    with registry[2]() as session:
        before = [session.scalar(select(func.count()).select_from(model)) for model in models]
    graph = replace(graph, entities=tuple(replace(item, location_precision="approximate") for item in graph.entities))

    def fail(*args, **kwargs):
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(code_entity_repository.EventOutboxRepository, "append", fail)
    with pytest.raises(RuntimeError, match="outbox unavailable"):
        register(registry[0], source, units, graph)
    with registry[2]() as session:
        assert [session.scalar(select(func.count()).select_from(model)) for model in models] == before


def structural_capture(registry, tmp_path, text=CONTROLLERS):
    path = tmp_path / "Controller.java"
    path.write_text(text)
    ingestion = _ingestion(tmp_path)
    source = RawAssetRecord(id="structural", project_id="project", source_type="code", source_uri=str(path))
    capture = ingestion.ingest(source)
    source = source.model_copy(update={"content_ref": capture.content_ref, "content_hash": capture.content_hash,
                                      "ingestion_status": "indexed"})
    registry[1].record_capture(source, capture.snapshot, captured_at="2026-10-08")
    units = ingestion.extract_text_units(source)
    graph = TreeSitterCodeIntelligenceAdapter().analyze(units)
    registered = register(registry[0], source, units, graph)
    app = EvidenceQueryApplicationService(SourceEvidenceRepository(), ArchivedEvidenceSourceReader(ingestion.snapshots.storage),
                                         Authorization(), Authorization())
    return source, graph, registered, ingestion, path, app


def test_structural_route_three_span_archive_survives_line_change_and_source_deletion(registry, tmp_path):
    from apps.api.app.infrastructure.system_image.code_identity_normalization import attach_symbol_keys
    from apps.api.tests.test_code_symbol_identity import external
    source, graph, registered, _, path, app = structural_capture(registry, tmp_path)
    routes = [item for item in graph.entities if item.entity_kind == "api_route"]
    old = {item.symbol_key: registered[item.provider_node_id] for item in routes}
    old_evidence = []
    for item in routes:
        ref = registered[item.provider_node_id]
        evidence = app.list_for_alias("project", ref.source_revision_id,
                                     legacy_code_object_id("project", source.id, item.provider_node_id),
                                     entity_revision_id=ref.entity_revision_id)
        assert len(evidence) == 3 and all(item.locator.precision == "exact" for item in evidence)
        contents = {app.read("project", item.evidence_id).content for item in evidence}
        assert contents == {'@RestController\n', '@RequestMapping("/api")\n', '    @GetMapping("/items")\n'}
        old_evidence.extend(item.evidence_id for item in evidence)
        with registry[2]() as session:
            row = session.get(CodeEntityRevisionRecord, ref.entity_revision_id)
            assert row.payload["schema"] == "nasus.code-entity-observation.v3"
            assert row.payload["observation_basis"] == "static_route_declaration"
    before = [app.read("project", key).content for key in old_evidence]
    newer, changed, new, new_ingestion, _, _ = structural_capture(registry, tmp_path, "// shifted\n\n" + CONTROLLERS)
    swapped = register(registry[0], newer, new_ingestion.extract_text_units(newer),
                       attach_symbol_keys(external(changed), changed))
    assert set(swapped.values()) == set(new.values())
    for item in changed.entities:
        if item.entity_kind == "api_route":
            assert new[item.provider_node_id].entity_id == old[item.symbol_key].entity_id
            assert new[item.provider_node_id].entity_revision_id != old[item.symbol_key].entity_revision_id
    path.unlink()
    assert [app.read("project", key).content for key in old_evidence] == before


def test_structural_evidence_registration_outbox_failure_is_atomic(registry, tmp_path, monkeypatch):
    source, graph, _, ingestion, _, _ = structural_capture(registry, tmp_path)
    models = (CodeEntityRevisionRecord, SourceEvidenceRecord, CodeEntityEvidenceRecord, CodeEntityProviderBindingRecord)
    with registry[2]() as session:
        before = [session.scalar(select(func.count()).select_from(model)) for model in models]
    changed = replace(graph, entities=tuple(replace(item, location_precision="approximate") for item in graph.entities))
    def fail(*args, **kwargs):
        raise RuntimeError("outbox unavailable")
    monkeypatch.setattr(code_entity_repository.EventOutboxRepository, "append", fail)
    with pytest.raises(RuntimeError, match="outbox unavailable"):
        register(registry[0], source, ingestion.extract_text_units(source), changed)
    with registry[2]() as session:
        assert [session.scalar(select(func.count()).select_from(model)) for model in models] == before
