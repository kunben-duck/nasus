"""Bounded partitions for a provider without a relationship cursor API."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, replace
import json


RELATIONSHIP_COLUMNS = ("a.qualified_name", "a.file_path", "type(r)", "b.qualified_name", "b.file_path",
                        "r.confidence", "r.strategy", "r.candidates")


class CodeGraphScanError(ValueError):
    pass


@dataclass(frozen=True)
class _Scope:
    source_paths: tuple[str, ...]
    source_names: tuple[str, ...] | None = None
    target_paths: tuple[str, ...] | None = None
    target_names: tuple[str, ...] | None = None


class CodeGraphRelationshipScanner:
    def __init__(self, *, call, project, allowed_paths, node_keys, page_size, max_queries):
        if any(type(value) is not int or value <= 0 for value in (page_size, max_queries)):
            raise CodeGraphScanError("code graph scan requires positive integer limits")
        self.call = call
        self.project = project
        self.allowed_paths = tuple(sorted(allowed_paths))
        self.names = defaultdict(set)
        for name, path in node_keys:
            self.names[path].add(name)
        self.page_limit = min(page_size + 1, 100000)
        self.max_queries = max_queries
        self.query_count = 0
        self.complete = False
        self.gaps = set()

    def pages(self):
        targets = self.allowed_paths if len(self.allowed_paths) <= 200 else None
        pending = deque(_Scope(self.allowed_paths[start:start + 100], target_paths=targets)
                        for start in range(0, len(self.allowed_paths), 100))
        while pending:
            if self.query_count >= self.max_queries:
                self.gaps.add("query-budget-exceeded")
                return
            scope = pending.popleft()
            # A fully narrowed pair has only the provider's raw relationship
            # kinds left; use a bounded probe, never an invented offset cursor.
            limit = max(64, self.page_limit) if scope.source_names and scope.target_names else self.page_limit
            self.query_count += 1
            payload = self.call("query_graph", {"project": self.project, "query": self._query(scope, limit), "format": "json"})
            rows = self._rows(payload, limit)
            if len(rows) == limit:
                children = self._split(scope)
                if children is None:
                    self.gaps.add("unsplittable-provider-row-limit")
                else:
                    pending.extendleft(reversed(children))
                # The parent is not a page: counting it would double-count
                # evidence and make LIMIT's arbitrary prefix authoritative.
                continue
            yield rows
        self.complete = not self.gaps

    @staticmethod
    def _rows(payload, limit):
        if payload.get("columns") != list(RELATIONSHIP_COLUMNS):
            raise CodeGraphScanError("code graph relationship schema is incompatible")
        rows = payload.get("rows")
        if (type(rows) is not list or len(rows) > limit
                or any(type(row) is not list or len(row) != len(RELATIONSHIP_COLUMNS) for row in rows)):
            raise CodeGraphScanError("code graph relationship rows are invalid")
        total = payload.get("total", len(rows))
        if type(total) is not int or total != len(rows):
            raise CodeGraphScanError("code graph relationship row count is invalid")
        return rows

    def _split(self, scope):
        for field in ("source_paths", "source_names", "target_paths", "target_names"):
            values = getattr(scope, field)
            if values is None:
                if field == "target_paths":
                    values = self.allowed_paths
                else:
                    paths = scope.source_paths if field == "source_names" else scope.target_paths
                    values = tuple(sorted({name for path in paths for name in self.names[path]}))
                return [replace(scope, **{field: values})] if values else []
            if len(values) > 1:
                middle = len(values) // 2
                return [replace(scope, **{field: values[:middle]}), replace(scope, **{field: values[middle:]})]
        return None

    @staticmethod
    def _query(scope, limit):
        predicates = []
        for field, values in (("a.file_path", scope.source_paths), ("a.qualified_name", scope.source_names),
                              ("b.file_path", scope.target_paths), ("b.qualified_name", scope.target_names)):
            if values is not None:
                predicates.append(field + " IN [" + ",".join(json.dumps(value) for value in values) + "]")
        return "MATCH (a)-[r]->(b) WHERE " + " AND ".join(predicates) + " RETURN " + ", ".join(RELATIONSHIP_COLUMNS) + f" LIMIT {limit}"
