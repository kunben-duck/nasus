"""Capture decoded query responses before lossy provider-to-Nasus mapping."""
from dataclasses import asdict
import json

from ...domain.system_image import code_native_observation as domain


class NativeQueryObservations:
    def __init__(self, provider, version):
        self.provider, self.version = provider, version
        self._items, self._bytes = [], 0

    @property
    def items(self):
        return tuple(self._items)

    def record(self, operation, request, response):
        if len(self._items) >= domain.MAX_NATIVE_QUERY_COUNT:
            raise ValueError("native query count exceeds limit")
        item = domain.CodeNativeQueryObservation(self.provider, self.version, operation,
            json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False),
            json.dumps(response, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False))
        size = len(json.dumps(asdict(item), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        if self._bytes + size > domain.MAX_NATIVE_QUERY_BYTES:
            raise ValueError("native query archive exceeds size limit")
        self._items.append(item)
        self._bytes += size
