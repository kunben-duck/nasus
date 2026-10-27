from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from apps.api.app.application.system_image.source_ports import (
    CodeIntelligenceResult, CodeRelationshipCandidate, SourceTextUnit,
)
from apps.api.app.domain.system_image.code_identity import CodeSymbolKey
from apps.api.app.infrastructure.system_image.code_identity_normalization import attach_symbol_keys
from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import CodebaseMemoryError
from apps.api.app.infrastructure.system_image.composite_code_intelligence import CompositeCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter


def analyze(text: str, path: str = "sample.java") -> CodeIntelligenceResult:
    raw = text.encode()
    return TreeSitterCodeIntelligenceAdapter().analyze([
        SourceTextUnit(path, text, len(raw), hashlib.sha256(raw).hexdigest()),
    ])


def named(result: CodeIntelligenceResult, name: str):
    return [item for item in result.entities if item.name == name]


def external(result: CodeIntelligenceResult, *, exact: bool = True) -> CodeIntelligenceResult:
    return replace(result, provider="replacement-provider", provider_version="2", relationships=(), entities=tuple(
        replace(item, provider_node_id=f"external:{index}", qualified_name=f"other-checkout.scope.{index}",
                symbol_key=None, identity_status="unresolved",
                location_precision="exact" if exact else "approximate",
                evidence_refs=("code-graph-location:exact" if exact else "code-graph-location:approximate",))
        for index, item in enumerate(result.entities)
    ))


def test_line_body_comment_changes_preserve_key_but_not_provider_locator() -> None:
    before = analyze("class A { int load(String name) { return 1; } }\n")
    after = analyze("// leading comment\n\nclass A {\n int load( String renamed ) {\n return 200;\n }\n}\n")
    old, new = named(before, "load")[0], named(after, "load")[0]
    assert old.symbol_key == new.symbol_key
    assert old.symbol_key.fingerprint == new.symbol_key.fingerprint
    assert old.provider_node_id != new.provider_node_id
    assert old.start_line != new.start_line


def test_same_line_overloads_and_scopes_remain_separate() -> None:
    result = analyze("class A { void f(int x){} void f(String x){} } class B { void f(int x){} }")
    methods = named(result, "f")
    assert len(methods) == 3
    assert len({item.provider_node_id for item in methods}) == 3
    assert len({item.symbol_key for item in methods}) == 3
    assert all(item.identity_status == "exact" for item in methods)


def test_python_nested_scope_and_defaults() -> None:
    result = analyze("def a():\n def inner(x=1): return x\n\ndef b():\n def inner(x=1): return x\n", "scope.py")
    changed = analyze("def a():\n def inner(x=200): return x+1\n\ndef b():\n def inner(x=300): return x\n", "scope.py")
    assert len({item.symbol_key for item in named(result, "inner")}) == 2
    assert [item.symbol_key for item in named(result, "inner")] == [item.symbol_key for item in named(changed, "inner")]


def test_go_receiver_types_are_part_of_scope() -> None:
    result = analyze("package p\ntype A struct{}\ntype B struct{}\nfunc (a A) Run(x int){}\nfunc (b B) Run(x int){}\n", "scope.go")
    renamed = analyze("package p\ntype A struct{}\ntype B struct{}\nfunc (other A) Run(renamed int){}\nfunc (b B) Run(x int){}\n", "scope.go")
    assert len({item.symbol_key for item in named(result, "Run")}) == 2
    assert named(result, "Run")[0].symbol_key == named(renamed, "Run")[0].symbol_key


def test_grouped_go_parameters_and_java_arrays_do_not_collapse() -> None:
    grouped = analyze("package p\nfunc F(a, b int){}\n", "p.go")
    separate = analyze("package p\nfunc F(a int, b int){}\n", "p.go")
    assert named(grouped, "F")[0].symbol_key == named(separate, "F")[0].symbol_key
    java = analyze("class A { void f(int x){} void f(int x[]){} void f(int... x){} }")
    assert len({item.symbol_key for item in named(java, "f")}) == 3


def test_case_sensitive_paths_and_names() -> None:
    first = analyze("class A { void Read(){} void read(){} }", "src/A.java")
    other = analyze("class A { void Read(){} void read(){} }", "src/a.java")
    assert named(first, "Read")[0].symbol_key != named(first, "read")[0].symbol_key
    assert named(first, "Read")[0].symbol_key != named(other, "Read")[0].symbol_key
    combined = CompositeCodeIntelligenceAdapter._merge(first, external(other))
    assert len(combined.entities) == len(first.entities) + len(other.entities)


def test_identical_redeclarations_and_name_only_calls_are_ambiguous() -> None:
    result = analyze("def load(): return 1\ndef load(): return 2\ndef call(): return load()\n", "p.py")
    assert len(named(result, "load")) == 2
    assert all(item.symbol_key is None and item.identity_status == "ambiguous" for item in named(result, "load"))
    assert not any(item.relationship_kind == "calls" for item in result.relationships)


def test_ambiguous_enclosing_scope_does_not_give_children_stable_keys() -> None:
    result = analyze("def outer():\n def first(): return 1\ndef outer():\n def second(): return 2\n", "p.py")
    for name in ("outer", "first", "second"):
        assert all(item.symbol_key is None and item.identity_status == "ambiguous" for item in named(result, name))


