from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Sequence

from ...application.system_image.source_ports import (
    CodeEntityCandidate,
    CodeEntityKind,
    CodeIntelligenceResult,
    CodeRelationshipCandidate,
    CodeRelationshipKind,
    SourceTextUnit,
)
from ..config.code_graph_config import CodeGraphConfig


class CodebaseMemoryError(RuntimeError):
    """Raised when the external graph cannot provide a trustworthy projection."""


@dataclass(frozen=True)
class _ExternalNode:
    provider_id: str
    provider_qualified_name: str
    qualified_name: str
    relative_path: str


@dataclass(frozen=True)
class _MappedEntity:
    candidate: CodeEntityCandidate
    provider_qualified_name: str


_LABEL_KIND: dict[str, CodeEntityKind] = {
    "Package": "module",
    "Folder": "module",
    "File": "module",
    "Module": "module",
    "Class": "class",
    "Interface": "interface",
    "Enum": "enum",
    "Function": "function",
    "Method": "method",
    "Route": "api_route",
    "Resource": "dependency",
}

_RELATION_KIND: dict[str, tuple[CodeRelationshipKind, bool]] = {
    "CONTAINS_PACKAGE": ("belongs_to", True),
    "CONTAINS_FOLDER": ("belongs_to", True),
    "CONTAINS_FILE": ("belongs_to", True),
    "DEFINES": ("belongs_to", True),
    "DEFINES_METHOD": ("belongs_to", True),
    "MEMBER_OF": ("belongs_to", False),
    "IMPORTS": ("depends_on", False),
    "IMPLEMENTS": ("depends_on", False),
    "USES_TYPE": ("depends_on", False),
    "USAGE": ("depends_on", False),
    "CONFIGURES": ("depends_on", False),
    "CALLS": ("calls", False),
    "CALL_REFERENCE": ("calls", False),
    "HTTP_CALLS": ("calls", False),
    "ASYNC_CALLS": ("calls", False),
    "HANDLES": ("exposes", False),
}

_LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".kt": "kotlin",
    ".swift": "swift",
}


