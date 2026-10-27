from dataclasses import replace

import pytest

from apps.api.app.domain.system_image.code_impact import conservative_code_impact
from apps.api.app.domain.system_image.code_index import CodeIndexStatus


INDEX = "cidx_" + "a" * 32
SNAPSHOT = "sha256:" + "b" * 64


@pytest.mark.parametrize("change", [
    {"index_id": False}, {"snapshot_hash": []}, {"provider_version": "bad\nversion"},
    {"state": "complete"}, {"state": []}, {"lifetime": "durable"}, {"projection_status": []},
    {"entity_count": False}, {"entity_count": 1}, {"relationship_count": -1},
    {"projection_status": "complete", "entity_count": 0, "relationship_count": 0},
    {"entity_count": 0, "relationship_count": 0},
])
def test_index_status_rejects_false_scope_lifetime_and_unread_counts(change):
    status = CodeIndexStatus(INDEX, SNAPSHOT, "codebase-memory", "unprobed", "pending")
    with pytest.raises(ValueError):
        replace(status, **change)


def traverse(*, seeds=("route",), direction="upstream", max_hops=2, max_entities=10):
    return conservative_code_impact(index_id=INDEX, snapshot_hash=SNAPSHOT, seeds=seeds,
        entity_ids=("module", "handler", "route", "caller"),
        relations=(("handler", "belongs_to", "module"), ("handler", "exposes", "route"),
                   ("caller", "calls", "handler")), direction=direction, max_hops=max_hops,
        max_entities=max_entities, gaps=(), check_current=lambda: None)


def test_impact_follows_containment_call_and_exposure_semantics():
    assert traverse().candidate_ids == ("caller", "handler", "module", "route")
    assert traverse(seeds=("module",), direction="downstream").candidate_ids == ("handler", "module", "route")
    assert traverse(seeds=("caller",), direction="downstream").candidate_ids == ("caller", "handler", "route")
    assert traverse(max_hops=1).truncated
    assert traverse(max_entities=2).truncated
    assert traverse().complete is False


@pytest.mark.parametrize("change", [
    {"seeds": ()}, {"seeds": ([],)}, {"seeds": ("route", "route")}, {"seeds": ("missing",)},
    {"max_hops": True}, {"max_hops": 0}, {"max_hops": 9}, {"max_entities": False},
    {"max_entities": 0}, {"max_entities": 10001}, {"direction": "both"},
])
def test_impact_rejects_unbounded_or_malformed_requests(change):
    with pytest.raises(ValueError):
        traverse(**change)


def test_impact_dto_cannot_promote_static_projection_to_complete():
    result = traverse()
    for change in ({"complete": True}, {"gaps": ()}, {"gaps": ("invented",)},
                   {"method": "native"}, {"candidate_ids": ("handler",)}, {"seed_candidate_ids": ["route"]},
                   {"truncated": 0}, {"index_id": "foreign"}):
        with pytest.raises(ValueError):
            replace(result, **change)
