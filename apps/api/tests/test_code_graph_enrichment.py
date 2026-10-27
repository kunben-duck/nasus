from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

from apps.api.app.application.system_image.source_ports import SourceTextUnit
from apps.api.app.infrastructure.config.code_graph_config import CodeGraphConfig
from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import (
    CodebaseMemoryCodeIntelligenceAdapter,
    CodebaseMemoryError,
)
from apps.api.app.infrastructure.system_image.composite_code_intelligence import (
    CompositeCodeIntelligenceAdapter,
)
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import (
    TreeSitterCodeIntelligenceAdapter,
)
from apps.api.app.infrastructure.system_image.code_graph_process import CodeGraphProcessRunner


class _FixtureProcessRunner(CodeGraphProcessRunner):
    def run(self, args, *, env, **kwargs):
        fixture_env = {key: value for key, value in os.environ.items() if key.startswith("FAKE_CBM_")}
        return super().run(args, env={**env, **fixture_env}, **kwargs)


def _adapter(config):
    return CodebaseMemoryCodeIntelligenceAdapter(config, process_runner=_FixtureProcessRunner())


def _config(binary: Path, *, mode: str = "optional") -> CodeGraphConfig:
    return CodeGraphConfig(
        mode=mode,  # type: ignore[arg-type]
        binary=str(binary),
        index_mode="moderate",
        timeout_seconds=5.0,
        max_entities=100,
        max_relationships=100,
        page_size=50,
        cache_dir=None,
    )


def _source_unit(root: Path) -> SourceTextUnit:
    path = root / "payments.py"
    data = path.read_bytes()
    return SourceTextUnit(
        relative_path="payments.py",
        text=data.decode("utf-8"),
        byte_count=len(data),
        content_hash=f"sha256:{hashlib.sha256(data).hexdigest()}",
        source_root=str(root),
    )


