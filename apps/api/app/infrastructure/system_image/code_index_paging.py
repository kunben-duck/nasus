"""Opaque page cursors pin the session, collection, and complete normalized set."""
from __future__ import annotations

import base64
from dataclasses import asdict
import hmac
import json

from ...domain.system_image.source_snapshots import snapshot_digest


class CodeIndexPaging:
    def __init__(self, index_id, key):
        self.index_id, self.key = index_id, key
        self._collections = {}

    def collection(self, kind, items):
        if kind not in self._collections:
            records = tuple(sorted(items, key=lambda item: item.provider_node_id)) if kind == "entities" else tuple(items)
            self._collections[kind] = (records, snapshot_digest([asdict(item) for item in records]))
        return self._collections[kind]

    def clear(self):
        self._collections.clear()

    def page(self, kind, items, *, cursor, limit):
        records, digest = self.collection(kind, items)
        offset = self._offset(cursor, kind, digest, len(records))
        end = min(offset + limit, len(records))
        page = records[offset:end]
        if len(json.dumps([asdict(item) for item in page], ensure_ascii=False).encode("utf-8")) > 256 * 1024:
            raise ValueError("code index page exceeds its byte bound; request fewer items")
        return page, self._cursor(kind, digest, end) if end < len(records) else None, len(records)

    def _cursor(self, kind, digest, offset):
        raw = json.dumps([self.index_id, kind, digest, offset], separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw + hmac.digest(self.key, raw, "sha256")).decode("ascii")

    def _offset(self, cursor, kind, digest, count):
        if cursor is None:
            return 0
        fingerprint, offset = self.validate_scope(cursor, kind)
        if fingerprint != digest or not 0 < offset < count:
            raise ValueError("invalid code index cursor")
        return offset

    def validate_scope(self, cursor, kind):
        if cursor is None:
            return None
        try:
            if type(cursor) is not str or len(cursor) > 1024:
                raise ValueError("invalid code index cursor")
            packed = base64.b64decode(cursor.encode("ascii"), altchars=b"-_", validate=True)
            raw, signature = packed[:-32], packed[-32:]
            if not hmac.compare_digest(hmac.digest(self.key, raw, "sha256"), signature):
                raise ValueError("invalid code index cursor")
            scope, collection, fingerprint, offset = json.loads(raw)
            if (scope != self.index_id or collection != kind or type(fingerprint) is not str
                    or type(offset) is not int or offset <= 0):
                raise ValueError("invalid code index cursor")
            return fingerprint, offset
        except (TypeError, UnicodeError, json.JSONDecodeError, ValueError):
            raise ValueError("invalid code index cursor") from None
