from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping


_MISSING = object()
MISSING_VALUE = {"$nasus_missing": True}


@dataclass(frozen=True)
class StructuredConflict:
    path: str
    conflict_kind: str
    base_value: Any
    left_value: Any
    right_value: Any
    merge_hint: str
    requires_manual_resolution: bool = True


@dataclass(frozen=True)
class StructuredMergeDecision:
    merged_value: Any
    auto_merged_patch: list[dict[str, Any]] = field(default_factory=list)
    conflict_entries: list[StructuredConflict] = field(default_factory=list)

    @property
    def ready_for_approval(self) -> bool:
        return not self.conflict_entries


def three_way_merge(base: Any, left: Any, right: Any) -> StructuredMergeDecision:
    """Merge JSON-compatible values without guessing through true conflicts.

    The merge follows Nasus' canonical rules: one-sided changes are accepted,
    nested objects are merged recursively, keyed object arrays are merged by
    stable ``id``, and ambiguous scalars/text/ordered arrays remain explicit
    conflict entries for a human or governed Agent decision.
    """

    patches: list[dict[str, Any]] = []
    conflicts: list[StructuredConflict] = []
    merged = _merge_node(
        base,
        left,
        right,
        path="",
        patches=patches,
        conflicts=conflicts,
    )
    return StructuredMergeDecision(
        merged_value=None if merged is _MISSING else merged,
        auto_merged_patch=patches,
        conflict_entries=conflicts,
    )


def apply_manual_resolutions(
    decision: StructuredMergeDecision,
    resolutions: Mapping[str, Any],
) -> StructuredMergeDecision:
    """Apply explicit path resolutions and retain every unresolved conflict."""

    merged = deepcopy(decision.merged_value)
    unresolved: list[StructuredConflict] = []
    patches = list(decision.auto_merged_patch)
    for conflict in decision.conflict_entries:
        if conflict.path not in resolutions:
            unresolved.append(conflict)
            continue
        resolved_value = _manual_value(conflict, resolutions[conflict.path])
        merged = _set_pointer(merged, conflict.path, resolved_value)
        patches.append(_patch_for(conflict.path, resolved_value, source="manual"))
    return StructuredMergeDecision(
        merged_value=merged,
        auto_merged_patch=patches,
        conflict_entries=unresolved,
    )


def _merge_node(
    base: Any,
    left: Any,
    right: Any,
    *,
    path: str,
    patches: list[dict[str, Any]],
    conflicts: list[StructuredConflict],
) -> Any:
    if _equal(base, left) and _equal(left, right):
        return _clone(base)

    # Recurse structured containers before applying one-sided shortcuts so the
    # resulting patch remains field-addressable and auditable. A delete-vs-edit
    # candidate is intentionally not recursed because that would erase the
    # deletion intent while silently accepting individual child values.
    if _recurse_objects(base, left, right):
        return _merge_objects(base, left, right, path=path, patches=patches, conflicts=conflicts)
    if _recurse_keyed_arrays(base, left, right):
        return _merge_keyed_arrays(base, left, right, path=path, patches=patches, conflicts=conflicts)

    if _equal(left, right):
        if not _equal(base, left):
            patches.append(_patch_for(path, left))
        return _clone(left)
    if _equal(left, base):
        patches.append(_patch_for(path, right))
        return _clone(right)
    if _equal(right, base):
        patches.append(_patch_for(path, left))
        return _clone(left)

    conflicts.append(
        StructuredConflict(
            path=path,
            conflict_kind=_conflict_kind(base, left, right),
            base_value=_public_value(base),
            left_value=_public_value(left),
            right_value=_public_value(right),
            merge_hint=_merge_hint(base, left, right),
        )
    )
    return _clone(base if base is not _MISSING else left)


def _merge_objects(
    base: Any,
    left: Any,
    right: Any,
    *,
    path: str,
    patches: list[dict[str, Any]],
    conflicts: list[StructuredConflict],
) -> dict[str, Any]:
    base_map = {} if base is _MISSING else base
    left_map = {} if left is _MISSING else left
    right_map = {} if right is _MISSING else right
    result: dict[str, Any] = {}
    keys = list(dict.fromkeys([*base_map.keys(), *left_map.keys(), *right_map.keys()]))
    for key in keys:
        child = _merge_node(
            base_map.get(key, _MISSING),
            left_map.get(key, _MISSING),
            right_map.get(key, _MISSING),
            path=_join_pointer(path, str(key)),
            patches=patches,
            conflicts=conflicts,
        )
        if child is not _MISSING:
            result[key] = child
    return result


def _merge_keyed_arrays(
    base: Any,
    left: Any,
    right: Any,
    *,
    path: str,
    patches: list[dict[str, Any]],
    conflicts: list[StructuredConflict],
) -> list[Any]:
    base_items = [] if base is _MISSING else base
    left_items = [] if left is _MISSING else left
    right_items = [] if right is _MISSING else right
    base_map = {str(item["id"]): item for item in base_items}
    left_map = {str(item["id"]): item for item in left_items}
    right_map = {str(item["id"]): item for item in right_items}
    ids = list(dict.fromkeys([*base_map.keys(), *left_map.keys(), *right_map.keys()]))
    result: list[Any] = []
    for item_id in ids:
        item = _merge_node(
            base_map.get(item_id, _MISSING),
            left_map.get(item_id, _MISSING),
            right_map.get(item_id, _MISSING),
            path=_join_pointer(path, item_id),
            patches=patches,
            conflicts=conflicts,
        )
        if item is not _MISSING:
            result.append(item)
    return result


