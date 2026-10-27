from copy import deepcopy
from dataclasses import replace
import json

import pytest

from apps.api.app.application.system_image.code_observations import received_code_observations
from apps.api.app.application.system_image.source_ports import code_projection_payload
from apps.api.app.domain.system_image.code_observation_archive import validate_observation_payload
from apps.api.app.infrastructure.system_image.code_native_query_observations import NativeQueryObservations
from apps.api.tests.test_code_observation_archives import archive, received
from apps.api.tests.test_code_graph_enrichment import _adapter, _config, _fake_codebase_memory, _source_unit
from apps.api.app.infrastructure.system_image.composite_code_intelligence import CompositeCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter


def observations(provider="codebase-memory", version="9.9.9"):
    collector = NativeQueryObservations(provider, version)
    response = {"columns": ["type(r)", "r.strategy", "r.extra"],
        "rows": [["UNMAPPED_NATIVE_KIND", "ambiguous", {"candidates": 3}]], "total": 1}
    collector.record("query_graph", {"project": "private-worker", "query": "fixed query"}, response)
    return collector, response


def test_decoded_queries_preserve_native_kinds_and_attributes_without_sharing_mutable_payloads():
    collector, response = observations()
    saved = deepcopy(response)
    response["rows"][0][0] = "changed"
    item = collector.items[0]
    assert item.provider == "codebase-memory" and item.provider_version == "9.9.9"
    assert json.loads(item.response_json) == saved
    assert json.loads(item.request_json)["project"] == "private-worker"
    assert item.basis == "decoded_query_response_not_complete_native_graph"


def test_native_queries_archive_separately_from_legacy_projection_and_roundtrip(tmp_path):
    manifest, result, old = received()
    collector, response = observations(result.provider, result.provider_version)
    enhanced = replace(result, native_query_observations=collector.items)
    assert enhanced == result
    assert json.loads(json.dumps(code_projection_payload(enhanced))) == old["result"]
    assert code_projection_payload(enhanced) == code_projection_payload(result)
    payload = received_code_observations(manifest, enhanced)
    assert payload["schema"] == "nasus.code-observation-archive.v2"
    assert payload["result"] == old["result"]
    assert json.loads(payload["native_queries"][0]["response_json"]) == response
    storage = archive(tmp_path)
    pin = storage.put(payload)
    report = {**{key: payload[key] for key in ("project_id", "source_id", "external_revision", "source_manifest_hash")},
        "provider": result.provider, "provider_version": result.provider_version, "observation_archive": pin}
    assert storage.read(report) == payload
    assert storage.put(payload) == pin
    assert old["schema"] == "nasus.code-observation-archive.v1" and "native_queries" not in old


@pytest.mark.parametrize("change", ["nan", "duplicate_key", "not_object", "extra_field", "wrong_basis", "empty", "old_schema", "wrong_provider"])
def test_native_archive_rejects_invalid_or_fabricated_transcripts(change):
    manifest, result, _ = received()
    collector, _ = observations(result.provider, result.provider_version)
    payload = received_code_observations(manifest, replace(result, native_query_observations=collector.items))
    item = payload["native_queries"][0]
    if change == "nan":
        item["response_json"] = '{"score":NaN}'
    elif change == "duplicate_key":
        item["response_json"] = '{"rows":[],"rows":[1]}'
    elif change == "not_object":
        item["request_json"] = "[]"
    elif change == "extra_field":
        item["token"] = "private"
    elif change == "wrong_basis":
        item["basis"] = "complete_native_graph"
    elif change == "empty":
        payload["native_queries"] = []
    elif change == "old_schema":
        payload["schema"] = "nasus.code-observation-archive.v1"
    else:
        item["provider"] = "borrowed-provider"
    with pytest.raises(ValueError):
        validate_observation_payload(payload)


def test_query_and_byte_bounds_reject_without_truncating_or_accepting_nan(monkeypatch):
    from apps.api.app.domain.system_image import code_native_observation as domain
    collector, _ = observations()
    with pytest.raises(ValueError):
        collector.record("query_graph", {}, {"score": float("nan")})
    assert len(collector.items) == 1
    monkeypatch.setattr(domain, "MAX_NATIVE_QUERY_COUNT", 1)
    with pytest.raises(ValueError, match="count"):
        collector.record("query_graph", {}, {})
    assert len(collector.items) == 1
    monkeypatch.setattr(domain, "MAX_NATIVE_QUERY_COUNT", 4096)
    monkeypatch.setattr(domain, "MAX_NATIVE_QUERY_BYTES", 1)
    with pytest.raises(ValueError, match="size"):
        collector.record("query_graph", {}, {})
    assert len(collector.items) == 1


