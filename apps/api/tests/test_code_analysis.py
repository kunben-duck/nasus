from __future__ import annotations

from dataclasses import replace
import hashlib
from types import SimpleNamespace

import pytest

from apps.api.app.application.system_image.code_analysis_inventory import build_code_analysis_inventory
from apps.api.app.application.system_image.source_ports import SourceTextUnit, CodeIntelligenceResult
from apps.api.app.domain.system_image.code_analysis import CodeFileAnalysis
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.composite_code_intelligence import CompositeCodeIntelligenceAdapter


def unit(path, text):
    data = text.encode()
    return SourceTextUnit(path, text, len(data), "sha256:" + hashlib.sha256(data).hexdigest())


def analyze(text, path="Controller.java"):
    return TreeSitterCodeIntelligenceAdapter().analyze([unit(path, text)])


def routes(result):
    return {(item.method, item.route_path) for item in result.structural_facts if item.kind == "route" and item.status == "observed"}


def test_spring_routes_use_ast_class_prefix_arrays_methods_and_multiline_annotations():
    result = analyze('''package example.payments;
import org.springframework.web.bind.annotation.*;
@RestController
@RequestMapping(path = {"/api/v1", "/api/v2"})
class Controller {
    // @PostMapping("/not-an-endpoint")
    String misleading = "@GetMapping(\\"/also-not-an-endpoint\\")";
    @RequestMapping(path = {"/orders", "/purchases/"},
                    method = {RequestMethod.GET, RequestMethod.POST})
    public String read() { return "ok"; }
}''')
    assert result.file_analyses[0].status == "parsed"
    assert routes(result) == {(method, prefix + suffix) for method in ("GET", "POST")
                              for prefix in ("/api/v1", "/api/v2") for suffix in ("/orders", "/purchases/")}
    assert {(fact.kind, fact.name) for fact in result.structural_facts} >= {("package", "example.payments")}
    assert len([item for item in result.entities if item.entity_kind == "api_route"]) == 8
    assert not any("not-an-endpoint" in fact.name for fact in result.structural_facts)
    for fact in result.structural_facts:
        if fact.kind == "route":
            assert fact.start_line < fact.end_line
            assert {span.role for span in fact.supporting_spans} == {"controller", "class_mapping"}


def test_spring_method_conditions_combine_by_union_not_intersection():
    result = analyze('''import org.springframework.web.bind.annotation.*;
@RestController
@RequestMapping(path = "/orders", method = RequestMethod.GET)
class Controller {
  @RequestMapping(path = "/create", method = { /* supported */ RequestMethod.POST }) void create() {}
  @RequestMapping(path = { /* supported */ "/query" }, method = {}) void query() {}
}''')
    assert routes(result) == {("GET", "/orders/create"), ("POST", "/orders/create"), ("GET", "/orders/query")}


def test_wildcard_prefix_requires_framework_pattern_resolution():
    result = analyze('''import org.springframework.web.bind.annotation.*;
@RestController @RequestMapping("/orders/*") class Controller {
    @GetMapping("/list") void list() {}
}''')
    assert not routes(result)
    assert any(fact.kind == "route" and fact.status == "unresolved" for fact in result.structural_facts)


@pytest.mark.parametrize("mapping", [
    '@GetMapping(BASE + "/orders")', '@GetMapping("${api.prefix}/orders")',
    '@GetMapping(path = "/orders", value = "/other")',
    '@GetMapping("/a") @PostMapping("/b")',
])
def test_dynamic_or_ambiguous_routes_are_unresolved_not_invented(mapping):
    result = analyze(f'''import org.springframework.web.bind.annotation.*;
@RestController class Controller {{ {mapping} String read() {{ return "ok"; }} }}''')
    assert result.file_analyses[0].status == "parsed"
    assert not routes(result)
    assert any(item.kind == "route" and item.status == "unresolved" for item in result.structural_facts)
    assert not any(item.entity_kind == "api_route" for item in result.entities)


@pytest.mark.parametrize("imports,shadow", [
    ("import own.RestController; import own.GetMapping;", ""),
    ("import org.springframework.web.bind.annotation.*; import own.*;", ""),
    ("import org.springframework.web.bind.annotation.*;", "@interface GetMapping { String value(); }"),
])
def test_annotations_require_unambiguous_framework_provenance(imports, shadow):
    result = analyze(f'''{imports}
{shadow}
@RestController class Controller {{ @GetMapping("/orders") String read() {{ return "ok"; }} }}''')
    assert not routes(result)


