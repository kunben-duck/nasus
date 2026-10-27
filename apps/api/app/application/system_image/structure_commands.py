from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


UNFINISHED_STRUCTURE_STATUSES = frozenset({"pending", "running", "waiting_confirmation", "waiting_approval"})


@dataclass(frozen=True)
class StructureCommandSummary:
    invocation_id: str
    target_baseline_id: str
    status: str
    idempotency_key: Optional[str]


@dataclass(frozen=True)
class StructureCommandPage:
    project_id: str
    plan_id: str
    plan_digest: str
    items: tuple[StructureCommandSummary, ...]
    next_after_id: Optional[str]


class StructureCommandQueryPort(Protocol):
    def unfinished(self, *, project_id: str, plan_id: str, plan_digest: str, actor_id: str,
                   after_id: str, limit: int) -> tuple[StructureCommandSummary, ...]: ...
