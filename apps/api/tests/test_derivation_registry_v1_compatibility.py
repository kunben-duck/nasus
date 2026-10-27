"""Replay real immutable PG registrations with future dataclass extensions."""
from dataclasses import asdict, dataclass

from sqlalchemy import select

from apps.api.app.domain.system_image.derivation_impact import DerivationNode
from apps.api.app.domain.system_image.derivation_registry import DerivationRegistration, REGISTRY_POLICY
from apps.api.app.domain.system_image.source_snapshots import SourceManifestMember, snapshot_digest
from apps.api.app.infrastructure.persistence import derivation_registry_projection as projection
from apps.api.app.infrastructure.persistence.derivation_registry_models import (
    DerivationRegistryRecord as Node, DerivationRegistryEdgeRecord as Edge,
    ContextQueryScopeRecord as QueryScope, ContextQuerySourceRecord as QuerySource,
)
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_derivation_registry_api import (
    impact, mapping, generation_result, design_scope, publication, documents, evidence_api,
    read_impact, read_roots,
)


def inventory(session):
    facts = []
    for model in (Node, Edge, QueryScope, QuerySource):
        statement = select(*(getattr(model, column.name) for column in model.__table__.columns))
        rows = session.execute(statement.order_by(*model.__table__.primary_key.columns))
        facts.append(tuple(tuple(row) for row in rows))
    return tuple(facts)


def test_future_dataclass_fields_do_not_change_populated_v1_backfill_or_api_receipts(impact, monkeypatch):
    v = impact
    original_impact = read_impact(v)
    original_roots = read_roots(v)
    assert original_impact.status_code == original_roots.status_code == 200
    with session_scope() as session:
        before = inventory(session)
        parents = {}
        for edge in session.scalars(select(Edge).order_by(Edge.parent_key)):
            parents.setdefault((edge.project_id, edge.node_key), []).append(edge.parent_key)
        for row in session.scalars(select(Node)):
            value = DerivationRegistration(row.project_id, row.context_id, row.invocation_id,
                DerivationNode(row.kind, row.artifact_id, row.artifact_hash,
                    tuple(parents.get((row.project_id, row.node_key), ()))))
            assert row.content_hash == snapshot_digest({"policy_revision": REGISTRY_POLICY, **asdict(value)})

    @dataclass(frozen=True)
    class FutureNode(DerivationNode):
        future_metadata: str = "not a v1 node field"

    @dataclass(frozen=True)
    class FutureRegistration(DerivationRegistration):
        future_metadata: str = "not a v1 registration field"

    @dataclass(frozen=True)
    class FutureMember(SourceManifestMember):
        future_metadata: str = "not a v1 source member field"

    monkeypatch.setattr(projection, "DerivationNode", FutureNode)
    monkeypatch.setattr(projection, "DerivationRegistration", FutureRegistration)
    monkeypatch.setattr(projection, "SourceManifestMember", FutureMember)
    with session_scope() as session:
        projection.DerivationRegistryProjector().backfill(session)
        assert inventory(session) == before
    assert read_impact(v).json() == original_impact.json()
    assert read_roots(v).json() == original_roots.json()

    # Also exercise first registration, not only the existing-row comparison.
    from apps.api.tests.test_source_context_roots_api import clone_context
    clone_context(v)
    with session_scope() as session:
        added = inventory(session)
        assert len(added[0]) > len(before[0]) and len(added[2]) == len(before[2]) + 1
        projection.DerivationRegistryProjector().backfill(session)
        assert inventory(session) == added
