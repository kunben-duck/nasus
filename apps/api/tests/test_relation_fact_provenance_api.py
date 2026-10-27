"""Committed, unselected relations use native PG/HTTP facts, not fabricated metadata."""
import importlib
from contextlib import contextmanager

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import delete, func, insert, or_, select, text, update
from sqlalchemy.orm import Session

from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.image_revision_models import ImageRevisionRecord as Image
from apps.api.app.infrastructure.persistence.link_decision_models import LinkDecisionRecord
from apps.api.app.infrastructure.persistence.reference_link_models import (
    ReferenceProposalRecord as Proposal, ReferenceAssertionRecord, ReferenceProposalInvocationRecord,
)
from apps.api.app.infrastructure.persistence.reference_link_repository import ReferenceLinkRepository
from apps.api.app.infrastructure.persistence.relation_fact_provenance_v1 import RelationFactProvenanceProjectorV1 as Facts
from apps.api.app.infrastructure.persistence.relation_provenance_models import (
    RelationProvenanceNodeRecord as Node, RelationProvenanceEdgeRecord as Edge,
)
from apps.api.app.infrastructure.persistence.relation_provenance_projection_v1 import RelationProvenanceProjectorV1
from apps.api.app.infrastructure.persistence.semantic_evaluation_models import SemanticEvaluationRecord as Evaluation, SemanticCallReservationRecord as Reservation
from apps.api.app.infrastructure.persistence.semantic_review_models import SemanticAssertionRecord as Assertion, SemanticDecisionRecord as Decision
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_semantic_review_api import semantic, documents, evidence_api, evaluate, submit, completed
from apps.api.tests.test_semantic_evaluations_api import count
from apps.api.tests.test_link_decisions_api import setup_review, submit as reference_review
from apps.api.tests.test_semantic_membership_api import setup, freeze, child
from apps.api.tests.test_relation_provenance_api import inventory, RollbackProbe
from apps.api.tests.test_reference_links_api import proposal, invoke as propose_references


def node_hashes(session, project):
    return dict(session.execute(select(Node.node_key, Node.content_hash).where(Node.project_id == project)).all())


def test_unreviewed_evaluation_and_reference_proposal_are_registered_without_image_membership(semantic):
    v = semantic
    review_url, _, original = evaluate(v)
    evaluation_id = original["assertion"]["evaluation_id"]
    saved, _, _ = setup_review(v)
    with session_scope() as session:
        assert count(v, Assertion) == count(v, Decision) == 0
        projector = Facts()
        assert projector.facts(session, "evaluation", (session.get(Evaluation, evaluation_id),), write=False) == 0
        assert projector.facts(session, "proposal", (session.get(Proposal, saved["proposal_id"]),), write=False) == 0
        hashes = node_hashes(session, v["project_id"])
        assert "semantic_evaluation:" + evaluation_id in hashes
        assert "reference_proposal:" + saved["proposal_id"] in hashes
        assert not any(key.startswith(("relation_member:", "semantic_assertion:", "semantic_decision:")) for key in hashes)
        image = session.get(Image, v["selection"]["image_revision_id"])
        assert image.assertion_count == 0
        assert projector.backfill(session) == 0
        assert node_hashes(session, v["project_id"]) == hashes
    assert len(v["calls"]) == 1
    assert v["client"].get(review_url, headers=v["headers"]).json() == original


def test_unselected_rejection_and_defer_keep_exact_predecessors_and_freeze_hashes(semantic):
    v = semantic
    url, review, payload, original = setup(v)
    with session_scope() as session:
        before = node_hashes(session, v["project_id"])
        row = session.get(Decision, original["head_decision_id"])
        assert Facts().facts(session, "semantic_review", (row,), write=False) == 0
        image = session.get(Image, v["selection"]["image_revision_id"])
        original_image = RelationProvenanceProjectorV1().expected(session, image)
        assert not any(node.kind == "relation_member" for node in original_image.values())
    _, frozen = child(v, freeze(v, payload))
    completed(submit(v, {**review, "decision": "defer", "expected_previous_decision_id": original["head_decision_id"]}))
    current = v["client"].get(url, headers=v["headers"]).json()
    with session_scope() as session:
        after = node_hashes(session, v["project_id"])
        assert all(after[key] == value for key, value in before.items())
        row = session.get(Decision, current["head_decision_id"])
        assert Facts().facts(session, "semantic_review", (row,), write=False) == 0
        image = session.get(Image, frozen["revision"]["image_revision_id"])
        nodes = RelationProvenanceProjectorV1().expected(session, image)
        assert "semantic_decision:" + current["head_decision_id"] not in nodes
        assert all(after[key] == value.content_hash for key, value in nodes.items())
        assert Facts().backfill(session) == 0
    assert len(v["calls"]) == 1
    history = v["client"].get(url, headers=v["headers"], params={"through_decision_id": original["head_decision_id"]}).json()
    assert history == original


