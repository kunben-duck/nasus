"""Actual PG provenance, atomic Outbox hooks and populated migration replay."""
import importlib
from uuid import uuid4

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from apps.api.app.domain.system_image.derivation_impact import DerivationImpactIntegrityError, DerivationNode
from apps.api.app.domain.system_image.derivation_registry import DerivationRegistration, REGISTRY_POLICY
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.context_pack_models import ContextPackRecord
from apps.api.app.infrastructure.persistence.context_dependency_inventory import QualityContextDependencyInventory
from apps.api.app.infrastructure.persistence.derivation_registry_models import (
    DerivationRegistryRecord as Node, DerivationRegistryEdgeRecord as Edge,
    ContextQueryScopeRecord as QueryScope, ContextQuerySourceRecord as QuerySource,
)
from apps.api.app.infrastructure.persistence.derivation_registry_projection import DerivationRegistryProjector
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord, LLMCallRecord
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceManifestMemberRecord as Member
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_context_change_impact_api import (
    impact, mapping, generation_result, design_scope, publication, documents, evidence_api, read as read_impact,
)
from apps.api.tests.test_source_context_roots_api import read as read_roots, clone_context
from apps.api.tests.test_semantic_evaluations_api import count
from apps.api.tests.test_context_packs_api import archive
from apps.api.tests.test_published_context_packs import preview_response, request_for
from apps.api.tests.migration_rehearsal import detach_downstream_foreign_keys, foreign_key_inventory


def counts(v):
    with session_scope() as session:
        return [session.scalar(select(func.count()).select_from(model).where(model.project_id == v["project_id"]))
            for model in (ContextPackRecord, Node, Edge, QueryScope, QuerySource)]


def test_business_commits_register_exact_graph_and_complete_query_scope_atomically(impact):
    v = impact
    response = read_impact(v)
    assert response.status_code == 200, response.text
    body = response.json()
    context_id = v["context"]["metadata"]["context_id"]
    with session_scope() as session:
        nodes = session.scalars(select(Node).where(Node.project_id == v["project_id"], Node.context_id == context_id)).all()
        edges = session.scalars(select(Edge).where(Edge.project_id == v["project_id"], Edge.context_id == context_id)
            .order_by(Edge.node_key, Edge.parent_key)).all()
        parents = {}
        for edge in edges:
            parents.setdefault(edge.node_key, []).append(edge.parent_key)
        actual = []
        for node in nodes:
            value = DerivationNode(node.kind, node.artifact_id, node.artifact_hash, tuple(parents.get(node.node_key, ())))
            assert DerivationRegistration(node.project_id, node.context_id, node.invocation_id, value).content_hash == node.content_hash
            assert node.policy_revision == REGISTRY_POLICY
            actual.append({"kind": value.kind, "artifact_id": value.artifact_id,
                "artifact_hash": value.artifact_hash, "dependencies": list(value.dependencies)})
        assert sorted(actual, key=lambda item: item["kind"] + ":" + item["artifact_id"]) == body["dependencies"]
        header = session.get(QueryScope, (v["project_id"], context_id))
        assert header.query_scope_fingerprint == body["assessment"]["query_scope_fingerprint"]
        members = session.scalars(select(Member).where(Member.project_id == v["project_id"], Member.manifest_id == header.manifest_id)).all()
        sources = session.scalars(select(QuerySource).where(QuerySource.project_id == v["project_id"], QuerySource.context_id == context_id)).all()
        expected = sorted([{key: getattr(member, key) for key in ("binding_id", "source_type", "source_revision_id", "status")}
            for member in members], key=lambda item: item["binding_id"])
        assert len(sources) == len(members) == header.member_count
        assert sorted([{key: getattr(source, key) for key in expected[0]} for source in sources], key=lambda item: item["binding_id"]) == expected
        assert header.source_members_hash == snapshot_digest(expected)
    before = counts(v)
    model_calls = count(v, LLMCallRecord)
    with session_scope() as session:
        DerivationRegistryProjector().backfill(session)
    assert counts(v) == before and count(v, LLMCallRecord) == model_calls
    assert read_roots(v).status_code == 200
    assert not body["assessment"]["impact_complete"] and not body["assessment"]["execution_authorized"]