def _fake_codebase_memory(tmp_path: Path) -> tuple[Path, Path]:
    binary = tmp_path / "codebase-memory-mcp"
    call_log = tmp_path / "calls.jsonl"
    binary.write_text(
        f"#!{sys.executable}\n" + """
import json
import os
import sys

if sys.argv[1:] == ["--version"]:
    print("codebase-memory-mcp 9.9.9")
    raise SystemExit(0)

if sys.argv[1:] == ["--ui=false"]:
    contracts = {
        "index_repository": {"repo_path": "string", "mode": "string", "persistence": "boolean"},
        "search_graph": {"project": "string", "name_pattern": "string", "offset": "integer", "limit": "integer"},
        "query_graph": {"project": "string", "query": "string"},
    }
    for line in sys.stdin:
        request = json.loads(line)
        method = request["method"]
        with open(os.environ["FAKE_CBM_CALL_LOG"], "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"tool": "mcp." + method, "payload": {}}) + "\\n")
        if method == "notifications/initialized":
            continue
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "codebase-memory-mcp", "version": "9.9.9"}}
        elif method == "tools/list":
            tools = []
            for name, fields in contracts.items():
                props = {key: {"type": value} for key, value in fields.items()}
                if name == "index_repository":
                    props["mode"]["enum"] = ["fast", "moderate", "full"]
                tools.append({"name": name, "inputSchema": {"type": "object", "properties": props}})
            result = {"tools": tools}
        else:
            raise SystemExit("unexpected contract probe operation")
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
    raise SystemExit(0)

tool = sys.argv[2]
payload = json.loads(sys.argv[3])
with open(os.environ["FAKE_CBM_CALL_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps({"tool": tool, "payload": payload}) + "\\n")

if tool == "index_repository":
    result = {
        "project": os.environ.get("FAKE_CBM_PROJECT") or payload["name"],
        "status": "indexed",
        "nodes": 3,
        "edges": 2,
    }
elif tool == "search_graph":
    if os.environ.get("FAKE_CBM_SCHEMA") == "flat":
        provider_prefix = (
            os.environ.get("FAKE_CBM_PROJECT", "") + "."
            if os.environ.get("FAKE_CBM_PROJECT")
            else ""
        )
        all_results = [
            {
                "name": f"ignored_{index}",
                "qualified_name": f"ignored.item_{index}",
                "label": "Function",
                "file_path": "ignored.py",
                "lines": 1,
            }
            for index in range(51)
        ] + [
            {
                "name": "PaymentService",
                "qualified_name": provider_prefix + "payments.PaymentService",
                "label": "Class",
                "file_path": "payments.py",
                "lines": 4,
            },
            {
                "name": "authorize",
                "qualified_name": provider_prefix + "payments.authorize",
                "label": "Method",
                "file_path": "payments.py",
                "lines": 2,
            },
            {
                "name": "POST /payments",
                "qualified_name": provider_prefix + "payments.POST /payments",
                "label": "Route",
                "file_path": "payments.py",
                "lines": 2,
            },
        ]
        offset = payload["offset"]
        limit = payload["limit"]
        page = all_results[offset:offset + limit]
        result = {
            "total": len(all_results),
            "results": page,
            "has_more": offset + len(page) < len(all_results),
        }
    else:
        result = {
            "total": 3,
            "count": 3,
            "cols": ["name", "label", "lines", "in", "out"],
            "groups": [{
                "qn_prefix": "payments",
                "file": "payments.py",
                "rows": [
                    ["PaymentService", "Class", "1-4", 0, 1],
                    ["authorize", "Method", "2-3", 1, 1],
                    ["POST /payments", "Route", "5-6", 1, 0],
                ],
            }],
            "has_more": False,
        }
elif tool == "query_graph":
    if "n.start_line" in payload["query"]:
        result = {
            "columns": ["n.qualified_name", "n.file_path", "n.start_line", "n.end_line"],
            "rows": [],
        }
        if os.environ.get("FAKE_CBM_LOCATIONS"):
            result["rows"] = [[os.environ.get("FAKE_CBM_PROJECT", "") + ".payments.PaymentService", "payments.py", "1", "3"]]
        print(json.dumps(result))
        raise SystemExit(0)
    provider_prefix = (
        os.environ.get("FAKE_CBM_PROJECT", "") + "."
        if os.environ.get("FAKE_CBM_SCHEMA") == "flat" and os.environ.get("FAKE_CBM_PROJECT")
        else ""
    )
    result = {
        "columns": [
            "a.qualified_name",
            "a.file_path",
            "type(r)",
            "b.qualified_name",
            "b.file_path",
            "r.confidence",
            "r.strategy",
            "r.candidates",
        ],
        "rows": [
            [provider_prefix + "payments.PaymentService", "payments.py", "DEFINES_METHOD", provider_prefix + "payments.authorize", "payments.py", "", "", ""],
            [provider_prefix + "payments.authorize", "payments.py", "HANDLES", provider_prefix + "payments.POST /payments", "payments.py", "", "", ""],
        ],
        "total": 2,
    }
else:
    raise SystemExit(2)
print(json.dumps(result))
""",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    return binary, call_log


def test_synthetic_provider_routes_are_quarantined_not_attributed_to_arbitrary_files(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "payments.py").write_text("def pay():\n    return True\n")
    adapter = _adapter(_config(Path(sys.executable)))
    adapter._probe_version = lambda: "synthetic-route-contract-fixture"

    def call(tool, payload, **kwargs):
        if tool == "index_repository":
            return {"project": "fixture", "status": "indexed"}
        if tool == "search_graph":
            return {"results": [{"name": "/", "qualified_name": "__route__GET__/", "label": "Route",
                                 "file_path": "payments.py", "lines": 1}], "has_more": False}
        raise AssertionError("unverified synthetic routes must not acquire edges or exact-location claims")

    adapter._call = call
    result = adapter.analyze([_source_unit(root)])
    assert not result.entities and not result.relationships
    assert "code-graph-routes:unverified-synthetic" in result.evidence_refs
    assert "code-graph-routes:excluded:1" in result.evidence_refs


def test_collapsed_edge_kinds_keep_all_evidence_independent_of_provider_row_order(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    (root / "payments.py").write_text("class PaymentService:\n    def authorize(self):\n        return True\n")
    binary, log = _fake_codebase_memory(tmp_path)
    monkeypatch.setenv("FAKE_CBM_CALL_LOG", str(log))
    adapter = _adapter(_config(binary))
    original = adapter._call
    reverse = False

    def call(tool, payload, **kwargs):
        value = original(tool, payload, **kwargs)
        if tool == "query_graph" and "type(r)" in payload["query"]:
            row = list(value["rows"][0])
            row[2] = "DEFINES"
            value["rows"].append(row)
            value["total"] = len(value["rows"])
            if reverse:
                value["rows"].reverse()
        return value

    monkeypatch.setattr(adapter, "_call", call)
    first = adapter.analyze([_source_unit(root)])
    reverse = True
    second = adapter.analyze([_source_unit(root)])
    assert first == second
    membership = next(item for item in first.relationships if item.relationship_kind == "belongs_to")
    assert set(membership.evidence_refs) == {"code-graph-edge:codebase-memory:DEFINES",
                                           "code-graph-edge:codebase-memory:DEFINES_METHOD"}


@pytest.mark.parametrize("strategy,candidates", [("suffix_match", "2"), ("suffix_match", "1"),
    ("field_type_hint", "3"), ("unique_name", "1"), ("unknown", ""), ("", ""),
    ("lsp_type_dispatch", "2"), ("lsp_type_dispatch", "0"), ("lsp_type_dispatch", ""),
    ("lsp_unreviewed_strategy", "1")])
def test_unverified_call_resolution_is_a_gap_not_a_certain_edge(tmp_path, monkeypatch, strategy, candidates):
    root = tmp_path / "source"
    root.mkdir()
    (root / "payments.py").write_text("class PaymentService:\n    def authorize(self):\n        return True\n")
    binary, log = _fake_codebase_memory(tmp_path)
    monkeypatch.setenv("FAKE_CBM_CALL_LOG", str(log))
    adapter = _adapter(_config(binary))
    original = adapter._call

    def call(tool, payload, **kwargs):
        value = original(tool, payload, **kwargs)
        if tool == "query_graph" and "type(r)" in payload["query"]:
            value["rows"].append(["payments.PaymentService", "payments.py", "CALLS", "payments.authorize", "payments.py",
                                  "0.55", strategy, candidates])
            value["total"] = len(value["rows"])
        return value

    monkeypatch.setattr(adapter, "_call", call)
    result = adapter.analyze([_source_unit(root)])
    assert not any(item.relationship_kind == "calls" for item in result.relationships)
    assert "code-graph-calls:unverified-resolution" in result.evidence_refs


@pytest.mark.parametrize("strategy", ["same_module", "lsp_type_dispatch"])
def test_call_resolution_keeps_provider_score_and_strategy_without_calibration_claim(tmp_path, monkeypatch, strategy):
    root = tmp_path / "source"
    root.mkdir()
    (root / "payments.py").write_text("class PaymentService:\n    def authorize(self):\n        return True\n")
    binary, log = _fake_codebase_memory(tmp_path)
    monkeypatch.setenv("FAKE_CBM_CALL_LOG", str(log))
    adapter = _adapter(_config(binary))
    original = adapter._call

    def call(tool, payload, **kwargs):
        value = original(tool, payload, **kwargs)
        if tool == "query_graph" and "type(r)" in payload["query"]:
            value["rows"].append(["payments.PaymentService", "payments.py", "CALLS", "payments.authorize", "payments.py",
                                  "0.91", strategy, "1"])
            value["total"] = len(value["rows"])
        return value

    monkeypatch.setattr(adapter, "_call", call)
    result = adapter.analyze([_source_unit(root)])
    edge = next(item for item in result.relationships if item.relationship_kind == "calls")
    assert edge.confidence == .91
    assert "code-graph-call-resolution:strategy:" + strategy in edge.evidence_refs
    assert "code-graph-call-resolution:candidates:1" in edge.evidence_refs
    assert "code-graph-call-resolution:uncalibrated-provider-score" in edge.evidence_refs


def test_codebase_memory_cli_is_mapped_through_provider_neutral_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "payments.py").write_text(
        "class PaymentService:\n"
        "    def authorize(self):\n"
        "        return True\n\n"
        "def create_payment():\n"
        "    return True\n",
        encoding="utf-8",
    )
    binary, call_log = _fake_codebase_memory(tmp_path)
    monkeypatch.setenv("FAKE_CBM_CALL_LOG", str(call_log))

    result = _adapter(_config(binary)).analyze(
        [_source_unit(root)]
    )

    assert result.provider == "codebase-memory"
    assert result.provider_version == "codebase-memory-mcp 9.9.9"
    assert {(item.entity_kind, item.name) for item in result.entities} == {
        ("class", "PaymentService"),
        ("method", "authorize"),
        ("api_route", "POST /payments"),
    }
    assert all(item.provider_node_id.startswith("codebase-memory:") for item in result.entities)
    assert all(str(root) not in ref for ref in result.evidence_refs)
    assert {item.relationship_kind for item in result.relationships} == {
        "belongs_to",
        "exposes",
    }
    calls = [json.loads(line) for line in call_log.read_text(encoding="utf-8").splitlines()]
    assert [item["tool"] for item in calls] == [
        "index_repository",
        "search_graph",
        "query_graph",
    ]
    staged = Path(calls[0]["payload"]["repo_path"])
    assert staged != root and staged.name.startswith("nasus-cbm-")
    assert not staged.exists()
    assert calls[0]["payload"]["persistence"] is False


@pytest.mark.parametrize("provider_project", [
    "Users-service-workspace-repository",
    "Users-uben-project-project-Nasus-.nasus-validation-system-image-sources-snapshots-"
    + "a" * 64 + "-" + "b" * 40,
])
def test_codebase_memory_accepts_provider_owned_project_identity_without_leaking_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_project: str,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "payments.py").write_text(
        "class PaymentService:\n"
        "    def authorize(self):\n"
        "        return True\n",
        encoding="utf-8",
    )
    binary, call_log = _fake_codebase_memory(tmp_path)
    monkeypatch.setenv("FAKE_CBM_CALL_LOG", str(call_log))
    monkeypatch.setenv("FAKE_CBM_PROJECT", provider_project)

    result = _adapter(_config(binary)).analyze(
        [_source_unit(root)]
    )

    calls = [json.loads(line) for line in call_log.read_text(encoding="utf-8").splitlines()]
    assert calls[1]["payload"]["project"] == provider_project
    assert calls[2]["payload"]["project"] == provider_project
    assert all(provider_project not in ref for ref in result.evidence_refs)
    assert all(provider_project not in item.provider_node_id for item in result.entities)