def _manual_value(conflict: StructuredConflict, resolution: Any) -> Any:
    if isinstance(resolution, Mapping) and "choice" in resolution:
        choice = str(resolution["choice"]).strip().lower()
        if choice == "base":
            return _from_public_value(conflict.base_value)
        if choice == "left":
            return _from_public_value(conflict.left_value)
        if choice == "right":
            return _from_public_value(conflict.right_value)
        if choice == "custom" and "value" in resolution:
            return _from_public_value(resolution["value"])
        raise ValueError(f"unsupported manual merge choice for {conflict.path}: {choice}")
    return _from_public_value(resolution)


def _set_pointer(document: Any, path: str, value: Any) -> Any:
    if path in {"", "/"}:
        return None if value is _MISSING else deepcopy(value)
    segments = [_unescape_pointer(part) for part in path.lstrip("/").split("/")]
    target = document
    for segment in segments[:-1]:
        if isinstance(target, list):
            target = next(item for item in target if isinstance(item, dict) and str(item.get("id")) == segment)
        else:
            target = target[segment]
    leaf = segments[-1]
    if isinstance(target, list):
        index = next(
            index
            for index, item in enumerate(target)
            if isinstance(item, dict) and str(item.get("id")) == leaf
        )
        if value is _MISSING:
            target.pop(index)
        else:
            target[index] = deepcopy(value)
    else:
        if value is _MISSING:
            target.pop(leaf, None)
        else:
            target[leaf] = deepcopy(value)
    return document


def _patch_for(path: str, value: Any, *, source: str = "auto") -> dict[str, Any]:
    if value is _MISSING:
        return {"op": "remove", "path": path, "source": source}
    return {
        "op": "replace" if path else "replace_root",
        "path": path,
        "value": deepcopy(value),
        "source": source,
    }


def _keyed_arrays(*values: Any) -> bool:
    present = [value for value in values if value is not _MISSING]
    return bool(present) and all(
        isinstance(value, list)
        and all(isinstance(item, dict) and "id" in item for item in value)
        for value in present
    )


def _recurse_objects(base: Any, left: Any, right: Any) -> bool:
    return (
        isinstance(left, dict)
        and isinstance(right, dict)
        and (base is _MISSING or isinstance(base, dict))
    )


def _recurse_keyed_arrays(base: Any, left: Any, right: Any) -> bool:
    return (
        isinstance(left, list)
        and isinstance(right, list)
        and (base is _MISSING or isinstance(base, list))
        and _keyed_arrays(base, left, right)
    )


def _all_dict_or_missing(*values: Any) -> bool:
    return all(value is _MISSING or isinstance(value, dict) for value in values)


def _all_list_or_missing(*values: Any) -> bool:
    return all(value is _MISSING or isinstance(value, list) for value in values)


def _conflict_kind(base: Any, left: Any, right: Any) -> str:
    present = [value for value in (base, left, right) if value is not _MISSING]
    if any(isinstance(value, list) for value in present):
        return "array"
    if any(isinstance(value, dict) for value in present):
        return "object"
    if any(isinstance(value, str) and ("\n" in value or len(value) >= 120) for value in present):
        return "text"
    return "scalar"


def _merge_hint(base: Any, left: Any, right: Any) -> str:
    kind = _conflict_kind(base, left, right)
    if kind == "array":
        return "Ordered arrays without stable ids require an explicit ordering decision."
    if kind == "text":
        return "Review both text revisions and submit an explicit base, left, right, or custom value."
    if kind == "object":
        return "The candidate types differ; select the intended object value explicitly."
    return "Both candidates changed the same scalar; select base, left, right, or a custom value."


def _public_value(value: Any) -> Any:
    return deepcopy(MISSING_VALUE if value is _MISSING else value)


def _from_public_value(value: Any) -> Any:
    if value == MISSING_VALUE:
        return _MISSING
    return deepcopy(value)


def _clone(value: Any) -> Any:
    return _MISSING if value is _MISSING else deepcopy(value)


def _equal(left: Any, right: Any) -> bool:
    if left is _MISSING or right is _MISSING:
        return left is right
    return left == right


def _join_pointer(path: str, segment: str) -> str:
    escaped = segment.replace("~", "~0").replace("/", "~1")
    return f"{path}/{escaped}" if path else f"/{escaped}"


def _unescape_pointer(segment: str) -> str:
    return segment.replace("~1", "/").replace("~0", "~")


__all__ = [
    "MISSING_VALUE",
    "StructuredConflict",
    "StructuredMergeDecision",
    "apply_manual_resolutions",
    "three_way_merge",
]
