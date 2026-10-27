"""Opt-in CodeGraph SDK anti-corruption adapter; never the production default."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import tempfile
from typing import Callable, Sequence

from ...application.system_image.source_ports import (
    CodeEntityCandidate, CodeIntelligenceResult,
    CodeRelationshipCandidate, SourceTextUnit,
)
from ...domain.system_image.code_provider import (
    CodeProjectionGap, CodeProviderCapabilities, CodeProviderLimits, CodeProviderObservation,
)
from ...domain.system_image.evidence import source_lines
from ...domain.system_image.image_revision import require_digest
from ...domain.system_image.code_provider_protocol import CodeProviderSDKReceipt
from ...domain.system_image.source_snapshots import snapshot_digest
from .code_graph_process import CodeGraphProcessError, CodeGraphProcessRunner
from .code_graph_dependencies import projection_dependency_manifest
from .code_graph_dependency_files import DependencyFiles
from .code_native_query_observations import NativeQueryObservations
from .codegraph_sdk_runtime import CodeGraphSDKError, codegraph_runtime_fingerprint, stage_codegraph_runtime


SDK_VERSION = "1.6.2"
SDK_SCHEMA = "nasus.codegraph-sdk-projection.v2"
SDK_OPERATIONS = ("CodeGraph.init", "setLogger", "graph.indexAll", "graph.getStats", "graph.getFiles",
                  "graph.getNodesInFile", "graph.getOutgoingEdges", "graph.getIndexState",
                  "graph.getPendingReferenceCount", "graph.close")
NODE_KINDS = {"file": "module", "module": "module", "class": "class", "interface": "interface",
              "enum": "enum", "function": "function", "method": "method", "route": "api_route"}
EDGE_KINDS = {"contains": ("belongs_to", True), "calls": ("calls", False),
              "imports": ("depends_on", False), "extends": ("depends_on", False),
              "implements": ("depends_on", False), "exports": ("exposes", False)}


def _unique_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate SDK JSON field")
        value[key] = item
    return value


@dataclass(frozen=True)
class CodeGraphSDKConfig:
    package_path: Path
    platform_path: Path
    cache_dir: Path
    expected_runtime_hash: str
    max_entities: int = 20000
    max_relationships: int = 50000
    max_files: int = 20000
    max_source_bytes: int = 100 * 1024 * 1024
    timeout_seconds: float = 180
    page_size: int = 500

    def __post_init__(self):
        require_digest(self.expected_runtime_hash)
        if any(type(value) is not int or value <= 0 for value in (
                self.max_entities, self.max_relationships, self.max_files, self.max_source_bytes, self.page_size)):
            raise ValueError("CodeGraph requires positive capacity bounds")
        if type(self.timeout_seconds) not in {int, float} or not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("CodeGraph requires a finite time limit")


class CodeGraphSDKCodeIntelligenceAdapter:
    provider = "codegraph"

    def __init__(self, config: CodeGraphSDKConfig, *, process_runner=None):
        self.config = config
        self.runner = process_runner or CodeGraphProcessRunner()

    def capabilities(self):
        return CodeProviderCapabilities(self.provider, SDK_VERSION,
            ("capabilities", "analyze", "analyze_controlled"), limits=CodeProviderLimits(
                self.config.max_entities, self.config.max_relationships,
                command_timeout_seconds=self.config.timeout_seconds))

    def analyze(self, units: Sequence[SourceTextUnit]):
        return self.analyze_controlled(units, check_current=lambda: None)

    def open_index(self, units, *, check_current, namespace=None, provider_fingerprint=None):
        from .codegraph_sdk_index_session import CodeGraphSDKIndexSession
        return CodeGraphSDKIndexSession(self, units, check_current=check_current,
            namespace=namespace, provider_fingerprint=provider_fingerprint)

    def projection_fingerprint(self, *, check_current=None):
        check = check_current or (lambda: None)
        try:
            self._require_runtime(check)
            reader = DependencyFiles(check_current=check)
            bridge_hash, _ = reader.read(Path(__file__).with_name("codegraph_sdk_bridge.cjs"))
            dependencies = projection_dependency_manifest(check_current=check, entrypoints=(
                "apps.api.app.infrastructure.system_image.codegraph_sdk_code_intelligence",
                "apps.api.app.infrastructure.system_image.codegraph_sdk_index_session",
                "apps.api.app.infrastructure.system_image.composite_code_intelligence",
                "apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence",
                "apps.api.app.application.system_image.code_entity_registry"))
            reader.finish()
            self._require_runtime(check)
            policy = {key: value for key, value in asdict(self.config).items()
                      if key not in {"package_path", "platform_path", "cache_dir"}}
            return snapshot_digest({"schema": "nasus.codegraph-sdk-generation-policy.v1", "provider": self.provider,
                "version": SDK_VERSION, "projection_schema": SDK_SCHEMA, "policy": policy,
                "bridge_hash": bridge_hash, "dependencies": dependencies})
        except CodeGraphProcessError as error:
            raise CodeGraphSDKError("CodeGraph projection dependencies are unavailable") from error

    def _require_runtime(self, check, *, package_path=None, platform_path=None):
        config = self.config
        package_path = package_path or config.package_path
        platform_path = platform_path or config.platform_path
        for root, name in ((package_path, "@colbymchenry/codegraph"),
                           (platform_path, platform_path.name.replace("codegraph-", "@colbymchenry/codegraph-", 1))):
            try:
                manifest = json.loads((root / "package.json").read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise CodeGraphSDKError("CodeGraph package metadata is unavailable") from error
            if type(manifest) is not dict or manifest.get("name") != name or manifest.get("version") != SDK_VERSION:
                raise CodeGraphSDKError("CodeGraph package does not match its pinned release")
        if platform_path.parent.resolve() != package_path.parent.resolve():
            raise CodeGraphSDKError("CodeGraph requires its matching installed platform bundle")
        if codegraph_runtime_fingerprint(package_path, platform_path, check_current=check) != config.expected_runtime_hash:
            raise CodeGraphSDKError("CodeGraph runtime assets changed")

    @staticmethod
    def _path(value):
        if type(value) is not str or not value or len(value) > 4096:
            raise CodeGraphSDKError("CodeGraph returned an invalid source path")
        path = PurePosixPath(value)
        if (not path.parts or path.is_absolute() or ".." in path.parts or str(path) != value or "\\" in value
                or any(ord(char) < 32 for char in value) or {".git", ".codegraph"}.intersection(path.parts)):
            raise CodeGraphSDKError("CodeGraph source path is outside its approved snapshot")
        return value

    def _stage(self, units, root, check):
        if not units or len(units) > self.config.max_files:
            raise CodeGraphSDKError("CodeGraph source inventory is empty or exceeds capacity")
        seen, directories, total = set(), set(), 0
        for unit in units:
            check()
            path = self._path(unit.relative_path)
            if path in seen or not unit.text_is_lossless:
                raise CodeGraphSDKError("CodeGraph source inventory is ambiguous or lossy")
            parents = {str(parent) for parent in PurePosixPath(path).parents}
            if path in directories or parents.intersection(seen):
                raise CodeGraphSDKError("CodeGraph source paths conflict with their directory inventory")
            seen.add(path)
            directories.update(parents)
            data = unit.text.encode("utf-8")
            total += len(data)
            if (len(data) != unit.byte_count or "sha256:" + hashlib.sha256(data).hexdigest() != unit.content_hash
                    or total > self.config.max_source_bytes):
                raise CodeGraphSDKError("CodeGraph source bytes do not match the approved snapshot")
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o400)

    def analyze_controlled(self, units: Sequence[SourceTextUnit], *, check_current: Callable[[], None]):
        result, _ = self._analyze_with_contract(units, check_current=check_current)
        return result

    def _analyze_with_contract(self, units, *, check_current):
        units = tuple(units)
        check_current()
        self._require_runtime(check_current)
        self.config.cache_dir.mkdir(parents=True, exist_ok=True)
        bridge = Path(__file__).with_name("codegraph_sdk_bridge.cjs")
        with tempfile.TemporaryDirectory(prefix="codegraph-", dir=self.config.cache_dir) as work:
            root, home = Path(work) / "source", Path(work) / "home"
            root.mkdir(mode=0o700)
            home.mkdir(mode=0o700)
            bridge_reader = DependencyFiles(check_current=check_current)
            try:
                _, bridge_data = bridge_reader.read(bridge, capture=True, limit=1024 * 1024)
                private_bridge = Path(work) / "bridge.cjs"
                private_bridge.write_bytes(bridge_data)
                private_bridge.chmod(0o400)
                bridge_reader.finish()
            except CodeGraphProcessError as error:
                raise CodeGraphSDKError("CodeGraph public bridge is unavailable") from error
            self._stage(units, root, check_current)
            sdk, platform = stage_codegraph_runtime(self.config.package_path, self.config.platform_path,
                Path(work) / "runtime", self.config.expected_runtime_hash, check_current=check_current)
            self._require_runtime(check_current, package_path=sdk, platform_path=platform)
            env = {"PATH": os.defpath, "HOME": str(home), "TMPDIR": work,
                "CODEGRAPH_INSTALL_DIR": str(home / "bundles"), "CODEGRAPH_TELEMETRY": "0", "DO_NOT_TRACK": "1",
                "CODEGRAPH_NO_UPDATE_CHECK": "1", "CODEGRAPH_NO_DAEMON": "1", "NO_COLOR": "1"}
            try:
                output = self.runner.run([str(platform / "node"), "--liftoff-only", str(private_bridge),
                    str(sdk), str(root), SDK_VERSION,
                    str(self.config.max_entities), str(self.config.max_relationships), str(self.config.max_files)],
                    env=env, cwd=work, timeout_seconds=self.config.timeout_seconds,
                    max_stdout_bytes=16 * 1024 * 1024, check_current=check_current)
            except CodeGraphProcessError as error:
                raise CodeGraphSDKError("CodeGraph controlled process is unavailable") from error
            if output.returncode != 0:
                raise CodeGraphSDKError("CodeGraph SDK could not prepare its projection")
            # Verify the actual staged files and runtime again after the process, not only before it.
            for unit in units:
                check_current()
                path = root / unit.relative_path
                if path.is_symlink() or "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != unit.content_hash:
                    raise CodeGraphSDKError("CodeGraph changed its approved source snapshot")
            self._require_runtime(check_current)
            self._require_runtime(check_current, package_path=sdk, platform_path=platform)
            try:
                bridge_reader.finish()
                payload = json.loads(output.stdout, object_pairs_hook=_unique_json_object,
                    parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite")))
                result = self._project(payload, units)
                receipt = self._sdk_receipt(payload["sdk_contract"])
                check_current()
                return result, receipt
            except CodeGraphProcessError as error:
                raise CodeGraphSDKError("CodeGraph public bridge changed") from error
            except (KeyError, TypeError, ValueError) as error:
                raise CodeGraphSDKError("CodeGraph SDK projection schema is incompatible") from error

    def _project(self, payload, units):
        if (type(payload) is not dict or set(payload) != {"schema", "version", "sdk_contract", "state", "pending_references", "stats", "files", "nodes", "edges"}
                or payload["schema"] != SDK_SCHEMA or payload["version"] != SDK_VERSION
                or payload["state"] not in {"complete", "partial"}):
            raise ValueError("invalid SDK envelope")
        self._sdk_receipt(payload["sdk_contract"])
        for key, limit in (("nodes", self.config.max_entities), ("edges", self.config.max_relationships), ("files", self.config.max_files)):
            if type(payload[key]) is not list or len(payload[key]) > limit:
                raise ValueError("invalid SDK collection capacity")
        stats = payload["stats"]
        if type(stats) is not dict or set(stats) != {"nodes", "edges", "files"}:
            raise ValueError("invalid SDK stats")
        if any(type(value) is not int or value < 0 for value in (*stats.values(), payload["pending_references"])):
            raise ValueError("invalid SDK counts")
        if any(stats[key] != len(payload[key]) for key in stats):
            raise ValueError("SDK public enumeration does not account for its entire graph")
        texts = {unit.relative_path: unit for unit in units}
        files, nodes, entities, gaps = {}, {}, [], Counter()
        for item in payload["files"]:
            if type(item) is not dict or set(item) != {"path", "node_count", "error_count"}:
                raise ValueError("invalid SDK file")
            path = self._path(item["path"])
            if path not in texts or path in files or any(type(item[key]) is not int or item[key] < 0 for key in ("node_count", "error_count")):
                raise ValueError("SDK file is outside inventory or ambiguous")
            files[path] = item
            gaps["provider_file_parse_errors"] += item["error_count"]
        file_counts = Counter()
        for item in payload["nodes"]:
            if type(item) is not dict or set(item) != {"id", "kind", "name", "qualified_name", "path", "language", "start_line", "end_line"}:
                raise ValueError("invalid SDK node")
            if any(type(item[key]) is not str or not item[key] or len(item[key]) > 4096 for key in ("id", "kind", "name", "qualified_name", "language")):
                raise ValueError("invalid SDK node fields")
            path = self._path(item["path"])
            if path not in files or item["id"] in nodes:
                raise ValueError("SDK node is outside source scope or duplicated")
            nodes[item["id"]] = item
            file_counts[path] += 1
            start, end = item["start_line"], item["end_line"]
            if type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(source_lines(texts[path].text)):
                raise ValueError("SDK node location is invalid")
            if item["kind"] not in NODE_KINDS:
                gaps["unmapped_native_node_kind"] += 1
                continue
            refs = (f"code-graph:codegraph:{item['id']}", f"code:{path}#L{start}-L{end}", "code-graph-location:exact")
            entities.append(CodeEntityCandidate(item["id"], item["name"], item["qualified_name"], NODE_KINDS[item["kind"]],
                path, item["language"], start, end, refs, location_precision="exact"))
        if any(file_counts[path] != item["node_count"] for path, item in files.items()):
            raise ValueError("SDK per-file node accounting differs")
        allowed, relationships, edge_keys = {item.provider_node_id for item in entities}, {}, set()
        for edge in payload["edges"]:
            if type(edge) is not dict or set(edge) != {"source", "target", "kind", "provenance", "line", "column", "metadata"}:
                raise ValueError("invalid SDK relationship")
            if any(type(edge[key]) is not str or not edge[key] or len(edge[key]) > 4096
                   for key in ("source", "target", "kind", "provenance")):
                raise ValueError("invalid SDK relationship fields")
            if edge["source"] not in nodes or edge["target"] not in nodes:
                raise ValueError("SDK relationship endpoints are not closed over its graph")
            if (edge["line"] is not None and (type(edge["line"]) is not int or edge["line"] < 1)
                    or edge["column"] is not None and (type(edge["column"]) is not int or edge["column"] < 0)
                    or edge["metadata"] is not None and type(edge["metadata"]) is not dict):
                raise ValueError("invalid native relationship location or metadata")
            raw_key = edge["source"], edge["kind"], edge["target"], edge["line"], edge["column"]
            if raw_key in edge_keys:
                raise ValueError("duplicate SDK relationship")
            edge_keys.add(raw_key)
            if edge["kind"] not in EDGE_KINDS:
                gaps["unmapped_native_relationship_kind"] += 1
                continue
            if edge["source"] not in allowed or edge["target"] not in allowed:
                gaps["relationship_endpoint_not_admitted"] += 1
                continue
            kind, reverse = EDGE_KINDS[edge["kind"]]
            source, target = (edge["target"], edge["source"]) if reverse else (edge["source"], edge["target"])
            refs = ("codegraph-native-kind:" + edge["kind"], "codegraph-native-provenance:" + edge["provenance"],
                    "codegraph-native-edge:" + snapshot_digest(edge), "codegraph-native-confidence:unknown")
            key = source, kind, target
            previous = relationships.get(key)
            if previous is not None:
                gaps["native_edges_aggregated_with_retained_evidence"] += 1
                refs = tuple(sorted(set((*previous.evidence_refs, *refs))))
            # The SDK provides provenance, not a calibrated numeric probability.
            relationships[key] = CodeRelationshipCandidate(source, kind, target, 0., refs)
        gaps["pending_native_references"] = payload["pending_references"]
        if payload["state"] == "partial":
            gaps["native_index_partial"] = 1
        native = NativeQueryObservations(self.provider, SDK_VERSION)
        native.record("sdk_snapshot", {"snapshot_hash": snapshot_digest(sorted((unit.relative_path, unit.content_hash) for unit in units)),
            "runtime_hash": self.config.expected_runtime_hash, "schema": SDK_SCHEMA}, payload)
        observation = CodeProviderObservation(self.capabilities(), len(entities), len(relationships), len(entities), 0,
            "partial" if len(entities) != stats["nodes"] else "complete",
            "partial" if len(relationships) != stats["edges"] else "complete",
            (*[CodeProjectionGap(reason, count) for reason, count in sorted(gaps.items()) if count],
             CodeProjectionGap("native_confidence_not_calibrated")))
        return CodeIntelligenceResult(self.provider, SDK_VERSION, tuple(entities), tuple(relationships[key] for key in sorted(relationships)),
            ("codegraph-sdk-runtime:" + self.config.expected_runtime_hash,),
            tuple(sorted(set(texts) - set(files))), provider_observations=(observation,),
            native_query_observations=native.items)

    def _sdk_receipt(self, contract):
        expected = {"schema": "nasus.codegraph-public-sdk-contract.v1", "package_name": "@colbymchenry/codegraph",
            "package_version": SDK_VERSION, "entry_point": "package_public_entry",
            "public_operations": list(SDK_OPERATIONS), "result_schema": SDK_SCHEMA}
        if type(contract) is not dict or contract != expected:
            raise ValueError("CodeGraph public SDK contract changed")
        return CodeProviderSDKReceipt(self.provider, contract["package_name"], contract["package_version"],
            contract["entry_point"], snapshot_digest(contract), self.config.expected_runtime_hash, SDK_OPERATIONS,
            ("sdk_projection_subset_not_complete_native_graph", "os_sandbox_not_verified"))