def test_codebase_memory_maps_flat_search_schema_and_scans_past_filtered_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "payments.py").write_text(
        "class PaymentService:\n"
        "    def authorize(self):\n"
        "        return True\n",
        encoding="utf-8",
    )
    binary, call_log = _fake_codebase_memory(tmp_path)
    monkeypatch.setenv("FAKE_CBM_CALL_LOG", str(call_log))
    monkeypatch.setenv("FAKE_CBM_SCHEMA", "flat")
    provider_project = "Users-service-workspace-repository"
    monkeypatch.setenv("FAKE_CBM_PROJECT", provider_project)

    result = _adapter(_config(binary)).analyze(
        [_source_unit(root)]
    )

    assert {(item.entity_kind, item.name) for item in result.entities} == {
        ("class", "PaymentService"),
        ("method", "authorize"),
        ("api_route", "POST /payments"),
    }
    assert all(
        "code-graph-location:approximate" in item.evidence_refs
        for item in result.entities
    )
    assert all(item.start_line == 1 for item in result.entities)
    assert next(item for item in result.entities if item.name == "PaymentService").end_line == 4
    assert all(provider_project not in item.qualified_name for item in result.entities)
    assert {item.relationship_kind for item in result.relationships} == {
        "belongs_to",
        "exposes",
    }
    calls = [json.loads(line) for line in call_log.read_text(encoding="utf-8").splitlines()]
    search_calls = [item for item in calls if item["tool"] == "search_graph"]
    assert [item["payload"]["offset"] for item in search_calls] == [0, 50]
    relationship_query = next(
        item["payload"]["query"] for item in calls if item["tool"] == "query_graph" and "type(r)" in item["payload"]["query"]
    )
    assert 'a.file_path IN ["payments.py"]' in relationship_query
    assert 'b.file_path IN ["payments.py"]' in relationship_query


