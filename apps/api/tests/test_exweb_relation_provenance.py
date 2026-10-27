"""Actual exweb/PG/MinIO ancestry; synthetic semantic replies are not business gold."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.persistence.context_pack_models import ContextPackRecord as Context
from apps.api.app.infrastructure.persistence.image_revision_models import ImageRevisionRecord as Image, ImageObjectMemberRecord as Member
from apps.api.app.infrastructure.persistence.relation_provenance_models import ContextRelationProvenanceRecord as Anchor
from apps.api.app.infrastructure.persistence.relation_provenance_projection_v1 import RelationProvenanceProjectorV1
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests import test_document_projection_api as document_tests
from apps.api.tests.test_exweb_context_change_impact import evidence_api
from apps.api.tests.test_exweb_source_delta import BEFORE
from apps.api.tests.test_semantic_evaluations_api import semantic, completed, invoke
from apps.api.tests.test_relation_provenance_api import verify_semantic_history, archive_image, inventory
from apps.api.tests.test_image_membership_api import setup_freeze, freeze as freeze_reference, child as reference_child
from apps.api.tests.test_semantic_membership_api import freeze, child


@pytest.fixture
def documents(evidence_api, request, monkeypatch):
    monkeypatch.setattr(document_tests, "REQUIREMENT", "# US-EXWEB-CHAT Chat stream protocol fixture\n"
        "Description: Synthetic Nasus validation material, not an authoritative exweb requirement.\n"
        "## Acceptance criteria\nAC-1: chatStream response content type requires independent confirmation.\n")
    monkeypatch.setattr(document_tests, "CASE", "# TC-EXWEB-CHAT Chat stream protocol fixture\n"
        "References: US-EXWEB-CHAT\nPreconditions: Runtime contract is not verified\n"
        "Steps: Investigate chatStream response\nExpected result: Independent response content type confirmation\n")
    return document_tests.documents.__wrapped__(evidence_api, request)


def test_real_exweb_code_and_companion_documents_have_fixed_review_and_context_ancestry(semantic):
    v = semantic
    asserts = verify_semantic_history(v)
    recall = completed(invoke(v, "query.system_image.links.candidates", {
        "project_id": v["project_id"], "image_revision_id": v["selection"]["image_revision_id"],
        "target_object_id": v["selection"]["target_object_id"], "relation": "implements", "limit": 100}))
    response = v["client"].get(f"/v1/tool-invocations/{recall['id']}/image-query", headers=v["headers"])
    assert response.status_code == 200, response.text
    with session_scope() as session:
        exweb_members = set(session.scalars(select(Member.object_id).where(Member.project_id == v["project_id"],
            Member.image_revision_id == v["selection"]["image_revision_id"], Member.binding_id == v["exweb_binding"])))
    selected = next(item["endpoint"]["object_id"] for item in response.json()["items"]
        if item["endpoint"]["object_id"] in exweb_members)
    assert selected.startswith("CODE-")
    v["selection"] = {**v["selection"], "relation": "implements", "subject_object_ids": [selected], "recall_limit": 100}
    preview = completed(invoke(v, "query.system_image.links.evaluation_preview", v["selection"]))
    v["request"] = preview["result"]["semantic_preview"]["request"]
    implements = verify_semantic_history(v)
    assert len(v["calls"]) == 2
    sent = json.loads(json.loads(v["calls"][-1].content)["messages"][1]["content"])
    assert sent["relation"] == "implements" and sent["subjects"][0]["object_id"] == selected
    assert any(span["basis"] == "source_excerpt" and span["binding_id"] == v["exweb_binding"]
        for span in sent["excerpts"])

    references, _, _ = setup_freeze(v)
    _, reference_image = reference_child(v, freeze_reference(v, references))
    _, mixed = child(v, freeze(v, {"project_id": v["project_id"],
        "parent_revision_id": reference_image["revision"]["image_revision_id"],
        "parent_artifact_hash": reference_image["revision"]["artifact_hash"],
        "decision_ids": [asserts["latest_decision_id"], implements["latest_decision_id"]]}))
    mixed_context, _ = archive_image(v, mixed["revision"])
    with session_scope() as session:
        projector = RelationProvenanceProjectorV1()
        nodes = projector.expected(session, session.get(Image, mixed["revision"]["image_revision_id"]))
        kinds = [node.kind for node in nodes.values()]
        assert kinds.count("relation_member") == 3
        assert kinds.count("semantic_decision") == 4 and kinds.count("reference_decision") == 1
        assert len(nodes["image_relations:" + mixed["revision"]["image_revision_id"]].parents) == 4
        anchors = session.scalars(select(Anchor).where(Anchor.project_id == v["project_id"])).all()
        assert len(anchors) == 3
        for anchor in anchors:
            assert projector.context(session, session.get(Context, anchor.context_id), write=False) == 0
        before = inventory(session, v["project_id"])
        assert projector.backfill(session) == 0 and inventory(session, v["project_id"]) == before
        summary = {"nodes": len(nodes), "edges": sum(len(node.parents) for node in nodes.values()),
            "context_anchors": len(anchors), "relation_members": kinds.count("relation_member"),
            "graph_digest": snapshot_digest(sorted(node.content_hash for node in nodes.values()))}
    assert not mixed_context["current_use"]["generation_authorized"]
    report = {"verified_at": datetime.now(timezone.utc).isoformat(),
        "repository": "https://github.com/kunben-duck/exweb.git", "git_commit": BEFORE,
        "export_file_count": v["exweb_before_file_count"], "export_tree_hash": v["exweb_before_tree_hash"],
        "postgresql": True, "minio": True, "canonical_confirmation_and_review": True,
        "asserts": asserts, "implements": implements, "mixed_graph": summary,
        "native_code_member_used": True, "native_source_excerpt_used": True,
        "later_decisions_do_not_rewrite_old_images_or_contexts": True, "backfill_idempotent": True,
        "companion_sources": "synthetic_protocol_not_exweb_business_gold_plus_orders_sentinel",
        "model_transport": "explicit_native_http_protocol_fixture_unknown_not_supports",
        "external_model_called": False, "target_executed": False,
        "complete_project_delta_dag_implemented": False}
    if os.getenv("EXWEB_RELATION_PROVENANCE_REPORT"):
        Path(os.environ["EXWEB_RELATION_PROVENANCE_REPORT"]).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