@pytest.mark.parametrize(("target", "retention"), [
    ("proposal", "retained"), ("proposal", "pruned"), ("evaluation", "retained"),
    ("reference_review", "retained"), ("semantic_review", "retained"),
])
@pytest.mark.parametrize("damage", ["missing", "metadata_hash"])
def test_unselected_corrupt_dependency_blocks_reads_without_leaking_or_auto_repair(semantic, target, retention, damage):
    v = semantic
    list_url, list_params = None, {}
    if target == "proposal":
        original, url, _ = proposal(v)
        ident, kind = original["proposal_id"], "reference_proposal"
        list_url = f"{v['image_url']}/revisions/{v['selection']['image_revision_id']}/reference-proposals"
    elif target == "reference_review":
        saved, url, payload = setup_review(v)
        completed(reference_review(v, payload))
        original = v["client"].get(url, headers=v["headers"]).json()
        ident = original["head_decision_id"]
        kind = "reference_decision"
    else:
        review_url, payload, _ = evaluate(v)
        if target == "semantic_review":
            completed(submit(v, payload))
            url = review_url
            original = v["client"].get(url, headers=v["headers"]).json()
            ident, kind = original["head_decision_id"], "semantic_decision"
        else:
            ident, kind = payload["evaluation_id"], "semantic_evaluation"
            url = f"{v['image_url']}/semantic-evaluations/{ident}"
            original = v["client"].get(url, headers=v["headers"]).json()
            list_url = f"{v['image_url']}/revisions/{v['selection']['image_revision_id']}/semantic-evaluations"
            list_params = {key: v["request"][key] for key in ("target_object_id", "relation")}
    if list_url:
        listing = v["client"].get(list_url, headers=v["headers"], params=list_params)
        assert listing.status_code == 200, listing.text
        original_listing = listing.json()
    key = kind + ":" + ident
    pruned_events = []
    with session_scope() as session:
        if retention == "pruned":
            event_filter = (SSEEventOutboxRecord.event_type == "system_image.references.proposed",
                            SSEEventOutboxRecord.entity_id == ident)
            pruned_events = [dict(row) for row in session.execute(
                select(*SSEEventOutboxRecord.__table__.columns).where(*event_filter)).mappings()]
            assert pruned_events
            session.execute(delete(SSEEventOutboxRecord).where(*event_filter))
        row = session.get(Node, (v["project_id"], key))
        values = {c.name: getattr(row, c.name) for c in Node.__table__.columns}
        removed_keys = [key]
        if target == "proposal" and damage == "missing":
            # Lose the full proposal projection, not only a parent whose intact
            # children would independently expose the missing adjacency.
            removed_keys.extend("reference_assertion:" + assertion_id for assertion_id in session.scalars(
                select(ReferenceAssertionRecord.assertion_id).where(ReferenceAssertionRecord.proposal_id == ident)))
        removed_nodes = [dict(row) for row in session.execute(select(*Node.__table__.columns).where(
            Node.project_id == v["project_id"], Node.node_key.in_(removed_keys))).mappings()]
        assert len(removed_nodes) == len(removed_keys)
        adjacent = (Edge.project_id == v["project_id"], or_(Edge.node_key.in_(removed_keys), Edge.parent_key.in_(removed_keys)))
        edges = [dict(row) for row in session.execute(select(*Edge.__table__.columns).where(
            *adjacent)).mappings()]
        session.execute(text("ALTER TABLE image_relation_provenance_edges DISABLE TRIGGER USER"))
        session.execute(text("ALTER TABLE image_relation_provenance_nodes DISABLE TRIGGER USER"))
        if damage == "missing":
            session.execute(delete(Edge).where(*adjacent))
            session.execute(delete(Node).where(Node.project_id == v["project_id"], Node.node_key.in_(removed_keys)))
        else:
            session.execute(update(Node).where(Node.project_id == v["project_id"], Node.node_key == key).values(
                metadata_hash="sha256:" + "0" * 64))
        session.execute(text("ALTER TABLE image_relation_provenance_nodes ENABLE TRIGGER USER"))
        session.execute(text("ALTER TABLE image_relation_provenance_edges ENABLE TRIGGER USER"))
    try:
        response = v["client"].get(url, headers=v["headers"])
        assert response.status_code == 502, response.text
        assert "items" not in response.json() and "evaluation" not in response.json()
        assert "Independent" not in response.text and "private-provider-key" not in response.text
        assert v["client"].get(url).status_code == 401
        assert v["client"].get(url, headers=v["member_headers"]).status_code == 403
        if list_url:
            response = v["client"].get(list_url, headers=v["headers"], params=list_params)
            assert response.status_code == 502, response.text
            assert "items" not in response.json() and "private-provider-key" not in response.text
        if target == "proposal":
            with session_scope() as session:
                before_command = inventory(session, v["project_id"])
                bindings = set(session.scalars(select(ReferenceProposalInvocationRecord.invocation_id).where(
                    ReferenceProposalInvocationRecord.project_id == v["project_id"])))
                events = set(session.scalars(select(SSEEventOutboxRecord.event_id).where(
                    SSEEventOutboxRecord.event_type == "system_image.references.proposed", SSEEventOutboxRecord.entity_id == ident)))
            assert propose_references(v).json()["status"] == "failed"
            with session_scope() as session:
                assert inventory(session, v["project_id"]) == before_command
                assert set(session.scalars(select(ReferenceProposalInvocationRecord.invocation_id).where(
                    ReferenceProposalInvocationRecord.project_id == v["project_id"]))) == bindings
                assert set(session.scalars(select(SSEEventOutboxRecord.event_id).where(
                    SSEEventOutboxRecord.event_type == "system_image.references.proposed", SSEEventOutboxRecord.entity_id == ident))) == events
        elif target != "evaluation":
            result = (reference_review(v, {**payload, "decision": "defer", "expected_previous_decision_id": ident})
                if target == "reference_review" else submit(v, {**payload, "decision": "defer", "expected_previous_decision_id": ident}))
            assert result.json()["status"] == "failed"
        with session_scope() as session:
            damaged = session.get(Node, (v["project_id"], key))
            if damage == "missing":
                assert damaged is None
            else:
                assert damaged.metadata_hash == "sha256:" + "0" * 64
    finally:
        with session_scope() as session:
            if damage == "missing":
                session.execute(text("ALTER TABLE image_relation_provenance_edges DISABLE TRIGGER USER"))
                session.execute(text("ALTER TABLE image_relation_provenance_nodes DISABLE TRIGGER USER"))
                session.execute(delete(Edge).where(*adjacent))
                session.execute(delete(Node).where(Node.project_id == v["project_id"], Node.node_key.in_(removed_keys)))
                session.execute(insert(Node), removed_nodes)
                session.execute(insert(Edge), edges)
                session.execute(text("ALTER TABLE image_relation_provenance_nodes ENABLE TRIGGER USER"))
                session.execute(text("ALTER TABLE image_relation_provenance_edges ENABLE TRIGGER USER"))
            else:
                session.execute(text("ALTER TABLE image_relation_provenance_nodes DISABLE TRIGGER USER"))
                session.execute(update(Node).where(Node.project_id == v["project_id"], Node.node_key == key).values(
                    metadata_hash=values["metadata_hash"]))
                session.execute(text("ALTER TABLE image_relation_provenance_nodes ENABLE TRIGGER USER"))
            if pruned_events:
                session.execute(insert(SSEEventOutboxRecord), pruned_events)
    assert v["client"].get(url, headers=v["headers"]).json() == original
    if list_url:
        assert v["client"].get(list_url, headers=v["headers"], params=list_params).json() == original_listing