def test_known_service_event_database_test_and_application_declarations_have_locations():
    result = analyze('''package example;
@org.springframework.stereotype.Service class Service {
  @org.springframework.kafka.annotation.KafkaListener(topics = "orders") void consume() {}
  @org.junit.jupiter.api.Test void verifiesOrder() {}
}
@org.springframework.stereotype.Repository interface Orders {}
@org.springframework.boot.autoconfigure.SpringBootApplication class Application {}
''')
    assert result.file_analyses[0].status == "parsed"
    assert {(fact.kind, fact.name) for fact in result.structural_facts} >= {
        ("package", "example"), ("service", "Service"), ("event_consumer", "consume"),
        ("test_entrypoint", "verifiesOrder"), ("database_access", "Orders"), ("entrypoint", "Application"),
    }
    assert all(fact.start_line >= 1 for fact in result.structural_facts)


def test_syntax_errors_are_diagnostic_and_cannot_become_precise_entities_or_enhanced_facts():
    failed = analyze("class Broken { void missing( {", "Broken.java")
    assert failed.file_analyses[0].status == "failed" and failed.file_analyses[0].syntax_errors > 0
    assert not failed.entities and not failed.relationships and not failed.structural_facts
    enhanced = analyze("class Broken { void missing() {} }", "Broken.java")
    merged = CompositeCodeIntelligenceAdapter._merge(failed, enhanced)
    assert not merged.entities and not merged.structural_facts
    assert merged.file_analyses == failed.file_analyses
    with pytest.raises(ValueError, match="syntax errors"):
        CodeFileAnalysis("Broken.java", "java", "parsed", "invalid", "parser-v1", syntax_errors=1)


def test_failed_syntax_is_reportable_without_contacting_required_graph_provider():
    def unexpected(units):
        pytest.fail("invalid source must not be delegated to the graph provider")
    adapter = CompositeCodeIntelligenceAdapter(TreeSitterCodeIntelligenceAdapter(), SimpleNamespace(analyze=unexpected), mode="required")
    result = adapter.analyze([unit("Broken.java", "class Broken { void missing( {")])
    assert result.file_analyses[0].status == "failed"
    assert "code-graph:skipped:parse-failure" in result.evidence_refs


def test_lossy_decoded_code_is_not_claimed_as_valid_syntax(tmp_path):
    from apps.api.app.application.system_image.system_image_models import RawAssetRecord
    from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
    path = tmp_path / "Bad.java"
    path.write_bytes(b"// corrupt comment \xff\nclass Bad {}")
    reader = SourceIngestionService()
    units = reader.extract_text_units(RawAssetRecord(id="source", project_id="project", source_type="code", source_uri=str(path)))
    assert not units[0].text_is_lossless
    result = TreeSitterCodeIntelligenceAdapter().analyze(units)
    assert result.file_analyses[0].reason == "non_utf8_source"
    assert result.file_analyses[0].status == "failed" and not result.entities


def test_report_accounts_for_every_raw_file_and_does_not_call_unsupported_formats_parsed():
    units = [unit("ok.py", "def run():\n    return True\n"), unit("pom.xml", "<project/>"), unit("test_other.rb", "puts 'x'")]
    result = TreeSitterCodeIntelligenceAdapter().analyze(units)
    files = [{"path": item.relative_path, "content_hash": item.content_hash, "byte_count": item.byte_count} for item in units]
    files.append({"path": "binary.dat", "content_hash": "sha256:" + "a" * 64, "byte_count": 12})
    manifest = {"files": files, "project_id": "project", "source_id": "source", "external_revision": "commit"}
    report = build_code_analysis_inventory(manifest, result, units)
    assert report["summary"] == {"file_count": 4, "parsed": 1, "failed": 0, "unsupported": 2, "not_analyzed": 1, "fact_count": 3}
    assert any(item["relative_path"] == "binary.dat" and item["reason"] == "text_not_extracted" for item in report["files"])
    assert any(item["kind"] == "configuration_boundary" and item["status"] == "path_hint" for item in report["facts"])
    assert report["raw_inventory_available"] is False
    assert all("source_file_hash" in item for item in report["facts"])
    with pytest.raises(ValueError, match="fingerprint"):
        build_code_analysis_inventory(manifest, result, [replace(units[0], content_hash="sha256:" + "b" * 64), *units[1:]])
    with pytest.raises(ValueError, match="outside"):
        build_code_analysis_inventory(manifest, result, [*units, unit("outside.py", "pass")])


def test_legacy_provider_without_diagnostics_remains_unknown_instead_of_falsely_complete():
    source_unit = unit("x.py", "pass")
    result = CodeIntelligenceResult("legacy", "v1", (), (), ())
    manifest = {"files": [{"path": "x.py", "content_hash": source_unit.content_hash, "byte_count": 4}],
                "project_id": "project", "source_id": "source", "external_revision": "commit"}
    report = build_code_analysis_inventory(manifest, result, [source_unit])
    assert report["summary"]["not_analyzed"] == 1
    assert report["files"][0]["reason"] == "provider_not_reported"
