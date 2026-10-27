"""Actual exweb snapshots/PG/MinIO; semantic fixtures are not business gold."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from sqlalchemy import select

from apps.api.tests.test_exweb_source_context_roots import (
    evidence_api, documents, publication, design_scope, generation_result, mapping,
    test_exweb_source_revision_discovers_all_visible_frozen_roots_and_preserves_old_receipts as verify_roots,
)
from apps.api.tests.test_exweb_source_delta import BEFORE, AFTER
from apps.api.tests.test_context_change_impact_api import read as read_impact
from apps.api.app.domain.system_image.source_snapshots import SourceManifestMember, snapshot_digest
from apps.api.app.domain.system_image.derivation_registry import DerivationRegistration, FrozenQueryScope, REGISTRY_POLICY
from apps.api.app.domain.system_image.derivation_impact import DerivationNode
from apps.api.app.infrastructure.persistence import derivation_registry_projection as projection
from apps.api.app.infrastructure.persistence.derivation_registry_models import (
    DerivationRegistryRecord as Node, DerivationRegistryEdgeRecord as Edge,
    ContextQueryScopeRecord as QueryScope, ContextQuerySourceRecord as QuerySource,
)
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.persistence.context_pack_models import ContextPackRecord
from apps.api.app.infrastructure.persistence.context_provenance_models import ContextProvenanceAnchorRecord
from apps.api.app.infrastructure.persistence.context_provenance_projection_v1 import ContextProvenanceProjectorV1


def _inventory(session, project_id):
    values = []
    for model in (Node, Edge, QueryScope, QuerySource):
        statement = select(*(getattr(model, column.name) for column in model.__table__.columns))
        rows = session.execute(statement.where(model.project_id == project_id)
            .order_by(*model.__table__.primary_key.columns))
        values.append(tuple(tuple(row) for row in rows))
    return tuple(values)


def test_exweb_commits_and_replays_complete_registered_dependencies_for_all_context_roots(mapping, monkeypatch):
    v = mapping
    with session_scope() as session:
        initial_contexts = len(session.scalars(select(QueryScope).where(QueryScope.project_id == v["project_id"])).all())

    @dataclass(frozen=True)
    class FutureNode(DerivationNode):
        future_metadata: str = "not a v1 node field"

    @dataclass(frozen=True)
    class FutureRegistration(DerivationRegistration):
        future_metadata: str = "not a v1 registration field"

    @dataclass(frozen=True)
    class FutureMember(SourceManifestMember):
        future_metadata: str = "not a v1 source member field"

    # Existing registrations and newly archived contexts must share v1 bytes.
    monkeypatch.setattr(projection, "DerivationNode", FutureNode)
    monkeypatch.setattr(projection, "DerivationRegistration", FutureRegistration)
    monkeypatch.setattr(projection, "SourceManifestMember", FutureMember)
    verify_roots(v)
    response = read_impact(v)
    assert response.status_code == 200, response.text
    impact = response.json()
    with session_scope() as session:
        nodes = session.scalars(select(Node).where(Node.project_id == v["project_id"]).order_by(Node.node_key)).all()
        edges = session.scalars(select(Edge).where(Edge.project_id == v["project_id"]).order_by(Edge.node_key, Edge.parent_key)).all()
        scopes = session.scalars(select(QueryScope).where(QueryScope.project_id == v["project_id"]).order_by(QueryScope.context_id)).all()
        sources = session.scalars(select(QuerySource).where(QuerySource.project_id == v["project_id"])
            .order_by(QuerySource.context_id, QuerySource.binding_id)).all()
        assert len(scopes) == 3 and len(nodes) == 11
        assert initial_contexts == 1
        assert len(sources) == sum(scope.member_count for scope in scopes)
        parents = {}
        for edge in edges:
            parents.setdefault(edge.node_key, []).append(edge.parent_key)
        for node in nodes:
            registration = DerivationRegistration(node.project_id, node.context_id, node.invocation_id,
                DerivationNode(node.kind, node.artifact_id, node.artifact_hash,
                    tuple(parents.get(node.node_key, ()))))
            assert registration.content_hash == node.content_hash
            assert snapshot_digest({"policy_revision": REGISTRY_POLICY, **asdict(registration)}) == node.content_hash
        for scope in scopes:
            members = tuple(SourceManifestMember(source.binding_id, source.source_type, source.source_revision_id,
                source.status) for source in sources if source.context_id == scope.context_id)
            assert len(members) == scope.member_count
            assert all(source.manifest_id == scope.manifest_id for source in sources if source.context_id == scope.context_id)
            original_members = [asdict(member) for member in members]
            frozen = FrozenQueryScope(scope.project_id, scope.context_id, scope.image_revision_id,
                scope.image_artifact_hash, scope.manifest_id, scope.manifest_hash, scope.input_digest, members)
            assert scope.source_members_hash == frozen.source_members_hash == snapshot_digest(original_members)
            assert scope.query_scope_fingerprint == frozen.fingerprint == snapshot_digest({
                "input_digest": scope.input_digest, "image_artifact_hash": scope.image_artifact_hash,
                "source_members": original_members})
        root = next(scope for scope in scopes if scope.context_id == v["context"]["metadata"]["context_id"])
        assert root.query_scope_fingerprint == impact["assessment"]["query_scope_fingerprint"]
        before = _inventory(session, v["project_id"])
        projection.DerivationRegistryProjector().backfill(session)
        assert _inventory(session, v["project_id"]) == before
        anchors = session.scalars(select(ContextProvenanceAnchorRecord).where(
            ContextProvenanceAnchorRecord.project_id == v["project_id"]).order_by(ContextProvenanceAnchorRecord.context_id)).all()
        assert len(anchors) == len(scopes) == 3
        bridge = ContextProvenanceProjectorV1()
        anchor_values = []
        for anchor in anchors:
            value = bridge.verify(session, session.get(ContextPackRecord, anchor.context_id))
            assert value["image_provenance_hash"] == anchor.image_provenance_hash
            anchor_values.append(value)
        assert bridge.backfill(session) == 0
        assert _inventory(session, v["project_id"]) == before
        summary = {"contexts": len(scopes), "nodes": len(nodes), "edges": len(edges), "query_source_members": len(sources),
            "registration_hashes": [node.content_hash for node in nodes],
            "query_scope_fingerprints": [scope.query_scope_fingerprint for scope in scopes]}
    report = {"verified_at": datetime.now(timezone.utc).isoformat(),
        "repository": "https://github.com/kunben-duck/exweb.git", "git_commits": [BEFORE, AFTER],
        "export_file_counts": [125, 126], "postgresql": True, "minio": True,
        "registration": summary, "registration_summary_hash": snapshot_digest(summary),
        "existing_fixed_impact_graph_hash": impact["assessment"]["graph_hash"],
        "backfill_idempotent": True, "complete_frozen_source_scopes_including_negative_queries": True,
        "historical_v1_hash_formula_verified": True,
        "future_dataclass_extensions_backfill_verified": True,
        "new_context_registrations_with_extended_types": len(scopes) - initial_contexts,
        "all_registration_columns_unchanged_after_backfill": True,
        "all_contexts_have_source_query_registration": True,
        "context_object_ancestry_anchors": anchor_values,
        "all_contexts_have_hash_pinned_object_ancestry": True,
        "context_object_bridge_backfill_idempotent": True,
        "historical_v1_inventory_unchanged_by_bridge": True,
        "scope_and_draft_basis": "explicit_synthetic_protocol_not_exweb_business_gold",
        "external_model_called": False, "target_executed": False,
        "impact_complete": False, "invalidation_applied": False,
        "complete_project_delta_dag_implemented": False}
    if os.getenv("EXWEB_DERIVATION_REGISTRY_REPORT"):
        Path(os.environ["EXWEB_DERIVATION_REGISTRY_REPORT"]).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
