from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .models import ContextRelationship, KnowledgeObject, QualityMetricSnapshot, RawAssetRecord


@dataclass
class ExtractedContext:
    objects: list[KnowledgeObject] = field(default_factory=list)
    relationships: list[ContextRelationship] = field(default_factory=list)
    metrics: list[QualityMetricSnapshot] = field(default_factory=list)


@dataclass(frozen=True)
class ContextAnchor:
    name: str
    object_type: str
    evidence_ref: str
    source_id: str


class ContextExtractionService:
    def extract(
        self,
        *,
        project_id: str,
        project_name: str,
        baseline_id: str,
        sources: list[RawAssetRecord],
        version_id: str | None,
        captured_at: str,
    ) -> ExtractedContext:
        indexed_sources = [source for source in sources if source.ingestion_status == "indexed"]
        core = KnowledgeObject(
            id=f"CTX-{self._stable_id(project_id, 'core')}",
            name=f"{project_name} Core",
            type="System",
            branch="Official",
            confidence="0.80",
            relations=[],
            evidence=[source.id for source in indexed_sources],
            freshness="just now",
        )
        objects: list[KnowledgeObject] = [core]
        relationships: list[ContextRelationship] = []
        anchors_by_type: dict[str, list[ContextAnchor]] = {"code": [], "us_doc": [], "test_asset": []}

        for source in indexed_sources:
            anchors = self._anchors_for_source(source)
            anchors_by_type[source.source_type].extend(anchors)
            for anchor in anchors[:30]:
                object_id = f"CTX-{self._stable_id(project_id, source.source_type, anchor.name, anchor.evidence_ref)}"
                relation_name = core.name
                obj = KnowledgeObject(
                    id=object_id,
                    name=anchor.name,
                    type=anchor.object_type,
                    branch="Official",
                    confidence="0.74",
                    relations=[relation_name],
                    evidence=[anchor.evidence_ref, source.id],
                    freshness="just now",
                )
                objects.append(obj)
                relationships.append(
                    ContextRelationship(
                        id=f"rel_{self._stable_id(project_id, object_id, core.id)}",
                        project_id=project_id,
                        baseline_id=baseline_id,
                        from_object_id=obj.id,
                        relationship_type=self._relationship_for_source(source.source_type),
                        to_object_id=core.id,
                        confidence=0.76,
                        source_refs=[source.id, anchor.evidence_ref],
                    )
                )

        metrics = self._metrics(
            project_id=project_id,
            baseline_id=baseline_id,
            version_id=version_id,
            captured_at=captured_at,
            code_count=len(anchors_by_type["code"]),
            us_count=len(anchors_by_type["us_doc"]),
            test_count=len(anchors_by_type["test_asset"]),
            source_ids=[source.id for source in indexed_sources],
        )
        core.relations = [item.name for item in objects[1:8]]
        return ExtractedContext(objects=objects, relationships=relationships, metrics=metrics)

    def _anchors_for_source(self, source: RawAssetRecord) -> list[ContextAnchor]:
        path = self._local_path(source.source_uri)
        if path is None or not path.exists():
            return []
        files = [path] if path.is_file() else [
            item
            for item in sorted(path.rglob("*"))
            if item.is_file() and not self._is_ignored_path(item)
        ]
        anchors: list[ContextAnchor] = []
        for file_path in files:
            relative = file_path.name if path.is_file() else str(file_path.relative_to(path))
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            evidence_ref = f"file:{relative}"
            if source.source_type == "code":
                anchors.extend(self._code_anchors(text, relative, source.id, evidence_ref))
            elif source.source_type == "us_doc":
                anchors.extend(self._us_anchors(text, relative, source.id, evidence_ref))
            else:
                anchors.extend(self._test_anchors(text, relative, source.id, evidence_ref))
        return anchors

    def _code_anchors(self, text: str, relative: str, source_id: str, evidence_ref: str) -> list[ContextAnchor]:
        if relative.endswith(".py"):
            try:
                parsed = ast.parse(text)
            except SyntaxError:
                return self._regex_code_anchors(text, relative, source_id, evidence_ref)
            anchors: list[ContextAnchor] = []
            for node in ast.walk(parsed):
                if isinstance(node, ast.ClassDef):
                    anchors.append(ContextAnchor(f"{node.name} ({relative})", "CodeClass", evidence_ref, source_id))
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    anchors.append(ContextAnchor(f"{node.name} ({relative})", "CodeFunction", evidence_ref, source_id))
            return anchors or [ContextAnchor(relative, "CodeModule", evidence_ref, source_id)]
        return self._regex_code_anchors(text, relative, source_id, evidence_ref)

    @staticmethod
    def _regex_code_anchors(text: str, relative: str, source_id: str, evidence_ref: str) -> list[ContextAnchor]:
        patterns = [
            r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)",
            r"\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)",
            r"\bdef\s+([A-Za-z_][A-Za-z0-9_]*)",
            r"\b(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\(",
            r"\bexport\s+function\s+([A-Za-z_][A-Za-z0-9_]*)",
        ]
        names: list[str] = []
        for pattern in patterns:
            names.extend(re.findall(pattern, text))
        return [
            ContextAnchor(f"{name} ({relative})", "CodeSymbol", evidence_ref, source_id)
            for name in dict.fromkeys(names)
        ] or [ContextAnchor(relative, "CodeModule", evidence_ref, source_id)]

    @staticmethod
    def _us_anchors(text: str, relative: str, source_id: str, evidence_ref: str) -> list[ContextAnchor]:
        anchors: list[ContextAnchor] = []
        for line in text.splitlines():
            stripped = line.strip(" #\t")
            if not stripped:
                continue
            if re.search(r"\bUS[-_ ]?\d+\b", stripped, re.IGNORECASE) or stripped.lower().startswith("as a "):
                anchors.append(ContextAnchor(stripped[:120], "USWorkItem", evidence_ref, source_id))
            elif line.startswith("#"):
                anchors.append(ContextAnchor(stripped[:120], "RequirementSection", evidence_ref, source_id))
        return anchors[:30] or [ContextAnchor(relative, "RequirementDocument", evidence_ref, source_id)]

    @staticmethod
    def _test_anchors(text: str, relative: str, source_id: str, evidence_ref: str) -> list[ContextAnchor]:
        names = re.findall(r"\bdef\s+(test_[A-Za-z0-9_]+)", text)
        names.extend(re.findall(r"\b(?:test|it)\s*\(\s*['\"]([^'\"]+)['\"]", text))
        return [
            ContextAnchor(f"{name} ({relative})", "TestCase", evidence_ref, source_id)
            for name in dict.fromkeys(names)
        ] or [ContextAnchor(relative, "TestAsset", evidence_ref, source_id)]

    @staticmethod
    def _metrics(
        *,
        project_id: str,
        baseline_id: str,
        version_id: str | None,
        captured_at: str,
        code_count: int,
        us_count: int,
        test_count: int,
        source_ids: list[str],
    ) -> list[QualityMetricSnapshot]:
        coverage = min(1.0, test_count / max(us_count, 1))
        automation = min(1.0, test_count / max(code_count, 1))
        return [
            QualityMetricSnapshot(
                id=f"metric_{project_id}_code",
                project_id=project_id,
                baseline_id=baseline_id,
                version_id=version_id,
                metric_group="code_quality",
                metrics={"code_symbols": code_count, "critical_paths": min(code_count, 5), "code_risk_score": max(10, 70 - code_count)},
                evidence_refs=source_ids,
                captured_at=captured_at,
            ),
            QualityMetricSnapshot(
                id=f"metric_{project_id}_us",
                project_id=project_id,
                baseline_id=baseline_id,
                version_id=version_id,
                metric_group="us_completion_quality",
                metrics={"requirements_count": us_count, "requirements_clarity": min(0.95, 0.55 + us_count * 0.08)},
                evidence_refs=source_ids,
                captured_at=captured_at,
            ),
            QualityMetricSnapshot(
                id=f"metric_{project_id}_tests",
                project_id=project_id,
                baseline_id=baseline_id,
                version_id=version_id,
                metric_group="test_quality",
                metrics={"test_count": test_count, "scenario_coverage": coverage, "automation_coverage": automation, "failed_runs": 0},
                evidence_refs=source_ids,
                captured_at=captured_at,
            ),
        ]

    @staticmethod
    def _relationship_for_source(source_type: str) -> str:
        if source_type == "code":
            return "implements"
        if source_type == "us_doc":
            return "impacts"
        return "covers"

    @staticmethod
    def _stable_id(*parts: str) -> str:
        raw = "|".join(parts)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16].upper()

    @staticmethod
    def _local_path(source_uri: str) -> Path | None:
        parsed = urlparse(source_uri)
        if parsed.scheme == "file":
            return Path(parsed.path).expanduser().resolve()
        if parsed.scheme:
            return None
        return Path(source_uri).expanduser().resolve()

    @staticmethod
    def _is_ignored_path(path: Path) -> bool:
        ignored_parts = {".git", "node_modules", "__pycache__", ".venv", "dist", "build"}
        return any(part in ignored_parts for part in path.parts)
