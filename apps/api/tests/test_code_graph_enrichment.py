from __future__ import annotations

import hashlib
import json
from pathlib import Path

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
        """#!/usr/bin/env python3
import json
import os
import sys

if sys.argv[1:] == ["--version"]:
    print("codebase-memory-mcp 9.9.9")
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
        ],
        "rows": [
            [provider_prefix + "payments.PaymentService", "payments.py", "DEFINES_METHOD", provider_prefix + "payments.authorize", "payments.py"],
            [provider_prefix + "payments.authorize", "payments.py", "HANDLES", provider_prefix + "payments.POST /payments", "payments.py"],
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

    result = CodebaseMemoryCodeIntelligenceAdapter(_config(binary)).analyze(
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
    assert calls[0]["payload"]["repo_path"] == str(root)
    assert calls[0]["payload"]["persistence"] is False


def test_codebase_memory_accepts_provider_owned_project_identity_without_leaking_it(
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
    provider_project = "Users-service-workspace-repository"
    monkeypatch.setenv("FAKE_CBM_PROJECT", provider_project)

    result = CodebaseMemoryCodeIntelligenceAdapter(_config(binary)).analyze(
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

    result = CodebaseMemoryCodeIntelligenceAdapter(_config(binary)).analyze(
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
        item["payload"]["query"] for item in calls if item["tool"] == "query_graph"
    )
    assert 'a.file_path IN ["payments.py"]' in relationship_query
    assert 'b.file_path IN ["payments.py"]' in relationship_query


def test_codebase_memory_rejects_unsafe_provider_project_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "payments.py").write_text("def authorize():\n    return True\n", encoding="utf-8")
    binary, call_log = _fake_codebase_memory(tmp_path)
    monkeypatch.setenv("FAKE_CBM_CALL_LOG", str(call_log))
    monkeypatch.setenv("FAKE_CBM_PROJECT", "../../escaped-project")

    with pytest.raises(CodebaseMemoryError, match="unsafe project identity"):
        CodebaseMemoryCodeIntelligenceAdapter(_config(binary)).analyze(
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
        CodebaseMemoryCodeIntelligenceAdapter(_config(binary)),
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