@pytest.mark.parametrize("provider_project", [
    "../../escaped-project", "project\nother", "project;other", "x" * 4097,
])
def test_codebase_memory_rejects_unsafe_provider_project_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_project: str,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "payments.py").write_text("def authorize():\n    return True\n", encoding="utf-8")
    binary, call_log = _fake_codebase_memory(tmp_path)
    monkeypatch.setenv("FAKE_CBM_CALL_LOG", str(call_log))
    monkeypatch.setenv("FAKE_CBM_PROJECT", provider_project)

    with pytest.raises(CodebaseMemoryError, match="unsafe project identity"):
        _adapter(_config(binary)).analyze(
            [_source_unit(root)]
        )


def test_composite_merges_graph_evidence_without_replacing_tree_sitter_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "payments.py").write_text(
        "class PaymentService:\n"
        "    def authorize(self):\n"
        "        return True\n\n"
        "def create_payment():\n"
        "    return True\n",
        encoding="utf-8",
    )
    binary, call_log = _fake_codebase_memory(tmp_path)
    monkeypatch.setenv("FAKE_CBM_CALL_LOG", str(call_log))
    adapter = CompositeCodeIntelligenceAdapter(
        TreeSitterCodeIntelligenceAdapter(),
        _adapter(_config(binary)),
        mode="optional",
    )

    result = adapter.analyze([_source_unit(root)])

    payment_classes = [
        item
        for item in result.entities
        if item.entity_kind == "class" and item.name == "PaymentService"
    ]
    assert len(payment_classes) == 1
    assert payment_classes[0].provider_node_id.startswith("tree-sitter:")
    assert any(ref.startswith("code-graph:codebase-memory:") for ref in payment_classes[0].evidence_refs)
    assert result.provider == "tree-sitter+codebase-memory"
    assert "code-graph:enriched" in result.evidence_refs
    entity_ids = {item.provider_node_id for item in result.entities}
    assert all(
        relation.from_provider_node_id in entity_ids
        and relation.to_provider_node_id in entity_ids
        for relation in result.relationships
    )


