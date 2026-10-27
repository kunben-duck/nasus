"""Public-query partition fixtures, not a native-provider completeness benchmark."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import sys

import pytest

from apps.api.app.application.system_image.source_ports import SourceTextUnit
from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import CodebaseMemoryCodeIntelligenceAdapter, CodebaseMemoryError
from apps.api.tests.test_code_graph_enrichment import _config


COLUMNS = ["a.qualified_name", "a.file_path", "type(r)", "b.qualified_name", "b.file_path",
           "r.confidence", "r.strategy", "r.candidates"]


def fixture(tmp_path, *, max_relationships=20, page_size=2):
    root = tmp_path / "source"
    root.mkdir()
    definitions = [("pkg.a", "a.py"), ("pkg.b", "b.py"), ("pkg.c", "c.py"), ("pkg.d", "d.py")]
    units = []
    for _, path in definitions:
        data = b"def run():\n    return True\n"
        (root / path).write_bytes(data)
        units.append(SourceTextUnit(path, data.decode(), len(data), "sha256:" + hashlib.sha256(data).hexdigest(), str(root)))
    config = replace(_config(Path(sys.executable)), max_relationships=max_relationships, page_size=page_size)
    adapter = CodebaseMemoryCodeIntelligenceAdapter(config)
    adapter._probe_version = lambda: "partition-protocol-fixture"
    rows = [
        ["pkg.a", "a.py", "CALLS", "pkg.b", "b.py", ".55", "suffix_match", "2"],
        ["pkg.a", "a.py", "CALLS", "pkg.c", "c.py", ".55", "suffix_match", "2"],
        ["pkg.a", "a.py", "CALLS", "pkg.d", "d.py", ".55", "suffix_match", "2"],
        ["pkg.b", "b.py", "CALLS", "pkg.c", "c.py", ".90", "import_map", "1"],
        ["pkg.c", "c.py", "CALLS", "pkg.d", "d.py", ".90", "import_map", "1"],
    ]
    queries = []

    def call(tool, payload, **kwargs):
        if tool == "index_repository":
            return {"project": "fixture", "status": "indexed"}
        if tool == "search_graph":
            start, limit = payload["offset"], payload["limit"]
            page = definitions[start:start + limit]
            return {"results": [{"name": qn.rsplit(".", 1)[1], "qualified_name": qn, "file_path": path,
                "label": "Function", "lines": 2} for qn, path in page],
                "has_more": start + len(page) < len(definitions), "total": len(definitions)}
        if "n.start_line" in payload["query"]:
            return {"columns": ["n.qualified_name", "n.file_path", "n.start_line", "n.end_line"], "rows": []}
        query = payload["query"]
        queries.append(query)
        assert "SKIP" not in query and "offset" not in payload
        filtered = rows
        for field, column in (("a.file_path", 1), ("a.qualified_name", 0), ("b.file_path", 4), ("b.qualified_name", 3)):
            match = re.search(re.escape(field) + r" IN (\[[^\]]*\])", query)
            if match:
                allowed = json.loads(match[1])
                filtered = [row for row in filtered if row[column] in allowed]
        limit = int(re.search(r"LIMIT (\d+)$", query)[1])
        return {"columns": COLUMNS, "rows": filtered[:limit], "total": len(filtered[:limit])}

    adapter._call = call
    return adapter, units, rows, queries


def test_filtered_call_rows_do_not_hide_valid_relationships_or_claim_a_complete_prefix(tmp_path):
    adapter, units, _, queries = fixture(tmp_path, max_relationships=2)
    result = adapter.analyze(units)
    assert len(result.relationships) == 2
    by_id = {item.provider_node_id: item for item in result.entities}
    assert {(by_id[edge.from_provider_node_id].qualified_name, by_id[edge.to_provider_node_id].qualified_name)
            for edge in result.relationships} == {("pkg.b", "pkg.c"), ("pkg.c", "pkg.d")}
    assert len(queries) > 1
    assert "code-graph-calls:excluded:3" in result.evidence_refs


def test_partitions_scan_dense_single_source_through_target_scopes(tmp_path):
    adapter, units, rows, queries = fixture(tmp_path, page_size=1)
    rows[:] = [["pkg.a", "a.py", "CALLS", qn, path, ".9", "import_map", "1"]
               for qn, path in (("pkg.b", "b.py"), ("pkg.c", "c.py"), ("pkg.d", "d.py"))]
    result = adapter.analyze(units)
    assert len(result.relationships) == 3
    assert "code-graph-relationships:truncated" not in result.evidence_refs
    assert any("a.qualified_name IN" in query for query in queries)
    assert any("b.file_path IN" in query for query in queries)


def test_query_budget_exhaustion_is_partial_not_silent_complete(tmp_path):
    adapter, units, _, queries = fixture(tmp_path)
    adapter.config = replace(adapter.config, max_relationship_queries=1)
    result = adapter.analyze(units)
    assert len(queries) == 1
    assert "code-graph-relationships:truncated" in result.evidence_refs
    assert "code-graph-relationship-scan:query-budget-exceeded" in result.evidence_refs


def test_relationship_row_budget_is_separate_from_normalized_edge_count(tmp_path):
    adapter, units, rows, _ = fixture(tmp_path, max_relationships=2)
    rows[:] = [["pkg.a", "a.py", "CALLS", qn, path, ".9", "import_map", "1"]
               for qn, path in (("pkg.b", "b.py"), ("pkg.c", "c.py"), ("pkg.d", "d.py"))]
    result = adapter.analyze(units)
    assert len(result.relationships) <= 2
    assert "code-graph-relationships:truncated" in result.evidence_refs


def test_unsplittable_native_pair_reports_an_explicit_gap(tmp_path):
    adapter, units, rows, _ = fixture(tmp_path, page_size=1)
    rows[:] = [["pkg.a", "a.py", "CALLS", "pkg.b", "b.py", ".9", "import_map", "1"] for _ in range(65)]
    result = adapter.analyze(units)
    assert "code-graph-relationships:truncated" in result.evidence_refs
    assert "code-graph-relationship-scan:unsplittable-provider-row-limit" in result.evidence_refs


def test_scan_does_not_double_count_parent_rows_or_depend_on_provider_order(tmp_path):
    adapter, units, rows, _ = fixture(tmp_path)
    first = adapter.analyze(units)
    rows.reverse()
    second = adapter.analyze(units)
    assert first == second
    assert "code-graph-calls:excluded:3" in first.evidence_refs


def test_endpoint_path_mismatch_cannot_be_resolved_by_a_unique_qualified_name(tmp_path):
    adapter, units, _, _ = fixture(tmp_path)
    original = adapter._call

    def corrupt(tool, payload, **kwargs):
        value = original(tool, payload, **kwargs)
        if tool == "query_graph" and "type(r)" in payload["query"]:
            value["rows"] = [["pkg.a", "not-selected.py", "CALLS", "pkg.b", "b.py", ".9", "import_map", "1"]]
            value["total"] = 1
        return value

    adapter._call = corrupt
    result = adapter.analyze(units)
    assert not result.relationships
    assert "code-graph-edges:unresolved-endpoints:1" in result.evidence_refs


def test_provider_absolute_endpoint_paths_must_normalize_inside_the_private_snapshot(tmp_path):
    adapter, units, _, _ = fixture(tmp_path)
    original = adapter._call

    def absolute(tool, payload, **kwargs):
        value = original(tool, payload, **kwargs)
        if tool == "query_graph" and "type(r)" in payload["query"]:
            root = adapter._execution_root.get()
            value["rows"] = [["pkg.a", str(root / "a.py"), "CALLS", "pkg.b", str(root / "b.py"), ".9", "import_map", "1"]]
            value["total"] = 1
        return value

    adapter._call = absolute
    result = adapter.analyze(units)
    assert len(result.relationships) == 1
    assert not any(ref.startswith("code-graph-edges:unresolved-endpoints:") for ref in result.evidence_refs)


@pytest.mark.parametrize("change", ["schema", "row_shape", "oversized_page", "count", "boolean_count"])
def test_malformed_provider_scan_is_rejected_not_a_partial_success(tmp_path, change):
    adapter, units, _, _ = fixture(tmp_path)
    original = adapter._call

    def corrupt(tool, payload, **kwargs):
        value = original(tool, payload, **kwargs)
        if tool == "query_graph" and "type(r)" in payload["query"]:
            if change == "schema":
                value["columns"] = []
            elif change == "row_shape":
                value["rows"][0] = value["rows"][0][:5]
            elif change == "oversized_page":
                value["rows"] *= 5
                value["total"] = len(value["rows"])
            else:
                value["total"] = True if change == "boolean_count" else len(value["rows"]) + 1
        return value

    adapter._call = corrupt
    with pytest.raises(CodebaseMemoryError, match="relationship"):
        adapter.analyze(units)


def test_query_limit_has_a_declared_environment_policy(monkeypatch):
    from apps.api.app.infrastructure.config.code_graph_config import CodeGraphConfig
    monkeypatch.setenv("NASUS_CODE_GRAPH_MAX_RELATIONSHIP_QUERIES", "17")
    assert CodeGraphConfig.from_env().max_relationship_queries == 17
    monkeypatch.setenv("NASUS_CODE_GRAPH_MAX_RELATIONSHIP_QUERIES", "0")
    with pytest.raises(ValueError, match="must be a positive integer"):
        CodeGraphConfig.from_env()


@pytest.mark.parametrize("values", [("NaN", "same_module", "1"), ("Infinity", "same_module", "1"),
    (True, "same_module", "1"), (".9", "same_module", True), (".9", "same_module", 1.5),
    (".9", "same_module", "1.0"), (".9", "same_module", "-1"), (".9", "../escape", "1")])
def test_invalid_provider_resolution_metadata_fails_closed(values):
    with pytest.raises(CodebaseMemoryError, match="metadata is invalid"):
        CodebaseMemoryCodeIntelligenceAdapter._call_resolution(values)
