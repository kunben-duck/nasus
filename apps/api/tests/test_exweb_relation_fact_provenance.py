"""Actual exweb source refresh preserves unselected relation facts; not business gold."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from sqlalchemy import delete, insert, select

from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord as Event
from apps.api.app.infrastructure.persistence.image_revision_models import ImageRevisionRecord as Image, ImageObjectMemberRecord as Member
from apps.api.app.infrastructure.persistence.relation_fact_provenance_v1 import RelationFactProvenanceProjectorV1 as Facts
from apps.api.app.infrastructure.persistence.relation_provenance_models import RelationProvenanceNodeRecord as Node, RelationProvenanceEdgeRecord as Edge
from apps.api.app.infrastructure.persistence.semantic_evaluation_models import SemanticEvaluationRecord as Evaluation
from apps.api.app.infrastructure.persistence.semantic_review_models import SemanticDecisionRecord as Decision
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_exweb_relation_provenance import documents, evidence_api
from apps.api.tests.test_exweb_context_change_impact import export_tree
from apps.api.tests.test_exweb_source_delta import BEFORE, AFTER
from apps.api.tests.test_semantic_review_api import semantic, evaluate, submit, completed
from apps.api.tests.test_semantic_evaluations_api import invoke
from apps.api.tests.test_link_decisions_api import setup_review, submit as reference_review
from apps.api.tests.test_relation_provenance_api import inventory
from apps.api.tests.test_reference_links_api import proposal


def test_actual_exweb_refresh_keeps_unselected_evaluations_and_negative_decisions_replayable(semantic):
    v = semantic
    assert_url, payload, _ = evaluate(v)
    completed(submit(v, payload))
    initial = v["client"].get(assert_url, headers=v["headers"]).json()
    completed(submit(v, {**payload, "decision": "defer", "expected_previous_decision_id": initial["head_decision_id"]}))
    assert_history = v["client"].get(assert_url, headers=v["headers"]).json()
    assert [decision["decision"] for decision in assert_history["items"]] == ["reject", "defer"]
    recall = completed(invoke(v, "query.system_image.links.candidates", {
        "project_id": v["project_id"], "image_revision_id": v["selection"]["image_revision_id"],
        "target_object_id": v["selection"]["target_object_id"], "relation": "implements", "limit": 100}))
    response = v["client"].get(f"/v1/tool-invocations/{recall['id']}/image-query", headers=v["headers"])
    assert response.status_code == 200, response.text
    with session_scope() as session:
        code_ids = set(session.scalars(select(Member.object_id).where(Member.project_id == v["project_id"],
            Member.image_revision_id == v["selection"]["image_revision_id"], Member.binding_id == v["exweb_binding"])))
    code = next(item["endpoint"]["object_id"] for item in response.json()["items"] if item["endpoint"]["object_id"] in code_ids)
    assert code.startswith("CODE-")
    v["selection"] = {**v["selection"], "relation": "implements", "subject_object_ids": [code], "recall_limit": 100}
    preview = completed(invoke(v, "query.system_image.links.evaluation_preview", v["selection"]))
    v["request"] = preview["result"]["semantic_preview"]["request"]
    code_url, code_payload, _ = evaluate(v)
    completed(submit(v, code_payload))
    code_history = v["client"].get(code_url, headers=v["headers"]).json()
    assert len(v["calls"]) == 2
    sent = json.loads(json.loads(v["calls"][-1].content)["messages"][1]["content"])
    assert any(span["basis"] == "source_excerpt" and span["binding_id"] == v["exweb_binding"] for span in sent["excerpts"])
    reference_proposal, reference_url, reference_payload = setup_review(v)
    completed(reference_review(v, reference_payload))
    reference_history = v["client"].get(reference_url, headers=v["headers"]).json()
    with session_scope() as session:
        image = session.get(Image, v["selection"]["image_revision_id"])
        assert image.assertion_count == 0
        for model, method in ((Evaluation, "evaluation"), (Decision, "semantic_review")):
            rows = session.scalars(select(model).where(model.project_id == v["project_id"])).all()
            assert Facts().facts(session, method, rows, write=False) == 0
        assert Facts().backfill(session) == 0
        before = inventory(session, v["project_id"])
        kinds = list(session.scalars(select(Node.kind).where(Node.project_id == v["project_id"])))
        assert kinds.count("semantic_evaluation") == 2 and kinds.count("semantic_decision") == 3
        assert kinds.count("reference_decision") == 1 and "relation_member" not in kinds
        summary = {"nodes": len(kinds), "edges": len(session.scalars(select(Edge.node_key).where(Edge.project_id == v["project_id"])).all()),
            "semantic_evaluations": 2, "semantic_decisions": 3, "reference_decisions": 1,
            "selected_relation_members": 0, "registry_digest": snapshot_digest(before)}

    after_count, after_hash = export_tree(v["exweb_git"], AFTER, v["exweb_export"])
    assert (v["exweb_before_file_count"], after_count) == (125, 126)
    v["invoke"]("system_image.sources.ingest")
    assert v["client"].get(assert_url, headers=v["headers"]).json() == assert_history
    assert v["client"].get(code_url, headers=v["headers"]).json() == code_history
    assert v["client"].get(reference_url, headers=v["headers"]).json() == reference_history
    historical = v["client"].get(assert_url, headers=v["headers"], params={"through_decision_id": initial["head_decision_id"]})
    assert historical.status_code == 200 and historical.json() == initial
    with session_scope() as session:
        assert inventory(session, v["project_id"]) == before
        assert Facts().backfill(session) == 0
    event_filter = (Event.event_type == "system_image.references.proposed",
                    Event.entity_id == reference_proposal["proposal_id"])
    with session_scope() as session:
        retained = [dict(row) for row in session.execute(select(*Event.__table__.columns).where(*event_filter)).mappings()]
        assert retained
        session.execute(delete(Event).where(*event_filter))
    try:
        repeated, _, _ = proposal(v, image=v["selection"])
        assert repeated == reference_proposal
        assert v["client"].get(reference_url, headers=v["headers"]).json() == reference_history
        assert len(v["calls"]) == 2
        with session_scope() as session:
            assert inventory(session, v["project_id"]) == before
            events = session.scalars(select(Event).where(*event_filter)).all()
            assert len(events) == 1 and events[0].sequence > max(row["sequence"] for row in retained)
    finally:
        with session_scope() as session:
            session.execute(insert(Event), retained)
    report = {"verified_at": datetime.now(timezone.utc).isoformat(),
        "repository": "https://github.com/kunben-duck/exweb.git", "git_commits": [BEFORE, AFTER],
        "export_file_counts": [125, 126], "export_tree_hashes": [v["exweb_before_tree_hash"], after_hash],
        "postgresql": True, "minio": True, "unselected_relation_facts": summary,
        "native_code_member_used": True, "native_source_excerpt_used": True,
        "negative_review_history_and_original_hashes_survive_source_refresh": True,
        "reference_reuse_after_outbox_retention_preserves_facts_and_review_history": True,
        "backfill_idempotent": True, "canonical_confirmation_and_review": True,
        "companion_sources": "synthetic_protocol_not_exweb_business_gold_plus_orders_sentinel",
        "model_transport": "explicit_native_http_protocol_fixture_unknown_not_supports",
        "external_model_called": False, "target_executed": False,
        "automatic_invalidation_applied": False, "complete_project_delta_dag_implemented": False}
    if os.getenv("EXWEB_RELATION_FACT_REPORT"):
        Path(os.environ["EXWEB_RELATION_FACT_REPORT"]).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
