"""Full selected-case metadata verification, without storage or model calls."""
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.test_design_results import TestDesignResultIntegrityError
from apps.api.app.domain.system_image.derivation_impact import DerivationNode
from apps.api.app.domain.system_image.derivation_registry import DerivationRegistration, REGISTRY_POLICY
from apps.api.app.infrastructure.persistence.automation_provenance_v1 import AutomationProvenanceProjectorV1


H = "sha256:" + "a" * 64


def registrations():
    specs = [("context", "ctx", ()), ("scope", "s", ("context:ctx",)),
        ("generation", "g", ("scope:s",)), ("coverage", "g", ("generation:g",)),
        ("mapping", "m", ("generation:g",))]
    specs.extend(("case", "g/c" + str(index), ("generation:g",)) for index in range(512))
    return tuple(DerivationRegistration("project", "ctx", "command", DerivationNode(kind, ident, H, parents))
        for kind, ident, parents in specs)


class MetadataSession:
    def __init__(self, values):
        self.nodes = [SimpleNamespace(project_id=value.project_id, context_id=value.context_id,
            node_key=value.node.key, kind=value.node.kind, artifact_id=value.node.artifact_id,
            artifact_hash=value.node.artifact_hash, invocation_id=value.invocation_id,
            content_hash=value.content_hash, policy_revision=REGISTRY_POLICY) for value in values]
        self.edges = [SimpleNamespace(project_id=value.project_id, context_id=value.context_id,
            node_key=value.node.key, parent_key=key) for value in values for key in value.node.dependencies]
        self.queries = []

    def scalars(self, statement):
        table = statement.get_final_froms()[0].name
        params = statement.compile().params
        assert params["project_id_1"] == "project"
        assert set(params["node_key_1"]) == {value.node.key for value in registrations()}
        self.queries.append(table)
        if table == "system_image_derivations":
            return iter(self.nodes)
        assert table == "system_image_derivation_edges"
        return iter(sorted(self.edges, key=lambda edge: edge.parent_key))


def test_all_517_script_parents_are_verified_in_two_batched_metadata_queries():
    values = registrations()
    session = MetadataSession(values)
    pins = AutomationProvenanceProjectorV1._design_pins(session, values)
    assert pins == tuple(sorted((value.node.key, value.node.artifact_hash, value.content_hash) for value in values))
    assert len(pins) == 517 and session.queries == ["system_image_derivations", "system_image_derivation_edges"]


@pytest.mark.parametrize("field,value", [("context_id", "other"), ("kind", "scope"), ("artifact_id", "other"),
    ("artifact_hash", "sha256:" + "b" * 64), ("invocation_id", "other"),
    ("content_hash", "sha256:" + "b" * 64), ("policy_revision", "future-policy")])
def test_corrupt_last_case_registration_is_not_hidden_by_a_bounded_impact_view(field, value):
    values = registrations()
    session = MetadataSession(values)
    setattr(session.nodes[-1], field, value)
    with pytest.raises(TestDesignResultIntegrityError):
        AutomationProvenanceProjectorV1._design_pins(session, values)


@pytest.mark.parametrize("fault", ["missing_node", "missing_edge", "foreign_edge", "different_parent", "extra_parent"])
def test_every_last_case_and_its_exact_parent_are_required(fault):
    values = registrations()
    session = MetadataSession(values)
    if fault == "missing_node":
        session.nodes.pop()
    elif fault == "missing_edge":
        session.edges.pop()
    elif fault == "foreign_edge":
        session.edges[-1].context_id = "other"
    elif fault == "different_parent":
        session.edges[-1].parent_key = "generation:other"
    else:
        session.edges.append(SimpleNamespace(project_id="project", context_id="ctx",
            node_key=values[-1].node.key, parent_key="generation:other"))
    with pytest.raises(TestDesignResultIntegrityError):
        AutomationProvenanceProjectorV1._design_pins(session, values)
