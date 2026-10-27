from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api.app.main import app
from apps.api.app.application.system_image.system_image_models import RawAssetRecord
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.persistence.code_entity_models import (
    CodeEntityIdentityRecord, CodeEntityProviderBindingRecord, CodeEntityRevisionRecord,
)
from apps.api.app.infrastructure.persistence.code_alias_models import CodeObjectAliasRecord
from apps.api.app.domain.system_image.code_alias import canonical_code_object_id


def test_tool_runtime_captures_multiple_sources_and_keeps_old_snapshots(tmp_path: Path) -> None:
    client = TestClient(app)
    project = client.post("/v1/projects", json={"name": f"Snapshot validation {uuid4()}"}).json()
    conversation = client.post("/v1/conversations", json={
        "space_type": "project", "space_id": project["id"], "title": "Snapshot validation",
    }).json()

    def invoke(tool, payload, expected_status="completed"):
        response = client.post("/v1/tool-invocations", json={
            "conversation_id": conversation["id"], "tool_id": tool,
            "input": {"project_id": project["id"], **payload},
        })
        assert response.status_code == 200, response.text
        assert response.json()["status"] == expected_status, response.text
        return response.json()

    specs = []
    for name, kind, content in (
        ("first.py", "code", "class Orders:\n    pass\n"),
        ("second.py", "code", "class Refunds:\n    pass\n"),
        ("us1.md", "us_doc", "# US-1\n订单创建必须幂等。\n"),
        ("us2.md", "us_doc", "# US-2\n退款金额不可大于原订单金额。\n"),
    ):
        path = tmp_path / name
        path.write_text(content)
        specs.append({"source_type": kind, "source_uri": str(path)})
    invoke("system_image.sources.register", {"source_specs": specs})
    invoke("system_image.sources.ingest", {})
    invoke("system_image.context.materialize", {})
    first = client.get(f"/v1/projects/{project['id']}/system-image").json()
    assert len(first["source_manifest"]["members"]) == 4
    assert all(item["status"] == "captured" for item in first["source_manifest"]["members"])
    old_source = next(item for item in first["sources"] if item["source_uri"] == specs[0]["source_uri"])
    old_manifest_id = first["source_manifest"]["manifest_id"]
    with session_scope() as session:
        identities = session.scalars(select(CodeEntityIdentityRecord).where(CodeEntityIdentityRecord.project_id == project["id"])).all()
        old_ids = {row.entity_id for row in identities}
        assert len(old_ids) == 4  # Two files and two classes, not requirements.
        mappings = session.scalars(select(CodeEntityProviderBindingRecord).where(CodeEntityProviderBindingRecord.project_id == project["id"])).all()
        assert {canonical_code_object_id(row.entity_id) for row in identities} <= {item["id"] for item in first["objects"]}
        assert {row.legacy_object_id for row in mappings}.isdisjoint({item["id"] for item in first["objects"]})
        aliases = session.scalars(select(CodeObjectAliasRecord).where(CodeObjectAliasRecord.project_id == project["id"])).all()
        assert len(aliases) == len(mappings)
    invoke("system_image.sources.register", {"source_specs": specs})
    repeated = client.get(f"/v1/projects/{project['id']}/system-image").json()
    assert repeated["chunks"] == first["chunks"]
    assert repeated["sources"] == first["sources"]

    (tmp_path / "first.py").write_text("# shifted location\nclass Orders:\n    pass\n")
    invoke("system_image.sources.ingest", {})
    invoke("system_image.context.materialize", {})
    second = client.get(f"/v1/projects/{project['id']}/system-image").json()
    assert second["source_manifest"]["manifest_id"] != old_manifest_id
    old_manifest = SourceSnapshotRepository().get_manifest(project["id"], old_manifest_id)
    assert {item.source_revision_id for item in old_manifest.members} == {
        item["source_revision_id"] for item in first["source_manifest"]["members"]
    }
    assert SourceIngestionService().extract_text_units(RawAssetRecord(**old_source))[0].text == "class Orders:\n    pass\n"
    with session_scope() as session:
        assert set(session.scalars(select(CodeEntityIdentityRecord.entity_id).where(CodeEntityIdentityRecord.project_id == project["id"]))) == old_ids
        revisions = session.scalars(select(CodeEntityRevisionRecord).where(CodeEntityRevisionRecord.project_id == project["id"])).all()
        assert len(revisions) == 6

    # One good repository must not hide a failed second required repository.
    invoke("system_image.sources.register", {"source_specs": [{"source_type": "code", "source_uri": str(tmp_path / "missing")}]})
    invoke("system_image.sources.ingest", {}, expected_status="failed")
    failed = client.get(f"/v1/projects/{project['id']}/system-image").json()
    assert failed["build_state"]["status"] == "partially_failed"
    assert "failed" in {item["status"] for item in failed["source_manifest"]["members"]}