def test_reference_reuse_after_outbox_retention_keeps_original_facts_and_appends_one_event(semantic):
    v = semantic
    saved, url, first = proposal(v)
    event_filter = (SSEEventOutboxRecord.event_type == "system_image.references.proposed",
                    SSEEventOutboxRecord.entity_id == saved["proposal_id"])
    with session_scope() as session:
        before = inventory(session, v["project_id"])
        pruned = [dict(row) for row in session.execute(
            select(*SSEEventOutboxRecord.__table__.columns).where(*event_filter)).mappings()]
        assert len(pruned) == 1
        session.execute(delete(SSEEventOutboxRecord).where(*event_filter))
    try:
        assert v["client"].get(url, headers=v["headers"]).json() == saved
        repeated, _, second = proposal(v)
        assert repeated == saved and first.json()["id"] != second.json()["id"]
        with session_scope() as session:
            assert inventory(session, v["project_id"]) == before
            events = session.scalars(select(SSEEventOutboxRecord).where(*event_filter)).all()
            assert len(events) == 1 and events[0].sequence > pruned[0]["sequence"]
    finally:
        with session_scope() as session:
            session.execute(insert(SSEEventOutboxRecord), pruned)


@pytest.mark.parametrize("damage", ["missing", "metadata_hash"])
def test_durable_invocation_event_guard_rejects_damage_after_repository_verification(semantic, monkeypatch, damage):
    v = semantic
    saved, url, _ = proposal(v)
    event_filter = (SSEEventOutboxRecord.event_type == "system_image.references.proposed",
                    SSEEventOutboxRecord.entity_id == saved["proposal_id"])
    with session_scope() as session:
        before = inventory(session, v["project_id"])
        retained = [dict(row) for row in session.execute(select(*SSEEventOutboxRecord.__table__.columns).where(*event_filter)).mappings()]
        assert retained
        session.execute(delete(SSEEventOutboxRecord).where(*event_filter))
    original, injected = Facts.project_event, []
    def damage_before_projection(self, session, event):
        if event.event_type == "system_image.references.proposed":
            assert event.entity_id == saved["proposal_id"]
            injected.append(event.event_id)
            keys = ["reference_proposal:" + saved["proposal_id"],
                    *("reference_assertion:" + item["assertion_id"] for item in saved["items"])]
            session.execute(text("ALTER TABLE image_relation_provenance_nodes DISABLE TRIGGER USER"))
            if damage == "missing":
                session.execute(text("ALTER TABLE image_relation_provenance_edges DISABLE TRIGGER USER"))
                session.execute(delete(Edge).where(Edge.project_id == v["project_id"],
                    or_(Edge.node_key.in_(keys), Edge.parent_key.in_(keys))))
                session.execute(delete(Node).where(Node.project_id == v["project_id"], Node.node_key.in_(keys)))
                session.execute(text("ALTER TABLE image_relation_provenance_edges ENABLE TRIGGER USER"))
            else:
                session.execute(update(Node).where(Node.project_id == v["project_id"], Node.node_key == keys[0]).values(
                    metadata_hash="sha256:" + "0" * 64))
            session.execute(text("ALTER TABLE image_relation_provenance_nodes ENABLE TRIGGER USER"))
        return original(self, session, event)
    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(Facts, "project_event", damage_before_projection)
            assert propose_references(v).json()["status"] == "failed"
        assert len(injected) == 1
        with session_scope() as session:
            assert inventory(session, v["project_id"]) == before
            assert session.scalar(select(func.count()).select_from(ReferenceProposalInvocationRecord).where(
                ReferenceProposalInvocationRecord.proposal_id == saved["proposal_id"])) == 1
            assert session.scalar(select(func.count()).select_from(SSEEventOutboxRecord).where(*event_filter)) == 0
        assert v["client"].get(url, headers=v["headers"]).json() == saved
    finally:
        with session_scope() as session:
            session.execute(insert(SSEEventOutboxRecord), retained)


