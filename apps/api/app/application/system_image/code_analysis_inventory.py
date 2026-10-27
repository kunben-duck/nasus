from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from pathlib import PurePosixPath
from typing import Protocol, Sequence

from ...domain.system_image.code_analysis import CodeStructureFact
from ...domain.system_image.evidence import source_lines, text_digest
from ...domain.system_image.source_snapshots import snapshot_digest
from ...domain.system_image.code_provider import projection_payload
from .source_ports import CodeIntelligenceResult, SourceTextUnit
from .system_image_models import RawAssetRecord


class CodeAnalysisInventoryPort(Protocol):
    def record(self, source: RawAssetRecord, result: CodeIntelligenceResult,
               units: Sequence[SourceTextUnit], *, captured_at: str) -> str | None: ...


def build_code_analysis_inventory(manifest: dict, result: CodeIntelligenceResult,
                                  units: Sequence[SourceTextUnit]) -> dict:
    files = {item["path"]: item for item in manifest["files"]}
    by_path = {item.relative_path: item for item in units}
    analyses = {item.relative_path: item for item in result.file_analyses}
    if len(by_path) != len(units) or len(analyses) != len(result.file_analyses):
        raise ValueError("duplicate code analysis path")
    if not by_path.keys() <= files.keys() or not analyses.keys() <= by_path.keys():
        raise ValueError("code analysis is outside the source snapshot")
    for path, unit in by_path.items():
        if unit.content_hash != files[path]["content_hash"] or unit.byte_count != files[path]["byte_count"]:
            raise ValueError("code analysis source fingerprint mismatch")
    observations = []
    facts = list(result.structural_facts)
    for path, file in sorted(files.items()):
        analysis = analyses.get(path)
        if analysis is not None:
            observation = asdict(analysis)
        else:
            observation = {
                "relative_path": path, "language": PurePosixPath(path).suffix.lstrip(".") or "unknown",
                "status": "not_analyzed", "reason": "provider_not_reported" if path in by_path else "text_not_extracted",
                "parser_version": "unavailable", "syntax_errors": 0, "rules": (),
            }
        observations.append({**observation, "source_file_hash": file["content_hash"], "byte_count": file["byte_count"]})
        name = PurePosixPath(path).name
        if (name in {"pom.xml", "package.json", "pyproject.toml", "go.mod", "Dockerfile", "Makefile"}
                or PurePosixPath(path).suffix.lower() in {".yaml", ".yml", ".properties", ".toml", ".ini"}):
            facts.append(CodeStructureFact(path, "configuration_boundary", path, 1, 1, "path.configuration-candidate.v1", "path_hint"))
        if name.startswith("test_") or name.endswith(("Test.java", "Tests.java", "_test.go", ".test.ts", ".spec.ts", ".test.js", ".spec.js")):
            facts.append(CodeStructureFact(path, "test_entrypoint", path, 1, 1, "path.test-candidate.v1", "path_hint"))
    unique = {}
    for fact in facts:
        if fact.relative_path not in files:
            raise ValueError("structural observation is outside the source snapshot")
        if fact.status != "path_hint":
            analysis = analyses.get(fact.relative_path)
            unit = by_path.get(fact.relative_path)
            if (analysis is None or analysis.status != "parsed" or unit is None
                    or fact.end_line > unit.text.count("\n") + 1):
                raise ValueError("structural observation lacks successful parser evidence")
        payload = {**asdict(fact), "source_file_hash": files[fact.relative_path]["content_hash"]}
        if fact.status != "path_hint":
            lines = source_lines(by_path[fact.relative_path].text)
            # Every composed route keeps the class-level support as well as
            # the method locator; a path hint never claims a parsed snippet.
            payload["snippet_hash"] = text_digest("".join(lines[fact.start_line - 1:fact.end_line]))
            payload["supporting_spans"] = []
            for span in fact.supporting_spans:
                if span.end_line > len(lines):
                    raise ValueError("supporting source span exceeds archived text")
                payload["supporting_spans"].append({**asdict(span), "snippet_hash": text_digest(
                    "".join(lines[span.start_line - 1:span.end_line]),
                )})
        unique[snapshot_digest(payload)] = payload
    if len(unique) > 50000:
        raise ValueError("structural inventory exceeds observation limit")
    counts = Counter(item["status"] for item in observations)
    payload = {
        "schema": "nasus.code-analysis.v1", "algorithm": "nasus.structure-inventory.v1",
        "project_id": manifest["project_id"], "source_id": manifest["source_id"],
        "source_manifest_hash": snapshot_digest(manifest), "external_revision": manifest["external_revision"],
        "provider": result.provider, "provider_version": result.provider_version,
        "scope": "static_observations_not_business_or_runtime_acceptance",
        "raw_inventory_available": "inventory" in manifest,
        "files": observations, "facts": [unique[key] for key in sorted(unique)],
        "summary": {"file_count": len(files), "parsed": counts["parsed"], "failed": counts["failed"],
                    "unsupported": counts["unsupported"], "not_analyzed": counts["not_analyzed"],
                    "fact_count": len(unique)},
    }
    if result.provider_observations:
        payload.update(schema="nasus.code-analysis.v2", projection=projection_payload(result.provider_observations))
    return payload
