"""Two real providers, pinned exweb, actual PG identities and private MinIO evidence."""
from collections import Counter
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
from time import monotonic
from uuid import uuid4

import pytest
from sqlalchemy import select

from apps.api.app.application.system_image.system_image_models import RawAssetRecord
from apps.api.app.domain.system_image.evidence import source_lines, text_digest
from apps.api.app.domain.system_image.code_index import CodeIndexCancelled
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage, ObjectStorageConfig
from apps.api.app.infrastructure.persistence.code_entity_models import CodeEntityIdentityRecord
from apps.api.app.infrastructure.persistence.source_evidence_models import SourceEvidenceRecord
from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import CodebaseMemoryCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.codegraph_sdk_code_intelligence import (
    CodeGraphSDKConfig, CodeGraphSDKCodeIntelligenceAdapter, codegraph_runtime_fingerprint,
)
from apps.api.app.infrastructure.system_image.code_identity_normalization import attach_symbol_keys
from apps.api.app.infrastructure.system_image import code_graph_process
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.tests.test_code_entity_registry import registry, pg_repo, register
from apps.api.tests.test_code_graph_enrichment import _config


REVISION = "fe5827f6b76f77ef34918d8b452ee823142332dc"


@pytest.fixture
def exweb_sdk_input(tmp_path):
    configured, runtime = os.environ.get("EXWEB_CODE_CONTROL_SOURCE"), os.environ.get("EXWEB_CODEGRAPH_RUNTIME")
    runtime_hash = os.environ.get("EXWEB_CODEGRAPH_RUNTIME_HASH")
    if not configured or not runtime or not runtime_hash:
        pytest.skip("set EXWEB_CODE_CONTROL_SOURCE, EXWEB_CODEGRAPH_RUNTIME and its reviewed EXWEB_CODEGRAPH_RUNTIME_HASH")
    root = Path(configured).resolve()
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()
    assert git("rev-parse", "HEAD") == REVISION and not git("status", "--porcelain")
    cfg = ObjectStorageConfig.from_env()
    assert cfg.endpoint and os.environ.get("NASUS_TEST_OBJECT_STORAGE_MODE") == "minio"
    storage = ObjectStorage(replace(cfg, local_dir=tmp_path / "objects"))
    reader = SourceIngestionService(object_storage=storage, snapshot_cache_dir=tmp_path / "restored")
    source = RawAssetRecord(id="source_" + uuid4().hex, project_id="probe_" + uuid4().hex,
        source_type="code", source_uri=str(root), ingestion_status="indexed")
    captured = reader._ingest_local_path(source, root, enforce_allowed_root=False, external_revision=REVISION)
    assert captured.snapshot.external_revision == REVISION and captured.inventory.enumeration_complete
    source = source.model_copy(update={"content_ref": captured.content_ref, "content_hash": captured.content_hash,
                                       "evidence_refs": captured.evidence_refs})
    units = reader.extract_text_units(source)
    assert len(units) == 126 and sum(unit.byte_count for unit in units) == 180868
    assert all(Path(unit.source_root) != root for unit in units)
    vendor_root = Path(runtime).resolve() / "node_modules/@colbymchenry"
    platforms = [path for path in vendor_root.glob("codegraph-*") if path.is_dir()]
    assert len(platforms) == 1
    assert codegraph_runtime_fingerprint(vendor_root / "codegraph", platforms[0]) == runtime_hash
    graph = CodeGraphSDKCodeIntelligenceAdapter(CodeGraphSDKConfig(vendor_root / "codegraph", platforms[0],
        tmp_path / "codegraph-cache", runtime_hash))
    return source, captured, units, storage, graph, git


