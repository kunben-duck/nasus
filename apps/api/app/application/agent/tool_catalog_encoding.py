"""Lossless planner-only registry encoding; never an execution authority."""
from __future__ import annotations

from collections import Counter
import json
import re


LEGACY_CATALOG_SCHEMA = "nasus.agent-tool-catalog.v2"
CATALOG_SCHEMA = "nasus.agent-tool-catalog.v3"
CATALOG_ENCODING_INSTRUCTIONS = (
    "In [tool_catalog], nasus.agent-tool-catalog.v2 and nasus.agent-tool-catalog.v3 encode each available_tool_ids entry "
    "as [prefix_index,[suffixes]]. Expand every suffix in each ordered group: "
    "the complete canonical tool ID is tool_id_prefixes[prefix_index] + suffix. "
    "v2 prefixes end at a dot; v3 also factors recurring underscore-delimited prefixes. "
    "Groups and suffixes retain registry order. "
    "relevant_tools always uses full canonical IDs and complete governance fields. "
    "Return full IDs, never a suffix or an encoded pair. Registry membership is not "
    "permission: do not infer missing inputs, confirmation, approval or execution authority."
)
_TOOL_ID = re.compile(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\Z")


def _validate_ids(ids: list[str], count: int) -> list[str]:
    if (type(count) is not int or count < 0 or count != len(ids)
            or any(type(value) is not str or len(value) > 256 or not _TOOL_ID.fullmatch(value) for value in ids)
            or len(set(ids)) != count):
        raise ValueError("invalid planner tool registry")
    return ids


def planner_registry_fields(ids: list[str]) -> dict:
    """Factor recurring ID prefixes without losing IDs or their order."""
    _validate_ids(ids, len(ids))
    frequencies = Counter(value[:index + 1] for value in ids
                          for index, character in enumerate(value)
                          if character in "._" and index + 1 < len(value))
    assignments: list[str] = []
    for value in ids:
        recurring = [value[:index + 1] for index, character in enumerate(value)
                     if character in "._" and index + 1 < len(value)
                     and frequencies[value[:index + 1]] >= 2]
        assignments.append(max(recurring, key=len) if recurring else "")
    legacy = {"available_tool_ids": ids}
    size = lambda value: len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    encoded = _encoded_registry(ids, assignments)
    # A longer prefix can cost more in table/group overhead than it saves in
    # suffixes. Coalesce only when the entire lossless representation shrinks.
    while True:
        best, best_size = None, size(encoded)
        for prefix in encoded["tool_id_prefixes"]:
            if not prefix:
                continue
            parents = [value for value, count in frequencies.items()
                       if count >= 2 and len(value) < len(prefix) and prefix.startswith(value)]
            for parent in (*parents, ""):
                candidate = [parent if value == prefix else value for value in assignments]
                candidate_encoded = _encoded_registry(ids, candidate)
                candidate_size = size(candidate_encoded)
                if candidate_size < best_size:
                    best, best_size = (candidate, candidate_encoded), candidate_size
        if best is None:
            break
        assignments, encoded = best
    return encoded if size(encoded) < size(legacy) else legacy


def _encoded_registry(ids: list[str], assignments: list[str]) -> dict:
    prefixes, indices, groups = [], {}, []
    for value, prefix in zip(ids, assignments):
        if prefix not in indices:
            indices[prefix] = len(prefixes)
            prefixes.append(prefix)
        index = indices[prefix]
        if groups and groups[-1][0] == index:
            groups[-1][1].append(value[len(prefix):])
        else:
            groups.append([index, [value[len(prefix):]]])
    # Frequent group references get single-digit indices; registry order is
    # carried by the groups, not by the prefix table.
    references = Counter(group[0] for group in groups)
    order = sorted(range(len(prefixes)), key=lambda index: (-references[index], index))
    remap = {previous: current for current, previous in enumerate(order)}
    prefixes = [prefixes[index] for index in order]
    groups = [[remap[index], suffixes] for index, suffixes in groups]
    return {"schema": CATALOG_SCHEMA, "tool_id_prefixes": prefixes, "available_tool_ids": groups}


def planner_catalog_tool_ids(payload: dict) -> list[str]:
    """Decode v3, historical v2, or an unencoded planner snapshot."""
    if type(payload) is not dict or type(payload.get("available_tool_ids")) is not list:
        raise ValueError("invalid planner tool registry")
    entries = payload["available_tool_ids"]
    if "schema" not in payload:
        if "tool_id_prefixes" in payload:
            raise ValueError("invalid planner tool registry")
        return _validate_ids(entries, payload.get("available_count"))
    schema = payload["schema"]
    if schema not in (LEGACY_CATALOG_SCHEMA, CATALOG_SCHEMA):
        raise ValueError("unsupported planner tool registry schema")
    prefixes = payload.get("tool_id_prefixes")
    if (type(prefixes) is not list
            or any(type(prefix) is not str or len(prefix) > 256
                   or not _valid_prefix(prefix, schema)
                   for prefix in prefixes)
            or len(set(prefixes)) != len(prefixes)):
        raise ValueError("invalid planner tool registry")
    ids = []
    for entry in entries:
        if (type(entry) is not list or len(entry) != 2 or type(entry[0]) is not int
                or not 0 <= entry[0] < len(prefixes) or type(entry[1]) is not list or not entry[1]
                or any(type(suffix) is not str or not suffix for suffix in entry[1])):
            raise ValueError("invalid planner tool registry")
        ids.extend(prefixes[entry[0]] + suffix for suffix in entry[1])
    return _validate_ids(ids, payload.get("available_count"))


def _valid_prefix(prefix: str, schema: str) -> bool:
    if not prefix:
        return True
    if prefix.endswith("."):
        return bool(_TOOL_ID.fullmatch(prefix[:-1]))
    return schema == CATALOG_SCHEMA and prefix.endswith("_") and bool(_TOOL_ID.fullmatch(prefix))
