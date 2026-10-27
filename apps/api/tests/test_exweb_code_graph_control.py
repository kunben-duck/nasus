"""Opt-in fixed exweb/native-provider probe; no dependency install or target execution."""
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

import pytest

from apps.api.app.application.system_image.system_image_models import RawAssetRecord
from apps.api.app.domain.system_image.code_provider import projection_payload, validate_projection_payload
from apps.api.app.domain.system_image.code_index import CodeIndexCancelled
from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import CodebaseMemoryCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.code_graph_process import CodeGraphProcessRunner
from apps.api.app.infrastructure.system_image.composite_code_intelligence import CompositeCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.tests.test_code_graph_enrichment import _config


REVISION = "fe5827f6b76f77ef34918d8b452ee823142332dc"


def test_fixed_exweb_native_analysis_uses_archived_snapshot_and_execution_checks(tmp_path):
    configured = os.environ.get("EXWEB_CODE_CONTROL_SOURCE")
    if not configured:
        pytest.skip("set EXWEB_CODE_CONTROL_SOURCE to the approved fixed exweb checkout")
    root = Path(configured).resolve()
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    clean = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], check=True, capture_output=True, text=True).stdout
    assert head == REVISION and not clean
    from apps.api.app.infrastructure.storage.object_storage import ObjectStorage, ObjectStorageConfig
    storage = ObjectStorage(ObjectStorageConfig(None, "probe", None, None, "us-east-1", tmp_path / "objects"))
    reader = SourceIngestionService(object_storage=storage, snapshot_cache_dir=tmp_path / "restored")
    source = RawAssetRecord(id="source_" + uuid4().hex, project_id="probe_" + uuid4().hex,
        source_type="code", source_uri=str(root), ingestion_status="indexed")
    capture = reader._ingest_local_path(source, root, enforce_allowed_root=False, external_revision=REVISION)
    assert capture.snapshot.external_revision == REVISION
    source = source.model_copy(update={"content_ref": capture.content_ref, "content_hash": capture.content_hash,
                                       "evidence_refs": capture.evidence_refs})
    units = reader.extract_text_units(source)
    assert units and all(Path(unit.source_root) != root for unit in units)
    config = replace(_config(Path(__file__).resolve().parents[3] / ".venv/bin/codebase-memory-mcp"),
        mode="required", cache_dir=tmp_path / "provider-cache", timeout_seconds=180,
        max_entities=20000, max_relationships=50000, page_size=500)
    class NativeProbeRunner(CodeGraphProcessRunner):
        def __init__(self):
            self.roots = []
            self.caches = []
            self.tools = []

        def run(self, args, **kwargs):
            self.roots.append(Path(kwargs["env"]["CBM_ALLOWED_ROOT"]))
            self.caches.append(Path(kwargs["env"]["CBM_CACHE_DIR"]))
            self.tools.append(args[2] if len(args) > 2 else "--version")
            output = super().run(args, **kwargs)
            assert output.returncode == 0, {"tool": args[2] if len(args) > 2 else "version", "stderr": output.stderr}
            return output

    native_runner = NativeProbeRunner()
    adapter = CompositeCodeIntelligenceAdapter(TreeSitterCodeIntelligenceAdapter(),
        CodebaseMemoryCodeIntelligenceAdapter(config, process_runner=native_runner), mode="required")
    checks = []
    started = time.monotonic()

    def check_current():
        checks.append(time.monotonic())
        if time.monotonic() - started > 180:
            raise TimeoutError("static probe budget exceeded")

    result = adapter.analyze_controlled(units, check_current=check_current)
    projection = projection_payload(result.provider_observations)
    validate_projection_payload(projection)
    assert projection["status"] == "partial"
    assert len(projection["providers"]) == 2
    native_projection = projection["providers"][1]
    assert native_projection["relationship_enumeration"] == "complete"
    assert native_projection["capabilities"]["language_coverage"] == "unknown"
    assert native_projection["capabilities"]["operations"] == ["capabilities", "analyze", "analyze_controlled"]
    assert len(checks) > len(units)
    assert not any("truncated" in item for item in result.evidence_refs)
    assert len(result.entities) > 500 and result.relationships
    names = {item.name for item in result.entities}
    assert {"ChatController", "DocumentUploadController", "ToolGatewayApplicationService"} <= names
    assert all(item.relative_path in {unit.relative_path for unit in units} for item in result.entities)
    ids = {item.provider_node_id for item in result.entities}
    assert all(edge.from_provider_node_id in ids and edge.to_provider_node_id in ids for edge in result.relationships)
    assert not any(item.status == "failed" for item in result.file_analyses)

    def normalized_facts(value):
        return {"entities": sorted((asdict(item) for item in value.entities), key=lambda item: item["provider_node_id"]),
                "relationships": sorted((asdict(item) for item in value.relationships),
                    key=lambda item: (item["from_provider_node_id"], item["relationship_kind"], item["to_provider_node_id"]))}

    before = normalized_facts(result)
    for repetition in range(2):
        repeated = adapter.analyze_controlled(units, check_current=check_current)
        assert projection_payload(repeated.provider_observations) == projection
        after = normalized_facts(repeated)
        first_by_id = {item["provider_node_id"]: item for item in before["entities"]}
        second_by_id = {item["provider_node_id"]: item for item in after["entities"]}
        changed = [(first_by_id[key], second_by_id[key]) for key in first_by_id.keys() & second_by_id.keys()
                   if first_by_id[key] != second_by_id[key]]
        edge_key = lambda item: (item["from_provider_node_id"], item["relationship_kind"], item["to_provider_node_id"])
        before_edges = {edge_key(item): item for item in before["relationships"]}
        after_edges = {edge_key(item): item for item in after["relationships"]}
        assert after == before, {"repetition": repetition + 2, "entity_counts": [len(first_by_id), len(second_by_id)],
            "missing": [first_by_id[key] for key in sorted(first_by_id.keys() - second_by_id.keys())[:3]],
            "new": [second_by_id[key] for key in sorted(second_by_id.keys() - first_by_id.keys())[:3]],
            "changed": changed[:3], "relationship_counts": [len(before["relationships"]), len(after["relationships"])],
            "changed_edges": [(before_edges[key], after_edges[key]) for key in before_edges.keys() & after_edges.keys()
                              if before_edges[key] != after_edges[key]][:3],
            "missing_edge_count": len(before_edges.keys() - after_edges.keys()),
            "new_edge_count": len(after_edges.keys() - before_edges.keys())}
    assert len(set(native_runner.roots)) == 3 and len(set(native_runner.caches)) == 3
    assert all(not path.exists() for path in native_runner.roots + native_runner.caches)
    native = CodebaseMemoryCodeIntelligenceAdapter(config, process_runner=native_runner)
    tool_start = len(native_runner.tools)
    with native.open_index(units, check_current=check_current) as prepared:
        assert prepared.status().state == "ready" and prepared.status().entity_count is None
        entity_pages, entities, cursor = 0, [], None
        while True:
            page = prepared.entities(cursor=cursor, limit=100)
            entity_pages += 1
            entities.extend(page.items)
            assert page.enumeration == "unknown"
            cursor = page.next_cursor
            if cursor is None:
                break
        assert len(entities) == len({item.provider_node_id for item in entities}) == page.normalized_count
        relation_pages, edges, cursor = 0, [], None
        while True:
            page = prepared.relations(cursor=cursor, limit=100)
            relation_pages += 1
            edges.extend(page.items)
            cursor = page.next_cursor
            if cursor is None:
                break
        assert len(edges) == page.normalized_count
        chat = next(item for item in entities if item.name == "ChatController" and item.location_precision == "exact")
        assert prepared.locate(chat.provider_node_id) == chat
        impact = prepared.impact([chat.provider_node_id], max_entities=500)
        assert impact.complete is False and impact.snapshot_hash == prepared.status().snapshot_hash
        prepared_evidence = {"lifetime": prepared.status().lifetime, "state": prepared.status().state,
            "snapshot_hash": prepared.status().snapshot_hash, "entity_count": len(entities),
            "relationship_count": len(edges), "entity_pages": entity_pages, "relationship_pages": relation_pages,
            "projection_status": prepared.status().projection_status, "located_symbol": chat.name,
            "location_precision": chat.location_precision, "impact_complete": impact.complete,
            "impact_candidate_count": len(impact.candidate_ids), "impact_truncated": impact.truncated}
        assert native_runner.tools[tool_start:].count("index_repository") == 1
        prepared_evidence["native_index_builds"] = 1
        prepared_evidence["scope"] = "native_candidates_before_composite_validation_not_accepted_knowledge"
        assert prepared.cancel().state == "cancellation_requested"
        with pytest.raises(CodeIndexCancelled):
            prepared.entities(limit=100)
        prepared_evidence["cancelled_reads_blocked"] = True
    assert prepared.status().state == "closed"
    assert len(set(native_runner.roots)) == 4 and len(set(native_runner.caches)) == 4
    assert all(not path.exists() for path in native_runner.roots + native_runner.caches)
    assert "code-graph-routes:unverified-synthetic" in result.evidence_refs
    primary_routes = [item for item in result.entities if item.entity_kind == "api_route" and item.provider_node_id.startswith("tree-sitter:")]
    assert len(primary_routes) == 13
    assert all(item.location_precision == "exact" for item in primary_routes)
    assert "code-graph-calls:unverified-resolution" in result.evidence_refs
    assert "code-graph-imports:unverified-java-target" in result.evidence_refs
    header_path = "src/main/java/com/huawei/finance/front/one/infrastructure/security/HeaderAuthContextProvider.java"
    by_id = {item.provider_node_id: item for item in result.entities}
    assert not any(by_id[edge.from_provider_node_id].relative_path == header_path
        and by_id[edge.to_provider_node_id].name == "stream" for edge in result.relationships)
    normalized_digest = hashlib.sha256(json.dumps(normalized_facts(result), sort_keys=True,
        ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    report = {"scope": "archived_local_snapshot_native_code_graph_transport_not_business_acceptance",
        "repository": "https://github.com/kunben-duck/exweb.git", "revision": REVISION,
        "manifest_hash": capture.snapshot.manifest_hash, "content_hash": capture.content_hash,
        "file_count": capture.file_count, "text_units": len(units), "provider": result.provider,
        "provider_version": result.provider_version, "entities": len(result.entities),
        "relationships": len(result.relationships), "control_checks": len(checks),
        "duration_seconds": round(time.monotonic() - started, 3), "external_model_called": False,
        "target_executed": False, "authority": "probe_budget_not_user_execution_grant"}
    report["provider_projection"] = projection
    report["prepared_native_index"] = prepared_evidence
    report.update({"analyses": 3, "normalized_facts_digest": "sha256:" + normalized_digest,
                   "identity_stable_with_new_private_roots": True, "private_snapshots_and_indexes_removed": True,
                   "syntax_verified_routes": len(primary_routes),
                   "provider_route_gap": [item for item in result.evidence_refs if item.startswith("code-graph-routes:")],
                   "provider_call_gap": [item for item in result.evidence_refs if item.startswith("code-graph-calls:")],
                   "provider_import_gap": [item for item in result.evidence_refs if item.startswith("code-graph-imports:")]})
    report["relationship_query_counts"] = [item for item in result.evidence_refs if item.startswith("code-graph-relationship-queries:")]
    destination = os.environ.get("EXWEB_CODE_CONTROL_REPORT")
    if destination:
        Path(destination).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