@pytest.mark.parametrize("target", ["proposal", "evaluation", "reference_review", "semantic_review"])
def test_fact_registration_failure_rolls_back_fact_and_outbox_in_originating_transaction(semantic, monkeypatch, target):
    v = semantic
    if target == "proposal":
        event_type, fact = "system_image.references.proposed", Proposal
    elif target == "reference_review":
        _, _, payload = setup_review(v)
        event_type, fact = "system_image.link.reviewed", LinkDecisionRecord
    elif target == "semantic_review":
        _, payload, _ = evaluate(v)
        event_type, fact = "system_image.semantic.reviewed", Decision
    else:
        event_type, fact = "system_image.semantic.evaluated", Evaluation
    with session_scope() as session:
        before = inventory(session, v["project_id"])
    original = Facts.project_event
    def fail(self, session, event):
        original(self, session, event)
        if event.event_type == event_type:
            raise ImageRevisionIntegrityError("injected relation fact registration failure")
    monkeypatch.setattr(Facts, "project_event", fail)
    if target == "proposal":
        result = propose_references(v)
    elif target == "reference_review":
        result = reference_review(v, payload)
    elif target == "semantic_review":
        result = submit(v, payload)
    else:
        from apps.api.tests.test_semantic_evaluations_api import invoke, confirm
        result = confirm(v, invoke(v, "system_image.links.evaluate", v["request"]).json())
        assert count(v, Reservation) == len(v["calls"]) == 1
    assert result.json()["status"] == "failed"
    assert count(v, fact) == 0
    with session_scope() as session:
        assert inventory(session, v["project_id"]) == before
        assert session.scalar(select(func.count()).select_from(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.event_type == event_type,
            SSEEventOutboxRecord.event_payload["correlation_id"].as_string() == v["project_id"])) == 0


