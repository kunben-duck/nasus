"""Actual adapter sessions over protocol subprocesses; not native-provider gold."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import sys
import time

import pytest

from apps.api.app.domain.system_image.code_index import CodeIndexCancelled, CodeIndexUnavailable
from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import CodebaseMemoryError
from apps.api.tests.test_code_graph_enrichment import _adapter, _config, _fake_codebase_memory, _source_unit
from apps.api.tests.test_code_graph_execution_control import stalled_provider


def fixture(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    (root / "payments.py").write_text("class PaymentService:\n    def authorize(self):\n        return True\n\n# POST /payments\n# route\n")
    binary, log = _fake_codebase_memory(tmp_path)
    monkeypatch.setenv("FAKE_CBM_CALL_LOG", str(log))
    adapter = _adapter(replace(_config(binary), cache_dir=tmp_path / "indexes"))
    return adapter, _source_unit(root), log


def test_ambiguous_native_endpoint_never_uses_the_last_search_result(tmp_path, monkeypatch):
    adapter, unit, _ = fixture(tmp_path, monkeypatch)
    rows = [["PaymentService", "Class", "1-5"], ["PaymentService", "Method", "2-3"]]
    def payload(tool, *args, **kwargs):
        assert tool == "search_graph"
        return {"cols": ["name", "label", "lines"], "groups": [{"qn_prefix": "project.PaymentService",
            "file": "payments.py", "rows": rows}], "count": 2, "has_more": False}
    monkeypatch.setattr(adapter, "_call", payload)
    first = adapter._load_entities(project="project", provider_namespace="namespace", root=Path(unit.source_root),
        allowed_paths={"payments.py"})
    rows.reverse()
    second = adapter._load_entities(project="project", provider_namespace="namespace", root=Path(unit.source_root),
        allowed_paths={"payments.py"})
    assert first == second
    entities, nodes, _, ambiguous_count = first
    assert len(entities) == 2 and not nodes and ambiguous_count == 1
    assert all(item.identity_status == "ambiguous" for item in entities)


def test_prepared_index_is_real_reused_and_unknown_counts_are_not_zero(tmp_path, monkeypatch):
    adapter, unit, log = fixture(tmp_path, monkeypatch)
    index = adapter.open_index([unit], check_current=lambda: None)
    assert index.status().state == "pending"
    assert index.status().entity_count is None
    prepared = index.prepare_index()
    assert prepared.state == "ready" and prepared.projection_status is None
    assert prepared.lifetime == "worker_owned_session"
    assert index._root.exists() and index._cache.exists()
    assert index.prepare_index() == prepared
    first = index.entities(limit=2)
    second = index.entities(cursor=first.next_cursor, limit=2)
    assert len(first.items) == 2 and len(second.items) == 1
    assert first.normalized_count == 3 and first.enumeration == "unknown"
    assert not second.next_cursor
    assert {item.provider_node_id for item in (*first.items, *second.items)} == {
        item.provider_node_id for item in index.read_projection().entities}
    relations = index.relations(limit=1)
    next_relations = index.relations(cursor=relations.next_cursor, limit=1)
    assert len(relations.items) == len(next_relations.items) == 1
    assert not next_relations.next_cursor
    status = index.status()
    assert status.entity_count == 3 and status.relationship_count == 2 and status.projection_status == "partial"
    calls = [json.loads(line)["tool"] for line in log.read_text().splitlines()]
    assert calls.count("index_repository") == calls.count("search_graph") == 1
    assert "repo_path" not in json.dumps(asdict(status))
    assert set(index.capabilities().operations) == {"capabilities", "prepare_index", "status", "entities", "relations", "locate", "impact", "cancel"}
    assert "prepare_index" not in adapter.capabilities().operations
    root, cache = index._root, index._cache
    index.close()
    index.close()
    assert not root.exists() and not cache.exists()
    assert index.status().state == "closed"
    assert index.status().entity_count is None
    with pytest.raises(CodeIndexUnavailable):
        index.entities()


@pytest.mark.parametrize("limit", [True, 0, -1, 51, 1.5])
def test_page_bounds_are_checked_before_native_queries(tmp_path, monkeypatch, limit):
    adapter, unit, log = fixture(tmp_path, monkeypatch)
    with adapter.open_index([unit], check_current=lambda: None) as index:
        with pytest.raises(ValueError, match="limit"):
            index.entities(limit=limit)
        assert "search_graph" not in log.read_text()
        assert index.status().state == "ready"


def test_cursors_are_bound_to_exact_index_and_collection(tmp_path, monkeypatch):
    adapter, unit, _ = fixture(tmp_path, monkeypatch)
    with adapter.open_index([unit], check_current=lambda: None) as first:
        cursor = first.entities(limit=1).next_cursor
        with pytest.raises(ValueError, match="cursor"):
            first.relations(cursor=cursor, limit=1)
        with pytest.raises(ValueError, match="cursor"):
            first.entities(cursor=cursor[:-2] + "!!", limit=1)
        with adapter.open_index([unit], check_current=lambda: None) as second:
            assert second.status().snapshot_hash == first.status().snapshot_hash
            assert second.status().index_id != first.status().index_id
            with pytest.raises(ValueError, match="cursor"):
                second.entities(cursor=cursor, limit=1)
            assert second.status().state == "ready"
            assert second.status().entity_count is None
        assert first.entities(cursor=cursor, limit=1).items


def test_locate_and_impact_are_fixed_static_projections_not_coverage(tmp_path, monkeypatch):
    adapter, unit, log = fixture(tmp_path, monkeypatch)
    with adapter.open_index([unit], check_current=lambda: None) as index:
        by_name = {item.name: item for item in index.read_projection().entities}
        route = by_name["POST /payments"]
        assert index.locate(route.provider_node_id) == route
        assert route.location_precision == "exact"
        impact = index.impact([route.provider_node_id], max_hops=2)
        assert len(impact.candidate_ids) == 3 and impact.complete is False
        assert impact.method == "nasus.normalized-static-graph.v1"
        assert "dynamic_impact_not_verified" in impact.gaps
        bounded = index.impact([route.provider_node_id], max_entities=1)
        assert bounded.truncated and bounded.candidate_ids == (route.provider_node_id,)
        assert "impact_traversal_truncated" in bounded.gaps
        with pytest.raises(CodeIndexUnavailable):
            index.locate("not-in-this-index")
        with pytest.raises(CodeIndexUnavailable):
            index.impact(["not-in-this-index"])
        with pytest.raises(ValueError):
            index.impact([route.provider_node_id], max_hops=True)
        assert "impact" not in [json.loads(line)["tool"] for line in log.read_text().splitlines()]


def test_source_changes_cannot_be_hidden_by_cached_projection(tmp_path, monkeypatch):
    adapter, unit, _ = fixture(tmp_path, monkeypatch)
    with adapter.open_index([unit], check_current=lambda: None) as index:
        index.entities(limit=1)
        Path(unit.source_root, unit.relative_path).write_text("CHANGED\n")
        with pytest.raises(CodebaseMemoryError, match="source changed"):
            index.entities(limit=1)
        assert index.status().state == "failed" and index.status().entity_count is None


def test_cached_reads_reauthorize_and_revoked_cleanup_still_works(tmp_path, monkeypatch):
    adapter, unit, _ = fixture(tmp_path, monkeypatch)
    revoked, checks = [], []

    def current():
        checks.append(True)
        if revoked:
            raise PermissionError("revoked")

    index = adapter.open_index([unit], check_current=current)
    index.prepare_index()
    index.entities(limit=1)
    root, cache = index._root, index._cache
    revoked.append(True)
    with pytest.raises(PermissionError):
        index.entities(limit=1)
    with pytest.raises(PermissionError):
        index.status()
    with pytest.raises(PermissionError):
        index.cancel()
    index.close()
    assert not root.exists() and not cache.exists() and len(checks) > 5


def test_standalone_cancel_interrupts_real_native_process_and_removes_index(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "payments.py").write_text("def pay():\n    return True\n")
    binary, marker = stalled_provider(tmp_path)
    adapter = _adapter(_config(binary))
    index = adapter.open_index([_source_unit(root)], check_current=lambda: None)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(index.prepare_index)
        deadline = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert marker.exists() and index.status().state == "preparing"
        started = time.monotonic()
        assert index.cancel().state == "cancellation_requested"
        with pytest.raises(CodeIndexCancelled):
            future.result(timeout=3)
        assert time.monotonic() - started < 3
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)
    assert index.status().state == "cancelled"
    assert not index._root.exists() and not index._cache.exists()
    index.close()


def test_context_entry_failure_and_keyboard_interrupt_close_owned_resources(tmp_path, monkeypatch):
    adapter, unit, _ = fixture(tmp_path, monkeypatch)
    original = adapter._call

    def call(tool, payload, **kwargs):
        if tool == "search_graph":
            raise KeyboardInterrupt()
        return original(tool, payload, **kwargs)

    adapter._call = call
    index = adapter.open_index([unit], check_current=lambda: None)
    with pytest.raises(KeyboardInterrupt):
        with index:
            index.entities(limit=1)
    assert index.status().state == "closed"
    assert not index._root.exists() and not index._cache.exists()


def test_cancel_while_waiting_for_provider_lock_does_not_start_a_command(tmp_path, monkeypatch):
    adapter, unit, log = fixture(tmp_path, monkeypatch)
    index = adapter.open_index([unit], check_current=lambda: None)
    with adapter._lock, ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(index.prepare_index)
        deadline = time.monotonic() + 3
        while index._root is None and time.monotonic() < deadline:
            time.sleep(.01)
        assert index.status().state == "preparing"
        index.cancel()
        with pytest.raises(CodeIndexCancelled):
            future.result(timeout=3)
    assert not log.exists()
    assert not index._root.exists() and not index._cache.exists()
    index.close()


def test_native_degraded_state_is_distinct_from_projection_completeness(tmp_path, monkeypatch):
    adapter, unit, _ = fixture(tmp_path, monkeypatch)
    original = adapter._call

    def call(tool, payload, **kwargs):
        result = original(tool, payload, **kwargs)
        return {**result, "status": "degraded"} if tool == "index_repository" else result

    adapter._call = call
    with adapter.open_index([unit], check_current=lambda: None) as index:
        assert index.status().state == "degraded" and index.status().projection_status is None
        result = index.read_projection()
        assert "native_index_degraded" in {gap.reason for gap in result.provider_observations[0].gaps}
        assert index.status().projection_status == "partial"


def test_pending_index_cannot_be_read_or_prepared_after_cancellation(tmp_path, monkeypatch):
    adapter, unit, log = fixture(tmp_path, monkeypatch)
    index = adapter.open_index([unit], check_current=lambda: None)
    with pytest.raises(CodeIndexUnavailable):
        index.read_projection()
    assert index.status().state == "pending" and index.status().entity_count is None
    index.cancel()
    with pytest.raises(CodeIndexCancelled):
        index.prepare_index()
    assert not log.exists()
    index.close()
