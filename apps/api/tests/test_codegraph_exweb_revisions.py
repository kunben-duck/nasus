"""Two actual exweb revisions, two native providers and revision-pinned PG/MinIO evidence."""
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from apps.api.app.domain.system_image.evidence import source_lines, text_digest
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.persistence.code_entity_models import CodeEntityIdentityRecord, CodeEntityRevisionRecord
from apps.api.app.infrastructure.persistence.source_evidence_models import SourceEvidenceRecord
from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import CodebaseMemoryCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.code_identity_normalization import attach_symbol_keys
from apps.api.app.infrastructure.system_image.code_graph_observation_validation import validate_java_imports
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
from apps.api.app.infrastructure.system_image.source_snapshot_archive import SourceSnapshotArchive
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.tests.exweb_git_trees import BEFORE, AFTER, git_bytes, read_git_tree
from apps.api.tests.test_codegraph_exweb import exweb_sdk_input, registry, pg_repo, register
from apps.api.tests.test_code_graph_enrichment import _config


def projection_hash(result):
    return snapshot_digest({"entities": [asdict(item) for item in result.entities],
                            "relationships": [asdict(item) for item in result.relationships]})


def test_native_providers_keep_entity_identity_but_pin_two_actual_source_revisions(registry, tmp_path, exweb_sdk_input):
    configured = os.environ.get("EXWEB_CODEGRAPH_HISTORY_SOURCE")
    if not configured:
        pytest.skip("set EXWEB_CODEGRAPH_HISTORY_SOURCE to the reviewed two-commit Git object store")
    root = Path(configured).resolve()
    assert git_bytes(root, "rev-parse", AFTER + "^").decode().strip() == BEFORE
    original_status = git_bytes(root, "status", "--porcelain")
    source, _, approved_units, storage, graph, git = exweb_sdk_input
    service, snapshots, sessions = registry
    reader = SourceIngestionService(object_storage=storage, snapshot_cache_dir=tmp_path / "history-restored")
    archive = SourceSnapshotArchive(storage)
    cbm = CodebaseMemoryCodeIntelligenceAdapter(replace(_config(Path(__file__).resolve().parents[3] / ".venv/bin/codebase-memory-mcp"),
        mode="required", cache_dir=tmp_path / "cbm-history-cache", timeout_seconds=180,
        max_entities=20000, max_relationships=50000, page_size=500))
    reports, syntax_maps, revision_ids, entity_revision_ids = {}, {}, [], {}
    for number, revision in enumerate((BEFORE, AFTER)):
        files, content_hash, inventory = read_git_tree(root, revision)
        assert len(files) == 125 + number
        if revision == AFTER:
            assert {path: text_digest(body.decode("utf-8")) for path, body in files} == {
                unit.relative_path: unit.content_hash for unit in approved_units}
        artifact = archive.capture(project_id=source.project_id, source_id=source.id, files=files,
            content_hash=content_hash, external_revision=revision, excluded_directories=[], inventory=inventory)
        current = source.model_copy(update={"content_ref": artifact.manifest_ref, "content_hash": artifact.content_hash})
        revision_ids.append(snapshots.record_capture(current, artifact, captured_at="2026-10-08T00:00:00Z"))
        units = reader.extract_text_units(current)
        assert len(units) == len(files) and sum(unit.byte_count for unit in units) == artifact.byte_count
        syntax = TreeSitterCodeIntelligenceAdapter().analyze(units)
        mapped = register(service, current, units, syntax)
        syntax_maps[revision] = {node.symbol_key: mapped[node.provider_node_id] for node in syntax.entities
                                if node.provider_node_id in mapped}
        entity_revision_ids[revision] = {ref.entity_revision_id for ref in mapped.values()}
        providers = {}
        for provider in (cbm, graph):
            raw = attach_symbol_keys(provider.analyze(units), syntax)
            admitted = validate_java_imports(raw, syntax)
            actual = register(service, current, units, admitted)
            assert actual and register(service, current, units, admitted) == actual
            # A provider's different locator is a new observation revision, not a new business identity.
            assert all(ref.entity_id == syntax_maps[revision][node.symbol_key].entity_id for node in admitted.entities
                       if (ref := actual.get(node.provider_node_id)) is not None)
            assert {ref.source_revision_id for ref in actual.values()} == {revision_ids[-1]}
            entity_revision_ids[revision].update(ref.entity_revision_id for ref in actual.values())
            providers[raw.provider] = {"version": raw.provider_version,
                "raw_projection_hash": projection_hash(raw), "admitted_projection_hash": projection_hash(admitted),
                "raw_entities": len(raw.entities), "raw_relationships": len(raw.relationships),
                "admitted_relationships": len(admitted.relationships), "registered_entities": len(actual),
                "observation_revision_differs_from_syntax": sum(
                    actual[node.provider_node_id].entity_revision_id != syntax_maps[revision][node.symbol_key].entity_revision_id
                    for node in admitted.entities if node.provider_node_id in actual),
                "observations": [asdict(item) for item in admitted.provider_observations],
                "native_snapshot_stats": [json.loads(item.response_json)["stats"] for item in raw.native_query_observations
                                          if item.operation == "sdk_snapshot"]}
        reports[revision] = {"source_revision_id": revision_ids[-1], "manifest_hash": artifact.manifest_hash,
            "source_files": len(units), "source_bytes": artifact.byte_count, "providers": providers}

    before, after = syntax_maps[BEFORE], syntax_maps[AFTER]
    shared = set(before) & set(after)
    assert shared and revision_ids[0] != revision_ids[1]
    assert all(before[key].entity_id == after[key].entity_id
               and before[key].entity_revision_id != after[key].entity_revision_id
               and before[key].source_revision_id != after[key].source_revision_id for key in shared)
    reads = 0
    with sessions() as session:
        assert set(session.scalars(select(CodeEntityIdentityRecord.entity_id))) == {
            ref.entity_id for group in syntax_maps.values() for ref in group.values()}
        for revision, expected in syntax_maps.items():
            records = session.scalars(select(CodeEntityRevisionRecord).where(
                CodeEntityRevisionRecord.source_revision_id == reports[revision]["source_revision_id"])).all()
            assert {row.entity_revision_id for row in records} == entity_revision_ids[revision]
            assert {row.entity_id for row in records} == {ref.entity_id for ref in expected.values()}
            evidence = session.scalars(select(SourceEvidenceRecord).where(
                SourceEvidenceRecord.source_revision_id == reports[revision]["source_revision_id"])).all()
            assert evidence
            for item in evidence:
                body = storage.get_bytes(item.object_ref)
                reads += 1
                assert "sha256:" + hashlib.sha256(body).hexdigest() == item.file_hash
                if item.precision == "exact":
                    assert text_digest("".join(source_lines(body.decode("utf-8"))[item.start_line - 1:item.end_line])) == item.snippet_hash
    assert not list(graph.config.cache_dir.iterdir())
    assert git_bytes(root, "status", "--porcelain") == original_status
    assert git("rev-parse", "HEAD") == AFTER and not git("status", "--porcelain")
    report = {"scope": "two_actual_document_only_revisions_native_provider_identity_and_evidence_not_code_lineage_gold",
        "revisions": reports, "shared_syntax_keys": len(shared), "shared_entity_ids_reused": True,
        "source_and_entity_revisions_distinct": True, "minio_evidence_reads": reads,
        "runtime_hash": graph.config.expected_runtime_hash, "provider_runs_per_revision": 1,
        "target_executed": False, "external_model_calls": 0, "production_provider_switched": False,
        "rename_delete_or_dynamic_call_verified": False, "gold_accuracy_or_p95_verified": False}
    path = os.environ.get("EXWEB_CODEGRAPH_HISTORY_REPORT")
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(report, indent=2) + "\n")
