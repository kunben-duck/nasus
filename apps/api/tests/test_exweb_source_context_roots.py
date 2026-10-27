"""Real Git/PG/MinIO reverse roots; companion business data is explicitly synthetic."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from apps.api.tests.test_exweb_context_change_impact import (
    evidence_api, documents, publication, design_scope, generation_result, mapping,
    test_actual_exweb_new_files_propagate_to_fixed_context_derivations as verify_exweb_impact,
)
from apps.api.tests.test_exweb_source_delta import BEFORE, AFTER
from apps.api.tests.test_semantic_evaluations_api import completed, count
from apps.api.tests.test_source_context_roots_api import read, query, expand, clone_context, archive_child_context
from apps.api.app.infrastructure.persistence.db_models import LLMCallRecord


def test_exweb_source_revision_discovers_all_visible_frozen_roots_and_preserves_old_receipts(mapping):
    v = mapping
    verify_exweb_impact(v)
    first = read(v)
    assert first.status_code == 200, first.text
    original = completed(query(v))
    assert first.json()["inventory"]["total"] == 1
    model_calls = count(v, LLMCallRecord)
    added = archive_child_context(v)
    response = read(v)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source_change_requires_reinvestigation"] and body["page_evidence_verified"]
    assert body["inventory"]["total"] == 2 and body["inventory"]["next_after_id"] is None
    assert {root["context_id"] for root in body["inventory"]["items"]} == {
        v["context"]["metadata"]["context_id"], added["metadata"]["context_id"]}
    assert len({root["image_revision_id"] for root in body["inventory"]["items"]}) == 2
    command = completed(query(v))
    assert expand(v, command).json() == body
    assert expand(v, original).json() == first.json()
    closures = []
    for root in body["inventory"]["items"]:
        impact = v["client"].get(v["image_url"] + f"/context-packs/{root['context_id']}/change-impact",
            headers=v["headers"], params={"context_artifact_hash": root["context_artifact_hash"],
                "before_revision_id": v["impact_request"]["before_revision_id"],
                "after_revision_id": v["impact_request"]["after_revision_id"]})
        assert impact.status_code == 200, impact.text
        impact = impact.json()
        assert impact["assessment"]["dependency_closure_complete"]
        assert not impact["assessment"]["impact_complete"] and not impact["assessment"]["invalidation_applied"]
        closures.append({"context_id": root["context_id"], "dependency_count": len(impact["dependencies"]),
            "graph_hash": impact["assessment"]["graph_hash"]})
    assert sorted(item["dependency_count"] for item in closures) == [1, 9]
    clone_context(v)
    assert read(v).json()["inventory"]["total"] == 3
    assert expand(v, command).json() == body
    new_source = read(v, before_revision_id=v["impact_request"]["after_revision_id"])
    assert new_source.status_code == 200 and new_source.json()["inventory"]["total"] == 0
    assert not new_source.json()["source_change_requires_reinvestigation"]
    assert count(v, LLMCallRecord) == model_calls
    for field in ("impact_complete", "invalidation_applied", "generation_authorized", "execution_authorized"):
        assert body[field] is False
    assert not body["downstream_dependency_graphs_verified"]
    report = {"verified_at": datetime.now(timezone.utc).isoformat(),
        "repository": "https://github.com/kunben-duck/exweb.git", "git_commits": [BEFORE, AFTER],
        "export_file_counts": [125, 126], "postgresql": True, "minio": True,
        "root_count_at_observation": 2, "frozen_image_count": 2, "root_count_after_new_archive": 3,
        "canonical_receipt": command["result"]["image_query"], "independent_bounded_closures": closures,
        "old_receipt_excludes_new_archives": True, "new_revision_has_no_old_context_roots": True,
        "scope_and_draft_basis": "explicit_synthetic_protocol_not_exweb_business_gold",
        "source_registration_and_ingestion": "canonical_local_git_tree_exports_content_hash_revisions",
        "external_model_called": False, "target_executed": False,
        "invalidation_applied": False, "impact_complete": False}
    if os.getenv("EXWEB_SOURCE_CONTEXT_ROOTS_REPORT"):
        Path(os.environ["EXWEB_SOURCE_CONTEXT_ROOTS_REPORT"]).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
