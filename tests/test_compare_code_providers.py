"""Probe accounting does not silently upgrade an unstable raw provider graph."""
from dataclasses import replace
import importlib.util
from pathlib import Path

from apps.api.app.application.system_image.source_ports import code_projection_payload
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.tests.test_code_graph_observation_validation import candidate, unit
from apps.api.app.application.system_image.source_ports import CodeIntelligenceResult, CodeRelationshipCandidate


def test_comparison_retains_disputed_raw_imports_and_separate_admitted_projection():
    path = Path(__file__).resolve().parents[1] / "scripts/compare-code-providers.py"
    spec = importlib.util.spec_from_file_location("nasus_code_provider_comparison", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    syntax = TreeSitterCodeIntelligenceAdapter().analyze([
        unit("pkg/A.java", "package pkg; import java.util.stream.Stream; class A {}"),
        unit("pkg/B.java", "package pkg; class B { void stream() {} }"),
        unit("pkg/C.java", "package pkg; class C { void stream() {} }"),
    ])
    result = CodeIntelligenceResult("codebase-memory", "explicit_protocol_fixture",
        (candidate("a", "A.java", "pkg/A.java"), candidate("b", "stream", "pkg/B.java", "method"),
         candidate("c", "stream", "pkg/C.java", "method")),
        (CodeRelationshipCandidate("a", "depends_on", "b", .88, ("code-graph-edge:codebase-memory:IMPORTS",)),), ())
    alternate = replace(result, relationships=(replace(result.relationships[0], to_provider_node_id="c"),))
    raw, admitted = module.comparison_projections(result, syntax)
    raw_other, admitted_other = module.comparison_projections(alternate, syntax)
    assert snapshot_digest(code_projection_payload(raw)) != snapshot_digest(code_projection_payload(raw_other))
    assert snapshot_digest(code_projection_payload(admitted)) == snapshot_digest(code_projection_payload(admitted_other))
    assert raw.relationships == result.relationships and not admitted.relationships
    assert "code-graph-imports:unverified-java-target" in admitted.evidence_refs
