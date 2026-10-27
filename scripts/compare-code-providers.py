"""Reproducible same-snapshot CBM/CodeGraph probe, without executing target code.

Use the opt-in PG/MinIO integration test for persistence and evidence acceptance.
This command emits exploratory structural comparisons, never quality/gold scores.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.api.app.application.system_image.source_ports import code_projection_payload
from apps.api.app.application.system_image.system_image_models import RawAssetRecord
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.config.code_graph_config import CodeGraphConfig
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage, ObjectStorageConfig
from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import CodebaseMemoryCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.codegraph_sdk_code_intelligence import CodeGraphSDKConfig, CodeGraphSDKCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.code_identity_normalization import attach_symbol_keys
from apps.api.app.infrastructure.system_image.code_graph_observation_validation import validate_java_imports
from apps.api.app.infrastructure.system_image.git_source_connector import GitSourceConnector
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter


def comparison_projections(result, syntax):
    """Keep the raw typed projection and the existing production admission separate."""
    normalized = attach_symbol_keys(result, syntax)
    admitted = validate_java_imports(normalized, syntax)
    return normalized, admitted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--sdk-package", type=Path, required=True)
    parser.add_argument("--platform-package", type=Path, required=True)
    parser.add_argument("--runtime-hash", required=True, help="Previously inspected complete installed runtime fingerprint")
    parser.add_argument("--cbm-binary", type=Path, default=ROOT / ".venv/bin/codebase-memory-mcp")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=3, choices=range(1, 6))
    args = parser.parse_args()
    root, output = args.source_root.resolve(), args.output.resolve()
    source = RawAssetRecord(id="comparison-source", project_id="comparison-project", source_type="code",
        source_uri=args.repository, evidence_refs=["git:revision:" + args.revision])
    revision = GitSourceConnector._pinned_revision(source)
    def git(*params):
        return subprocess.run(["git", "-C", str(root), *params], check=True, capture_output=True, text=True).stdout.strip()
    if (git("rev-parse", "HEAD") != revision or git("status", "--porcelain")
            or git("config", "--get", "remote.origin.url") != args.repository):
        parser.error("the approved clean checkout, repository and exact revision must match")
    if root == output or root in output.parents:
        parser.error("output must be outside the target checkout")
    if output.exists():
        parser.error("output must be a new directory; previous comparison evidence is not overwritten")
    output.mkdir(parents=True, mode=0o700)
    storage = ObjectStorage(ObjectStorageConfig(None, "provider-comparison", None, None, "us-east-1", output / "objects"))
    reader = SourceIngestionService(object_storage=storage, snapshot_cache_dir=output / "restored")
    captured = reader._ingest_local_path(source, root, enforce_allowed_root=False, external_revision=revision)
    if not captured.snapshot or captured.snapshot.external_revision != revision or not captured.inventory.enumeration_complete:
        raise ValueError("comparison requires a complete fixed source snapshot")
    source = source.model_copy(update={"content_ref": captured.content_ref, "content_hash": captured.content_hash})
    units = reader.extract_text_units(source)
    syntax = TreeSitterCodeIntelligenceAdapter().analyze(units)
    adapters = (
        CodebaseMemoryCodeIntelligenceAdapter(CodeGraphConfig(mode="required", binary=str(args.cbm_binary.resolve()),
            index_mode="moderate", timeout_seconds=180, max_entities=20000, max_relationships=50000,
            page_size=500, cache_dir=output / "cbm-cache")),
        CodeGraphSDKCodeIntelligenceAdapter(CodeGraphSDKConfig(args.sdk_package.resolve(), args.platform_package.resolve(),
            output / "codegraph-cache", args.runtime_hash)),
    )
    reports, keys = {}, {}
    for adapter in adapters:
        runs, signatures, admitted_signatures = [], [], []
        for number in range(args.repetitions):
            started = monotonic()
            normalized, admitted = comparison_projections(adapter.analyze(units), syntax)
            projection = code_projection_payload(normalized)
            admitted_projection = code_projection_payload(admitted)
            signatures.append(snapshot_digest(projection))
            admitted_signatures.append(snapshot_digest(admitted_projection))
            runs.append(round(monotonic() - started, 6))
            (output / f"{adapter.provider}-{number + 1}.json").write_text(
                json.dumps({"projection": projection, "admitted_projection": admitted_projection,
                    "native_query_observations": [asdict(item) for item in normalized.native_query_observations]},
                    ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        keys[adapter.provider] = {node.symbol_key for node in normalized.entities if node.symbol_key is not None}
        reports[adapter.provider] = {"version": normalized.provider_version, "repetitions": args.repetitions,
            "stable_projection": len(set(signatures)) == 1, "projection_hashes": signatures, "elapsed_seconds": runs,
            "admitted_stable_projection": len(set(admitted_signatures)) == 1, "admitted_projection_hashes": admitted_signatures,
            "entities": len(normalized.entities), "relationships": len(normalized.relationships),
            "admitted_relationships": len(admitted.relationships),
            "identity_status": dict(Counter(node.identity_status for node in normalized.entities)),
            "provider_observations": [asdict(item) for item in normalized.provider_observations],
            "admitted_provider_observations": [asdict(item) for item in admitted.provider_observations]}
    if git("rev-parse", "HEAD") != revision or git("status", "--porcelain"):
        raise ValueError("target checkout changed during the comparison")
    report = {"scope": "same_snapshot_structural_comparison_not_business_gold", "repository": args.repository, "revision": revision,
        "manifest_hash": captured.snapshot.manifest_hash, "source_files": len(units), "source_bytes": sum(unit.byte_count for unit in units),
        "runtime_hash": args.runtime_hash, "providers": reports,
        "canonical_key_intersection": len(keys["codegraph"] & keys["codebase-memory"]),
        "codegraph_only_canonical_keys": len(keys["codegraph"] - keys["codebase-memory"]),
        "cbm_only_canonical_keys": len(keys["codebase-memory"] - keys["codegraph"]),
        "target_executed": False, "external_model_calls": 0, "production_provider_switched": False,
        "persisted_identity_verified": False, "quality_gold_or_p95_verified": False}
    report["stability_policy"] = "raw_typed_projection_must_repeat;_admission_does_not_hide_provider_instability"
    (output / "comparison.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if all(item["stable_projection"] for item in reports.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
