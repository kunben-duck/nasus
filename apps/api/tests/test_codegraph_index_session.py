"""SDK session contracts use an explicit process double, not a native quality gold set."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest

from apps.api.app.domain.system_image.code_index import CodeIndexCancelled, CodeIndexUnavailable
from apps.api.app.domain.system_image.code_provider_protocol import CodeProviderSDKReceipt, read_code_provider_contract
from apps.api.app.infrastructure.config.code_graph_config import CodeGraphConfig
from apps.api.app.infrastructure.system_image.code_intelligence_factory import configured_code_graph
from apps.api.app.infrastructure.system_image import codegraph_sdk_code_intelligence as module
from apps.api.tests.test_codegraph_sdk import Runner, config, payload, unit


def adapter(tmp_path, runner=None):
    return module.CodeGraphSDKCodeIntelligenceAdapter(config(tmp_path), process_runner=runner or Runner())


def test_session_pages_locations_impact_and_contract_reuse_one_sdk_projection(tmp_path):
    graph = adapter(tmp_path)
    with graph.open_index([unit()], check_current=lambda: None) as index:
        assert index.status().state == "degraded"
        assert index.status().snapshot_hash.startswith("sha256:")
        receipt = index.protocol_receipt()
        assert isinstance(receipt, CodeProviderSDKReceipt)
        assert receipt.entry_point == "package_public_entry" and "graph.close" in receipt.public_operations
        assert not hasattr(receipt, "protocol_version") and not hasattr(receipt, "tools_schema_hash")
        assert read_code_provider_contract(receipt.payload()) == receipt
        first = index.entities(limit=1)
        second = index.entities(cursor=first.next_cursor, limit=1)
        assert first.normalized_count == 2 and [item.provider_node_id for item in (*first.items, *second.items)] == ["a", "b"]
        assert second.next_cursor is None and first.enumeration == "complete"
        assert index.relations(limit=1).items[0].relationship_kind == "belongs_to"
        assert index.locate("b").name == "load"
        impact = index.impact(["b"])
        assert impact.index_id == first.index_id and not impact.complete
        assert index.read_projection() is index.read_projection()
        assert index.prepare_index().index_id == first.index_id and len(graph.runner.calls) == 1
        assert set(index.capabilities().operations) >= {"prepare_index", "entities", "cancel"}
    assert index.status().state == "closed" and list(graph.config.cache_dir.iterdir()) == []
    with pytest.raises(CodeIndexUnavailable):
        index.entities()


def test_bad_cursors_and_bounds_do_not_fail_a_prepared_session(tmp_path):
    graph = adapter(tmp_path)
    with graph.open_index([unit()], check_current=lambda: None) as index:
        cursor = index.entities(limit=1).next_cursor
        for operation in (lambda: index.relations(cursor=cursor), lambda: index.entities(cursor="bad"),
                          lambda: index.entities(limit=True), lambda: index.entities(limit=1001)):
            with pytest.raises(ValueError):
                operation()
            assert index.status().state == "degraded"
        with pytest.raises(CodeIndexUnavailable):
            index.locate("not-in-this-index")
    with graph.open_index([unit()], check_current=lambda: None) as replacement:
        with pytest.raises(ValueError):
            replacement.entities(cursor=cursor)


def test_each_read_rechecks_authority_and_cached_projection_rechecks_runtime(tmp_path):
    graph = adapter(tmp_path)
    permitted = True
    def authority():
        if not permitted:
            raise PermissionError("revoked")
    index = graph.open_index([unit()], check_current=authority)
    index.prepare_index()
    permitted = False
    with pytest.raises(PermissionError):
        index.entities()
    permitted = True
    (graph.config.platform_path / "grammar.wasm").write_bytes(b"changed grammar")
    with pytest.raises(module.CodeGraphSDKError, match="changed"):
        index.entities()
    permitted = False
    index.close()  # Cleanup must remain possible after revocation.
    assert list(graph.config.cache_dir.iterdir()) == []


def test_cancel_interrupts_preparation_without_waiting_for_the_operation_lock(tmp_path):
    started = Event()
    def waiting(args, kwargs):
        started.set()
        while True:
            kwargs["check_current"]()
            Event().wait(.01)
    graph = adapter(tmp_path, Runner(after=waiting))
    index = graph.open_index([unit()], check_current=lambda: None)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(index.prepare_index)
        assert started.wait(5)
        assert index.cancel().state == "cancellation_requested"
        with pytest.raises(CodeIndexCancelled):
            result.result(timeout=5)
    assert index.status().state == "cancelled" and list(graph.config.cache_dir.iterdir()) == []
    index.close()


@pytest.mark.parametrize("change", [
    {"schema": "nasus.code-provider-protocol.v1"}, {"entry_point": "lib/dist/index.js"},
    {"runtime_hash": "latest"}, {"contract_hash": "bad"}, {"package_name": "../source"},
    {"public_operations": []}, {"public_operations": ["graph.close", "graph.close"]},
    {"scope": "complete"}, {"public_operations": ["private/implementation"]}, {"gaps": ["bad/path"]},
])
def test_sdk_receipt_drift_rejected(tmp_path, change):
    receipt = adapter(tmp_path)._sdk_receipt(payload()["sdk_contract"])
    with pytest.raises((ValueError, TypeError)):
        read_code_provider_contract({**receipt.payload(), **change})


@pytest.mark.parametrize("change", [
    {"package_version": "1.6.3"}, {"public_operations": []}, {"entry_point": "internal"},
    {"schema": "mcp"}, {"result_schema": "nasus.codegraph-sdk-projection.v1"},
])
def test_bridge_contract_drift_never_prepares_or_returns_a_partial_projection(tmp_path, change):
    data = payload()
    data["sdk_contract"].update(change)
    graph = adapter(tmp_path, Runner(data))
    index = graph.open_index([unit()], check_current=lambda: None)
    with pytest.raises(module.CodeGraphSDKError):
        index.prepare_index()
    assert index.status().state == "failed" and index.protocol_receipt() is None
    assert list(graph.config.cache_dir.iterdir()) == []
    index.close()


def test_sdk_fingerprint_includes_bridge_dependencies_runtime_and_capacity(tmp_path, monkeypatch):
    graph = adapter(tmp_path)
    seen = []
    def dependencies(**kwargs):
        seen.append(kwargs["entrypoints"])
        kwargs["check_current"]()
        return {"fixture": "dependency closure"}
    monkeypatch.setattr(module, "projection_dependency_manifest", dependencies)
    before = graph.projection_fingerprint()
    assert any("codegraph_sdk_index_session" in entry for entry in seen[0])
    other = module.CodeGraphSDKCodeIntelligenceAdapter(replace(graph.config, max_entities=5))
    assert before != other.projection_fingerprint()
    with graph.open_index([unit()], check_current=lambda: None, namespace="nasus_" + "a" * 32,
                          provider_fingerprint=before) as index:
        assert index.protocol_receipt().runtime_hash == graph.config.expected_runtime_hash
    graph.config = replace(graph.config, max_entities=5)
    index = graph.open_index([unit()], check_current=lambda: None, namespace="nasus_" + "a" * 32,
                             provider_fingerprint=before)
    with pytest.raises(module.CodeGraphSDKError, match="policy changed"):
        index.prepare_index()
    assert index.status().state == "failed"
    index.close()


def test_provider_selection_is_explicit_and_disabled_default_does_not_install(tmp_path, monkeypatch):
    for key in ("NASUS_CODE_GRAPH_MODE", "NASUS_CODE_GRAPH_PROVIDER", "NASUS_CODEGRAPH_SDK_PACKAGE_PATH",
                "NASUS_CODEGRAPH_SDK_PLATFORM_PATH", "NASUS_CODEGRAPH_SDK_RUNTIME_HASH"):
        monkeypatch.delenv(key, raising=False)
    default = CodeGraphConfig.from_env()
    assert default.provider == "codebase-memory" and default.mode == "disabled"
    assert configured_code_graph(default, max_files=10, max_source_bytes=100) is None
    enabled = replace(default, mode="required", provider="codegraph")
    with pytest.raises(ValueError, match="requires explicit"):
        configured_code_graph(enabled, max_files=10, max_source_bytes=100)
    cfg = config(tmp_path)
    selected = replace(enabled, sdk_package_path=cfg.package_path, sdk_platform_path=cfg.platform_path,
                       sdk_runtime_hash=cfg.expected_runtime_hash, cache_dir=cfg.cache_dir)
    graph = configured_code_graph(selected, max_files=10, max_source_bytes=100)
    assert graph.config.max_files == 10 and graph.config.max_source_bytes == 100
    assert graph.config.expected_runtime_hash == cfg.expected_runtime_hash
    assert not cfg.cache_dir.exists()


def test_runtime_hashing_coalesces_checks_but_forces_both_operation_boundaries(tmp_path, monkeypatch):
    from apps.api.app.infrastructure.system_image import codegraph_sdk_runtime as runtime
    cfg = config(tmp_path)
    monkeypatch.setattr(runtime.time, "monotonic", lambda: 0.)
    calls = []
    actual = runtime.codegraph_runtime_fingerprint(cfg.package_path, cfg.platform_path,
        check_current=lambda: calls.append(1))
    assert actual == cfg.expected_runtime_hash and len(calls) == 2
    def revoke_at_exit():
        calls.append(1)
        if len(calls) == 2:
            raise PermissionError("revoked at the exit boundary")
    calls.clear()
    with pytest.raises(PermissionError):
        runtime.codegraph_runtime_fingerprint(cfg.package_path, cfg.platform_path, check_current=revoke_at_exit)