def test_real_codegraph_and_cbm_exweb_identity_replacement(registry, tmp_path, exweb_sdk_input):
    source, captured, units, storage, graph, git = exweb_sdk_input
    service, snapshots, sessions = registry
    snapshots.record_capture(source, captured.snapshot, captured_at="2026-10-08T00:00:00Z")
    syntax = TreeSitterCodeIntelligenceAdapter().analyze(units)
    original = register(service, source, units, syntax)
    originals = {item.symbol_key: original[item.provider_node_id] for item in syntax.entities if item.provider_node_id in original}
    cbm = CodebaseMemoryCodeIntelligenceAdapter(replace(_config(Path(__file__).resolve().parents[3] / ".venv/bin/codebase-memory-mcp"),
        mode="required", cache_dir=tmp_path / "cbm-cache", timeout_seconds=180,
        max_entities=20000, max_relationships=50000, page_size=500))
    results, summaries = {}, {}
    for provider in (cbm, graph):
        started = monotonic()
        raw = provider.analyze(units)
        normalized = attach_symbol_keys(raw, syntax)
        mapped = register(service, source, units, normalized)
        assert mapped and all(item.entity_id == originals[node.symbol_key].entity_id
            for node in normalized.entities if (item := mapped.get(node.provider_node_id)) is not None)
        assert register(service, source, units, normalized) == mapped
        assert len({node.provider_node_id for node in normalized.entities}) == len(normalized.entities)
        ids = {node.provider_node_id for node in normalized.entities}
        assert all(edge.from_provider_node_id in ids and edge.to_provider_node_id in ids for edge in normalized.relationships)
        for name in ("ChatController", "DocumentUploadController", "ToolGatewayApplicationService"):
            node = next(node for node in normalized.entities if node.entity_kind == "class" and node.name == name)
            assert node.provider_node_id in mapped and node.symbol_key is not None
        # Replacing a provider may add revisions, never a second identity for an already canonical symbol.
        with sessions() as session:
            assert set(session.scalars(select(CodeEntityIdentityRecord.entity_id))) == {item.entity_id for item in original.values()}
        results[raw.provider] = normalized
        summaries[raw.provider] = {"version": raw.provider_version, "elapsed_seconds": round(monotonic() - started, 6),
            "raw_entities": len(raw.entities), "raw_relationships": len(raw.relationships),
            "canonical_status": dict(Counter(node.identity_status for node in normalized.entities)),
            "mapped_entities": len(mapped), "approximate_locations": sum(node.location_precision == "approximate" for node in normalized.entities),
            "projection": [asdict(item) for item in normalized.provider_observations]}
    first_hash = snapshot_digest({"entities": [asdict(item) for item in results["codegraph"].entities],
                                 "relationships": [asdict(item) for item in results["codegraph"].relationships]})
    for _ in range(2):
        repeated = attach_symbol_keys(graph.analyze(units), syntax)
        assert snapshot_digest({"entities": [asdict(item) for item in repeated.entities],
                                "relationships": [asdict(item) for item in repeated.relationships]}) == first_hash
        assert register(service, source, units, repeated) == register(service, source, units, results["codegraph"])
    other_source = source.model_copy(update={"project_id": "probe_" + uuid4().hex, "id": "source_" + uuid4().hex})
    snapshots.record_capture(other_source, captured.snapshot, captured_at="2026-10-08T00:00:00Z")
    other_syntax = register(service, other_source, units, syntax)
    other_result = attach_symbol_keys(graph.analyze(units), syntax)
    other_mapped = register(service, other_source, units, other_result)
    other_originals = {node.symbol_key: other_syntax[node.provider_node_id] for node in syntax.entities
                       if node.provider_node_id in other_syntax}
    assert other_mapped and all(ref.entity_id == other_originals[node.symbol_key].entity_id
        for node in other_result.entities if (ref := other_mapped.get(node.provider_node_id)) is not None)
    assert not {ref.entity_id for ref in original.values()} & {ref.entity_id for ref in other_syntax.values()}
    with sessions() as session:
        first_ids = set(session.scalars(select(CodeEntityIdentityRecord.entity_id).where(
            CodeEntityIdentityRecord.project_id == source.project_id)))
        second_ids = set(session.scalars(select(CodeEntityIdentityRecord.entity_id).where(
            CodeEntityIdentityRecord.project_id == other_source.project_id)))
        assert first_ids == {ref.entity_id for ref in original.values()}
        assert second_ids == {ref.entity_id for ref in other_syntax.values()} and not first_ids & second_ids
    assert list((tmp_path / "codegraph-cache").iterdir()) == []
    body_reads = 0
    with sessions() as session:
        evidence = session.scalars(select(SourceEvidenceRecord)).all()
        assert evidence
        for item in evidence:
            data = storage.get_bytes(item.object_ref)
            body_reads += 1
            assert "sha256:" + hashlib.sha256(data).hexdigest() == item.file_hash
            if item.precision == "exact":
                lines = source_lines(data.decode("utf-8"))
                assert text_digest("".join(lines[item.start_line - 1:item.end_line])) == item.snippet_hash
    assert git("rev-parse", "HEAD") == REVISION and not git("status", "--porcelain")
    keys = {name: {node.symbol_key for node in result.entities if node.symbol_key is not None} for name, result in results.items()}
    report = {"scope": "real_two_provider_identity_and_evidence_contract_not_quality_gold", "revision": REVISION,
        "source_files": len(units), "source_bytes": sum(unit.byte_count for unit in units), "runtime_hash": graph.config.expected_runtime_hash,
        "providers": summaries, "shared_canonical_keys": len(keys["codegraph"] & keys["codebase-memory"]),
        "codegraph_only_canonical_keys": len(keys["codegraph"] - keys["codebase-memory"]),
        "cbm_only_canonical_keys": len(keys["codebase-memory"] - keys["codegraph"]),
        "all_persisted_ids_reused": True, "minio_evidence_reads": body_reads, "codegraph_repetitions": 3,
        "projects_verified": 2, "cross_project_id_overlap": 0,
        "codegraph_repetitions_equal": True, "target_executed": False, "external_model_calls": 0,
        "production_provider_switched": False, "gold_accuracy_or_p95_verified": False}
    path = os.environ.get("EXWEB_CODEGRAPH_REPORT")
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(report, indent=2) + "\n")