def test_populated_backfill_adds_only_missing_fact_nodes_and_rejects_destructive_downgrade(semantic, monkeypatch):
    v = semantic
    _, payload, _ = evaluate(v)
    completed(submit(v, payload))
    migration = importlib.import_module("apps.api.migrations.versions.0073_relation_fact_provenance")
    with session_scope() as session:
        before = inventory(session, v["project_id"])
    with pytest.raises(RollbackProbe), engine.connect() as connection, connection.begin():
        with Session(bind=connection) as session:
            keys = tuple(session.scalars(select(Node.node_key).where(Node.project_id == v["project_id"],
                Node.kind.in_(("semantic_evaluation", "semantic_assertion", "semantic_decision")))))
            assert len(keys) == 3
            session.execute(text("ALTER TABLE image_relation_provenance_edges DISABLE TRIGGER USER"))
            session.execute(text("ALTER TABLE image_relation_provenance_nodes DISABLE TRIGGER USER"))
            session.execute(delete(Edge).where(Edge.project_id == v["project_id"], Edge.node_key.in_(keys)))
            session.execute(delete(Node).where(Node.project_id == v["project_id"], Node.node_key.in_(keys)))
            session.flush()
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            assert inventory(session, v["project_id"]) == before
            assert Facts().backfill(session) == 0
            with pytest.raises(RuntimeError, match="Cannot discard"):
                migration.downgrade()
            raise RollbackProbe()
    with session_scope() as session:
        assert inventory(session, v["project_id"]) == before


def test_backfill_rejects_corrupt_original_assertion_without_rewriting_any_graph(semantic):
    v = semantic
    _, payload, _ = evaluate(v)
    completed(submit(v, payload))
    with session_scope() as session:
        before = inventory(session, v["project_id"])
    with pytest.raises(ImageRevisionIntegrityError), engine.connect() as connection, connection.begin():
        with Session(bind=connection) as session:
            session.execute(text("ALTER TABLE image_semantic_assertions DISABLE TRIGGER USER"))
            session.execute(update(Assertion).where(Assertion.project_id == v["project_id"]).values(content_hash="sha256:" + "0" * 64))
            Facts().backfill(session)
    with session_scope() as session:
        assert inventory(session, v["project_id"]) == before


@pytest.mark.parametrize("damage", ["missing", "metadata_hash"])
def test_reference_commit_replay_verifies_existing_registry_without_emitting_a_repair_event(semantic, monkeypatch, damage):
    v = semantic
    saved, url, invocation = proposal(v)
    repository = ReferenceLinkRepository()
    original = repository.get(v["project_id"], saved["proposal_id"])
    module = importlib.import_module(repository.__module__)
    with pytest.raises(RollbackProbe), engine.connect() as connection, connection.begin():
        with Session(bind=connection) as session, monkeypatch.context() as scoped:
            # Simulate a worker resuming after its fact commit but before the
            # canonical invocation terminal transition. All mutation rolls back.
            session.execute(update(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation.json()["id"]).values(status="running"))
            @contextmanager
            def resumed_transaction():
                yield session
                session.flush()

            scoped.setattr(module, "session_scope", resumed_transaction)
            event_count = session.scalar(select(func.count()).select_from(SSEEventOutboxRecord))
            kwargs = {"actor_id": v["owner"]["id"], "invocation_id": invocation.json()["id"],
                "created_at": original.created_at, "require_current_scope": lambda: None}
            assert repository.record(original.proposal, **kwargs) == original
            key = "reference_proposal:" + saved["proposal_id"]
            session.execute(text("ALTER TABLE image_relation_provenance_nodes DISABLE TRIGGER USER"))
            if damage == "missing":
                session.execute(text("ALTER TABLE image_relation_provenance_edges DISABLE TRIGGER USER"))
                session.execute(delete(Edge).where(Edge.project_id == v["project_id"],
                    or_(Edge.node_key == key, Edge.parent_key == key)))
                session.execute(delete(Node).where(Node.project_id == v["project_id"], Node.node_key == key))
            else:
                session.execute(update(Node).where(Node.project_id == v["project_id"], Node.node_key == key).values(
                    metadata_hash="sha256:" + "0" * 64))
            with pytest.raises(ImageRevisionIntegrityError, match="provenance"):
                repository.record(original.proposal, **kwargs)
            damaged = session.get(Node, (v["project_id"], key))
            assert (damaged is None if damage == "missing" else damaged.metadata_hash == "sha256:" + "0" * 64)
            assert session.scalar(select(func.count()).select_from(SSEEventOutboxRecord)) == event_count
            raise RollbackProbe()
    assert v["client"].get(url, headers=v["headers"]).json() == saved
