from collections import defaultdict
from dataclasses import replace

from ...application.system_image.source_ports import CodeIntelligenceResult
from ...domain.system_image.code_provider import CodeProjectionGap


def validate_java_imports(observed: CodeIntelligenceResult, syntax: CodeIntelligenceResult) -> CodeIntelligenceResult:
    """Verify provider import targets against existing syntax observations.

    The external graph may resolve a library name to an unrelated project
    symbol. This does not add a resolver or parse source independently.
    """
    imported = defaultdict(set)
    syntax_entities = {item.provider_node_id: item for item in syntax.entities}
    for edge in syntax.relationships:
        source = syntax_entities.get(edge.from_provider_node_id)
        target = syntax_entities.get(edge.to_provider_node_id)
        if (source is not None and target is not None and source.language == "java"
                and edge.relationship_kind == "depends_on" and target.entity_kind == "dependency"):
            imported[source.relative_path].add(target.name)
    packages = {item.relative_path: item.name for item in syntax.structural_facts
                if item.kind == "package" and item.status == "observed"}
    declarations = defaultdict(set)
    for entity in syntax.entities:
        package = packages.get(entity.relative_path)
        if package and entity.language == "java" and entity.entity_kind in {"class", "interface", "enum"}:
            declarations[entity.relative_path].add(package + "." + entity.name)

    entities = {item.provider_node_id: item for item in observed.entities}
    marker = "code-graph-edge:codebase-memory:IMPORTS"
    retained = []
    excluded = 0
    for edge in observed.relationships:
        source = entities.get(edge.from_provider_node_id)
        target = entities.get(edge.to_provider_node_id)
        if source is not None and target is not None and source.language == "java" and marker in edge.evidence_refs:
            names = declarations[target.relative_path]
            if target.entity_kind != "module":
                names = {name for name in names if name.rsplit(".", 1)[-1] == target.name}
            if target.entity_kind not in {"module", "class", "interface", "enum"} or not (names & imported[source.relative_path]):
                excluded += 1
                refs = tuple(ref for ref in edge.evidence_refs if ref != marker)
                if not refs:
                    continue
                edge = replace(edge, evidence_refs=refs)
        retained.append(edge)
    refs = observed.evidence_refs
    if excluded:
        refs = (*refs, "code-graph-imports:unverified-java-target", f"code-graph-imports:excluded:{excluded}")
    reports = observed.provider_observations
    if excluded:
        reports = tuple(replace(report, relationship_count=len(retained),
            gaps=(*report.gaps, CodeProjectionGap("unverified_java_import_targets", excluded)))
            if report.capabilities.provider == "codebase-memory" else report for report in reports)
    return replace(observed, relationships=tuple(retained), evidence_refs=tuple(dict.fromkeys(refs)),
                   provider_observations=reports)
