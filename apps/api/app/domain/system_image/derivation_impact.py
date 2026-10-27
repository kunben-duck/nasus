"""Prospective invalidation of pinned artifacts, never mutation or execution consent."""
from dataclasses import dataclass

from .evidence import valid_digest
from .source_delta import SourceDelta
from .source_snapshots import snapshot_digest


IMPACT_POLICY = "nasus.context-change-impact.v1"
MAX_DEPENDENCIES = 128
DEPENDENCY_KINDS = frozenset({"context", "scope", "generation", "case", "coverage", "mapping"})


class DerivationImpactIntegrityError(ValueError):
    pass


class DerivationImpactTooLarge(ValueError):
    pass


@dataclass(frozen=True)
class DerivationNode:
    kind: str
    artifact_id: str
    artifact_hash: str
    dependencies: tuple[str, ...]

    @property
    def key(self):
        return self.kind + ":" + self.artifact_id

    @property
    def payload_v1(self):
        # Future dataclass fields must not alter a historical graph digest.
        return {"kind": self.kind, "artifact_id": self.artifact_id,
            "artifact_hash": self.artifact_hash, "dependencies": self.dependencies}

    def __post_init__(self):
        if (type(self.kind) is not str or self.kind not in DEPENDENCY_KINDS or type(self.artifact_id) is not str
                or not 1 <= len(self.artifact_id) <= 256 or type(self.artifact_hash) is not str or not valid_digest(self.artifact_hash)
                or type(self.dependencies) is not tuple
                or any(type(value) is not str or not 1 <= len(value) <= 512 for value in self.dependencies)
                or tuple(sorted(set(self.dependencies))) != self.dependencies):
            raise DerivationImpactIntegrityError("invalid derivation node")


@dataclass(frozen=True)
class DerivationImpact:
    graph_hash: str
    affected_keys: tuple[str, ...]
    reason_codes: tuple[str, ...]
    query_scope_fingerprint: str
    dependency_count: int
    dependency_closure_complete: bool = True
    impact_complete: bool = False
    invalidation_applied: bool = False
    generation_authorized: bool = False
    execution_authorized: bool = False
    schema_version: str = IMPACT_POLICY


def validate_derivation_graph(nodes: tuple[DerivationNode, ...], root_key: str):
    if (type(nodes) is not tuple or any(not isinstance(node, DerivationNode) for node in nodes)
            or type(root_key) is not str):
        raise DerivationImpactIntegrityError("invalid fixed dependency graph")
    if len(nodes) > MAX_DEPENDENCIES:
        raise DerivationImpactTooLarge("dependency graph exceeds 128 nodes; no partial closure is returned")
    graph = {node.key: node for node in nodes}
    if len(graph) != len(nodes) or root_key not in graph or graph[root_key].kind != "context":
        raise DerivationImpactIntegrityError("dependency graph has duplicate nodes or no context root")
    children, remaining = {key: [] for key in graph}, {}
    for key, node in graph.items():
        if (key == root_key) != (not node.dependencies):
            raise DerivationImpactIntegrityError("every derived artifact requires a context-rooted dependency")
        remaining[key] = len(node.dependencies)
        for dependency in node.dependencies:
            if dependency not in graph:
                raise DerivationImpactIntegrityError("dependency closure is missing an ancestor")
            children[dependency].append(key)
        parent_kinds = sorted(graph[dependency].kind for dependency in node.dependencies)
        allowed = {"context": [[]], "scope": [["context"], ["context", "scope"]],
            "generation": [["scope"]], "case": [["generation"]], "coverage": [["generation"]],
            "mapping": [["generation"], ["generation", "mapping"]]}
        if parent_kinds not in allowed[node.kind]:
            raise DerivationImpactIntegrityError("dependency edge types do not match artifact semantics")
    ready, ordered = [root_key], []
    while ready:
        key = ready.pop()
        ordered.append(key)
        for child in children[key]:
            remaining[child] -= 1
            if remaining[child] == 0:
                ready.append(child)
    if len(ordered) != len(graph):
        raise DerivationImpactIntegrityError("dependency graph is cyclic or disconnected")
    return graph, tuple(sorted(ordered))


def assess_derivation_impact(nodes: tuple[DerivationNode, ...], root_key: str,
                             delta: SourceDelta, query_scope_fingerprint: str) -> DerivationImpact:
    if type(query_scope_fingerprint) is not str or not valid_digest(query_scope_fingerprint):
        raise DerivationImpactIntegrityError("invalid query scope fingerprint")
    graph, ordered = validate_derivation_graph(nodes, root_key)
    reasons = set()
    if any(delta.counts[kind] for kind in ("added", "modified", "deleted")):
        reasons.add("source_files_changed")
        # Negative results/top-k selection also depend on the entire source scope.
        # Matching only already-selected evidence would miss newly added files.
        reasons.add("query_scope_changed")
    if not delta.complete or delta.counts["unresolved"]:
        reasons.add("source_inventory_incomplete")
    if delta.full_validation_required:
        reasons.add("full_source_validation_required")
    return DerivationImpact(
        snapshot_digest([graph[key].payload_v1 for key in sorted(graph)]),
        tuple(sorted(ordered)) if reasons else (), tuple(sorted(reasons)),
        query_scope_fingerprint, len(graph))
