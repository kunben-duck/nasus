"""Real exweb/MinIO history; companion documents/reviewer are explicit protocol fixtures."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from sqlalchemy.engine import make_url

from apps.api.app.domain.system_image.publication import ROLLBACK_TOOL
from apps.api.app.infrastructure.persistence.publication_provenance_projection_v1 import PublicationProvenanceProjectorV1
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_exweb_context_change_impact import evidence_api, export_tree
from apps.api.tests.test_exweb_source_delta import BEFORE, AFTER
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_image_publications_api import publication, history, review, review_request, publish_request
from apps.api.tests.test_image_rollbacks_api import rollback_review
from apps.api.tests.test_published_image_reads import publish
from apps.api.tests.test_published_context_packs import request_for, preview_response
from apps.api.tests.test_context_packs_api import archive, read
from apps.api.tests.test_reference_links_api import candidate
from apps.api.tests.test_semantic_evaluations_api import invoke, completed
from apps.api.tests.test_publication_provenance_api import inventory


def test_fixed_exweb_publication_and_context_dependencies_survive_update_and_rollback(publication):
    v = publication
    assert make_url(os.environ["NASUS_DATABASE_URL"]).database.startswith("nasus_test_")
    assert v["exweb_before_file_count"] == 125
    old = publish(v)
    view = preview_response(v, request_for(v, old))
    assert view.status_code == 200, view.text
    response, _ = archive(v, view.json())
    initial, context_url = read(v, completed(response))
    original = inventory(v)
    count, tree_hash = export_tree(v["exweb_git"], AFTER, v["exweb_export"])
    assert count == 126
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    new = candidate(v)
    target = {**v["target"], "image_revision_id": new["image_revision_id"],
        "image_artifact_hash": new["artifact_hash"], "expected_head_id": old["publication_id"]}
    approval, _ = review(v, review_request(v, target=target))
    completed(invoke(v, "baseline.promote", publish_request(v, approval, target)))
    current = history(v)["head"]
    v.update(old_publication=old, new_publication=current, rollback_target={
        "project_id": v["project_id"], "image_revision_id": old["image_revision_id"],
        "image_artifact_hash": old["image_artifact_hash"], "target_baseline_id": old["baseline_id"],
        "expected_head_id": current["publication_id"], "rollback_publication_id": old["publication_id"],
        "policy_revision": "nasus.image-rollback.v1"})
    completed(invoke(v, ROLLBACK_TOOL, rollback_review(v)))
    restored = history(v)["head"]
    assert restored["sequence"] == 3 and restored["image_revision_id"] == old["image_revision_id"]
    later = v["client"].get(context_url, headers=v["headers"])
    assert later.status_code == 200, later.text
    assert later.json()["context"] == initial["context"]
    assert later.json()["current_use"]["stale"] is True
    after = inventory(v)
    assert after["context_publication_dependencies"] == original["context_publication_dependencies"]
    pins = {row["fact_id"]: row for row in after["image_publication_provenance"]}
    assert all(pins[row["fact_id"]] == row for row in original["image_publication_provenance"])
    edges = {row["relation"]: row for row in after["image_publication_dependencies"] if row["fact_id"] == restored["publication_id"]}
    assert edges["rollback_source"]["parent_hash"] == pins[old["publication_id"]]["content_hash"]
    assert edges["previous_publication"]["parent_hash"] == pins[current["publication_id"]]["content_hash"]
    assert edges["approval"]["parent_hash"] == pins[restored["approval_id"]]["content_hash"]
    with session_scope() as session:
        PublicationProvenanceProjectorV1().backfill(session)
    assert inventory(v) == after
    report = dict(verified_at=datetime.now(timezone.utc).isoformat(), repository="https://github.com/kunben-duck/exweb.git",
        git_commits=[BEFORE, AFTER], export_file_counts=[125, 126],
        export_tree_hashes=[v["exweb_before_tree_hash"], tree_hash], postgresql=True, minio=True,
        publication_and_review_node_count=len(pins), publication_dependency_count=len(after["image_publication_dependencies"]),
        context_dependency_count=len(after["context_publication_dependencies"]),
        old_fact_and_registration_hashes_unchanged=True, rollback_parent_hashes_verified=True,
        historical_context_pinned_and_stale=True, backfill_idempotent=True,
        final_publication_registration_hash=pins[restored["publication_id"]]["content_hash"],
        companion_sources="explicit_synthetic_protocol_not_exweb_business_gold", external_model_called=False,
        target_executed=False, complete_delta_dag=False)
    if os.getenv("EXWEB_PUBLICATION_PROVENANCE_REPORT"):
        Path(os.environ["EXWEB_PUBLICATION_PROVENANCE_REPORT"]).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
