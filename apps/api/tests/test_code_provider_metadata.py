from __future__ import annotations

from dataclasses import replace

import pytest

from apps.api.app.application.system_image.code_analysis_inventory import build_code_analysis_inventory
from apps.api.app.application.system_image.source_ports import CodeIntelligenceResult, SourceTextUnit
from apps.api.app.domain.system_image.code_provider import (
    CodeProjectionGap, CodeProviderCapabilities, CodeProviderLimits, CodeProviderObservation,
    projection_payload, validate_projection_payload,
)
from apps.api.app.domain.system_image.evidence import text_digest
from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import (
    CodebaseMemoryCodeIntelligenceAdapter, CodebaseMemoryError,
)
from apps.api.app.infrastructure.system_image.composite_code_intelligence import CompositeCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.code_identity_normalization import attach_symbol_keys
from apps.api.tests.test_code_graph_enrichment import _config
from apps.api.tests.test_code_graph_relationship_scan import fixture as scan_fixture


def unit(path="source.py", text="def example():\n    return True\n"):
    return SourceTextUnit(path, text, len(text.encode("utf-8")), text_digest(text))


def observation(**changes):
    value = CodeProviderObservation(CodeProviderCapabilities("fixture", "1", ("capabilities", "analyze")),
        1, 0, 1, 0, "complete", "complete")
    return replace(value, **changes)


@pytest.mark.parametrize("identity", ["unresolved", "ambiguous", "duplicate"])
def test_unmapped_native_identities_remain_explicit_counted_projection_gaps(identity):
    syntax = TreeSitterCodeIntelligenceAdapter().analyze([unit()])
    symbol = next(item for item in syntax.entities if item.entity_kind == "function")
    candidate = replace(symbol, provider_node_id="native-function", symbol_key=None)
    reference = syntax
    if identity == "unresolved":
        candidate = replace(candidate, name="unknown_function")
    elif identity == "ambiguous":
        reference = replace(syntax, entities=(*syntax.entities, replace(symbol, provider_node_id="other-function")))
    entities = (candidate, replace(candidate, provider_node_id="duplicate-native")) if identity == "duplicate" else (candidate,)
    report = observation(entity_count=len(entities), exact_locations=len(entities))
    native = CodeIntelligenceResult("fixture", "1", entities, (), (), provider_observations=(report,))
    normalized = attach_symbol_keys(native, reference)
    assert normalized.entities and len(normalized.entities) == len(native.entities)
    assert all(item.symbol_key is None for item in normalized.entities)
    expected = "unresolved_symbol_identity" if identity == "unresolved" else "ambiguous_symbol_identity"
    assert {gap.reason: gap.count for gap in normalized.provider_observations[0].gaps} == {expected: len(entities)}
    assert normalized.provider_observations[0].entity_count == len(entities)
    assert native.provider_observations == (report,) and not report.gaps
    assert attach_symbol_keys(normalized, reference) == normalized
    payload = projection_payload(normalized.provider_observations)
    assert payload["status"] == "partial"
    validate_projection_payload(payload)


def test_identity_normalization_preserves_other_gaps_without_accumulating_old_counts():
    syntax = TreeSitterCodeIntelligenceAdapter().analyze([unit()])
    symbol = next(item for item in syntax.entities if item.entity_kind == "function")
    report = observation(gaps=(CodeProjectionGap("provider_scores_uncalibrated"),
                               CodeProjectionGap("unresolved_symbol_identity", 10)))
    native = CodeIntelligenceResult("fixture", "1", (replace(symbol, name="unknown_function"),), (), (),
        provider_observations=(report,))
    normalized = attach_symbol_keys(native, syntax)
    assert normalized.provider_observations[0].gaps == (CodeProjectionGap("provider_scores_uncalibrated"),
        CodeProjectionGap("unresolved_symbol_identity", 1))


