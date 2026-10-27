"""Real exweb exports/PG/MinIO; accompanying scope and draft are protocol fixtures."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.engine import make_url

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceBindingRecord
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.storage.object_storage import ObjectStorageConfig
from apps.api.tests.test_source_evidence_api import evidence_api as base_evidence_api
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_image_publications_api import publication
from apps.api.tests.test_test_design_scope_api import design_scope
from apps.api.tests.test_test_design_results_api import generation_result
from apps.api.tests.test_test_design_mapping_api import mapping, submit
from apps.api.tests.test_semantic_evaluations_api import completed
from apps.api.tests.test_context_change_impact_api import query, read, expand
from apps.api.tests.test_exweb_source_delta import BEFORE, AFTER, _tree


def export_tree(root, revision, destination):
    files, content_hash, _ = _tree(root, revision)
    destination.mkdir(exist_ok=True)
    for name, body in files:
        relative = Path(name)
        assert not relative.is_absolute() and ".." not in relative.parts
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    return len(files), content_hash


@pytest.fixture
def evidence_api(tmp_path, monkeypatch):
    root = os.getenv("EXWEB_DELTA_GIT_ROOT")
    if not root or not os.getenv("EXWEB_MINIO_ENDPOINT"):
        pytest.skip("explicit exweb Git objects and local MinIO opt-in required")
    database = make_url(os.environ["NASUS_DATABASE_URL"])
    assert database.get_backend_name() == "postgresql" and database.database.startswith("nasus_test_")
    storage = app.state.container.context_packs.artifacts.storage
    config = ObjectStorageConfig(os.environ["EXWEB_MINIO_ENDPOINT"], os.environ["EXWEB_MINIO_BUCKET"],
        os.environ["EXWEB_MINIO_ACCESS_KEY"], os.environ["EXWEB_MINIO_SECRET_KEY"], "us-east-1", tmp_path)
    written = set()
    original_put = storage.put_bytes
    def tracked(key, body, **kwargs):
        result = original_put(key, body, **kwargs)
        assert result.backend == "s3"
        written.add(result.key)
        return result
    monkeypatch.setattr(storage, "config", config)
    monkeypatch.setattr(storage, "put_bytes", tracked)
    try:
        v = base_evidence_api.__wrapped__(tmp_path, monkeypatch)
        exported = tmp_path / "exweb-export"
        file_count, tree_hash = export_tree(Path(root), BEFORE, exported)
        v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "code", "source_uri": str(exported)}]})
        v["invoke"]("system_image.sources.ingest")
        v["invoke"]("system_image.context.materialize")
        with session_scope() as session:
            binding = session.scalar(select(SourceBindingRecord).where(SourceBindingRecord.project_id == v["project_id"],
                SourceBindingRecord.external_identity == str(exported)))
            assert binding is not None
            binding_id = binding.binding_id
        v.update(exweb_export=exported, exweb_git=Path(root), exweb_binding=binding_id,
                 exweb_before_file_count=file_count, exweb_before_tree_hash=tree_hash)
        yield v
    finally:
        if written:
            import boto3
            s3 = boto3.client("s3", endpoint_url=config.endpoint, aws_access_key_id=config.access_key,
                aws_secret_access_key=config.secret_key, region_name=config.region)
            keys = sorted(written)
            for start in range(0, len(keys), 1000):
                deleted = s3.delete_objects(Bucket=config.bucket,
                    Delete={"Objects": [{"Key": key} for key in keys[start:start + 1000]]})
                assert not deleted.get("Errors"), "only this isolated test's private objects must be cleaned"


def test_actual_exweb_new_files_propagate_to_fixed_context_derivations(mapping):
    v = mapping
    completed(submit(v))
    metadata = v["context"]["metadata"]
    revision_url = v["image_url"] + "/revisions/" + metadata["image_revision_id"]
    response = v["client"].get(revision_url, headers=v["headers"], params={"section": "source_members"})
    assert response.status_code == 200, response.text
    before = next(item for item in response.json()["items"] if item["binding_id"] == v["exweb_binding"])
    count, tree_hash = export_tree(v["exweb_git"], AFTER, v["exweb_export"])
    assert (v["exweb_before_file_count"], count) == (125, 126)
    v["invoke"]("system_image.sources.ingest")
    after = next(item for item in SourceSnapshotRepository().latest_manifest(v["project_id"]).members
                 if item.binding_id == v["exweb_binding"])
    request = {"project_id": v["project_id"], "context_id": metadata["context_id"],
        "context_artifact_hash": metadata["artifact_hash"], "before_revision_id": before["source_revision_id"],
        "after_revision_id": after.source_revision_id}
    v.update(impact_request=request, impact_url=f"{v['image_url']}/context-packs/{metadata['context_id']}/change-impact")
    delta = v["client"].get(v["image_url"] + "/source-delta", headers=v["headers"], params={
        "before_revision_id": request["before_revision_id"], "after_revision_id": request["after_revision_id"]})
    assert delta.status_code == 200, delta.text
    delta = delta.json()
    assert delta["counts"]["added"] == delta["counts"]["modified"] == 1
    assert delta["complete"] and delta["counts"]["unresolved"] == 0
    observed = read(v)
    assert observed.status_code == 200, observed.text
    body = observed.json()
    assert body["delta_hash"] == delta["content_hash"]
    assert {node["kind"] for node in body["dependencies"]} == {"context", "scope", "generation", "case", "coverage", "mapping"}
    assert set(body["assessment"]["affected_keys"]) == {node["kind"] + ":" + node["artifact_id"] for node in body["dependencies"]}
    assert "query_scope_changed" in body["assessment"]["reason_codes"]
    assert not body["assessment"]["impact_complete"] and not body["assessment"]["invalidation_applied"]
    command = completed(query(v))
    assert expand(v, command).json() == body
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(command["id"], v["project_id"]) == command["result"]["image_query"]
    unchanged = read(v, after_revision_id=request["before_revision_id"])
    assert unchanged.status_code == 200 and unchanged.json()["assessment"]["affected_keys"] == []
    assert not any(value in json.dumps(command["result"]) for value in
                   ("README.md", "HTTP 400", str(v["exweb_export"]), "s3://"))
    report = {"verified_at": datetime.now(timezone.utc).isoformat(), "repository": "https://github.com/kunben-duck/exweb.git",
        "git_commits": [BEFORE, AFTER], "export_file_counts": [125, 126],
        "export_tree_hashes": [v["exweb_before_tree_hash"], tree_hash], "source_delta_hash": body["delta_hash"],
        "source_delta_counts": delta["counts"], "canonical_receipt": command["result"]["image_query"],
        "dependency_count": len(body["dependencies"]), "query_scope_change_verified": True,
        "fixed_receipt_replayed": True, "agent_observation_reauthorized": True,
        "source_registration_and_ingestion": "canonical_local_git_tree_exports_content_hash_revisions",
        "postgresql": True, "minio": True, "scope_and_draft_basis": "explicit_synthetic_protocol_not_exweb_business_gold",
        "companion_sources": "synthetic_search_requirement_and_case_plus_orders_sentinel",
        "external_model_called": False, "target_executed": False, "invalidation_applied": False, "impact_complete": False}
    if os.getenv("EXWEB_CONTEXT_IMPACT_REPORT"):
        Path(os.environ["EXWEB_CONTEXT_IMPACT_REPORT"]).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
