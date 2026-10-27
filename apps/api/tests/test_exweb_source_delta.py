"""Two actual Git commits -> private MinIO captures -> PG pins -> authorized HTTP delta."""
from datetime import datetime, timezone
from dataclasses import replace
import json
import os
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from apps.api.app.application.system_image.system_image_models import RawAssetRecord
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage, ObjectStorageConfig
from apps.api.app.infrastructure.system_image.source_snapshot_archive import SourceSnapshotArchive
from apps.api.app.infrastructure.system_image.source_delta_archive import ArchivedSourceDeltaReader
from apps.api.app.main import app
from sqlalchemy import select
from apps.api.tests.exweb_git_trees import BEFORE, AFTER, git_bytes as _git, read_git_tree as _tree


def test_exweb_two_actual_commits_have_replayable_pg_minio_source_delta(tmp_path, monkeypatch):
    root = os.getenv("EXWEB_DELTA_GIT_ROOT")
    isolated_minio = os.getenv("NASUS_TEST_OBJECT_STORAGE_MODE") == "minio"
    if not root or not (isolated_minio or os.getenv("EXWEB_MINIO_ENDPOINT")):
        pytest.skip("explicit fixed Git clone and local MinIO opt-in required")
    root = Path(root).resolve()
    assert _git(root, "rev-parse", AFTER + "^").decode().strip() == BEFORE
    assert not _git(root, "status", "--porcelain", "--untracked-files=no") or not (root / "README.md").exists()
    monkeypatch.setattr(app.state, "auth_config", replace(app.state.auth_config, mode="required", bearer_token=uuid4().hex))
    client = TestClient(app)
    registered = client.post("/v1/auth/register", json={"email": f"delta-exweb-{uuid4().hex}@example.com",
        "name": "Exweb delta reviewer", "password": "exweb-delta-password-123"})
    assert registered.status_code == 200, registered.text
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    project = client.post("/v1/projects", headers=headers, json={"name": f"Exweb delta {uuid4().hex}"})
    assert project.status_code == 200, project.text
    project_id = project.json()["id"]
    source = RawAssetRecord(id="delta_source_" + uuid4().hex, project_id=project_id,
        source_type="code", source_uri="https://github.com/kunben-duck/exweb.git")
    repository = SourceSnapshotRepository()
    repository.register_bindings(project_id, (source,))
    config = (replace(ObjectStorageConfig.from_env(), local_dir=tmp_path) if isolated_minio else
        ObjectStorageConfig(os.environ["EXWEB_MINIO_ENDPOINT"], os.environ["EXWEB_MINIO_BUCKET"],
            os.environ["EXWEB_MINIO_ACCESS_KEY"], os.environ["EXWEB_MINIO_SECRET_KEY"], "us-east-1", tmp_path))
    assert config.s3_enabled
    storage, written = ObjectStorage(config), set()
    original_put = storage.put_bytes
    def tracked(key, body, **kwargs):
        written.add(key)
        return original_put(key, body, **kwargs)
    monkeypatch.setattr(storage, "put_bytes", tracked)
    archive = SourceSnapshotArchive(storage)
    monkeypatch.setattr(app.state.container.source_deltas, "reader", ArchivedSourceDeltaReader(storage))
    try:
        revisions = []
        file_counts = []
        for sha in (BEFORE, AFTER):
            files, content_hash, inventory = _tree(root, sha)
            artifact = archive.capture(project_id=project_id, source_id=source.id, files=files,
                content_hash=content_hash, external_revision=sha, excluded_directories=[], inventory=inventory)
            assert artifact.manifest_ref.startswith("s3://")
            revisions.append(repository.record_capture(source, artifact, captured_at=datetime.now(timezone.utc).isoformat()))
            file_counts.append(len(files))
        params = {"before_revision_id": revisions[0], "after_revision_id": revisions[1]}
        url = f"/v1/projects/{project_id}/system-image/source-delta"
        first = client.get(url, headers=headers, params={**params, "limit": 1})
        assert first.status_code == 200, first.text
        result = first.json()
        assert result["before"]["external_revision"] == BEFORE and result["after"]["external_revision"] == AFTER
        assert result["complete"] and not result["gaps"]
        assert result["counts"]["added"] == result["counts"]["modified"] == 1
        assert result["counts"]["deleted"] == result["counts"]["unresolved"] == 0
        changes = []
        for kind in ("added", "modified"):
            page = client.get(url, headers=headers, params={**params, "kind": kind})
            assert page.status_code == 200 and page.json()["content_hash"] == result["content_hash"]
            changes.extend(page.json()["items"])
        assert {(item["path"], item["kind"]) for item in changes} == {
            ("README.md", "modified"), ("docs/architecture/README.md", "added")}
        assert result["counts"]["unchanged"] == file_counts[0] - 1
        assert file_counts[1] == file_counts[0] + 1
        assert not result["impact_complete"] and not result["publication_authorized"]
        assert client.get(url, headers=headers, params={**params, "limit": 1}).json() == result
        assert not any(ref in first.text for ref in ("s3://", "manifest_ref", "local-object://"))
        conversation = client.post("/v1/conversations", headers=headers, json={
            "space_type": "project", "space_id": project_id, "title": "Fixed exweb source delta"})
        assert conversation.status_code == 200, conversation.text
        invocation = client.post("/v1/tool-invocations", headers=headers, json={
            "conversation_id": conversation.json()["id"], "tool_id": "query.system_image.sources.delta",
            "input": {"project_id": project_id, **params, "kind": "modified"},
            "initiator_surface": "agent_loop", "initiator_actor": "agent"})
        assert invocation.status_code == 200 and invocation.json()["status"] == "completed", invocation.text
        invocation_id = invocation.json()["id"]
        receipt = invocation.json()["result"]["image_query"]
        assert receipt["delta_hash"] == result["content_hash"] and receipt["total"] == 1
        expanded = client.get(f"/v1/tool-invocations/{invocation_id}/image-query", headers=headers)
        assert expanded.status_code == 200, expanded.text
        assert expanded.json()["items"][0]["path"] == "README.md"
        with actor_scope(UserProfile.model_validate(registered.json()["user"])):
            assert app.state.container.tool_evidence.describe(invocation_id, project_id) == receipt
        with session_scope() as session:
            stored = session.get(ToolInvocationRecord, invocation_id)
            events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == invocation_id)).all()
            assert events and stored.result_payload["image_query"] == receipt
            durable = json.dumps(stored.result_payload) + json.dumps([event.event_payload for event in events])
        assert not any(secret in durable for secret in ("README.md", "manifest_ref", "s3://", "local-object://"))
        report = {"verified_at": datetime.now(timezone.utc).isoformat(), "before_commit": BEFORE,
            "after_commit": AFTER, "source_revision_ids": revisions, "file_counts": file_counts,
            "delta_hash": result["content_hash"], "counts": result["counts"], "changed_files": changes,
            "minio": True, "postgresql": True, "http_authorization": True,
            "source_binding_registration": "explicit_persistence_fixture",
            "canonical_tool_invocation": invocation_id, "canonical_receipt": receipt,
            "agent_observation_reauthorized": True, "canonical_outbox_metadata_only": True,
            "target_executed": False, "external_model_called": False, "provider_index_used": False,
            "impact_complete": False, "publication_authorized": False}
        if os.getenv("EXWEB_DELTA_REPORT"):
            Path(os.environ["EXWEB_DELTA_REPORT"]).write_text(json.dumps(report, indent=2), encoding="utf-8")
    finally:
        if written:
            import boto3
            s3 = boto3.client("s3", endpoint_url=config.endpoint, aws_access_key_id=config.access_key,
                aws_secret_access_key=config.secret_key, region_name=config.region)
            keys = sorted(written)
            for start in range(0, len(keys), 1000):
                deleted = s3.delete_objects(Bucket=config.bucket,
                    Delete={"Objects": [{"Key": key} for key in keys[start:start + 1000]]})
                assert not deleted.get("Errors"), "isolated source delta artifacts must be cleaned"