def test_native_adapter_and_composite_preserve_all_received_query_responses(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    (root / "payments.py").write_text("class PaymentService:\n    def authorize(self):\n        return True\n\n# POST /payments\n# route\n")
    binary, log = _fake_codebase_memory(tmp_path)
    monkeypatch.setenv("FAKE_CBM_CALL_LOG", str(log))
    adapter = CompositeCodeIntelligenceAdapter(TreeSitterCodeIntelligenceAdapter(), _adapter(_config(binary)), mode="required")
    result = adapter.analyze_controlled([_source_unit(root)], check_current=lambda: None)
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    queried = [item for item in calls if item["tool"] in {"search_graph", "query_graph"}]
    assert len(result.native_query_observations) == len(queried) > 1
    assert [item.operation for item in result.native_query_observations] == [item["tool"] for item in queried]
    assert [json.loads(item.request_json) for item in result.native_query_observations] == [item["payload"] for item in queried]
    assert all(item.provider == "codebase-memory" for item in result.native_query_observations)
    assert "DEFINES_METHOD" in "".join(item.response_json for item in result.native_query_observations)
    assert any(edge.relationship_kind == "belongs_to" for edge in result.relationships)
    assert "native_query_observations" not in code_projection_payload(result)


def test_unmapped_native_types_endpoints_and_resolution_metadata_survive_rejection(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    (root / "payments.py").write_text("class PaymentService:\n    def authorize(self):\n        return True\n\n# POST /payments\n# route\n")
    binary, log = _fake_codebase_memory(tmp_path)
    monkeypatch.setenv("FAKE_CBM_CALL_LOG", str(log))
    adapter = _adapter(_config(binary))
    native_call = adapter._call

    def with_unmapped_rows(tool, request, **kwargs):
        payload = native_call(tool, request, **kwargs)
        if tool == "query_graph" and "type(r)" in request["query"]:
            payload["rows"].extend([
                ["payments.PaymentService", "payments.py", "NEW_NATIVE_KIND", "payments.authorize", "payments.py", "0.91", "provider-rule", {"extra": "unchanged"}],
                ["unresolved.symbol", "payments.py", "CALLS", "payments.authorize", "payments.py", "0.5", "fuzzy", 3],
                ["payments.PaymentService", "payments.py", "CALLS", "payments.authorize", "payments.py", "0.5", "fuzzy", 3],
            ])
            payload["total"] = len(payload["rows"])
        return payload

    adapter._call = with_unmapped_rows
    result = adapter.analyze_controlled([_source_unit(root)], check_current=lambda: None)
    rows = [row for item in result.native_query_observations if item.operation == "query_graph"
        for row in json.loads(item.response_json)["rows"]]
    assert any(row[2] == "NEW_NATIVE_KIND" and row[7] == {"extra": "unchanged"} for row in rows)
    assert any(row[0] == "unresolved.symbol" for row in rows)
    assert any(row[6:] == ["fuzzy", 3] for row in rows)
    assert not any(edge.relationship_kind == "calls" for edge in result.relationships)
    assert len(result.relationships) == 2


@pytest.mark.parametrize("raw", ['{"rows":[],"rows":[1]}', '{"score":NaN}', '{"score":Infinity}', '{"score":1e999}'])
@pytest.mark.parametrize("wrapped", [False, True])
def test_native_cli_decode_rejects_lossy_json_before_observation_capture(raw, wrapped):
    from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import CodebaseMemoryCodeIntelligenceAdapter, CodebaseMemoryError
    if wrapped:
        raw = json.dumps({"content": [{"type": "text", "text": raw}]})
    with pytest.raises(CodebaseMemoryError):
        CodebaseMemoryCodeIntelligenceAdapter._decode_payload(raw, "query_graph")


def test_unavailable_provider_cannot_supply_archived_native_observations():
    manifest, result, _ = received()
    observation = result.provider_observations[0]
    unavailable = replace(observation, entity_count=0, relationship_count=0, exact_locations=0,
        approximate_locations=0, entity_enumeration="not_run", relationship_enumeration="not_run", availability="unavailable")
    queries, _ = observations(result.provider, result.provider_version)
    with pytest.raises(ValueError, match="provider"):
        received_code_observations(manifest, replace(result, provider_observations=(unavailable,),
            native_query_observations=queries.items))


@pytest.mark.parametrize("wrapped", [False, True])
def test_native_cli_decode_preserves_valid_unicode_objects(wrapped):
    from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import CodebaseMemoryCodeIntelligenceAdapter
    value = {"rows": [["\u4e2d\u6587\U0001f986", {"score": 0.91}]], "total": 1}
    raw = json.dumps(value, ensure_ascii=False)
    if wrapped:
        raw = json.dumps({"content": [{"type": "text", "text": raw}]}, ensure_ascii=False)
    assert CodebaseMemoryCodeIntelligenceAdapter._decode_payload(raw, "query_graph") == value


@pytest.mark.parametrize("raw", ["[]", "null", "{} trailing", '{"content":[]}', '{"content":[{}]}',
    '{"content":[{"type":"text","text":"[]"}]}', '{"isError":true,"content":[{"text":"{}"}]}'])
def test_native_cli_decode_rejects_invalid_or_error_envelopes(raw):
    from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import CodebaseMemoryCodeIntelligenceAdapter, CodebaseMemoryError
    with pytest.raises(CodebaseMemoryError):
        CodebaseMemoryCodeIntelligenceAdapter._decode_payload(raw, "query_graph")


def test_legacy_projection_without_provider_declarations_retains_native_query_compatibility():
    manifest, result, _ = received()
    queries, _ = observations(result.provider, result.provider_version)
    payload = received_code_observations(manifest, replace(result, provider_observations=(),
        native_query_observations=queries.items))
    assert len(payload["native_queries"]) == 1
    validate_observation_payload(payload)
