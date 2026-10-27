"""Canonical targeted refresh with actual HTTP and isolated PG/storage."""
from copy import deepcopy
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceRevisionRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
from apps.api.tests.test_source_evidence_api import evidence_api


def read(v):
    response = v["client"].get(f"/v1/projects/{v['project_id']}/system-image", headers=v["headers"])
    assert response.status_code == 200, response.text
    return response.json()


def selection(image, source_id):
    manifest = image["source_manifest"]
    return {"source_ids": [source_id], "expected_manifest_id": manifest["manifest_id"],
        "expected_manifest_hash": manifest["content_hash"]}


def refresh(v, request, *, key=None, status="completed", headers=None):
    response = v["client"].post("/v1/tool-invocations", headers=headers or v["headers"], json={
        "conversation_id": v["conversation"].json()["id"], "tool_id": "system_image.sources.ingest",
        "input": {"project_id": v["project_id"], **request}, "idempotency_key": key})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == status, response.text
    return response.json()


def add_optional(v, tmp_path):
    path = tmp_path / "requirements.md"
    path.write_text("# US-1\nOriginal requirement\n")
    v["invoke"]("system_image.sources.register", {"source_specs": [
        {"source_type": "us_doc", "source_uri": str(path)}]})
    v["invoke"]("system_image.sources.ingest")
    image = read(v)
    source = next(item for item in image["sources"] if item["source_type"] == "us_doc")
    return path, image, source


def test_selected_refresh_keeps_unselected_sources_chunks_and_historical_images(evidence_api, tmp_path, monkeypatch):
    v = evidence_api
    path, before, source = add_optional(v, tmp_path)
    originals = deepcopy(before)
    selected = selection(before, source["id"])
    path.write_text("# US-1\nUpdated requirement\n")
    # Unavailable unselected source must not be reopened or replaced by its live state.
    v["path"].unlink()
    original_ingest, original_units = SourceIngestionService.ingest, SourceIngestionService.extract_text_units
    calls, unit_calls = [], []
    def ingest(service, item):
        calls.append(item.id)
        return original_ingest(service, item)
    def units(service, item):
        unit_calls.append(item.id)
        return original_units(service, item)
    monkeypatch.setattr(SourceIngestionService, "ingest", ingest)
    monkeypatch.setattr(SourceIngestionService, "extract_text_units", units)
    key = uuid4().hex
    result = refresh(v, selected, key=key)
    after = read(v)
    assert calls == unit_calls == [source["id"]]
    assert next(item for item in after["sources"] if item["source_type"] == "code") == next(
        item for item in originals["sources"] if item["source_type"] == "code")
    assert [item for item in after["chunks"] if item["raw_asset_id"] != source["id"]] == [
        item for item in originals["chunks"] if item["raw_asset_id"] != source["id"]]
    assert after["objects"] == originals["objects"] and after["candidate_revision"] == originals["candidate_revision"]
    assert after["source_manifest"]["manifest_id"] != originals["source_manifest"]["manifest_id"]
    archived = SourceSnapshotRepository().get_manifest(v["project_id"], originals["source_manifest"]["manifest_id"])
    assert {m.binding_id: m.source_revision_id for m in archived.members} == {
        m["binding_id"]: m["source_revision_id"] for m in originals["source_manifest"]["members"]}
    assert f"raw_asset:{source['id']}" in result["result"]["object_refs"]
    assert result["result"]["next_recommended_tools"] == ["system_image.build.structure"]
    assert refresh(v, selected, key=key)["id"] == result["id"]
    assert calls == [source["id"]]
    conflict = refresh(v, selected, status="failed")
    assert conflict["result"]["followup_reason"] == "source_refresh_scope_changed"
    assert calls == [source["id"]]
    with session_scope() as session:
        stored = session.get(ToolInvocationRecord, result["id"])
        assert stored.input_payload["source_ids"] == selected["source_ids"]
        assert stored.result_payload["object_refs"] == result["result"]["object_refs"]
        assert session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == result["id"])).all()


@pytest.mark.parametrize("fault", ["missing_field", "null", "duplicate", "foreign", "wrong_hash", "wrong_id"])
def test_invalid_or_stale_selection_never_reads_sources_or_changes_the_manifest(evidence_api, monkeypatch, fault):
    v = evidence_api
    before = read(v)
    source = next(item for item in before["sources"] if item["source_type"] == "code")
    request = selection(before, source["id"])
    if fault == "missing_field":
        del request["expected_manifest_hash"]
    elif fault == "null":
        request["source_ids"] = None
    elif fault == "duplicate":
        request["source_ids"] *= 2
    elif fault == "foreign":
        request["source_ids"] = ["private-foreign-source"]
    elif fault == "wrong_hash":
        request["expected_manifest_hash"] = "sha256:" + "0" * 64
    else:
        request["expected_manifest_id"] = "private-foreign-manifest"
    calls = []
    monkeypatch.setattr(SourceIngestionService, "ingest", lambda _service, source: calls.append(source))
    result = refresh(v, request, status="failed")
    assert not calls
    assert result["result"]["followup_reason"] in {"source_refresh_scope_changed", "invalid_source_refresh_selection"}
    assert "private-foreign" not in result["result"]["summary"]
    after = read(v)
    assert after["sources"] == before["sources"] and after["chunks"] == before["chunks"]
    assert after["source_manifest"] == before["source_manifest"]


def test_selected_optional_failure_retains_old_revision_without_using_it_as_current(evidence_api, tmp_path):
    v = evidence_api
    path, before, source = add_optional(v, tmp_path)
    request = selection(before, source["id"])
    path.unlink()
    result = refresh(v, request)
    after = read(v)
    assert result["result"]["followup_reason"] == "optional_source_gap"
    assert str(tmp_path) not in json.dumps(result["result"])
    assert next(item for item in after["sources"] if item["id"] == source["id"])["ingestion_status"] == "failed"
    assert next(item for item in after["sources"] if item["source_type"] == "code") == next(
        item for item in before["sources"] if item["source_type"] == "code")
    assert after["build_state"]["status"] != "partially_failed"
    assert not any(item["raw_asset_id"] == source["id"] for item in after["chunks"])
    binding = next(item["binding_id"] for item in before["source_manifest"]["members"] if item["source_type"] == "us_doc")
    current = next(item for item in after["source_manifest"]["members"] if item["binding_id"] == binding)
    assert current["status"] == "failed" and current["source_revision_id"] is None
    old = SourceSnapshotRepository().get_manifest(v["project_id"], before["source_manifest"]["manifest_id"])
    old_revision = next(item.source_revision_id for item in old.members if item.binding_id == binding)
    with session_scope() as session:
        assert session.get(SourceRevisionRecord, old_revision) is not None


def test_selected_required_failure_does_not_hide_behind_an_unselected_healthy_repository(evidence_api, tmp_path):
    v = evidence_api
    second = tmp_path / "second.py"
    second.write_text("class Second:\n    pass\n")
    v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "code", "source_uri": str(second)}]})
    v["invoke"]("system_image.sources.ingest")
    before = read(v)
    source = next(item for item in before["sources"] if item["source_uri"] == str(v["path"]))
    v["path"].unlink()
    result = refresh(v, selection(before, source["id"]), status="failed")
    assert result["result"]["followup_reason"] == "required_source_ingestion_failed"
    assert str(tmp_path) not in json.dumps(result["result"])
    after = read(v)
    assert after["build_state"]["status"] == "partially_failed"
    assert next(item for item in after["sources"] if item["source_uri"] == str(second)) == next(
        item for item in before["sources"] if item["source_uri"] == str(second))