def test_projection_failure_rolls_back_pack_registry_sources_and_fact_outbox(impact, monkeypatch):
    v = impact
    before = counts(v)
    with session_scope() as session:
        events = session.scalar(select(func.count()).select_from(SSEEventOutboxRecord)
            .where(SSEEventOutboxRecord.event_type == "system_image.context.compiled"))
    original = DerivationRegistryProjector.project_event
    def fail_after_registration(self, session, event):
        original(self, session, event)
        if event.event_type == "system_image.context.compiled":
            raise DerivationImpactIntegrityError("injected registry failure")
    view = preview_response(v, request_for(v, v["context_head"])).json()
    with monkeypatch.context() as scoped:
        scoped.setattr(DerivationRegistryProjector, "project_event", fail_after_registration)
        response, _ = archive(v, view)
    assert response.status_code == 200 and response.json()["status"] == "failed", response.text
    assert counts(v) == before
    with session_scope() as session:
        assert events == session.scalar(select(func.count()).select_from(SSEEventOutboxRecord)
            .where(SSEEventOutboxRecord.event_type == "system_image.context.compiled"))
    assert read_roots(v).status_code == 200 and read_impact(v).status_code == 200


class RollbackProbe(RuntimeError):
    pass


def test_populated_0067_to_0068_backfill_is_complete_and_downgrade_is_guarded(impact, monkeypatch):
    v = impact
    before = counts(v)
    migration = importlib.import_module("apps.api.migrations.versions.0068_derivation_registry")
    with engine.connect() as connection:
        foreign_keys = foreign_key_inventory(connection)
    # The destructive setup is confined to a rolled-back DDL transaction in the
    # disposable test database. No immutable business fact/trigger is changed.
    with pytest.raises(RollbackProbe), engine.begin() as connection:
        scoped_op = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(migration, "op", scoped_op)
        # Replay historical DDL below the additive bridge, then rebuild the
        # bridge in the same rolled-back transaction; no old fact is rewritten.
        from apps.api.tests.test_context_provenance_api import reset_bridge
        bridge = reset_bridge(scoped_op)
        monkeypatch.setattr(bridge, "op", scoped_op)
        detach_downstream_foreign_keys(connection, scoped_op, migration.TABLES)
        for table in reversed(migration.TABLES):
            scoped_op.drop_table(table)
        migration.upgrade()
        assert connection.scalar(select(func.count()).select_from(Node).where(Node.project_id == v["project_id"])) == before[1]
        assert connection.scalar(select(func.count()).select_from(QuerySource).where(QuerySource.project_id == v["project_id"])) == before[4]
        with pytest.raises(RuntimeError, match="cannot downgrade"):
            migration.downgrade()
        bridge.upgrade()
        raise RollbackProbe()
    with engine.connect() as connection:
        assert foreign_key_inventory(connection) == foreign_keys
    assert counts(v) == before
    assert read_roots(v).status_code == 200 and read_impact(v).status_code == 200


