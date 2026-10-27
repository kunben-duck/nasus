from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import stat
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from pathlib import Path
from threading import RLock
import time
from typing import Any, Callable, Sequence

from ...application.system_image.source_ports import (
    CodeEntityCandidate,
    CodeEntityKind,
    CodeIntelligenceResult,
    CodeIntelligenceUnavailable,
    CodeRelationshipCandidate,
    CodeRelationshipKind,
    SourceTextUnit,
)
from ..config.code_graph_config import CodeGraphConfig
from ...domain.system_image.code_provider import (
    CodeProjectionGap, CodeProviderCapabilities, CodeProviderLimits, CodeProviderObservation,
)
from ...domain.system_image.code_native_observation import native_query_object
from .codebase_memory_locations import load_exact_locations
from .code_graph_process import CodeGraphProcessError, CodeGraphProcessRunner
from .code_graph_executable import code_graph_executable_digest
from .code_graph_dependencies import projection_dependency_manifest
from .code_native_query_observations import NativeQueryObservations


class CodebaseMemoryError(CodeIntelligenceUnavailable):
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


@dataclass(frozen=True)
class _RelationshipEnumeration:
    complete: bool
    unresolved_endpoints: int = 0
    gaps: tuple[str, ...] = ()


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

    def __init__(self, config: CodeGraphConfig, *, process_runner: CodeGraphProcessRunner | None = None) -> None:
        self.config = config
        self._lock = RLock()
        self._version: str | None = None
        self._process_runner = process_runner or CodeGraphProcessRunner()
        self._execution_check = ContextVar("code_graph_execution_check", default=None)
        self._execution_root = ContextVar("code_graph_execution_root", default=None)
        self._execution_cache = ContextVar("code_graph_execution_cache", default=None)
        self._execution_binary = ContextVar("code_graph_execution_binary", default=None)
        self._snapshot_check_after = ContextVar("code_graph_snapshot_check_after", default=0.0)

    def analyze(self, units: Sequence[SourceTextUnit]) -> CodeIntelligenceResult:
        return self._analyze(units)

    def capabilities(self) -> CodeProviderCapabilities:
        # Language marketing and native CLI operations are not Nasus port capabilities.
        return CodeProviderCapabilities(self.provider, self._version or "unprobed",
            ("capabilities", "analyze", "analyze_controlled"), limits=CodeProviderLimits(
                self.config.max_entities, self.config.max_relationships, self.config.page_size,
                self.config.max_relationship_queries, self.config.timeout_seconds))

    def analyze_controlled(self, units: Sequence[SourceTextUnit], *, check_current: Callable[[], None]) -> CodeIntelligenceResult:
        token = self._execution_check.set(check_current)
        polling_token = self._snapshot_check_after.set(0.0)
        try:
            check_current()
            return self._analyze(units)
        finally:
            self._snapshot_check_after.reset(polling_token)
            self._execution_check.reset(token)

    def _check_snapshot_current(self, *, force=False):
        check = self._execution_check.get()
        now = time.monotonic()
        if check is not None and (force or now >= self._snapshot_check_after.get()):
            check()
            self._snapshot_check_after.set(time.monotonic() + .25)

    @contextmanager
    def _execution_lock(self):
        while not self._lock.acquire(timeout=.1):
            check = self._execution_check.get()
            if check is not None:
                check()
        try:
            check = self._execution_check.get()
            if check is not None:
                check()
            yield
        finally:
            self._lock.release()

    def _analyze(self, units: Sequence[SourceTextUnit]) -> CodeIntelligenceResult:
        with self.open_index(units, check_current=self._execution_check.get() or (lambda: None)) as index:
            return index.read_projection()

    def open_index(self, units: Sequence[SourceTextUnit], *, check_current: Callable[[], None], namespace=None,
                   provider_fingerprint=None):
        from .codebase_memory_index_session import CodebaseMemoryIndexSession
        return CodebaseMemoryIndexSession(self, units, check_current=check_current, namespace=namespace,
                                          provider_fingerprint=provider_fingerprint)

    def projection_fingerprint(self, *, executable=None, check_current=None):
        from ...domain.system_image.source_snapshots import snapshot_digest
        executable = Path(executable if executable is not None else self.prepared_executable()).resolve()
        check = check_current if check_current is not None else self._execution_check.get()
        try:
            digest = code_graph_executable_digest(executable, check_current=check)
            dependencies = projection_dependency_manifest(check_current=check)
        except CodeGraphProcessError as error:
            raise CodebaseMemoryError("code graph executable or dependency fingerprint is unavailable") from error
        return snapshot_digest({"provider": self.provider, "binary_sha256": digest,
            "dependencies": dependencies, "index_mode": self.config.index_mode,
            "max_entities": self.config.max_entities, "max_relationships": self.config.max_relationships,
            "max_relationship_queries": self.config.max_relationship_queries, "page_size": self.config.page_size,
            "schema": "nasus.code-index-generation.v2"})

    def prepared_executable(self):
        resolved = shutil.which(self.config.binary)
        if resolved is None:
            raise CodebaseMemoryError("code graph executable is not available")
        with Path(resolved).open("rb") as handle:
            header = handle.read(4096)
        if b"from codebase_memory_mcp import main" not in header:
            return resolved
        # The installed launcher can download on first execution. Durable work
        # uses only its already-installed native binary, with no bootstrap IO.
        from codebase_memory_mcp import _cli
        path = _cli._bin_path(_cli._version())
        if not path.is_file() or not os.access(path, os.X_OK):
            raise CodebaseMemoryError("durable code graph requires a preinstalled native executable")
        return str(path)

    def _stage_snapshot(self, root, staged_root, units):
        self._check_snapshot_current(force=True)
        if len({self._safe_relative_path(unit.relative_path) for unit in units}) != len(units):
            raise CodebaseMemoryError("code graph snapshot contains duplicate paths")
        for unit in units:
            relative = self._safe_relative_path(unit.relative_path)
            data = self._read_snapshot_file(root, unit)
            target = staged_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o400)
        self._check_snapshot_current(force=True)

    def _read_prepared_projection(self, root, units, allowed_paths, project_namespace, *, version, project, index_status):
        native_queries = NativeQueryObservations(self.provider, version)

        def observed_call(tool, request):
            response = self._call(tool, request)
            try:
                native_queries.record(tool, request, response)
            except ValueError as error:
                raise CodebaseMemoryError("native query observations cannot be retained") from error
            return response

        with self._execution_lock():
            entities, nodes, unverified_routes, ambiguous_nodes = self._load_entities(
                project=project,
                provider_namespace=project_namespace,
                root=root,
                allowed_paths=allowed_paths,
                call=observed_call,
            )
            relationships, unverified_calls, scan_refs, enumeration = self._load_relationships(
                project=project,
                nodes=nodes,
                allowed_paths=allowed_paths,
                root=root,
                call=observed_call,
            )
            self._assert_source_snapshot(root, units)

        evidence = [
            "code-graph:codebase-memory",
            f"code-graph-project:{project_namespace}",
            f"code-graph-index:{index_status}",
            f"code-graph-entities:{len(entities)}",
            f"code-graph-relationships:{len(relationships)}",
            *scan_refs,
        ]
        if unverified_routes:
            evidence.extend(("code-graph-routes:unverified-synthetic", f"code-graph-routes:excluded:{unverified_routes}"))
        if unverified_calls:
            evidence.extend(("code-graph-calls:unverified-resolution", f"code-graph-calls:excluded:{unverified_calls}"))
        if ambiguous_nodes:
            evidence.append(f"code-graph-entities:ambiguous-endpoints:{ambiguous_nodes}")
        if len(entities) >= self.config.max_entities:
            evidence.append("code-graph-entities:truncated")
        if len(relationships) >= self.config.max_relationships:
            evidence.append("code-graph-relationships:truncated")
        gaps = [CodeProjectionGap("provider_language_coverage_unverified"),
                CodeProjectionGap("provider_scores_uncalibrated")]
        if index_status == "degraded":
            gaps.append(CodeProjectionGap("native_index_degraded"))
        if ambiguous_nodes:
            gaps.append(CodeProjectionGap("ambiguous_native_entity_mapping", ambiguous_nodes))
        entity_limit = len(entities) >= self.config.max_entities
        gaps.append(CodeProjectionGap("entity_limit_reached" if entity_limit else "entity_pagination_completeness_unverified"))
        gaps.extend(CodeProjectionGap(reason) for reason in enumeration.gaps)
        relationship_limit = len(relationships) >= self.config.max_relationships
        if relationship_limit and "relationship_limit_reached" not in enumeration.gaps:
            gaps.append(CodeProjectionGap("relationship_limit_reached"))
        for reason, count in (("unverified_synthetic_routes", unverified_routes),
                              ("unverified_call_resolution", unverified_calls),
                              ("unresolved_relationship_endpoints", enumeration.unresolved_endpoints)):
            if count:
                gaps.append(CodeProjectionGap(reason, count))
        exact = sum(item.location_precision == "exact" for item in entities)
        observation = CodeProviderObservation(replace(self.capabilities(), provider_version=version),
            len(entities), len(relationships), exact, len(entities) - exact,
            "partial" if entity_limit else "unknown",
            "complete" if enumeration.complete and not relationship_limit else "partial", tuple(gaps))
        return CodeIntelligenceResult(
            provider=self.provider,
            provider_version=version,
            entities=tuple(entities),
            relationships=tuple(relationships),
            evidence_refs=tuple(dict.fromkeys(evidence)),
            provider_observations=(observation,),
            native_query_observations=native_queries.items,
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
        call=None,
    ) -> tuple[list[CodeEntityCandidate], dict[tuple[str, str], _ExternalNode], int, int]:
        call = call or self._call
        entities: list[CodeEntityCandidate] = []
        nodes: dict[tuple[str, str], _ExternalNode] = {}
        ambiguous_keys = set()
        ambiguous_ids = set()
        unverified_routes = 0
        offset = 0
        while len(entities) < self.config.max_entities:
            payload = call(
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
                # CBM 0.8 synthetic route keys are global HTTP/path keys. They
                # can collapse distinct controller handlers and return an
                # arbitrary source file. Do not promote those as source facts.
                if entity.entity_kind == "api_route" and entity.qualified_name.startswith("__route__"):
                    unverified_routes += 1
                    continue
                entities.append(entity)
                node = _ExternalNode(
                    entity.provider_node_id,
                    mapped.provider_qualified_name,
                    entity.qualified_name,
                    entity.relative_path,
                )
                key = (mapped.provider_qualified_name, entity.relative_path)
                previous = nodes.get(key)
                if key in ambiguous_keys or (previous is not None and previous.provider_id != node.provider_id):
                    ambiguous_keys.add(key)
                    ambiguous_ids.add(node.provider_id)
                    if previous is not None:
                        ambiguous_ids.add(previous.provider_id)
                    nodes.pop(key, None)
                else:
                    nodes[key] = node
            offset += count
            if count == 0 or not bool(payload.get("has_more")):
                break
        approximate = {
            entity.provider_node_id: entity for entity in entities
            if "code-graph-location:approximate" in entity.evidence_refs
        }
        if approximate:
            try:
                locations = load_exact_locations(
                    call, project=project, root=root,
                    identities=[key for key, node in nodes.items() if node.provider_id in approximate],
                )
            except ValueError as exc:
                raise CodebaseMemoryError(str(exc)) from exc
            exact_by_id = {
                node.provider_id: locations[key] for key, node in nodes.items() if key in locations
            }
            entities = [
                replace(
                    entity, start_line=exact_by_id[entity.provider_node_id][0],
                    end_line=exact_by_id[entity.provider_node_id][1],
                    location_precision="exact",
                    evidence_refs=(
                        f"code-graph:codebase-memory:{entity.relative_path}:"
                        f"{exact_by_id[entity.provider_node_id][0]}-{exact_by_id[entity.provider_node_id][1]}",
                        "code-graph-location:exact",
                    ),
                ) if entity.provider_node_id in exact_by_id else entity
                for entity in entities
            ]
        # Provider search order is not a contract. Ambiguous native keys must
        # never select whichever overloaded/class endpoint happened to be last.
        entities = [replace(entity, identity_status="ambiguous") if entity.provider_node_id in ambiguous_ids else entity
                    for entity in entities]
        return sorted(entities, key=lambda item: item.provider_node_id), nodes, unverified_routes, len(ambiguous_keys)

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
            location_precision="approximate" if approximate_location else "exact",
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
        root: Path,
        call=None,
    ) -> tuple[list[CodeRelationshipCandidate], int, tuple[str, ...], _RelationshipEnumeration]:
        from .code_graph_relationship_scan import CodeGraphRelationshipScanner, CodeGraphScanError
        if not nodes:
            return [], 0, (), _RelationshipEnumeration(False, gaps=("no_mapped_relationship_endpoints",))

        relationships: dict[tuple[str, str, str], CodeRelationshipCandidate] = {}
        unverified_calls = 0
        unresolved_endpoints = 0
        scanner = CodeGraphRelationshipScanner(call=call or self._call, project=project, allowed_paths=allowed_paths,
            node_keys=nodes.keys(), page_size=self.config.page_size, max_queries=self.config.max_relationship_queries)
        edge_limit = False
        try:
            for rows in scanner.pages():
                for row in rows:
                    source_path = self._normalize_provider_path(root, row[1])
                    target_path = self._normalize_provider_path(root, row[4])
                    source = nodes.get((str(row[0]), source_path))
                    target = nodes.get((str(row[3]), target_path))
                    relation = _RELATION_KIND.get(str(row[2]).upper())
                    if source is None or target is None:
                        unresolved_endpoints += 1
                        continue
                    if relation is None:
                        continue
                    kind, invert = relation
                    score = .88
                    resolution_refs = ()
                    if kind == "calls":
                        resolution = self._call_resolution(row[5:])
                        if resolution is None:
                            unverified_calls += 1
                            continue
                        score, strategy = resolution
                        resolution_refs = (f"code-graph-call-resolution:strategy:{strategy}",
                            "code-graph-call-resolution:candidates:1", "code-graph-call-resolution:uncalibrated-provider-score",
                            f"code-graph-call-resolution:provider-score:{score:.6g}")
                    if invert:
                        source, target = target, source
                    key = (source.provider_id, kind, target.provider_id)
                    if source.provider_id == target.provider_id:
                        continue
                    evidence = f"code-graph-edge:codebase-memory:{str(row[2]).upper()}"
                    existing = relationships.get(key)
                    if existing is not None:
                        relationships[key] = replace(existing, confidence=max(existing.confidence, score),
                            evidence_refs=tuple(sorted({*existing.evidence_refs, evidence, *resolution_refs})))
                    elif len(relationships) < self.config.max_relationships:
                        relationships[key] = CodeRelationshipCandidate(
                            from_provider_node_id=source.provider_id,
                            relationship_kind=kind,
                            to_provider_node_id=target.provider_id,
                            confidence=score,
                            evidence_refs=tuple(sorted((evidence, *resolution_refs))),
                        )
                    else:
                        edge_limit = True
                        break
                if edge_limit:
                    break
        except CodeGraphScanError as exc:
            raise CodebaseMemoryError(str(exc)) from exc
        refs = [f"code-graph-relationship-queries:{scanner.query_count}"]
        if unresolved_endpoints:
            refs.append(f"code-graph-edges:unresolved-endpoints:{unresolved_endpoints}")
        if edge_limit or not scanner.complete:
            refs.append("code-graph-relationships:truncated")
        refs.extend("code-graph-relationship-scan:" + gap for gap in sorted(scanner.gaps))
        gaps = set(scanner.gaps)
        if edge_limit:
            gaps.add("relationship_limit_reached")
        return ([relationships[key] for key in sorted(relationships)], unverified_calls, tuple(refs),
                _RelationshipEnumeration(scanner.complete and not edge_limit, unresolved_endpoints, tuple(sorted(gaps))))

    @staticmethod
    def _call_resolution(values):
        confidence, strategy, candidates = values
        if confidence in (None, "") or strategy in (None, "") or candidates in (None, ""):
            return None
        if (isinstance(confidence, bool) or isinstance(candidates, bool) or not isinstance(strategy, str)
                or re.fullmatch(r"[a-z0-9_-]{1,80}", strategy) is None):
            raise CodebaseMemoryError("code graph call resolution metadata is invalid")
        try:
            score = float(confidence)
            count = int(candidates)
        except (TypeError, ValueError, OverflowError):
            raise CodebaseMemoryError("code graph call resolution metadata is invalid") from None
        if not math.isfinite(score) or not 0 <= score <= 1 or str(count) != str(candidates) or count < 0:
            raise CodebaseMemoryError("code graph call resolution metadata is invalid")
        if count != 1 or strategy not in {"same_module", "import_map", "import_map_suffix", "lsp_override", "lsp_type_dispatch"}:
            return None
        return score, strategy

    def _call(
        self,
        tool: str,
        payload: dict[str, Any],
        *,
        allowed_root: Path | None = None,
    ) -> dict[str, Any]:
        binary = self._resolve_binary()
        env = self._process_environment(allowed_root=allowed_root or self._execution_root.get())
        try:
            completed = self._process_runner.run(
                [binary, "cli", tool, json.dumps(payload, separators=(",", ":"))],
                timeout_seconds=self.config.timeout_seconds, env=env,
                check_current=self._execution_check.get(),
            )
        except CodeGraphProcessError as exc:
            raise CodebaseMemoryError(f"code graph {tool} process failed") from exc
        if completed.returncode != 0:
            raise CodebaseMemoryError(f"code graph {tool} command failed")
        return self._decode_payload(completed.stdout, tool)

    def _process_environment(self, *, allowed_root=None):
        # Credentials, proxy settings and unrelated provider controls are not inherited.
        env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR") if key in os.environ}
        cache = self._execution_cache.get() or self.config.cache_dir
        if cache is not None:
            cache.mkdir(parents=True, exist_ok=True)
            env["CBM_CACHE_DIR"] = str(cache)
        if allowed_root is not None:
            env["CBM_ALLOWED_ROOT"] = str(allowed_root)
        return env

    def _probe_version(self, *, refresh=False) -> str:
        if self._version is not None and not refresh:
            return self._version
        binary = self._resolve_binary()
        try:
            completed = self._process_runner.run(
                [binary, "--version"],
                timeout_seconds=min(self.config.timeout_seconds, 5.0),
                max_stdout_bytes=4096, max_stderr_bytes=4096,
                env=self._process_environment(allowed_root=self._execution_root.get()),
                check_current=self._execution_check.get(),
            )
        except CodeGraphProcessError as exc:
            raise CodebaseMemoryError("code graph executable is unavailable") from exc
        if completed.returncode != 0:
            raise CodebaseMemoryError("code graph executable check failed")
        version = (completed.stdout or completed.stderr).strip().splitlines()
        if not version:
            raise CodebaseMemoryError("code graph executable did not report a version")
        self._version = version[0][:120]
        return self._version

    def negotiate_native_contract(self, *, cli_version=None):
        from tempfile import TemporaryDirectory
        from .code_graph_mcp_contract import CodeGraphMcpDialogue
        dialogue = CodeGraphMcpDialogue(index_mode=self.config.index_mode,
            cli_version=cli_version or self._probe_version(refresh=True))
        # The server's initialization may read HOME/config, inspect cwd and
        # invoke helper programs. It sees neither source nor operator tools.
        with TemporaryDirectory(prefix="nasus-cbm-protocol-") as temporary:
            root = Path(temporary).resolve()
            for name in ("home", "cwd", "cache", "tmp", "helpers"):
                (root / name).mkdir(mode=0o700)
            environment = {key: os.environ[key] for key in ("LANG", "LC_ALL") if key in os.environ}
            environment.update(HOME=str(root / "home"), PATH=str(root / "helpers"), TMPDIR=str(root / "tmp"),
                CBM_ALLOWED_ROOT=str(root / "cwd"), CBM_CACHE_DIR=str(root / "cache"))
            try:
                result = self._process_runner.run([self._resolve_binary(), "--ui=false"], env=environment,
                    cwd=str(root / "cwd"), timeout_seconds=min(self.config.timeout_seconds, 5),
                    max_stdout_bytes=512 * 1024, max_stderr_bytes=64 * 1024,
                    check_current=self._execution_check.get(), dialogue=dialogue)
            except CodeGraphProcessError as error:
                raise CodebaseMemoryError("code graph native negotiation failed") from error
            if result.returncode != 0:
                raise CodebaseMemoryError("code graph native negotiation exited unsuccessfully")
            return dialogue.receipt()

    def _resolve_binary(self) -> str:
        prepared = self._execution_binary.get()
        if prepared is not None:
            return prepared
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
            value = native_query_object(raw)
        except ValueError as exc:
            raise CodebaseMemoryError(f"code graph {tool} returned invalid JSON") from exc
        if isinstance(value.get("content"), list):
            if value.get("isError"):
                raise CodebaseMemoryError(f"code graph {tool} returned an error")
            content = value["content"]
            text = content[0].get("text") if content and isinstance(content[0], dict) else None
            try:
                value = native_query_object(text)
            except ValueError as exc:
                raise CodebaseMemoryError(f"code graph {tool} envelope is invalid") from exc
        return value

    @staticmethod
    def _repository_root(units: Sequence[SourceTextUnit]) -> Path:
        if not units or any(not unit.source_root for unit in units):
            raise CodebaseMemoryError("code graph requires one declared repository root for every source")
        roots = {unit.source_root for unit in units if unit.source_root}
        if len(roots) != 1:
            raise CodebaseMemoryError("code graph requires one materialized repository root")
        root = Path(next(iter(roots))).expanduser().resolve()
        if not root.is_dir():
            raise CodebaseMemoryError("code graph repository root is unavailable")
        return root

    def _assert_source_snapshot(self, root: Path, units: Sequence[SourceTextUnit]) -> None:
        self._check_snapshot_current(force=True)
        for unit in units:
            self._read_snapshot_file(root, unit)
        self._check_snapshot_current(force=True)

    def _read_snapshot_file(self, root: Path, unit: SourceTextUnit) -> bytes:
        relative = self._safe_relative_path(unit.relative_path)
        expected = unit.content_hash.removeprefix("sha256:")
        if (re.fullmatch(r"[a-f0-9]{64}", expected) is None
                or type(unit.byte_count) is not int or unit.byte_count < 0):
            raise CodebaseMemoryError("code graph snapshot requires an exact digest and byte count")
        descriptors = []

        def open_owned(path, flags, *, parent=None):
            self._check_snapshot_current()
            try:
                fd = os.open(path, flags, dir_fd=parent)
            except OSError as exc:
                raise CodebaseMemoryError("code graph snapshot path is unavailable or contains symbolic links") from exc
            descriptors.append(fd)
            return fd

        try:
            # Resolve each component against an already-open directory; a
            # symlink swap must not redirect a read outside the owned snapshot.
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            parent = open_owned(root, flags)
            parts = Path(relative).parts
            if not parts:
                raise CodebaseMemoryError("code graph received an unsafe relative path")
            for part in parts[:-1]:
                parent = open_owned(part, flags, parent=parent)
            fd = open_owned(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, parent=parent)
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != unit.byte_count:
                raise CodebaseMemoryError("code source changed during graph analysis")
            data = bytearray()
            while len(data) <= unit.byte_count:
                self._check_snapshot_current()
                chunk = os.read(fd, min(65536, unit.byte_count + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            if len(data) != unit.byte_count or hashlib.sha256(data).hexdigest() != expected:
                raise CodebaseMemoryError("code source changed during graph analysis")
            return bytes(data)
        finally:
            for fd in reversed(descriptors):
                os.close(fd)

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
        # CBM 0.8 derives this opaque query parameter from the absolute checkout
        # path, ignoring the requested short name. Revision snapshots are deep.
        if len(value) > 4096 or re.fullmatch(r"[A-Za-z0-9_.-]+", value) is None:
            raise CodebaseMemoryError("code graph returned an unsafe project identity")
        return value

__all__ = ["CodebaseMemoryCodeIntelligenceAdapter", "CodebaseMemoryError"]
