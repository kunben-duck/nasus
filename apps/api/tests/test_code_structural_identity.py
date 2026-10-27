from dataclasses import replace

import pytest

from apps.api.app.application.system_image.code_entity_registry import CodeEntityRegistrationService
from apps.api.app.application.system_image.system_image_models import RawAssetRecord
from apps.api.app.domain.system_image.code_analysis import CodeStructureSpan
from apps.api.app.infrastructure.system_image.code_identity_normalization import attach_symbol_keys
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.tests.test_code_analysis import unit
from apps.api.tests.test_code_symbol_identity import external


CONTROLLERS = '''import org.springframework.web.bind.annotation.*;
@RestController
@RequestMapping("/api")
class First {
    @GetMapping("/items")
    String read() { return "first"; }
}
@RestController
@RequestMapping("/api")
class Second {
    @GetMapping("/items")
    String read() { return "second"; }
}
'''


class RecordingRegistry:
    def register(self, source, observations, **kwargs):
        self.observations = observations
        return {item.provider_node_id: item for item in observations}


def analyze(text=CONTROLLERS, path="Controller.java"):
    units = [unit(path, text)]
    return units, TreeSitterCodeIntelligenceAdapter().analyze(units)


def routes(result):
    return [item for item in result.entities if item.entity_kind == "api_route"]


def test_routes_pin_distinct_handler_scopes_and_parent_relationships():
    _, result = analyze()
    candidates = routes(result)
    assert len(candidates) == 2 and len({item.symbol_key for item in candidates}) == 2
    by_id = {item.provider_node_id: item for item in result.entities}
    for candidate in candidates:
        assert candidate.identity_status == "exact" and candidate.location_precision == "exact"
        parents = [edge.to_provider_node_id for edge in result.relationships
                   if edge.from_provider_node_id == candidate.provider_node_id and edge.relationship_kind == "belongs_to"]
        assert len(parents) == 1 and by_id[parents[0]].entity_kind == "method"
        assert candidate.symbol_key.scope[-1] == by_id[parents[0]].symbol_key.scope_segment
        assert {span.role for span in candidate.supporting_spans} == {"controller", "class_mapping"}


def test_line_motion_and_provider_swap_preserve_route_keys_and_supporting_evidence():
    _, first = analyze()
    _, shifted = analyze("// moved\n\n" + CONTROLLERS)
    assert {item.symbol_key for item in routes(first)} == {item.symbol_key for item in routes(shifted)}
    swapped = attach_symbol_keys(external(first), first)
    assert [(item.symbol_key, item.supporting_spans) for item in routes(swapped)] == [
        (item.symbol_key, item.supporting_spans) for item in routes(first)]
    assert all(item.provider_node_id not in {node.provider_node_id for node in first.entities} for item in routes(swapped))


def test_duplicate_owner_is_not_promoted_even_when_route_paths_differ():
    text = '''
import org.springframework.web.bind.annotation.*;
@RestController class Controller {
 @GetMapping("/one") String read() { return "one"; }
 @GetMapping("/two") String read() { return "two"; }
}
'''
    _, result = analyze(text)
    assert len(routes(result)) == 2
    assert all(item.symbol_key is None and item.identity_status == "ambiguous" for item in routes(result))


def test_same_line_handlers_without_unique_owner_stay_unresolved():
    _, result = analyze('''import org.springframework.web.bind.annotation.*;
@RestController class C { @GetMapping("/a") String a(){return "a";} @GetMapping("/b") String b(){return "b";} }
''')
    assert len(routes(result)) == 2
    assert all(item.symbol_key is None and item.identity_status == "unresolved" for item in routes(result))


def test_import_identity_is_order_independent_and_retains_wildcards():
    units = [unit("Z.java", "import java.util.*;\nclass Z {}\n"),
             unit("A.java", "import java.util.*;\nclass A {}\n")]
    adapter = TreeSitterCodeIntelligenceAdapter()
    before, after = adapter.analyze(units), adapter.analyze(list(reversed(units)))
    dependencies = [item for item in before.entities if item.entity_kind == "dependency"]
    assert len(dependencies) == 1 and dependencies[0].name == "java.util.*"
    assert dependencies[0].relative_path == "A.java"
    assert dependencies[0].identity_status == "exact" and dependencies[0].location_precision == "exact"
    assert dependencies == [item for item in after.entities if item.entity_kind == "dependency"]


def test_verified_file_identity_does_not_claim_unsupported_declarations():
    _, result = analyze("class NotParsed\nend\n", "file.rb")
    module = next(item for item in result.entities if item.entity_kind == "module")
    assert module.symbol_key is not None and module.location_precision == "exact"
    assert result.file_analyses[0].status == "unsupported"
    assert all(item.symbol_key is None for item in result.entities if item.entity_kind != "module")
    assert any(gap.reason == "unsupported_source_grammar" for observation in result.provider_observations for gap in observation.gaps)


def test_registration_preserves_three_route_spans_and_static_only_basis():
    units, result = analyze()
    registry = RecordingRegistry()
    observations = CodeEntityRegistrationService(registry).register(
        RawAssetRecord(id="code", project_id="project", source_type="code", source_uri="fixture"),
        result, units, captured_at="2026-10-08")
    first = observations[routes(result)[0].provider_node_id].payload
    assert first["schema"] == "nasus.code-entity-observation.v3"
    assert first["observation_basis"] == "static_route_declaration"
    assert len(first["supporting_locators"]) == 2
    assert all(item["decoded_snippet_hash"].startswith("sha256:") for item in first["supporting_locators"])
    imported = next(item.payload for item in registry.observations if item.symbol_key.kind == "dependency")
    assert imported["observation_basis"] == "static_import_not_resolved_runtime_dependency"
    assert imported["supporting_locators"] == []


@pytest.mark.parametrize("fault", ["lossy", "foreign_support", "support_on_method"])
def test_registration_rejects_lossy_or_out_of_scope_structural_evidence(fault):
    units, result = analyze()
    target = routes(result)[0] if fault != "support_on_method" else next(
        item for item in result.entities if item.entity_kind == "method")
    if fault == "lossy":
        units = [replace(units[0], text_is_lossless=False)]
    else:
        target = replace(target, supporting_spans=(CodeStructureSpan(999, 999, "controller"),))
    with pytest.raises(ValueError):
        CodeEntityRegistrationService(RecordingRegistry()).register(
            RawAssetRecord(id="code", project_id="project", source_type="code", source_uri="fixture"),
            replace(result, entities=(target,)), units, captured_at="2026-10-08")