def test_syntax_error_and_unsupported_symbols_are_not_exact_identities() -> None:
    broken = analyze("class A { void f( {\n")
    assert all(item.symbol_key is None for item in broken.entities if item.entity_kind != "module")
    unsupported = analyze("class A\n def f\n end\nend\n", "p.rb")
    assert all(item.symbol_key is None for item in unsupported.entities if item.entity_kind != "module")
    module = next(item for item in unsupported.entities if item.entity_kind == "module")
    assert module.symbol_key == CodeSymbolKey("p.rb", "rb", "module", (), "p.rb")
    assert unsupported.file_analyses[0].status == "unsupported"


def test_provider_swap_and_namespace_changes_keep_matching_keys() -> None:
    reference = analyze("class A {\n void read(int x){}\n void read(String x){}\n}\n")
    replaced = attach_symbol_keys(external(reference), reference)
    assert [item.symbol_key for item in replaced.entities] == [item.symbol_key for item in reference.entities]
    assert all(item.provider_node_id != ref.provider_node_id for item, ref in zip(replaced.entities, reference.entities))
    merged = CompositeCodeIntelligenceAdapter._merge(reference, replaced)
    assert len(merged.entities) == len(reference.entities)


def test_unique_symbol_with_wrong_in_bounds_span_is_not_exact_evidence() -> None:
    primary = analyze("class A {\n void read(){}\n void write(){}\n}\n")
    provider = external(primary)
    incorrect = replace(named(provider, "read")[0], start_line=3, end_line=3)
    provider = replace(provider, entities=(incorrect,))
    enhanced = attach_symbol_keys(provider, primary)
    entity = named(enhanced, "read")[0]
    assert entity.symbol_key == named(primary, "read")[0].symbol_key
    assert entity.identity_status == "exact"
    assert entity.location_precision == "approximate"
    assert (entity.start_line, entity.end_line) == (3, 3)
    assert "code-graph-location:syntax-mismatch" in entity.evidence_refs
    assert "code-graph-location:exact" not in entity.evidence_refs
    merged = CompositeCodeIntelligenceAdapter._merge(primary, enhanced)
    exact = named(merged, "read")[0]
    assert exact.location_precision == "exact"
    assert (exact.start_line, exact.end_line) == (2, 2)


def test_approximate_overloads_are_not_merged_or_assigned_keys() -> None:
    reference = analyze("class A {\n void read(int x){}\n void read(String x){}\n}\n")
    replaced = attach_symbol_keys(external(reference, exact=False), reference)
    assert all(item.symbol_key is None and item.identity_status == "ambiguous" for item in named(replaced, "read"))
    merged = CompositeCodeIntelligenceAdapter._merge(reference, replaced)
    assert len(named(merged, "read")) == 4


def test_same_line_overloads_remain_ambiguous_without_columns() -> None:
    reference = analyze("class A { void read(int x){} void read(String x){} }")
    replaced = attach_symbol_keys(external(reference), reference)
    assert all(item.symbol_key is None for item in named(replaced, "read"))


def test_duplicate_external_nodes_do_not_share_one_canonical_key() -> None:
    reference = analyze("class A {}")
    candidate = named(external(reference), "A")[0]
    replaced = attach_symbol_keys(replace(external(reference), entities=(candidate, replace(candidate, provider_node_id="duplicate"))), reference)
    assert all(item.identity_status == "ambiguous" and item.symbol_key is None for item in replaced.entities)


def test_enhancer_approximation_does_not_downgrade_precise_primary_locator() -> None:
    primary = analyze("class A {}")
    enhanced = attach_symbol_keys(external(primary, exact=False), primary)
    merged = CompositeCodeIntelligenceAdapter._merge(primary, enhanced)
    entity = named(merged, "A")[0]
    assert "code-graph-location:approximate" in entity.evidence_refs
    assert entity.location_precision == "exact"


def test_colliding_provider_ids_do_not_redirect_primary_edges() -> None:
    primary = analyze("def a(): return b()\ndef b(): return 1", "p.py")
    a, b = named(primary, "a")[0], named(primary, "b")[0]
    foreign = replace(a, name="other", relative_path="other.py", symbol_key=None, identity_status="unresolved")
    enhanced = replace(primary, entities=(foreign,), relationships=(
        CodeRelationshipCandidate(foreign.provider_node_id, "calls", "missing", .8, ()),
    ))
    merged = CompositeCodeIntelligenceAdapter._merge(primary, enhanced)
    assert len({item.provider_node_id for item in merged.entities}) == len(merged.entities)
    assert any(item.from_provider_node_id == a.provider_node_id and item.to_provider_node_id == b.provider_node_id
               for item in merged.relationships)


def test_ambiguous_provider_ids_are_rejected_instead_of_redirecting_edges() -> None:
    primary = analyze("class A {}")
    provider = external(primary)
    duplicate = replace(provider, entities=(provider.entities[0], provider.entities[0]))
    with pytest.raises(CodebaseMemoryError, match="duplicate provider node IDs"):
        CompositeCodeIntelligenceAdapter._merge(primary, duplicate)


@pytest.mark.parametrize("path", [".", "/tmp/a.java", "../a.java", "src/../a.java", "src\\a.java", "a\x00.java", "src//a.java"])
def test_canonical_keys_reject_non_relative_paths(path: str) -> None:
    with pytest.raises(ValueError):
        CodeSymbolKey(path, "java", "class", (), "A")
