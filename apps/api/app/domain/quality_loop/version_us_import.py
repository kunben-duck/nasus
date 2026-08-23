from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol


DEFAULT_US_OWNER = "Unassigned"
DEFAULT_US_STATUS = "imported"
DEFAULT_US_RISK = "medium"
DEFAULT_US_PROGRESS = 8
DEFAULT_US_NEXT_ACTION = "Start quality loop"
US_INPUT_KEYS = ("us_items", "items", "work_items", "inputs")


class ExistingUSItemLike(Protocol):
    id: str
    title: str
    owner: str
    status: str
    risk: str
    progress: int
    next_action: str


@dataclass(frozen=True)
class USImportItemDecision:
    id: str
    title: str
    owner: str
    status: str
    risk: str
    progress: int
    next_action: str


@dataclass(frozen=True)
class VersionUSImportDecision:
    imported_items: list[USImportItemDecision]
    ordered_items: list[USImportItemDecision]


def raw_us_items_from_payload(payload: dict[str, Any]) -> list[Any]:
    for key in US_INPUT_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    title = payload.get("title") or payload.get("us_title")
    return [{"title": title}] if title else []


def decide_version_us_import(
    *,
    existing_items: list[ExistingUSItemLike],
    raw_items: list[Any],
    id_factory: Callable[[], str],
) -> VersionUSImportDecision:
    existing_by_id = {item.id: _decision_from_existing(item) for item in existing_items}
    imported: list[USImportItemDecision] = []

    for index, raw in enumerate(raw_items or [{}], start=1):
        normalized = normalize_us_import_item(raw, index=index, id_factory=id_factory)
        merged = merge_us_import_item(existing_by_id.get(normalized.id), normalized)
        existing_by_id[merged.id] = merged
        imported.append(merged)

    imported_ids = {item.id for item in imported}
    ordered = [
        *imported,
        *[item for item_id, item in existing_by_id.items() if item_id not in imported_ids],
    ]
    return VersionUSImportDecision(imported_items=imported, ordered_items=ordered)


def normalize_us_import_item(
    raw: Any,
    *,
    index: int,
    id_factory: Callable[[], str],
) -> USImportItemDecision:
    if isinstance(raw, dict):
        return USImportItemDecision(
            id=str(raw.get("id") or raw.get("us_id") or id_factory()),
            title=str(raw.get("title") or raw.get("summary") or f"Imported US {index}"),
            owner=str(raw.get("owner") or DEFAULT_US_OWNER),
            status=str(raw.get("status") or DEFAULT_US_STATUS),
            risk=str(raw.get("risk") or DEFAULT_US_RISK),
            progress=int(raw.get("progress") or DEFAULT_US_PROGRESS),
            next_action=str(raw.get("next_action") or DEFAULT_US_NEXT_ACTION),
        )

    return USImportItemDecision(
        id=id_factory(),
        title=str(raw or f"Imported US {index}"),
        owner=DEFAULT_US_OWNER,
        status=DEFAULT_US_STATUS,
        risk=DEFAULT_US_RISK,
        progress=DEFAULT_US_PROGRESS,
        next_action=DEFAULT_US_NEXT_ACTION,
    )


def merge_us_import_item(
    existing: USImportItemDecision | None,
    incoming: USImportItemDecision,
) -> USImportItemDecision:
    if existing is None:
        return incoming
    return USImportItemDecision(
        id=incoming.id,
        title=incoming.title or existing.title,
        owner=incoming.owner or existing.owner,
        status=incoming.status or existing.status,
        risk=incoming.risk or existing.risk,
        progress=max(existing.progress, incoming.progress),
        next_action=incoming.next_action or existing.next_action,
    )


def _decision_from_existing(item: ExistingUSItemLike) -> USImportItemDecision:
    return USImportItemDecision(
        id=item.id,
        title=item.title,
        owner=item.owner,
        status=item.status,
        risk=item.risk,
        progress=item.progress,
        next_action=item.next_action,
    )