def test_optional_graph_failure_is_explicit_and_required_mode_fails_closed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "payments.py").write_text("def authorize():\n    return True\n", encoding="utf-8")
    missing = tmp_path / "missing-codebase-memory"
    enhancer = CodebaseMemoryCodeIntelligenceAdapter(_config(missing))

    optional = CompositeCodeIntelligenceAdapter(
        TreeSitterCodeIntelligenceAdapter(),
        enhancer,
        mode="optional",
    ).analyze([_source_unit(root)])
    assert optional.provider == "tree-sitter"
    assert "code-graph:unavailable" in optional.evidence_refs
    assert "code-graph-reason:provider-unavailable" in optional.evidence_refs

    required = CompositeCodeIntelligenceAdapter(
        TreeSitterCodeIntelligenceAdapter(),
        CodebaseMemoryCodeIntelligenceAdapter(_config(missing, mode="required")),
        mode="required",
    )
    with pytest.raises(CodebaseMemoryError, match="executable is unavailable"):
        required.analyze([_source_unit(root)])


def test_disabled_graph_mode_records_policy_evidence_without_calling_provider() -> None:
    adapter = CompositeCodeIntelligenceAdapter(
        TreeSitterCodeIntelligenceAdapter(),
        None,
        mode="disabled",
    )
    text = "def authorize():\n    return True\n"
    result = adapter.analyze(
        [
            SourceTextUnit(
                relative_path="payments.py",
                text=text,
                byte_count=len(text.encode("utf-8")),
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
        ]
    )

    assert result.provider == "tree-sitter"
    assert "code-graph:disabled" in result.evidence_refs
    assert adapter.diagnostics()["graph_status"] == "disabled"
