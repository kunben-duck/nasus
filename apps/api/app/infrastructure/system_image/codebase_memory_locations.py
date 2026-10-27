from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ...domain.system_image.evidence import source_lines


def load_exact_locations(
    call: Callable[..., dict[str, Any]], *, project: str, root: Path,
    identities: list[tuple[str, str]],
) -> dict[tuple[str, str], tuple[int, int]]:
    """Resolve search results using public node properties, not provider DBs."""
    columns = ["n.qualified_name", "n.file_path", "n.start_line", "n.end_line"]
    locations: dict[tuple[str, str], tuple[int, int]] = {}
    line_counts: dict[str, int] = {}
    for offset in range(0, len(identities), 100):
        batch = identities[offset:offset + 100]
        names = ",".join(json.dumps(qn) for qn, _path in batch)
        paths = ",".join(json.dumps(path) for path in sorted({path for _qn, path in batch}))
        payload = call("query_graph", {
            "project": project, "format": "json",
            "query": f"MATCH (n) WHERE n.qualified_name IN [{names}] AND n.file_path IN [{paths}] "
            + "RETURN " + ", ".join(columns) + " LIMIT 1001",
        })
        if payload.get("columns") != columns or not isinstance(payload.get("rows"), list):
            raise ValueError("code graph location schema is incompatible")
        # Duplicate QNs or a truncated answer are not precise symbol identities.
        if len(payload["rows"]) >= 1001:
            continue
        seen: set[tuple[str, str]] = set()
        ambiguous: set[tuple[str, str]] = set()
        allowed = set(batch)
        for row in payload["rows"]:
            if not isinstance(row, list) or len(row) != 4:
                raise ValueError("code graph location row is invalid")
            key = (str(row[0]), str(row[1]))
            if key not in allowed:
                continue
            if key in seen:
                ambiguous.add(key)
                continue
            seen.add(key)
            if not all(str(value).isdigit() for value in row[2:]):
                continue
            start, end = int(row[2]), int(row[3])
            path = key[1]
            if path not in line_counts:
                try:
                    line_counts[path] = len(source_lines((root / path).read_bytes().decode("utf-8")))
                except UnicodeError:
                    line_counts[path] = 0
            if 1 <= start <= end <= line_counts[path]:
                locations[key] = (start, end)
        for key in ambiguous:
            locations.pop(key, None)
    return locations
