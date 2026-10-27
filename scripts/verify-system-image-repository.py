"""Probe a pinned repository using Nasus ingestion and a real code-graph adapter.

This is a structural integration probe, not business-link or release acceptance.
It never installs dependencies or executes code from the inspected repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.api.app.application.system_image.system_image_models import RawAssetRecord
from apps.api.app.application.system_image.code_analysis_inventory import build_code_analysis_inventory
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.config.code_graph_config import CodeGraphConfig
from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import (
    CodebaseMemoryCodeIntelligenceAdapter,
)
from apps.api.app.infrastructure.system_image.git_source_connector import GitSourceConnector
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.code_identity_normalization import attach_symbol_keys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--expect-symbol", action="append", default=[])
    parser.add_argument("--structure-gold", type=Path)
    parser.add_argument("--binary", type=Path, default=ROOT / ".venv/bin/codebase-memory-mcp")
    parser.add_argument("--runtime-dir", type=Path, default=ROOT / ".nasus/validation/system-image")
    args = parser.parse_args()
    parsed = urlsplit(args.repository)
    if parsed.scheme != "https" or not parsed.hostname:
        parser.error("a source-authorized HTTPS repository is required")
    namespace = hashlib.sha256(args.repository.encode()).hexdigest()[:20]
    source = RawAssetRecord(
        id=f"source_{namespace}",
        project_id=f"probe_{namespace}",
        source_type="code",
        source_uri=args.repository,
        ingestion_status="indexed",
        evidence_refs=[f"git:revision:{args.revision}"],
    )
    # Validate before constructing an output path or invoking any external tool.
    revision = GitSourceConnector._pinned_revision(source)
    runtime_dir = args.runtime_dir.resolve()
    connector = GitSourceConnector(
        cache_dir=runtime_dir / "sources",
        allowed_schemes={"https"},
        allowed_hosts={parsed.hostname},
    )
    started = monotonic()
    snapshot = connector.materialize(source, refresh=False)
    ingestion = SourceIngestionService(connectors=[connector], snapshot_cache_dir=runtime_dir / "archived-sources")
    captured = ingestion.ingest(source)
    if captured.snapshot is None or captured.snapshot.external_revision != revision:
        raise RuntimeError("repository ref changed before capture; retry with the approved revision")
    if captured.inventory is None or captured.inventory.status != "complete":
        raise RuntimeError("repository acquisition did not produce a complete raw inventory")
    inventory_report = ingestion.snapshots.storage.get_json(captured.inventory.report_ref)
    manifest = ingestion.snapshots.storage.get_json(captured.snapshot.manifest_ref)
    source = source.model_copy(update={
        "content_hash": captured.content_hash, "content_ref": captured.content_ref,
        "evidence_refs": captured.evidence_refs,
    })
    units = ingestion.extract_text_units(source)
    if not units:
        raise RuntimeError("repository produced no text units")
    adapter = CodebaseMemoryCodeIntelligenceAdapter(CodeGraphConfig(
        mode="required",
        binary=str(args.binary.resolve()),
        index_mode="moderate",
        timeout_seconds=180.0,
        max_entities=20_000,
        max_relationships=50_000,
        page_size=500,
        cache_dir=runtime_dir / "provider-cache",
    ))
    result = adapter.analyze(units)
    syntax_result = TreeSitterCodeIntelligenceAdapter().analyze(units)
    analysis = build_code_analysis_inventory(manifest, syntax_result, units)
    identity_result = attach_symbol_keys(result, syntax_result)
    connector.materialize(source, refresh=False)
    paths = {unit.relative_path for unit in units}
    ids = {entity.provider_node_id for entity in result.entities}
    symbols = {entity.name for entity in result.entities}
    checks = {
        "fixed_revision": snapshot.revision == revision,
        "raw_inventory_complete": captured.inventory.enumeration_complete,
        "raw_inventory_pinned": manifest.get("inventory_hash") == captured.inventory.report_hash,
        "all_raw_files_accounted": analysis["summary"]["file_count"] == captured.snapshot.file_count,
        "no_syntax_failures": analysis["summary"]["failed"] == 0,
        "has_entities": bool(result.entities),
        "has_relationships": bool(result.relationships),
        "source_scope": all(entity.relative_path in paths for entity in result.entities),
        "relation_endpoints": all(
            edge.from_provider_node_id in ids and edge.to_provider_node_id in ids
            for edge in result.relationships
        ),
        "not_truncated": not any("truncated" in ref for ref in result.evidence_refs),
    }
    structure_gold = None
    if args.structure_gold:
        gold = json.loads(args.structure_gold.read_text())
        if (gold["repository"], gold["revision"]) != (args.repository, revision):
            raise ValueError("structural gold belongs to a different source revision")
        for controller in gold["controllers"]:
            path = gold["source_root"] + controller["file"]
            actual = {(item.method, item.route_path, item.start_line) for item in syntax_result.structural_facts
                      if item.relative_path == path and item.kind == "route" and item.status == "observed"}
            expected = {(item["method"], item["path"], item["line"]) for item in controller["routes"]}
            checks[f"controller_routes:{controller['file']}"] = actual == expected
        structure_gold = {"hash": snapshot_digest(gold), "scope": gold["scope"],
                          "controllers": len(gold["controllers"]),
                          "routes": sum(len(item["routes"]) for item in gold["controllers"])}
    for symbol in args.expect_symbol:
        checks[f"symbol:{symbol}"] = symbol in symbols
        checks[f"exact_symbol:{symbol}"] = any(
            entity.name == symbol
            and "code-graph-location:exact" in entity.evidence_refs
            for entity in result.entities
        )
        checks[f"canonical_class:{symbol}"] = any(
            entity.name == symbol and entity.entity_kind == "class" and entity.symbol_key is not None
            for entity in identity_result.entities
        )
    approximate = sum(
        "code-graph-location:approximate" in entity.evidence_refs
        for entity in result.entities
    )
    report = {
        "scope": "structural_integration_only",
        "status": "passed" if all(checks.values()) else "failed",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "repository": args.repository,
        "revision": snapshot.revision,
        "snapshot_path": str(snapshot.local_path),
        "raw_manifest_ref": captured.snapshot.manifest_ref,
        "raw_manifest_hash": captured.snapshot.manifest_hash,
        "source_id": source.id,
        "project_id": source.project_id,
        "source_snapshot": asdict(captured.snapshot),
        "source_inventory": asdict(captured.inventory),
        "code_analysis": {"report_hash": snapshot_digest(analysis), "summary": analysis["summary"],
                          "language_status_counts": dict(Counter(f"{item['language']}:{item['status']}" for item in analysis["files"])),
                          "fact_kind_counts": dict(Counter(item["kind"] for item in analysis["facts"])),
                          "gold": structure_gold},
        "inventory_status_counts": dict(Counter(item["status"] for item in inventory_report["inventory"]["entries"])),
        "provider": result.provider,
        "provider_version": result.provider_version,
        "launcher_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
        "text_files": len(units),
        "text_bytes": sum(unit.byte_count for unit in units),
        "languages": dict(Counter(entity.language for entity in result.entities)),
        "entities": len(result.entities),
        "relationships": len(result.relationships),
        "approximate_locations": approximate,
        "canonical_identity_status": dict(Counter(entity.identity_status for entity in identity_result.entities)),
        "duration_seconds": round(monotonic() - started, 3),
        "checks": checks,
        "limitations": [
            "Raw acquisition inventory is not parser/language coverage or a localization-accuracy benchmark.",
            "Parser success is syntax coverage, not semantic completeness; path hints are not parsed facts.",
            "Java annotation observations do not resolve all framework configuration, inherited or functional routes.",
            "Excluded directory entries are pruned boundaries, not an enumeration of their descendants.",
            "No business assertions, cross-source links, autonomous build or run acceptance verified.",
            "Provider launcher digest is not the digest of every transitive runtime asset.",
            "Canonical matching keys are not persisted UUIDs; unsupported or ambiguous symbols remain unresolved.",
        ],
    }
    output_dir = runtime_dir / "reports" / namespace / str(revision)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "normalized-graph.json").write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    (output_dir / "code-analysis.json").write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    (output_dir / "probe.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps({**report, "report_path": str(output_dir / "probe.json")}, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
