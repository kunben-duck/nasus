"""CodeGraph public-SDK ACL, schema, accounting and lifecycle contract tests."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from apps.api.app.application.system_image.source_ports import CodeIntelligenceUnavailable, SourceTextUnit
from apps.api.app.domain.system_image.code_index import CodeIndexCancelled
from apps.api.app.domain.system_image.code_provider import projection_payload
from apps.api.app.infrastructure.system_image import codegraph_sdk_code_intelligence as module
from apps.api.app.infrastructure.system_image.code_graph_process import CodeGraphProcessOutput
from apps.api.app.infrastructure.system_image.composite_code_intelligence import CompositeCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter


def unit(path="sample.java", text="class A { void load(){} }\n"):
    data = text.encode()
    return SourceTextUnit(path, text, len(data), "sha256:" + hashlib.sha256(data).hexdigest())


def payload():
    return {"schema": module.SDK_SCHEMA, "version": module.SDK_VERSION, "state": "complete", "pending_references": 0,
        "sdk_contract": {"schema": "nasus.codegraph-public-sdk-contract.v1", "package_name": "@colbymchenry/codegraph",
            "package_version": module.SDK_VERSION, "entry_point": "package_public_entry",
            "public_operations": list(module.SDK_OPERATIONS), "result_schema": module.SDK_SCHEMA},
        "stats": {"nodes": 2, "edges": 1, "files": 1},
        "files": [{"path": "sample.java", "node_count": 2, "error_count": 0}],
        "nodes": [{"id": "a", "kind": "class", "name": "A", "qualified_name": "sample::A", "path": "sample.java",
                   "language": "java", "start_line": 1, "end_line": 1},
                  {"id": "b", "kind": "method", "name": "load", "qualified_name": "sample::A.load", "path": "sample.java",
                   "language": "java", "start_line": 1, "end_line": 1}],
        "edges": [{"source": "a", "target": "b", "kind": "contains", "provenance": "tree-sitter",
                   "line": None, "column": None, "metadata": None}]}


def config(tmp_path):
    sdk = tmp_path / "codegraph"
    platform = tmp_path / "codegraph-darwin-arm64"
    for root, name in ((sdk, "@colbymchenry/codegraph"), (platform, "@colbymchenry/codegraph-darwin-arm64")):
        root.mkdir()
        (root / "package.json").write_text(json.dumps({"name": name, "version": module.SDK_VERSION}))
    (platform / "node").write_bytes(b"test-node-not-executed")
    (platform / "grammar.wasm").write_bytes(b"grammar")
    return module.CodeGraphSDKConfig(sdk, platform, tmp_path / "sessions",
        module.codegraph_runtime_fingerprint(sdk, platform))


class Runner:
    def __init__(self, data=None, after=None):
        self.data, self.after, self.calls = payload() if data is None else data, after, []

    def run(self, args, **kwargs):
        self.calls.append((args, kwargs))
        kwargs["check_current"]()
        assert args[5] == module.SDK_VERSION
        if self.after:
            self.after(args, kwargs)
        output = self.data if isinstance(self.data, str) else json.dumps(self.data)
        return CodeGraphProcessOutput(output, "", 0)


def test_public_sdk_mapping_and_raw_observation_are_explicit(tmp_path):
    adapter = module.CodeGraphSDKCodeIntelligenceAdapter(config(tmp_path))
    result = adapter._project(payload(), [unit()])
    assert result.provider == "codegraph" and result.provider_version == "1.6.2"
    assert result.relationships[0].from_provider_node_id == "b"
    assert result.relationships[0].relationship_kind == "belongs_to"
    assert result.relationships[0].to_provider_node_id == "a"
    assert result.relationships[0].confidence == 0. and "codegraph-native-confidence:unknown" in result.relationships[0].evidence_refs
    assert all(item.symbol_key is None and item.location_precision == "exact" for item in result.entities)
    projection = projection_payload(result.provider_observations)
    assert projection["status"] == "partial"  # native scores are not calibrated business accuracy
    assert json.loads(result.native_query_observations[0].response_json) == payload()
    assert result.native_query_observations[0].operation == "sdk_snapshot"


def test_source_and_runtime_guarded_minimal_environment_and_cleanup(tmp_path, monkeypatch):
    cfg, runner = config(tmp_path), Runner()
    monkeypatch.setenv("NASUS_S3_SECRET_KEY", "do-not-forward")
    monkeypatch.setenv("NODE_OPTIONS", "--require attacker.cjs")
    calls = []
    result = module.CodeGraphSDKCodeIntelligenceAdapter(cfg, process_runner=runner).analyze_controlled([unit()], check_current=lambda: calls.append(1))
    args, call = runner.calls[0]
    modules = Path(call["cwd"]) / "runtime/node_modules/@colbymchenry"
    assert args[0] == str(modules / "codegraph-darwin-arm64/node") and args[1] == "--liftoff-only"
    assert args[3] == str(modules / "codegraph")
    assert not {"NASUS_S3_SECRET_KEY", "NODE_OPTIONS"} & set(call["env"])
    assert call["env"]["CODEGRAPH_TELEMETRY"] == "0" and call["env"]["CODEGRAPH_NO_DAEMON"] == "1"
    assert call["env"]["CODEGRAPH_NO_UPDATE_CHECK"] == "1" and call["env"]["DO_NOT_TRACK"] == "1"
    assert Path(call["cwd"]).parent == cfg.cache_dir and not Path(call["cwd"]).exists()
    assert list(cfg.cache_dir.iterdir()) == [] and len(calls) > 10 and len(result.entities) == 2


@pytest.mark.parametrize("change", [
    lambda p: p.update(version="next"), lambda p: p.update(state="indexing"),
    lambda p: p["stats"].update(nodes=3), lambda p: p["stats"].update(files=True),
    lambda p: p["files"][0].update(node_count=3), lambda p: p["files"][0].update(path="../secret"),
    lambda p: p["nodes"][0].update(path="private.java"), lambda p: p["nodes"][0].update(start_line=True),
    lambda p: p["nodes"][0].update(end_line=100), lambda p: p["nodes"][1].update(id="a"),
    lambda p: p["edges"][0].update(target="foreign"), lambda p: p.update(pending_references=-1),
    lambda p: p["nodes"][0].update(extra="private"), lambda p: p["files"][0].update(error_count="zero"),
])
def test_schema_or_scope_drift_fails_closed_without_partial_projection(tmp_path, change):
    cfg, data = config(tmp_path), payload()
    change(data)
    with pytest.raises(module.CodeGraphSDKError):
        module.CodeGraphSDKCodeIntelligenceAdapter(cfg, process_runner=Runner(data)).analyze([unit()])
    assert list(cfg.cache_dir.iterdir()) == []


@pytest.mark.parametrize("data", ['{"schema":1,"schema":2}', '{"count":NaN}', "private source is not JSON"])
def test_duplicate_json_and_invalid_output_rejected(tmp_path, data):
    with pytest.raises(module.CodeGraphSDKError, match="schema"):
        module.CodeGraphSDKCodeIntelligenceAdapter(config(tmp_path), process_runner=Runner(data)).analyze([unit()])


def test_unsupported_native_facts_remain_raw_and_report_partial(tmp_path):
    data = payload()
    data["nodes"][1]["kind"] = "field"
    data["edges"][0]["kind"] = "references"
    data["pending_references"] = 3
    data["files"][0]["error_count"] = 1
    result = module.CodeGraphSDKCodeIntelligenceAdapter(config(tmp_path))._project(data, [unit(), unit("other.txt", "text")])
    assert len(result.entities) == 1 and not result.relationships and result.unsupported_paths == ("other.txt",)
    assert {item.reason: item.count for item in result.provider_observations[0].gaps} == {
        "unmapped_native_node_kind": 1, "unmapped_native_relationship_kind": 1, "pending_native_references": 3,
        "provider_file_parse_errors": 1, "native_confidence_not_calibrated": None}
    assert json.loads(result.native_query_observations[0].response_json) == data


def test_repeated_native_call_sites_keep_distinct_evidence_and_true_raw_counts(tmp_path):
    data = payload()
    data["edges"][0].update(kind="calls", line=1, column=0, metadata={"source": "native"})
    data["edges"].append({**data["edges"][0], "column": 10})
    data["stats"]["edges"] = 2
    result = module.CodeGraphSDKCodeIntelligenceAdapter(config(tmp_path))._project(data, [unit()])
    assert len(result.relationships) == 1
    assert len([ref for ref in result.relationships[0].evidence_refs if ref.startswith("codegraph-native-edge:")]) == 2
    assert json.loads(result.native_query_observations[0].response_json)["stats"]["edges"] == 2
    assert any(gap.reason == "native_edges_aggregated_with_retained_evidence" and gap.count == 1
               for gap in result.provider_observations[0].gaps)


def test_duplicate_exact_native_edge_is_still_invalid(tmp_path):
    data = payload()
    data["edges"] *= 2
    data["stats"]["edges"] = 2
    with pytest.raises(ValueError, match="duplicate"):
        module.CodeGraphSDKCodeIntelligenceAdapter(config(tmp_path))._project(data, [unit()])


@pytest.mark.parametrize("case", ["hash", "size", "lossy", "duplicate", "escape", "reserved", "capacity"])
def test_unapproved_source_input_never_starts_sdk(tmp_path, case):
    cfg, units = config(tmp_path), [unit()]
    if case == "hash": units = [replace(unit(), content_hash="sha256:" + "0" * 64)]
    if case == "size": units = [replace(unit(), byte_count=999)]
    if case == "lossy": units = [replace(unit(), text_is_lossless=False)]
    if case == "duplicate": units *= 2
    if case == "escape": units = [unit("../private.java")]
    if case == "reserved": units = [unit(".codegraph/config.json")]
    if case == "capacity": cfg = replace(cfg, max_source_bytes=1)
    runner = Runner()
    with pytest.raises(module.CodeGraphSDKError):
        module.CodeGraphSDKCodeIntelligenceAdapter(cfg, process_runner=runner).analyze(units)
    assert not runner.calls and list(cfg.cache_dir.iterdir()) == []


@pytest.mark.parametrize("paths", [(".",), ("folder/.git/config",), ("folder/.codegraph/config",),
                                  ("nested", "nested/source.java"), ("nested/source.java", "nested")])
def test_ambiguous_or_reserved_source_paths_fail_with_provider_neutral_error(tmp_path, paths):
    cfg, runner = config(tmp_path), Runner()
    with pytest.raises(CodeIntelligenceUnavailable):
        module.CodeGraphSDKCodeIntelligenceAdapter(cfg, process_runner=runner).analyze([unit(path) for path in paths])
    assert not runner.calls and list(cfg.cache_dir.iterdir()) == []


def test_dot_path_in_native_projection_fails_closed(tmp_path):
    cfg, data = config(tmp_path), payload()
    data["files"][0]["path"] = "."
    with pytest.raises(CodeIntelligenceUnavailable):
        module.CodeGraphSDKCodeIntelligenceAdapter(cfg, process_runner=Runner(data)).analyze([unit()])
    assert list(cfg.cache_dir.iterdir()) == []


def test_runtime_changed_before_or_during_execution_is_rejected(tmp_path):
    cfg = config(tmp_path)
    runner = Runner(after=lambda *_: (cfg.platform_path / "grammar.wasm").write_bytes(b"changed"))
    adapter = module.CodeGraphSDKCodeIntelligenceAdapter(cfg, process_runner=runner)
    with pytest.raises(module.CodeGraphSDKError, match="assets changed"):
        adapter.analyze([unit()])
    assert len(runner.calls) == 1
    with pytest.raises(module.CodeGraphSDKError, match="assets changed"):
        adapter.analyze([unit()])
    assert len(runner.calls) == 1 and list(cfg.cache_dir.iterdir()) == []


def test_source_changed_by_provider_rejected_and_control_cancellation_propagates(tmp_path):
    cfg = config(tmp_path)
    def change(args, _):
        path = Path(args[4]) / "sample.java"
        path.chmod(0o600)
        path.write_bytes(b"changed")
    runner = Runner(after=change)
    with pytest.raises(module.CodeGraphSDKError, match="source snapshot"):
        module.CodeGraphSDKCodeIntelligenceAdapter(cfg, process_runner=runner).analyze([unit()])
    class CancelRunner(Runner):
        def run(self, *_args, **_kwargs):
            raise CodeIndexCancelled("revoked")
    with pytest.raises(CodeIndexCancelled):
        module.CodeGraphSDKCodeIntelligenceAdapter(cfg, process_runner=CancelRunner()).analyze([unit()])
    assert list(cfg.cache_dir.iterdir()) == []


def test_fingerprint_includes_transitive_assets_and_refuses_links(tmp_path):
    cfg = config(tmp_path)
    (cfg.platform_path / "grammar.wasm").write_bytes(b"other")
    assert module.codegraph_runtime_fingerprint(cfg.package_path, cfg.platform_path) != cfg.expected_runtime_hash
    (cfg.platform_path / "linked").symlink_to(cfg.package_path / "package.json")
    with pytest.raises(module.CodeGraphSDKError, match="symbolic"):
        module.codegraph_runtime_fingerprint(cfg.package_path, cfg.platform_path)


def test_runtime_change_then_restore_cannot_change_the_actually_executed_private_assets(tmp_path):
    cfg = config(tmp_path)
    observations = []

    def change_and_restore(args, _):
        installed = cfg.platform_path / "grammar.wasm"
        installed.write_bytes(b"changed only between parent checks")
        copied = Path(args[0]).parent / "grammar.wasm"
        observations.append(copied.read_bytes())
        assert copied != installed and copied.stat().st_mode & 0o222 == 0
        installed.write_bytes(b"grammar")

    runner = Runner(after=change_and_restore)
    result = module.CodeGraphSDKCodeIntelligenceAdapter(cfg, process_runner=runner).analyze([unit()])
    assert observations == [b"grammar"] and result.entities and list(cfg.cache_dir.iterdir()) == []


def test_runtime_non_regular_asset_is_rejected_without_blocking_or_starting_sdk(tmp_path):
    cfg, runner = config(tmp_path), Runner()
    fifo = cfg.platform_path / "injected.pipe"
    import os
    os.mkfifo(fifo)
    with pytest.raises(CodeIntelligenceUnavailable, match="non-regular"):
        module.CodeGraphSDKCodeIntelligenceAdapter(cfg, process_runner=runner).analyze([unit()])
    assert not runner.calls


def test_shared_composite_optional_fallback_is_not_vendor_specific(tmp_path):
    class Unavailable:
        provider = "codegraph"
        def analyze(self, units):
            raise CodeIntelligenceUnavailable("provider unavailable")
    units = [unit()]
    optional = CompositeCodeIntelligenceAdapter(TreeSitterCodeIntelligenceAdapter(), Unavailable(), mode="optional").analyze(units)
    assert optional.entities and any(report.availability == "unavailable" for report in optional.provider_observations)
    with pytest.raises(CodeIntelligenceUnavailable):
        CompositeCodeIntelligenceAdapter(TreeSitterCodeIntelligenceAdapter(), Unavailable(), mode="required").analyze(units)
