"""Expose verified quality artifacts through a bounded application read port."""
from typing import Protocol

from ...domain.system_image.derivation_impact import (
    DerivationImpactIntegrityError, DerivationImpactTooLarge, DerivationNode, MAX_DEPENDENCIES,
)
from ...domain.system_image.source_snapshots import snapshot_digest


class ContextDependencyInventoryPort(Protocol):
    def list(self, project_id, context_id): ...


class QualityContextDependencyApplicationService:
    def __init__(self, inventory: ContextDependencyInventoryPort, scopes, results, mappings, authorization):
        self.inventory, self.scopes, self.results = inventory, scopes, results
        self.mappings, self.authorization = mappings, authorization

    def read(self, project_id, context_id, *, pinned=None):
        access = self.authorization.scope(project_id)
        try:
            selected = self.inventory.list(project_id, context_id) if pinned is None else pinned
        except Exception:
            self.authorization.require_current(access)
            raise
        self.authorization.require_current(access)
        if (type(selected) is not tuple or any(type(item) is not tuple or len(item) != 2
                or item[0] not in {"scope", "generation", "mapping"}
                or type(item[1]) is not str or not 1 <= len(item[1]) <= 128 for item in selected)):
            raise DerivationImpactIntegrityError("invalid quality dependency inventory")
        if len(selected) > MAX_DEPENDENCIES - 1:
            raise DerivationImpactTooLarge("quality dependency inventory exceeds the complete query budget")
        if len({(kind, ident) for kind, ident in selected}) != len(selected):
            raise DerivationImpactIntegrityError("duplicate quality dependency pin")
        nodes, values = [], {}
        for kind, ident in sorted(selected, key=lambda item: ({"scope": 0, "generation": 1, "mapping": 2}[item[0]], item[1])):
            self.authorization.require_current(access)
            if kind == "scope":
                value = self.scopes.read(project_id, ident)
                self.authorization.require_current(access)
                revision = value["revision"]
                if revision["context_id"] != context_id or revision["revision_id"] != ident:
                    raise DerivationImpactIntegrityError("scope dependency belongs to another context")
                parents = ["context:" + context_id]
                if revision["previous_revision_id"]:
                    parents.append("scope:" + revision["previous_revision_id"])
            elif kind == "generation":
                value = self.results.read(project_id, ident)
                self.authorization.require_current(access)
                revision = value["metadata"]
                if revision["generation_id"] != ident:
                    raise DerivationImpactIntegrityError("generation dependency identity mismatch")
                parents = ["scope:" + revision["scope_revision_id"]]
                proposal = value["result"]["proposal"]
                for case in proposal["cases"]:
                    nodes.append(DerivationNode("case", ident + "/" + case["case_id"], snapshot_digest(case),
                                                ("generation:" + ident,)))
                nodes.append(DerivationNode("coverage", ident, snapshot_digest(proposal["coverage"]),
                                            ("generation:" + ident,)))
            elif kind == "mapping":
                value = self.mappings.read(project_id, ident)
                self.authorization.require_current(access)
                revision = value["revision"]
                if revision["revision_id"] != ident:
                    raise DerivationImpactIntegrityError("mapping dependency identity mismatch")
                parents = ["generation:" + revision["generation_id"]]
                if revision["previous_revision_id"]:
                    parents.append("mapping:" + revision["previous_revision_id"])
            else:
                raise DerivationImpactIntegrityError("unknown quality dependency kind")
            if revision["project_id"] != project_id:
                raise DerivationImpactIntegrityError("cross-project quality dependency")
            values[(kind, ident)] = revision
            nodes.append(DerivationNode(kind, ident, revision["artifact_hash"], tuple(sorted(parents))))
            self.authorization.require_current(access)
            if len(nodes) > MAX_DEPENDENCIES - 1:
                raise DerivationImpactTooLarge("expanded quality graph exceeds 128 nodes; nothing was truncated")
        # A pinned replay never discovers new records, but must still include all
        # ancestors and verify exact cross-artifact content pins.
        for node in nodes:
            if node.kind == "scope":
                revision = values[("scope", node.artifact_id)]
            elif node.kind == "generation":
                revision = values[("generation", node.artifact_id)]
                parent = values.get(("scope", revision["scope_revision_id"]))
                if parent is None:
                    raise DerivationImpactIntegrityError("generation scope ancestor missing")
            elif node.kind == "mapping":
                revision = values[("mapping", node.artifact_id)]
                parent = values.get(("generation", revision["generation_id"]))
                if parent is None or parent["artifact_hash"] != revision["generation_artifact_hash"]:
                    raise DerivationImpactIntegrityError("mapping generation ancestor mismatch")
        self.authorization.require_current(access)
        return tuple(sorted(nodes, key=lambda node: node.key))
