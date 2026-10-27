"""Index availability is separate from knowledge approval and graph completeness."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

from .code_provider import CodeProjectionGap, CodeProviderCapabilities


INDEX_STATES = frozenset({"pending", "preparing", "ready", "degraded", "cancellation_requested",
                          "cancelled", "failed", "closed"})


class CodeIndexUnavailable(RuntimeError):
    pass


class CodeIndexCancelled(RuntimeError):
    pass


def _scope(index_id, snapshot_hash):
    if (type(index_id) is not str or re.fullmatch(r"cidx_[0-9a-f]{32}", index_id) is None
            or type(snapshot_hash) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", snapshot_hash) is None):
        raise ValueError("invalid prepared code index scope")


@dataclass(frozen=True)
class CodeIndexStatus:
    index_id: str
    snapshot_hash: str
    provider: str
    provider_version: str
    state: str
    lifetime: str = "worker_owned_session"
    projection_status: Optional[str] = None
    entity_count: Optional[int] = None
    relationship_count: Optional[int] = None

    def __post_init__(self):
        _scope(self.index_id, self.snapshot_hash)
        CodeProviderCapabilities(self.provider, self.provider_version, ())
        if (type(self.state) is not str or self.state not in INDEX_STATES or self.lifetime != "worker_owned_session"
                or type(self.projection_status) not in {str, type(None)}
                or self.projection_status not in {None, "complete", "partial"}):
            raise ValueError("invalid prepared code index status")
        for count in (self.entity_count, self.relationship_count):
            if count is not None and (type(count) is not int or not 0 <= count <= 100000000):
                raise ValueError("invalid prepared code index count")
        if (self.projection_status is None) != (self.entity_count is None and self.relationship_count is None):
            raise ValueError("unread index cannot claim projection counts")
        if (self.entity_count is None) != (self.relationship_count is None):
            raise ValueError("index projection requires both counts")
        if self.state in {"pending", "preparing", "cancelled", "failed", "closed"} and self.projection_status is not None:
            raise ValueError("unavailable index cannot expose a current projection")


@dataclass(frozen=True)
class CodeImpactProjection:
    index_id: str
    snapshot_hash: str
    seed_candidate_ids: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    direction: str
    max_hops: int
    truncated: bool
    complete: bool = False
    method: str = "nasus.normalized-static-graph.v1"
    gaps: tuple[str, ...] = ("dynamic_impact_not_verified",)

    def __post_init__(self):
        _scope(self.index_id, self.snapshot_hash)
        if (type(self.direction) is not str or self.direction not in {"upstream", "downstream"} or type(self.max_hops) is not int
                or not 1 <= self.max_hops <= 8 or type(self.truncated) is not bool
                or self.complete is not False or self.method != "nasus.normalized-static-graph.v1"
                or type(self.seed_candidate_ids) is not tuple or type(self.candidate_ids) is not tuple
                or not 1 <= len(self.seed_candidate_ids) <= 100 or not 1 <= len(self.candidate_ids) <= 10000
                or any(type(ident) is not str or not 1 <= len(ident) <= 240 for ident in (*self.seed_candidate_ids, *self.candidate_ids))
                or len(set(self.seed_candidate_ids)) != len(self.seed_candidate_ids) or not set(self.seed_candidate_ids) <= set(self.candidate_ids)
                or type(self.gaps) is not tuple or not 1 <= len(self.gaps) <= 66
                or len(set(self.candidate_ids)) != len(self.candidate_ids)):
            raise ValueError("invalid conservative code impact projection")
        for gap in self.gaps:
            CodeProjectionGap(gap)
        if len(set(self.gaps)) != len(self.gaps) or "dynamic_impact_not_verified" not in self.gaps:
            raise ValueError("code impact must preserve explicit unknowns")