def test_registry_append_only_cross_context_edges_and_conflicting_replay_are_rejected(impact):
    v = impact
    with session_scope() as session:
        row = session.scalar(select(Node).where(Node.project_id == v["project_id"], Node.kind == "context"))
        context_id, invocation_id = row.context_id, row.invocation_id
    for operation in (update(Node).where(Node.project_id == v["project_id"]).values(artifact_hash="corrupt"),
            delete(Edge).where(Edge.project_id == v["project_id"]),
            delete(QuerySource).where(QuerySource.project_id == v["project_id"]),
            update(QueryScope).where(QueryScope.project_id == v["project_id"]).values(member_count=1)):
        with pytest.raises(DBAPIError), session_scope() as session:
            session.execute(operation)
    with pytest.raises(DerivationImpactIntegrityError, match="conflict"), session_scope() as session:
        DerivationRegistryProjector()._node(session, DerivationRegistration(v["project_id"], context_id,
            invocation_id, DerivationNode("context", context_id, "sha256:" + "f" * 64, ())))
    with pytest.raises(IntegrityError), session_scope() as session:
        session.add(Edge(project_id=v["project_id"], context_id=uuid4().hex,
            node_key="context:" + context_id, parent_key="scope:missing-parent"))
        session.flush()
    other_context = clone_context(v)["metadata"]["context_id"]
    with pytest.raises(IntegrityError), session_scope() as session:
        # Both endpoints really exist in this project, but not this context.
        session.add(Edge(project_id=v["project_id"], context_id=context_id,
            node_key="generation:" + v["generation_metadata"]["generation_id"],
            parent_key="context:" + other_context))
        session.flush()
    assert read_roots(v).status_code == 200


def test_missing_registry_row_cannot_silently_shrink_an_authoritative_inventory(impact, monkeypatch):
    v = impact
    # Inject the adapter result rather than deleting provenance or disabling
    # append-only protection. Both consumers must check the same SQL count.
    original = engine.dialect.do_execute
    with session_scope() as session:
        selected = QualityContextDependencyInventory().list(v["project_id"], v["context"]["metadata"]["context_id"])
        assert {item[0] for item in selected} == {"scope", "generation", "mapping"}
    from sqlalchemy.orm import Session
    execute = Session.execute
    def missing(self, statement, *args, **kwargs):
        sql = str(statement)
        result = execute(self, statement, *args, **kwargs)
        if "indexed_context_dependencies" not in sql and "indexed_source_context_roots" not in sql:
            return result
        rows = result.all()
        changed = []
        for row in rows:
            data = dict(row._mapping)
            data["total"] = data["canonical_total"] - 1
            from types import SimpleNamespace
            changed.append(SimpleNamespace(**data))
        from types import SimpleNamespace
        return SimpleNamespace(all=lambda: changed)
    with monkeypatch.context() as scoped:
        scoped.setattr(Session, "execute", missing)
        for response in (read_roots(v), read_impact(v)):
            assert response.status_code == 502, response.text
            assert response.json()["detail"]["error"] == {"code": "context_impact_integrity_failed",
                "message": "Context dependencies failed integrity verification.", "details": {}, "retry_after": None}
            assert all(key not in response.json() for key in ("dependencies", "inventory", "graph_hash"))
    assert engine.dialect.do_execute == original


def test_batched_pg_metadata_registration_keeps_all_540_nodes_without_impact_view_truncation(impact):
    v = impact
    before = counts(v)
    context_id = v["context"]["metadata"]["context_id"]
    generation_id = v["generation_metadata"]["generation_id"]
    invocation_id = v["generation_metadata"]["invocation_id"]
    registrations = tuple(DerivationRegistration(v["project_id"], context_id, invocation_id,
        DerivationNode("case", generation_id + "/volume-probe-" + str(i), snapshot_digest({"probe": i}),
            ("generation:" + generation_id,))) for i in range(540))
    # A metadata-volume fixture, not 540 generated business cases or accepted
    # mappings. Roll it back so no synthetic graph becomes a project fact.
    with pytest.raises(RollbackProbe), session_scope() as session:
        projector = DerivationRegistryProjector()
        for offset in range(0, len(registrations), 256):
            projector._nodes(session, registrations[offset:offset + 256])
        assert session.scalar(select(func.count()).select_from(Node).where(Node.project_id == v["project_id"])) == before[1] + 540
        for offset in range(0, len(registrations), 256):
            projector._nodes(session, registrations[offset:offset + 256])
        assert session.scalar(select(func.count()).select_from(Node).where(Node.project_id == v["project_id"])) == before[1] + 540
        assert session.scalar(select(func.count()).select_from(Edge).where(Edge.project_id == v["project_id"])) == before[2] + 540
        raise RollbackProbe()
    assert counts(v) == before
