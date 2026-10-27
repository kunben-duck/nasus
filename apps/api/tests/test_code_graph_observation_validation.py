from dataclasses import replace
import hashlib

from apps.api.app.application.system_image.source_ports import CodeEntityCandidate, CodeIntelligenceResult, CodeRelationshipCandidate, SourceTextUnit
from apps.api.app.infrastructure.system_image.composite_code_intelligence import CompositeCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter


def unit(path, text):
    data = text.encode()
    return SourceTextUnit(path, text, len(data), "sha256:" + hashlib.sha256(data).hexdigest())


def candidate(identifier, name, path, kind="module"):
    return CodeEntityCandidate(identifier, name, "provider." + name, kind, path, "java", 1, 1, ())


def test_native_java_imports_require_matching_syntax_verified_declarations():
    units = [unit("pkg/Header.java", "package pkg; import pkg.Foo; class Header {}"),
             unit("pkg/Foo.java", "package pkg; class Foo {}"),
             unit("pkg/Bar.java", "package pkg; class Bar { void stream() {} }")]
    observed = CodeIntelligenceResult("codebase-memory", "contract-fixture",
        (candidate("header", "Header.java", "pkg/Header.java"), candidate("foo", "Foo.java", "pkg/Foo.java"),
         candidate("bar", "Bar.java", "pkg/Bar.java"), candidate("stream", "stream", "pkg/Bar.java", "method")),
        tuple(CodeRelationshipCandidate("header", "depends_on", target, .88,
              ("code-graph-edge:codebase-memory:IMPORTS",)) for target in ("foo", "bar", "stream")), ())

    class Provider:
        def analyze(self, _):
            return observed

    result = CompositeCodeIntelligenceAdapter(TreeSitterCodeIntelligenceAdapter(), Provider(), mode="required").analyze(units)
    imports = [edge for edge in result.relationships if "code-graph-edge:codebase-memory:IMPORTS" in edge.evidence_refs]
    assert len(imports) == 1 and imports[0].to_provider_node_id == "foo"
    assert "code-graph-imports:unverified-java-target" in result.evidence_refs
    assert "code-graph-imports:excluded:2" in result.evidence_refs
    assert any(item.entity_kind == "dependency" and item.name == "pkg.Foo" for item in result.entities)


def test_shared_dependency_observation_does_not_lose_per_file_import_evidence():
    units = [unit("pkg/A.java", "package pkg; import pkg.Foo; class A {}"),
             unit("pkg/B.java", "package pkg; import pkg.Foo; class B {}"),
             unit("pkg/Foo.java", "package pkg; class Foo {}")]
    observed = CodeIntelligenceResult("codebase-memory", "contract-fixture",
        tuple(candidate(key, name, path) for key, name, path in
            (("a", "A.java", "pkg/A.java"), ("b", "B.java", "pkg/B.java"), ("foo", "Foo.java", "pkg/Foo.java"))),
        tuple(CodeRelationshipCandidate(source, "depends_on", "foo", .88,
            ("code-graph-edge:codebase-memory:IMPORTS",)) for source in ("a", "b")), ())

    class Provider:
        def analyze(self, _):
            return observed

    result = CompositeCodeIntelligenceAdapter(TreeSitterCodeIntelligenceAdapter(), Provider(), mode="required").analyze(units)
    imports = [edge for edge in result.relationships if "code-graph-edge:codebase-memory:IMPORTS" in edge.evidence_refs]
    assert {edge.from_provider_node_id for edge in imports} == {"a", "b"}
    assert not any(item.startswith("code-graph-imports:") for item in result.evidence_refs)


def test_rejecting_import_evidence_does_not_discard_another_edge_observation():
    from apps.api.app.infrastructure.system_image.code_graph_observation_validation import validate_java_imports
    primary = TreeSitterCodeIntelligenceAdapter().analyze([unit("pkg/A.java", "package pkg; class A {}"),
                                                         unit("pkg/B.java", "package pkg; class B {}")])
    edge = CodeRelationshipCandidate("a", "depends_on", "b", .88,
        ("code-graph-edge:codebase-memory:IMPORTS", "code-graph-edge:codebase-memory:USAGE"))
    observed = CodeIntelligenceResult("codebase-memory", "fixture",
        (candidate("a", "A.java", "pkg/A.java"), candidate("b", "B.java", "pkg/B.java")), (edge,), ())
    validated = validate_java_imports(observed, primary)
    assert validated.relationships == (replace(edge, evidence_refs=("code-graph-edge:codebase-memory:USAGE",)),)
