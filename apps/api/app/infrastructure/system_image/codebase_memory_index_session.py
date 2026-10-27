"""A real native index reused by bounded reads, with independent cancellation."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import replace
from pathlib import Path
import re
from secrets import token_bytes
from tempfile import TemporaryDirectory
from threading import Event, RLock
from uuid import uuid4

from ...application.system_image.code_index_ports import CodeEntityPage, CodeRelationPage
from ...domain.system_image.code_index import (
    CodeIndexCancelled, CodeIndexStatus, CodeIndexUnavailable,
)
from ...domain.system_image.code_impact import conservative_code_impact
from ...domain.system_image.code_provider import projection_payload
from ...domain.system_image.source_snapshots import snapshot_digest
from .codebase_memory_code_intelligence import CodebaseMemoryError
from .code_graph_executable import stage_code_graph_executable
from .code_graph_process import CodeGraphProcessError
from .code_index_paging import CodeIndexPaging


class CodebaseMemoryIndexSession:
    """Worker-owned projection cache; not a persisted business job or access grant."""

    def __init__(self, adapter, units, *, check_current, namespace=None, provider_fingerprint=None):
        if not callable(check_current):
            raise ValueError("prepared index requires an execution authority check")
        check_current()
        self._adapter, self._units, self._authority = adapter, tuple(units), check_current
        self._source_root = adapter._repository_root(self._units)
        paths = [adapter._safe_relative_path(unit.relative_path) for unit in self._units]
        if len(set(paths)) != len(paths):
            raise CodebaseMemoryError("prepared index contains duplicate source paths")
        self._allowed_paths = set(paths)
        if namespace is not None and (type(namespace) is not str or not re.fullmatch(r"nasus_[a-f0-9]{32}", namespace)):
            raise ValueError("invalid durable code index namespace")
        self._namespace = namespace or adapter._project_name(self._source_root)
        self._durable = namespace is not None
        if provider_fingerprint is not None:
            if not self._durable or type(provider_fingerprint) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", provider_fingerprint) is None:
                raise ValueError("invalid native generation fingerprint")
        self._provider_fingerprint = provider_fingerprint if provider_fingerprint is not None else (
            adapter.projection_fingerprint(check_current=check_current) if self._durable else None)
        self._binary = adapter.prepared_executable() if self._durable else None
        self._snapshot_hash = snapshot_digest(sorted((adapter._safe_relative_path(unit.relative_path), unit.content_hash, unit.byte_count)
            for unit in self._units))
        self._id = "cidx_" + uuid4().hex
        self._paging = CodeIndexPaging(self._id, token_bytes(32))
        self._state, self._version = "pending", "unprobed"
        self._state_lock, self._operations = RLock(), RLock()
        self._cancelled = Event()
        self._resources = ExitStack()
        self._root = self._cache = self._project = self._native_status = self._result = None
        self._protocol = None

    def __enter__(self):
        try:
            self.prepare_index()
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self, *_):
        self.close()

    def _check(self):
        if self._state == "closed":
            raise CodeIndexUnavailable("prepared code index is closed")
        if self._cancelled.is_set():
            raise CodeIndexCancelled("prepared code index was cancelled")
        self._authority()

    @contextmanager
    def _operation(self):
        while not self._operations.acquire(timeout=.1):
            self._check()
        adapter = self._adapter
        tokens = []
        try:
            self._check()
            for variable, value in ((adapter._execution_check, self._check),
                                    (adapter._execution_root, self._root),
                                    (adapter._execution_cache, self._cache),
                                    (adapter._execution_binary, self._binary),
                                    (adapter._snapshot_check_after, 0.0)):
                tokens.append((variable, variable.set(value)))
            yield
            self._check()
        finally:
            for variable, token in reversed(tokens):
                variable.reset(token)
            self._operations.release()

    def _snapshot_status(self):
        with self._state_lock:
            result = self._result
            return CodeIndexStatus(self._id, self._snapshot_hash, self._adapter.provider, self._version, self._state,
                projection_status=projection_payload(result.provider_observations)["status"] if result else None,
                entity_count=len(result.entities) if result else None,
                relationship_count=len(result.relationships) if result else None)

    def status(self):
        self._authority()
        return self._snapshot_status()

    def capabilities(self):
        self._authority()
        return replace(self._adapter.capabilities(), provider_version=self._version,
            operations=("capabilities", "prepare_index", "status", "entities", "relations", "locate", "impact", "cancel"))

    def _set_state(self, state):
        with self._state_lock:
            if self._cancelled.is_set():
                raise CodeIndexCancelled("prepared code index was cancelled")
            self._state = state

    def _failed(self, error):
        with self._state_lock:
            self._state = "cancelled" if isinstance(error, CodeIndexCancelled) or self._cancelled.is_set() else "failed"
            self._result = None
            self._paging.clear()

    def prepare_index(self):
        with self._operation():
            if self._state in {"ready", "degraded"}:
                try:
                    self._adapter._assert_source_snapshot(self._source_root, self._units)
                    self._adapter._assert_source_snapshot(self._root, self._units)
                except BaseException as error:
                    self._failed(error)
                    raise
                return self._snapshot_status()
            if self._state != "pending":
                raise CodeIndexUnavailable("prepared code index cannot be reopened")
            self._set_state("preparing")
            adapter = self._adapter
            try:
                adapter._assert_source_snapshot(self._source_root, self._units)
                if adapter.config.cache_dir is not None:
                    adapter.config.cache_dir.mkdir(parents=True, exist_ok=True)
                self._root = Path(self._resources.enter_context(TemporaryDirectory(prefix="nasus-cbm-"))).resolve()
                self._cache = Path(self._resources.enter_context(TemporaryDirectory(
                    prefix="nasus-cbm-cache-", dir=adapter.config.cache_dir))).resolve()
                # Newly allocated paths must be bound before staging or native commands.
                binary_token = None
                root_token = adapter._execution_root.set(self._root)
                cache_token = adapter._execution_cache.set(self._cache)
                try:
                    if self._durable:
                        executable_root = Path(self._resources.enter_context(TemporaryDirectory(prefix="nasus-cbm-exec-"))).resolve()
                        try:
                            executable = stage_code_graph_executable(self._binary, executable_root, check_current=self._check)
                        except CodeGraphProcessError as error:
                            raise CodebaseMemoryError("code graph executable snapshot failed") from error
                        if adapter.projection_fingerprint(executable=executable) != self._provider_fingerprint:
                            raise CodebaseMemoryError("code graph executable or projection policy changed before preparation")
                        self._binary = str(executable)
                        binary_token = adapter._execution_binary.set(self._binary)
                    adapter._stage_snapshot(self._source_root, self._root, self._units)
                    with adapter._execution_lock():
                        self._version = adapter._probe_version(refresh=True) if self._durable else adapter._probe_version()
                        if self._durable:
                            self._protocol = adapter.negotiate_native_contract(cli_version=self._version)
                        payload = adapter._call("index_repository", {"repo_path": str(self._root),
                            "name": self._namespace, "mode": adapter.config.index_mode, "persistence": False},
                            allowed_root=self._root)
                    self._native_status = adapter._required_string(payload, "status")
                    if self._native_status not in {"indexed", "degraded"}:
                        raise CodebaseMemoryError("native code index did not finish preparing")
                    self._project = adapter._provider_project_id(payload)
                    adapter._assert_source_snapshot(self._source_root, self._units)
                    adapter._assert_source_snapshot(self._root, self._units)
                    self._check()
                    self._set_state("ready" if self._native_status == "indexed" else "degraded")
                finally:
                    if binary_token is not None:
                        adapter._execution_binary.reset(binary_token)
                    adapter._execution_cache.reset(cache_token)
                    adapter._execution_root.reset(root_token)
            except BaseException as error:
                self._failed(error)
                self._resources.close()
                raise
            return self._snapshot_status()

    def protocol_receipt(self):
        self._check()
        return self._protocol

    def _read_projection(self):
        if self._state not in {"ready", "degraded"}:
            raise CodeIndexUnavailable("prepared code index is not queryable")
        adapter = self._adapter
        try:
            adapter._assert_source_snapshot(self._source_root, self._units)
            adapter._assert_source_snapshot(self._root, self._units)
            if self._result is None:
                result = adapter._read_prepared_projection(self._root, self._units, self._allowed_paths,
                    self._namespace, version=self._version, project=self._project, index_status=self._native_status)
                if self._durable and any(Path(unit.relative_path).suffix.lower() == ".java" for unit in self._units):
                    from .tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
                    from .code_graph_observation_validation import validate_java_imports
                    syntax = TreeSitterCodeIntelligenceAdapter().analyze_controlled(self._units, check_current=self._check)
                    result = validate_java_imports(result, syntax)
                adapter._assert_source_snapshot(self._source_root, self._units)
                adapter._assert_source_snapshot(self._root, self._units)
                self._check()
                with self._state_lock:
                    if self._cancelled.is_set():
                        raise CodeIndexCancelled("prepared code index was cancelled")
                    self._result = result
            return self._result
        except BaseException as error:
            self._failed(error)
            self._resources.close()
            raise

    def read_projection(self):
        with self._operation():
            return self._read_projection()

    def _page(self, kind, cursor, limit):
        if type(limit) is not int or not 1 <= limit <= min(1000, self._adapter.config.page_size):
            raise ValueError("code index page limit exceeds its declared bound")
        with self._operation():
            self._paging.validate_scope(cursor, kind)
            result = self._read_projection()
            items = result.entities if kind == "entities" else result.relationships
            page, next_cursor, count = self._paging.page(kind, items, cursor=cursor, limit=limit)
            observation = result.provider_observations[0]
            enumeration = observation.entity_enumeration if kind == "entities" else observation.relationship_enumeration
            page_type = CodeEntityPage if kind == "entities" else CodeRelationPage
            return page_type(self._id, self._snapshot_hash, page, next_cursor, count, enumeration, observation.gaps)

    def entities(self, *, cursor=None, limit=50):
        return self._page("entities", cursor, limit)

    def relations(self, *, cursor=None, limit=50):
        return self._page("relations", cursor, limit)

    def locate(self, provider_node_id):
        with self._operation():
            result = self._read_projection()
            matches = [item for item in result.entities if item.provider_node_id == provider_node_id]
            if len(matches) != 1:
                raise CodeIndexUnavailable("code location is not unique in this index")
            return matches[0]

    def impact(self, provider_node_ids, *, direction="upstream", max_hops=2, max_entities=500):
        seeds = tuple(provider_node_ids)
        with self._operation():
            result = self._read_projection()
            if any(type(seed) is not str for seed in seeds):
                raise ValueError("invalid code impact bounds")
            if not set(seeds) <= {item.provider_node_id for item in result.entities}:
                raise CodeIndexUnavailable("code impact seed is not in this index")
            return conservative_code_impact(index_id=self._id, snapshot_hash=self._snapshot_hash,
                seeds=seeds, entity_ids=tuple(item.provider_node_id for item in result.entities),
                relations=tuple((edge.from_provider_node_id, edge.relationship_kind, edge.to_provider_node_id)
                    for edge in result.relationships), direction=direction, max_hops=max_hops,
                max_entities=max_entities, gaps=tuple(gap.reason for gap in result.provider_observations[0].gaps),
                check_current=self._check)

    def cancel(self):
        self._authority()
        with self._state_lock:
            if self._state not in {"cancelled", "closed", "failed"}:
                self._cancelled.set()
                self._state = "cancellation_requested"
        return self._snapshot_status()

    def close(self):
        # Cleanup cannot depend on permissions that may already have been revoked.
        self._cancelled.set()
        with self._operations:
            self._resources.close()
            with self._state_lock:
                self._result = None
                self._paging.clear()
                self._state = "closed"