class CodebaseMemoryCodeIntelligenceAdapter:
    """Anti-corruption adapter over Codebase Memory's documented CLI surface.

    The provider owns its graph database. Nasus only consumes structured CLI
    results and maps them into provider-neutral candidates.
    """

    provider = "codebase-memory"

    def __init__(self, config: CodeGraphConfig) -> None:
        self.config = config
        self._lock = RLock()
        self._version: str | None = None

    def analyze(self, units: Sequence[SourceTextUnit]) -> CodeIntelligenceResult:
        root = self._repository_root(units)
        allowed_paths = {self._safe_relative_path(unit.relative_path) for unit in units}
        self._assert_source_snapshot(root, units)
        project_namespace = self._project_name(root)

        with self._lock:
            version = self._probe_version()
            index_result = self._call(
                "index_repository",
                {
                    "repo_path": str(root),
                    "name": project_namespace,
                    "mode": self.config.index_mode,
                    "persistence": False,
                },
                allowed_root=root,
            )
            status = self._required_string(index_result, "status")
            if status not in {"indexed", "degraded"}:
                raise CodebaseMemoryError("code graph indexing did not complete")
            provider_project = self._provider_project_id(index_result)

            entities, nodes = self._load_entities(
                project=provider_project,
                provider_namespace=project_namespace,
                root=root,
                allowed_paths=allowed_paths,
            )
            relationships = self._load_relationships(
                project=provider_project,
                nodes=nodes,
                allowed_paths=allowed_paths,
            )

        evidence = [
            "code-graph:codebase-memory",
            f"code-graph-project:{project_namespace}",
            f"code-graph-index:{status}",
            f"code-graph-entities:{len(entities)}",
            f"code-graph-relationships:{len(relationships)}",
        ]
        if len(entities) >= self.config.max_entities:
            evidence.append("code-graph-entities:truncated")
        if len(relationships) >= self.config.max_relationships:
            evidence.append("code-graph-relationships:truncated")
        return CodeIntelligenceResult(
            provider=self.provider,
            provider_version=version,
            entities=tuple(entities),
            relationships=tuple(relationships),
            evidence_refs=tuple(evidence),
        )

    def diagnostics(self) -> dict[str, str]:
        try:
            version = self._probe_version()
        except CodebaseMemoryError:
            return {
                "graph_backend": self.provider,
                "graph_status": "unavailable",
                "graph_mode": self.config.mode,
            }
        return {
            "graph_backend": self.provider,
            "graph_status": "ready",
            "graph_mode": self.config.mode,
            "graph_version": version,
            "graph_index_mode": self.config.index_mode,
        }

    def _load_entities(
        self,
        *,
        project: str,
        provider_namespace: str,
        root: Path,
        allowed_paths: set[str],
    ) -> tuple[list[CodeEntityCandidate], dict[tuple[str, str], _ExternalNode]]:
        entities: list[CodeEntityCandidate] = []
        nodes: dict[tuple[str, str], _ExternalNode] = {}
        offset = 0
        while len(entities) < self.config.max_entities:
            payload = self._call(
                "search_graph",
                {
                    "project": project,
                    "name_pattern": ".*",
                    "limit": self.config.page_size,
                    "offset": offset,
                    "format": "json",
                },
            )
            page, count = self._entity_page(
                payload=payload,
                provider_namespace=provider_namespace,
                provider_project=project,
                root=root,
                allowed_paths=allowed_paths,
            )
            for mapped in page:
                if len(entities) >= self.config.max_entities:
                    break
                entity = mapped.candidate
                entities.append(entity)
                node = _ExternalNode(
                    entity.provider_node_id,
                    mapped.provider_qualified_name,
                    entity.qualified_name,
                    entity.relative_path,
                )
                nodes[(mapped.provider_qualified_name, entity.relative_path)] = node
            offset += count
            if count == 0 or not bool(payload.get("has_more")):
                break
        return entities, nodes

    def _entity_page(
        self,
        *,
        payload: dict[str, Any],
        provider_namespace: str,
        provider_project: str,
        root: Path,
        allowed_paths: set[str],
    ) -> tuple[list[_MappedEntity], int]:
        results = payload.get("results")
        if isinstance(results, list):
            entities = [
                entity
                for item in results
                if isinstance(item, dict)
                for entity in [
                    self._flat_entity(
                        item,
                        provider_namespace=provider_namespace,
                        provider_project=provider_project,
                        root=root,
                        allowed_paths=allowed_paths,
                    )
                ]
                if entity is not None
            ]
            return entities, len(results)

        cols = self._string_list(payload.get("cols"), "search_graph.cols")
        col_index = {name: index for index, name in enumerate(cols)}
        for required in ("name", "label", "lines"):
            if required not in col_index:
                raise CodebaseMemoryError("code graph search schema is incompatible")
        groups = payload.get("groups")
        if not isinstance(groups, list):
            raise CodebaseMemoryError("code graph search groups are invalid")
        entities: list[_MappedEntity] = []
        row_count = 0
        for group in groups:
            if not isinstance(group, dict):
                continue
            prefix = str(group.get("qn_prefix") or "").strip()
            path = self._normalize_provider_path(root, group.get("file"))
            rows = group.get("rows")
            if not isinstance(rows, list):
                continue
            row_count += len(rows)
            if path not in allowed_paths:
                continue
            for row in rows:
                if not isinstance(row, list):
                    continue
                name = self._row_string(row, col_index["name"])
                label = self._row_string(row, col_index["label"])
                provider_qualified_name = f"{prefix}.{name}" if prefix else name
                entity = self._entity_candidate(
                    provider_namespace=provider_namespace,
                    name=name,
                    label=label,
                    qualified_name=self._normalize_qualified_name(
                        provider_project,
                        provider_qualified_name,
                    ),
                    path=path,
                    line_value=self._row_string(row, col_index["lines"]),
                    approximate_location=False,
                )
                if entity is not None:
                    entities.append(_MappedEntity(entity, provider_qualified_name))
        count = payload.get("count", row_count)
        if not isinstance(count, int) or count < 0:
            raise CodebaseMemoryError("code graph search count is invalid")
        return entities, count

    def _flat_entity(
        self,
        item: dict[str, Any],
        *,
        provider_namespace: str,
        provider_project: str,
        root: Path,
        allowed_paths: set[str],
    ) -> _MappedEntity | None:
        path = self._normalize_provider_path(root, item.get("file_path"))
        if path not in allowed_paths:
            return None
        name = str(item.get("name") or "").strip()
        provider_qualified_name = str(item.get("qualified_name") or name).strip()
        candidate = self._entity_candidate(
            provider_namespace=provider_namespace,
            name=name,
            label=str(item.get("label") or "").strip(),
            qualified_name=self._normalize_qualified_name(
                provider_project,
                provider_qualified_name,
            ),
            path=path,
            line_value=item.get("lines"),
            approximate_location=True,
        )
        if candidate is None:
            return None
        return _MappedEntity(candidate, provider_qualified_name)

    @classmethod
    def _entity_candidate(
        cls,
        *,
        provider_namespace: str,
        name: str,
        label: str,
        qualified_name: str,
        path: str,
        line_value: Any,
        approximate_location: bool,
    ) -> CodeEntityCandidate | None:
        kind = _LABEL_KIND.get(label)
        if not name or not qualified_name or kind is None:
            return None
        if approximate_location:
            start_line, end_line = cls._parse_line_count(str(line_value or ""))
        else:
            start_line, end_line = cls._parse_lines(str(line_value or ""))
        evidence_refs = [
            f"code-graph:codebase-memory:{path}:{start_line}-{end_line}"
        ]
        if approximate_location:
            evidence_refs.append("code-graph-location:approximate")
        provider_id = cls._provider_id(
            provider_namespace,
            label,
            qualified_name,
            path,
            start_line,
        )
        return CodeEntityCandidate(
            provider_node_id=provider_id,
            name=name,
            qualified_name=qualified_name,
            entity_kind=kind,
            relative_path=path,
            language=_LANGUAGE_BY_SUFFIX.get(Path(path).suffix.lower(), "unknown"),
            start_line=start_line,
            end_line=end_line,
            evidence_refs=tuple(evidence_refs),
        )

    def _load_relationships(
        self,
        *,
        project: str,
        nodes: dict[tuple[str, str], _ExternalNode],
        allowed_paths: set[str],
    ) -> list[CodeRelationshipCandidate]:
        if not nodes:
            return []
        expected = [
            "a.qualified_name",
            "a.file_path",
            "type(r)",
            "b.qualified_name",
            "b.file_path",
        ]

        by_qn: dict[str, list[_ExternalNode]] = {}
        for node in nodes.values():
            by_qn.setdefault(node.provider_qualified_name, []).append(node)

        relationships: list[CodeRelationshipCandidate] = []
        seen: set[tuple[str, str, str]] = set()
        path_chunks = self._chunks(sorted(allowed_paths), 100)
        for path_chunk in path_chunks:
            if len(relationships) >= self.config.max_relationships:
                break
            query = self._relationship_query(
                source_paths=path_chunk,
                target_paths=allowed_paths if len(allowed_paths) <= 200 else None,
                limit=self.config.max_relationships - len(relationships),
            )
            payload = self._call(
                "query_graph",
                {"project": project, "query": query, "format": "json"},
            )
            columns = self._string_list(payload.get("columns"), "query_graph.columns")
            if columns != expected:
                raise CodebaseMemoryError("code graph relationship schema is incompatible")
            rows = payload.get("rows")
            if not isinstance(rows, list):
                raise CodebaseMemoryError("code graph relationship rows are invalid")
            for row in rows:
                if not isinstance(row, list) or len(row) < 5:
                    continue
                source = self._resolve_node(nodes, by_qn, str(row[0]), str(row[1]))
                target = self._resolve_node(nodes, by_qn, str(row[3]), str(row[4]))
                relation = _RELATION_KIND.get(str(row[2]).upper())
                if source is None or target is None or relation is None:
                    continue
                kind, invert = relation
                if invert:
                    source, target = target, source
                key = (source.provider_id, kind, target.provider_id)
                if key in seen or source.provider_id == target.provider_id:
                    continue
                seen.add(key)
                relationships.append(
                    CodeRelationshipCandidate(
                        from_provider_node_id=source.provider_id,
                        relationship_kind=kind,
                        to_provider_node_id=target.provider_id,
                        confidence=0.88,
                        evidence_refs=(
                            f"code-graph-edge:codebase-memory:{str(row[2]).upper()}",
                        ),
                    )
                )
        return relationships

    @staticmethod
    def _relationship_query(
        *,
        source_paths: Sequence[str],
        target_paths: set[str] | None,
        limit: int,
    ) -> str:
        source_values = ",".join(json.dumps(path) for path in source_paths)
        predicates = [f"a.file_path IN [{source_values}]"]
        if target_paths is not None:
            target_values = ",".join(json.dumps(path) for path in sorted(target_paths))
            predicates.append(f"b.file_path IN [{target_values}]")
        return (
            "MATCH (a)-[r]->(b) WHERE "
            + " AND ".join(predicates)
            + " RETURN a.qualified_name, a.file_path, type(r), "
            + "b.qualified_name, b.file_path "
            + f"LIMIT {max(1, limit)}"
        )

    @staticmethod
    def _chunks(values: Sequence[str], size: int) -> list[list[str]]:
        return [list(values[index : index + size]) for index in range(0, len(values), size)]

    def _call(
        self,
        tool: str,
        payload: dict[str, Any],
        *,
        allowed_root: Path | None = None,
    ) -> dict[str, Any]:
        binary = self._resolve_binary()
        env = os.environ.copy()
        if self.config.cache_dir is not None:
            self.config.cache_dir.mkdir(parents=True, exist_ok=True)
            env["CBM_CACHE_DIR"] = str(self.config.cache_dir)
        if allowed_root is not None:
            env["CBM_ALLOWED_ROOT"] = str(allowed_root)
        try:
            completed = subprocess.run(
                [binary, "cli", tool, json.dumps(payload, separators=(",", ":"))],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CodebaseMemoryError(f"code graph {tool} process failed") from exc
        if completed.returncode != 0:
            raise CodebaseMemoryError(f"code graph {tool} command failed")
        return self._decode_payload(completed.stdout, tool)

    def _probe_version(self) -> str:
        if self._version is not None:
            return self._version
        binary = self._resolve_binary()
        try:
            completed = subprocess.run(
                [binary, "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=min(self.config.timeout_seconds, 5.0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CodebaseMemoryError("code graph executable is unavailable") from exc
        if completed.returncode != 0:
            raise CodebaseMemoryError("code graph executable check failed")
        version = (completed.stdout or completed.stderr).strip().splitlines()
        if not version:
            raise CodebaseMemoryError("code graph executable did not report a version")
        self._version = version[0][:120]
        return self._version

    def _resolve_binary(self) -> str:
        configured = self.config.binary
        resolved = shutil.which(configured)
        if resolved:
            return resolved
        path = Path(configured).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
        raise CodebaseMemoryError("code graph executable is unavailable")

    @staticmethod
    def _decode_payload(raw: str, tool: str) -> dict[str, Any]:
        try:
            value: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CodebaseMemoryError(f"code graph {tool} returned invalid JSON") from exc
        if isinstance(value, dict) and isinstance(value.get("content"), list):
            if value.get("isError"):
                raise CodebaseMemoryError(f"code graph {tool} returned an error")
            content = value["content"]
            text = content[0].get("text") if content and isinstance(content[0], dict) else None
            try:
                value = json.loads(text) if isinstance(text, str) else None
            except json.JSONDecodeError as exc:
                raise CodebaseMemoryError(f"code graph {tool} envelope is invalid") from exc
        if not isinstance(value, dict):
            raise CodebaseMemoryError(f"code graph {tool} response must be an object")
        return value

    @staticmethod
    def _repository_root(units: Sequence[SourceTextUnit]) -> Path:
        roots = {unit.source_root for unit in units if unit.source_root}
        if len(roots) != 1:
            raise CodebaseMemoryError("code graph requires one materialized repository root")
        root = Path(next(iter(roots))).expanduser().resolve()
        if not root.is_dir():
            raise CodebaseMemoryError("code graph repository root is unavailable")
        return root

    @classmethod
    def _assert_source_snapshot(cls, root: Path, units: Sequence[SourceTextUnit]) -> None:
        for unit in units:
            relative = cls._safe_relative_path(unit.relative_path)
            path = (root / relative).resolve()
            if root not in path.parents or not path.is_file():
                raise CodebaseMemoryError("code graph source path escaped the repository root")
            expected = unit.content_hash.removeprefix("sha256:")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if expected and actual != expected:
                raise CodebaseMemoryError("code source changed during graph analysis")

    @staticmethod
    def _safe_relative_path(value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise CodebaseMemoryError("code graph received an unsafe relative path")
        return path.as_posix()

    @classmethod
    def _normalize_provider_path(cls, root: Path, value: Any) -> str:
        raw = str(value or "").strip().replace("\\", "/")
        if not raw:
            return ""
        path = Path(raw)
        if path.is_absolute():
            try:
                raw = path.resolve().relative_to(root).as_posix()
            except ValueError:
                return ""
        return cls._safe_relative_path(raw)

    @staticmethod
    def _project_name(root: Path) -> str:
        slug = re.sub(r"[^A-Za-z0-9_-]+", "-", root.name).strip("-").lower() or "repository"
        digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
        return f"nasus-{slug[:40]}-{digest}"

    @staticmethod
    def _provider_id(project: str, label: str, qn: str, path: str, line: int) -> str:
        digest = hashlib.sha256(
            f"{project}\0{label}\0{qn}\0{path}\0{line}".encode("utf-8")
        ).hexdigest()[:24]
        return f"codebase-memory:{digest}"

    @staticmethod
    def _parse_lines(value: str) -> tuple[int, int]:
        numbers = [int(item) for item in re.findall(r"\d+", value)]
        if not numbers:
            return 1, 1
        start = max(numbers[0], 1)
        end = max(numbers[-1], start)
        return start, end

    @staticmethod
    def _parse_line_count(value: str) -> tuple[int, int]:
        numbers = [int(item) for item in re.findall(r"\d+", value)]
        return 1, max(numbers[0] if numbers else 1, 1)

    @staticmethod
    def _normalize_qualified_name(provider_project: str, value: str) -> str:
        qualified_name = value.strip()
        prefix = f"{provider_project}."
        if qualified_name.startswith(prefix):
            return qualified_name[len(prefix) :]
        return qualified_name

    @staticmethod
    def _row_string(row: list[Any], index: int) -> str:
        if index >= len(row) or row[index] is None:
            return ""
        return str(row[index]).strip()

    @staticmethod
    def _string_list(value: Any, field: str) -> list[str]:
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise CodebaseMemoryError(f"{field} is invalid")
        return value

    @staticmethod
    def _required_string(payload: dict[str, Any], field: str) -> str:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise CodebaseMemoryError(f"code graph response is missing {field}")
        return value.strip()

    @classmethod
    def _provider_project_id(cls, payload: dict[str, Any]) -> str:
        """Keep provider-owned project identities outside persisted Nasus facts."""

        value = cls._required_string(payload, "project")
        if len(value) > 160 or re.fullmatch(r"[A-Za-z0-9_.-]+", value) is None:
            raise CodebaseMemoryError("code graph returned an unsafe project identity")
        return value

    @classmethod
    def _resolve_node(
        cls,
        nodes: dict[tuple[str, str], _ExternalNode],
        by_qn: dict[str, list[_ExternalNode]],
        qualified_name: str,
        path: str,
    ) -> _ExternalNode | None:
        normalized_path = path.strip().replace("\\", "/")
        exact = nodes.get((qualified_name, normalized_path))
        if exact is not None:
            return exact
        matches = by_qn.get(qualified_name, [])
        return matches[0] if len(matches) == 1 else None


__all__ = ["CodebaseMemoryCodeIntelligenceAdapter", "CodebaseMemoryError"]
