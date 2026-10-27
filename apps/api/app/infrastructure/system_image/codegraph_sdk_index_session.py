"""Bounded worker-local SDK projection; PG pins, not native cache files, are durable."""
from contextlib import contextmanager
from dataclasses import replace
import re
from secrets import token_bytes
from threading import Event, RLock
from uuid import uuid4

from ...application.system_image.code_index_ports import CodeEntityPage, CodeRelationPage
from ...domain.system_image.code_impact import conservative_code_impact
from ...domain.system_image.code_index import CodeIndexCancelled, CodeIndexStatus, CodeIndexUnavailable
from ...domain.system_image.code_provider import CodeProviderLimits, projection_payload
from ...domain.system_image.source_snapshots import snapshot_digest
from .code_index_paging import CodeIndexPaging
from .codegraph_sdk_runtime import CodeGraphSDKError


class CodeGraphSDKIndexSession:
    def __init__(self, adapter, units, *, check_current, namespace=None, provider_fingerprint=None):
        if not callable(check_current):
            raise ValueError("prepared SDK index requires a current authority check")
        check_current()
        if namespace is not None and (type(namespace) is not str or re.fullmatch(r"nasus_[a-f0-9]{32}", namespace) is None):
            raise ValueError("invalid durable SDK namespace")
        if provider_fingerprint is not None and (namespace is None or type(provider_fingerprint) is not str
                or re.fullmatch(r"sha256:[0-9a-f]{64}", provider_fingerprint) is None):
            raise ValueError("invalid durable SDK fingerprint")
        self._adapter, self._units, self._authority = adapter, tuple(units), check_current
        self._durable, self._fingerprint = namespace is not None, provider_fingerprint
        self._snapshot = snapshot_digest(sorted((adapter._path(unit.relative_path), unit.content_hash, unit.byte_count)
            for unit in self._units))
        self._id = "cidx_" + uuid4().hex
        self._paging = CodeIndexPaging(self._id, token_bytes(32))
        self._state, self._result, self._receipt = "pending", None, None
        self._cancelled, self._state_lock, self._operations = Event(), RLock(), RLock()

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
            raise CodeIndexUnavailable("SDK index is closed")
        if self._cancelled.is_set():
            raise CodeIndexCancelled("SDK index was cancelled")
        self._authority()

    @contextmanager
    def _operation(self):
        while not self._operations.acquire(timeout=.1):
            self._check()
        try:
            self._check()
            yield
            self._check()
        finally:
            self._operations.release()

    def _status(self):
        with self._state_lock:
            result = self._result
            return CodeIndexStatus(self._id, self._snapshot, self._adapter.provider,
                self._adapter.capabilities().provider_version, self._state,
                projection_status=projection_payload(result.provider_observations)["status"] if result else None,
                entity_count=len(result.entities) if result else None,
                relationship_count=len(result.relationships) if result else None)

    def status(self):
        self._authority()
        return self._status()

    def capabilities(self):
        self._authority()
        config = self._adapter.config
        return replace(self._adapter.capabilities(),
            operations=("capabilities", "prepare_index", "status", "entities", "relations", "locate", "impact", "cancel"),
            limits=CodeProviderLimits(config.max_entities, config.max_relationships, config.page_size,
                command_timeout_seconds=config.timeout_seconds))

    def prepare_index(self):
        with self._operation():
            if self._state in {"ready", "degraded"}:
                self._adapter._require_runtime(self._check)
                return self._status()
            if self._state != "pending":
                raise CodeIndexUnavailable("SDK index cannot be reopened")
            with self._state_lock:
                self._state = "preparing"
            try:
                if self._durable:
                    fingerprint = self._adapter.projection_fingerprint(check_current=self._check)
                    if self._fingerprint is not None and fingerprint != self._fingerprint:
                        raise CodeGraphSDKError("SDK generation build or policy changed before preparation")
                    self._fingerprint = fingerprint
                result, receipt = self._adapter._analyze_with_contract(self._units, check_current=self._check)
                if self._durable and self._adapter.projection_fingerprint(check_current=self._check) != self._fingerprint:
                    raise CodeGraphSDKError("SDK generation build or policy changed during preparation")
                with self._state_lock:
                    self._check()
                    self._result, self._receipt = result, receipt
                    self._state = "ready" if projection_payload(result.provider_observations)["status"] == "complete" else "degraded"
            except BaseException as error:
                with self._state_lock:
                    self._state = "cancelled" if isinstance(error, CodeIndexCancelled) or self._cancelled.is_set() else "failed"
                    self._result = self._receipt = None
                    self._paging.clear()
                raise
            return self._status()

    def protocol_receipt(self):
        self._check()
        return self._receipt

    def _projection(self):
        if self._state not in {"ready", "degraded"} or self._result is None:
            raise CodeIndexUnavailable("SDK index is not queryable")
        self._adapter._require_runtime(self._check)
        return self._result

    def read_projection(self):
        with self._operation():
            return self._projection()

    def _page(self, kind, cursor, limit):
        if type(limit) is not int or not 1 <= limit <= min(1000, self._adapter.config.page_size):
            raise ValueError("SDK page exceeds its declared bound")
        with self._operation():
            self._paging.validate_scope(cursor, kind)
            result = self._projection()
            observation = result.provider_observations[0]
            items = result.entities if kind == "entities" else result.relationships
            page, following, count = self._paging.page(kind, items, cursor=cursor, limit=limit)
            page_type = CodeEntityPage if kind == "entities" else CodeRelationPage
            enumeration = observation.entity_enumeration if kind == "entities" else observation.relationship_enumeration
            return page_type(self._id, self._snapshot, page, following, count, enumeration, observation.gaps)

    def entities(self, *, cursor=None, limit=50):
        return self._page("entities", cursor, limit)

    def relations(self, *, cursor=None, limit=50):
        return self._page("relations", cursor, limit)

    def locate(self, provider_node_id):
        with self._operation():
            matches = [item for item in self._projection().entities if item.provider_node_id == provider_node_id]
            if len(matches) != 1:
                raise CodeIndexUnavailable("SDK node is not unique in this index")
            return matches[0]

    def impact(self, provider_node_ids, *, direction="upstream", max_hops=2, max_entities=500):
        seeds = tuple(provider_node_ids)
        with self._operation():
            result = self._projection()
            if any(type(seed) is not str for seed in seeds):
                raise ValueError("invalid SDK impact seed")
            if not set(seeds) <= {item.provider_node_id for item in result.entities}:
                raise CodeIndexUnavailable("SDK impact seed is outside this index")
            return conservative_code_impact(index_id=self._id, snapshot_hash=self._snapshot, seeds=seeds,
                entity_ids=tuple(item.provider_node_id for item in result.entities),
                relations=tuple((item.from_provider_node_id, item.relationship_kind, item.to_provider_node_id)
                    for item in result.relationships), direction=direction, max_hops=max_hops, max_entities=max_entities,
                gaps=tuple(item.reason for item in result.provider_observations[0].gaps), check_current=self._check)

    def cancel(self):
        self._authority()
        with self._state_lock:
            if self._state not in {"cancelled", "closed", "failed"}:
                self._cancelled.set()
                self._state = "cancellation_requested"
        return self._status()

    def close(self):
        self._cancelled.set()
        with self._operations:
            with self._state_lock:
                self._result = self._receipt = None
                self._paging.clear()
                self._state = "closed"