def test_verified_identity_does_not_invent_an_identity_gap():
    syntax = TreeSitterCodeIntelligenceAdapter().analyze([unit()])
    symbol = next(item for item in syntax.entities if item.entity_kind == "function")
    report = observation()
    native = CodeIntelligenceResult("fixture", "1", (replace(symbol, symbol_key=None),), (), (),
        provider_observations=(report,))
    normalized = attach_symbol_keys(native, syntax)
    assert normalized.entities[0].symbol_key == symbol.symbol_key
    assert normalized.provider_observations == (report,)
    assert projection_payload(normalized.provider_observations)["status"] == "complete"


def test_capabilities_are_local_and_do_not_invent_v2_or_language_support(tmp_path, monkeypatch):
    adapter = CodebaseMemoryCodeIntelligenceAdapter(_config(tmp_path / "missing-binary"))
    monkeypatch.setattr(adapter, "_probe_version", lambda: pytest.fail("declarations must not probe or index"))
    declaration = adapter.capabilities()
    assert declaration.provider_version == "unprobed"
    assert declaration.operations == ("capabilities", "analyze", "analyze_controlled")
    assert declaration.languages == () and declaration.language_coverage == "unknown"
    assert declaration.limits.max_entities == adapter.config.max_entities
    assert declaration.limits.max_relationship_queries == adapter.config.max_relationship_queries
    syntax = TreeSitterCodeIntelligenceAdapter().capabilities()
    assert set(syntax.languages) == {"python", "javascript", "typescript", "tsx", "java", "go"}
    assert syntax.language_coverage == "declared"


@pytest.mark.parametrize("change", [
    {"entity_enumeration": "partial"}, {"relationship_enumeration": "unknown"},
    {"exact_locations": 0, "approximate_locations": 1}, {"gaps": (CodeProjectionGap("unverified"),)},
])
def test_partial_unknown_or_approximate_cannot_claim_complete(change):
    payload = projection_payload((observation(**change),))
    assert payload["status"] == "partial"
    validate_projection_payload(payload)
    payload["status"] = "complete"
    with pytest.raises(ValueError):
        validate_projection_payload(payload)


@pytest.mark.parametrize("change", [
    "boolean_count", "float_count", "location_count", "zero_gap", "duplicate_gap", "negative_limit",
    "infinite_timeout", "false_timeout", "invented_operation", "unknown_languages", "version_control",
    "extra_field", "schema", "scope", "missing_provider", "oversized_provider_set", "availability",
])
def test_corrupt_metadata_is_rejected(change):
    payload = projection_payload((observation(),))
    item, caps = payload["providers"][0], payload["providers"][0]["capabilities"]
    if change in {"boolean_count", "float_count"}:
        item["entity_count"] = True if change == "boolean_count" else 1.0
    elif change == "location_count":
        item["exact_locations"] = 2
    elif change in {"zero_gap", "duplicate_gap"}:
        item["gaps"] = [{"reason": "gap", "count": 0}] if change == "zero_gap" else [{"reason": "gap", "count": 1}] * 2
    elif change == "negative_limit":
        caps["limits"]["max_entities"] = -1
    elif change in {"infinite_timeout", "false_timeout"}:
        caps["limits"]["command_timeout_seconds"] = float("inf") if change == "infinite_timeout" else False
    elif change == "invented_operation":
        caps["operations"].append("delete_all")
    elif change == "unknown_languages":
        caps["languages"] = ["java"]
    elif change == "version_control":
        caps["provider_version"] = "1\nsecret"
    elif change == "extra_field":
        item["private_path"] = "/private/source"
    elif change in {"schema", "scope"}:
        payload[change] = "other"
    elif change == "missing_provider":
        payload["providers"] = []
    elif change == "oversized_provider_set":
        payload["providers"] *= 9
    elif change == "availability":
        item["availability"] = "not_run"
    with pytest.raises(ValueError):
        validate_projection_payload(payload)


def test_syntax_report_tracks_failed_unsupported_and_non_complete_call_coverage():
    adapter = TreeSitterCodeIntelligenceAdapter()
    result = adapter.analyze([unit(), unit("broken.py", "def broken(\n"), unit("README.md", "text")])
    report, = result.provider_observations
    assert report.entity_enumeration == "partial" and report.relationship_enumeration == "unknown"
    assert {gap.reason: gap.count for gap in report.gaps} == {
        "dynamic_dispatch_not_covered": None, "failed_source_parsing": 1, "unsupported_source_grammar": 1,
    }
    assert report.entity_count == len(result.entities)
    assert projection_payload(result.provider_observations)["status"] == "partial"


