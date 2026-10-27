from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from botocore.exceptions import ClientError
from sqlalchemy import select

from apps.api.app.main import app
from apps.api.app.domain.system_image.source_inventory import SourceInventory
from apps.api.app.infrastructure.persistence.source_inventory_models import SourceInventoryRecord
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceRevisionRecord
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage


def test_tool_runtime_persists_failed_scan_and_preserves_previous_revision(tmp_path, monkeypatch):
    client = TestClient(app)
    project = client.post("/v1/projects", json={"name": f"Inventory validation {uuid4()}"}).json()
    conversation = client.post("/v1/conversations", json={
        "space_type": "project", "space_id": project["id"], "title": "Inventory validation",
    }).json()
    root = tmp_path / "repo"
    root.mkdir()
    (root / "order.py").write_text("class Order:\n    pass\n")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "ignored.js").write_text("excluded")

    def invoke(tool, payload=None, status="completed"):
        response = client.post("/v1/tool-invocations", json={
            "conversation_id": conversation["id"], "tool_id": tool,
            "input": {"project_id": project["id"], **(payload or {})},
        })
        assert response.status_code == 200, response.text
        assert response.json()["status"] == status, response.text
        return response.json()

    invoke("system_image.sources.register", {"source_specs": [{"source_type": "code", "source_uri": str(root)}]})
    invoke("system_image.sources.ingest")
    original = client.get(f"/v1/projects/{project['id']}/system-image").json()
    original_manifest = original["source_manifest"]["manifest_id"]
    original_revision = original["source_manifest"]["members"][0]["source_revision_id"]
    with session_scope() as session:
        first = session.scalars(select(SourceInventoryRecord).where(SourceInventoryRecord.project_id == project["id"])).one()
        assert first.status == "complete" and first.file_count == 1
        first_id = first.inventory_id
        report = ObjectStorage().get_json(first.report_ref)
        assert any(item["path"] == "node_modules" and item["status"] == "excluded" for item in report["inventory"]["entries"])
        revision = session.get(SourceRevisionRecord, original_revision)
        assert ObjectStorage().get_json(revision.manifest_ref)["inventory_hash"] == first.report_hash
    assert f"source-inventory:{first_id}" in original["sources"][0]["evidence_refs"]
    # Retrying the same scan is an idempotent observation, not a new revision.
    invoke("system_image.sources.ingest")
    (root / "link").symlink_to(tmp_path / "outside")
    invoke("system_image.sources.ingest", status="failed")
    failed = client.get(f"/v1/projects/{project['id']}/system-image").json()
    assert failed["source_manifest"]["members"][0]["status"] == "failed"
    assert failed["source_manifest"]["members"][0]["source_revision_id"] is None
    with session_scope() as session:
        inventories = session.scalars(select(SourceInventoryRecord).where(SourceInventoryRecord.project_id == project["id"])).all()
        assert len(inventories) == 2
        failure = next(item for item in inventories if item.status == "failed")
        report = ObjectStorage().get_json(failure.report_ref)
        assert not SourceInventory.from_payload(report["inventory"]).complete
        assert f"source-inventory:{failure.inventory_id}" in failed["sources"][0]["evidence_refs"]
        revisions = session.scalars(select(SourceRevisionRecord).where(SourceRevisionRecord.project_id == project["id"])).all()
        assert len(revisions) == 1 and revisions[0].source_revision_id == original_revision
    assert SourceSnapshotRepository().get_manifest(project["id"], original_manifest).members[0].source_revision_id == original_revision
    (root / "link").unlink()
    original_put = ObjectStorage.put_bytes

    def unavailable(storage, key, body, **kwargs):
        if "/files/" in key:
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "private endpoint"}}, "PutObject")
        return original_put(storage, key, body, **kwargs)

    monkeypatch.setattr(ObjectStorage, "put_bytes", unavailable)
    storage_invocation = invoke("system_image.sources.ingest", status="failed")
    assert "private endpoint" not in str(storage_invocation)
    storage_failure = client.get(f"/v1/projects/{project['id']}/system-image").json()
    assert storage_failure["sources"][0]["ingestion_status"] == "failed"
    assert f"source-inventory:{first_id}" in storage_failure["sources"][0]["evidence_refs"]
    assert "private endpoint" not in str(storage_failure)
    with session_scope() as session:
        assert len(session.scalars(select(SourceRevisionRecord).where(SourceRevisionRecord.project_id == project["id"])).all()) == 1