def test_real_codegraph_exweb_cancel_reaps_live_native_group_and_cleans_private_snapshot(exweb_sdk_input, monkeypatch):
    source, captured, units, storage, graph, git = exweb_sdk_input
    processes, observed_live = [], []
    popen = code_graph_process.subprocess.Popen

    def track(*args, **kwargs):
        process = popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(code_graph_process.subprocess, "Popen", track)

    def cancel_when_live():
        for process in processes:
            if process.poll() is None:
                observed_live.append(process.pid)
                raise CodeIndexCancelled("controlled native probe cancellation")

    with pytest.raises(CodeIndexCancelled):
        graph.analyze_controlled(units, check_current=cancel_when_live)
    assert len(processes) == 1 and observed_live == [processes[0].pid]
    assert processes[0].poll() is not None and list(graph.config.cache_dir.iterdir()) == []
    with pytest.raises(ProcessLookupError):
        os.killpg(processes[0].pid, 0)
    assert codegraph_runtime_fingerprint(graph.config.package_path, graph.config.platform_path) == graph.config.expected_runtime_hash
    assert git("rev-parse", "HEAD") == REVISION and not git("status", "--porcelain")
    report = {"scope": "real_native_process_group_cancellation_not_workflow_restart_or_strong_kill_gc",
        "revision": REVISION, "source_files": len(units), "source_bytes": sum(unit.byte_count for unit in units),
        "runtime_hash": graph.config.expected_runtime_hash, "live_native_process_observed": True,
        "cancelled_process_reaped": True, "owned_process_group_absent": True, "private_session_removed": True,
        "target_executed": False, "external_model_calls": 0}
    path = os.environ.get("EXWEB_CODEGRAPH_CANCEL_REPORT")
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(report, indent=2) + "\n")
