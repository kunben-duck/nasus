"""Conservative traversal respects dependency and containment edge directions."""
from __future__ import annotations

from .code_index import CodeImpactProjection


def conservative_code_impact(*, index_id, snapshot_hash, seeds, entity_ids, relations,
                             direction, max_hops, max_entities, gaps, check_current):
    seeds = tuple(seeds)
    if (not seeds or len(seeds) > 100 or any(type(seed) is not str or not 1 <= len(seed) <= 240 for seed in seeds)
            or len(set(seeds)) != len(seeds) or direction not in {"upstream", "downstream"}
            or type(max_hops) is not int or not 1 <= max_hops <= 8
            or type(max_entities) is not int or not len(seeds) <= max_entities <= 10000):
        raise ValueError("invalid code impact bounds")
    if not set(seeds) <= set(entity_ids):
        raise ValueError("code impact seed is not in this graph")
    adjacency = {}
    for source, kind, target in relations:
        if kind not in {"belongs_to", "calls", "depends_on", "exposes"}:
            raise ValueError("unsupported code impact relation")
        # Member -> owner is stored opposite to owner -> exposed interface.
        reverse = (direction == "upstream") != (kind == "belongs_to")
        if reverse:
            source, target = target, source
        adjacency.setdefault(source, set()).add(target)
    visited, frontier, truncated = set(seeds), set(seeds), False
    for _ in range(max_hops):
        check_current()
        following = set().union(*(adjacency.get(item, set()) for item in frontier)) - visited
        available = max_entities - len(visited)
        selected = set(sorted(following)[:available])
        truncated |= len(selected) < len(following)
        visited.update(selected)
        frontier = selected
        if not frontier or truncated:
            break
    truncated |= any(adjacency.get(item, set()) - visited for item in frontier)
    reasons = tuple(sorted({"dynamic_impact_not_verified", *gaps,
                           *(["impact_traversal_truncated"] if truncated else [])}))
    return CodeImpactProjection(index_id, snapshot_hash, tuple(sorted(seeds)), tuple(sorted(visited)),
        direction, max_hops, truncated, gaps=reasons)