def test_native_scan_metadata_preserves_query_budget_and_counted_resolution_gaps(tmp_path):
    adapter, units, _, _ = scan_fixture(tmp_path)
    report, = adapter.analyze(units).provider_observations
    assert report.relationship_enumeration == "complete"
    assert {gap.reason: gap.count for gap in report.gaps}["unverified_call_resolution"] == 3
    other = tmp_path / "other"
    other.mkdir()
    adapter2, units2, _, _ = scan_fixture(other, page_size=1)
    adapter2.config = replace(adapter2.config, max_relationship_queries=1)
    report2, = adapter2.analyze(units2).provider_observations
    assert report2.relationship_enumeration == "partial"
    assert "query-budget-exceeded" in {gap.reason for gap in report2.gaps}


def test_exact_relationship_cap_is_conservatively_partial_not_complete(tmp_path):
    adapter, units, _, _ = scan_fixture(tmp_path, max_relationships=2)
    result = adapter.analyze(units)
    report, = result.provider_observations
    assert report.relationship_count == 2 and report.relationship_enumeration == "partial"
    assert "relationship_limit_reached" in {gap.reason for gap in report.gaps}
    assert "code-graph-relationships:truncated" in result.evidence_refs


def test_unconfigured_enhancer_does_not_claim_any_implemented_operations():
    adapter = CompositeCodeIntelligenceAdapter(TreeSitterCodeIntelligenceAdapter(), None, mode="optional")
    _, unavailable = adapter.analyze([unit()]).provider_observations
    assert unavailable.capabilities.operations == ()
    assert unavailable.availability == "unavailable"


@pytest.mark.parametrize("mode", ["disabled", "optional"])
def test_disabled_and_unavailable_enhancers_remain_visible_as_unobserved(mode):
    class Unavailable:
        provider = "fixture-enhancer"

        def capabilities(self):
            return CodeProviderCapabilities(self.provider, "1", ("capabilities", "analyze", "analyze_controlled"))

        def analyze(self, units):
            if mode == "disabled":
                pytest.fail("disabled graph must not run")
            raise CodebaseMemoryError("provider unavailable")

    adapter = CompositeCodeIntelligenceAdapter(TreeSitterCodeIntelligenceAdapter(), Unavailable(), mode=mode)
    assert set(adapter.capabilities().operations) == {"capabilities", "analyze", "analyze_controlled"}
    result = adapter.analyze([unit()])
    primary, enhancer = result.provider_observations
    assert primary.availability == "observed"
    assert enhancer.availability == ("not_run" if mode == "disabled" else "unavailable")
    assert enhancer.entity_enumeration == enhancer.relationship_enumeration == "not_run"
    assert enhancer.entity_count == enhancer.relationship_count == 0
    validate_projection_payload(projection_payload(result.provider_observations))


def test_new_inventory_versions_provider_metadata_without_rewriting_legacy():
    units = [unit()]
    manifest = {"project_id": "project", "source_id": "source", "external_revision": "fixed", "files": [
        {"path": units[0].relative_path, "content_hash": units[0].content_hash, "byte_count": units[0].byte_count},
    ]}
    result = TreeSitterCodeIntelligenceAdapter().analyze(units)
    current = build_code_analysis_inventory(manifest, result, units)
    assert current["schema"] == "nasus.code-analysis.v2" and current["projection"]["status"] == "partial"
    validate_projection_payload(current["projection"])
    legacy_result = replace(result, provider_observations=())
    legacy = build_code_analysis_inventory(manifest, legacy_result, units)
    assert legacy["schema"] == "nasus.code-analysis.v1" and "projection" not in legacy
    assert {key: value for key, value in current.items() if key != "projection" and key != "schema"} == {
        key: value for key, value in legacy.items() if key != "schema"}
    assert CodeIntelligenceResult("old", "1", (), (), ()).provider_observations == ()
