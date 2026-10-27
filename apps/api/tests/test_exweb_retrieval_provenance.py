"""Fixed real exweb code; embedding and companion requirements are protocol fixtures."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from sqlalchemy.engine import make_url

from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.persistence.retrieval_provenance_projection_v1 import RetrievalProvenanceProjectorV1
from apps.api.tests.test_exweb_context_change_impact import evidence_api, export_tree
from apps.api.tests.test_exweb_source_delta import BEFORE, AFTER
from apps.api.tests.test_retrieval_provenance_api import inventory
from apps.api.tests.test_indexed_context_packs_api import recalled, response
from apps.api.tests.test_frozen_indexes_api import indexed
from apps.api.tests.test_image_publications_api import publication, history, review, review_request, publish_request
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_context_packs_api import archive, read
from apps.api.tests.test_reference_links_api import candidate
from apps.api.tests.test_semantic_evaluations_api import completed, invoke


def test_exweb_complete_index_ancestry_and_context_pins_survive_source_update(recalled):
    v = recalled
    assert make_url(os.environ["NASUS_DATABASE_URL"]).database.startswith("nasus_test_")
    assert v["exweb_before_file_count"] == 125
    preview = response(v)
    assert preview.status_code == 200, preview.text
    done = completed(archive(v, preview.json())[0])
    initial, url = read(v, done)
    before = inventory(v)
    nodes = before["image_retrieval_provenance"]
    assert {row["kind"] for row in nodes} == {"reservation", "generation", "retrieval"}
    documents = before["image_index_document_dependencies"]
    assert len(documents) == v["index_preview"]["document_count"] and len(documents) >= 500
    assert len(before["context_retrieval_dependencies"]) == len(v["context_request"]["retrieval_bindings"])
    call_count = len(v["index_calls"])
    count, tree_hash = export_tree(v["exweb_git"], AFTER, v["exweb_export"])
    assert count == 126
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    new = candidate(v)
    target = {**v["target"], "image_revision_id": new["image_revision_id"], "image_artifact_hash": new["artifact_hash"],
        "expected_head_id": v["index_head"]["publication_id"]}
    approval, _ = review(v, review_request(v, target=target))
    completed(invoke(v, "baseline.promote", publish_request(v, approval, target)))
    assert history(v)["head"]["image_revision_id"] != v["index_head"]["image_revision_id"]
    after = v["client"].get(url, headers=v["headers"])
    assert after.status_code == 200, after.text
    assert after.json()["context"] == initial["context"] and after.json()["current_use"]["stale"]
    assert inventory(v) == before and len(v["index_calls"]) == call_count
    with session_scope() as session:
        RetrievalProvenanceProjectorV1().backfill(session)
    assert inventory(v) == before
    report = dict(verified_at=datetime.now(timezone.utc).isoformat(), repository="https://github.com/kunben-duck/exweb.git",
        git_commits=[BEFORE, AFTER], export_file_counts=[125, 126],
        export_tree_hashes=[v["exweb_before_tree_hash"], tree_hash], postgresql=True, minio=True,
        registration_count=len(nodes), complete_index_document_dependencies=len(documents),
        context_trace_dependencies=len(before["context_retrieval_dependencies"]),
        original_index_trace_context_hashes_unchanged=True, historical_context_stale=True, backfill_idempotent=True,
        embedding="explicit_native_http_constant_vectors_not_semantic_gold", companion_sources="synthetic_protocol_and_orders_sentinel",
        external_model_called=False, target_executed=False, complete_project_delta_dag=False)
    if os.getenv("EXWEB_RETRIEVAL_PROVENANCE_REPORT"):
        Path(os.environ["EXWEB_RETRIEVAL_PROVENANCE_REPORT"]).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
