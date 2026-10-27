"""Fresh canonical acquisition must obey live PG source policy, not just tool RBAC."""
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import select

from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceRevisionRecord
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.system_image_repository import SystemImageRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
from apps.api.app.main import app
from apps.api.tests.test_source_access_api import policy
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_refresh_api import add_optional, read, selection, refresh


def grant_tester(v):
    url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(url, headers=v["headers"], json={"role": "tester"}).status_code == 200


def revisions(v):
    with session_scope() as session:
        return sorted(session.scalars(select(SourceRevisionRecord.source_revision_id).where(
            SourceRevisionRecord.project_id == v["project_id"])).all())


def facts(v):
    return deepcopy(SystemImageRepository().load_project_snapshot(v["project_id"]))


def submit(v, image, mode):
    source = next(item for item in image["sources"] if item["source_type"] == "code")
    body = {"tool_id": "system_image.sources.ingest", "idempotency_key": uuid4().hex,
        "input": {"project_id": v["project_id"], **(selection(image, source["id"]) if mode == "selected" else {})}}
    response = v["client"].post("/v1/tool-invocations", headers=v["member_headers"], json=body)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("mode", ["selected", "whole_project"])
def test_fresh_ingestion_denies_restricted_sources_before_connector_or_projection_changes(evidence_api, monkeypatch, mode):
    v = evidence_api
    grant_tester(v)
    before = read(v)
    policy(v)
    before_facts = facts(v)
    before_manifest = SourceSnapshotRepository().latest_manifest(v["project_id"])
    old_revisions = revisions(v)
    original_ingest = SourceIngestionService.ingest
    calls = []

    def counted(service, source):
        calls.append(source.id)
        return original_ingest(service, source)

    monkeypatch.setattr(SourceIngestionService, "ingest", counted)
    denied = submit(v, before, mode)
    assert denied["status"] == "failed", denied
    assert denied["result"]["followup_reason"] == "source_access_denied"
    assert str(v["path"]) not in denied["summary"]
    assert not calls
    assert facts(v) == before_facts
    assert SourceSnapshotRepository().latest_manifest(v["project_id"]) == before_manifest
    assert revisions(v) == old_revisions
    # Restoring access allows a separately authorized new command, not rewriting
    # the denied command or carrying its past authorization forward.
    policy(v, (v["member"]["id"],))
    restored = submit(v, before, mode)
    assert restored["status"] == "completed", restored
    assert len(calls) == 1
    from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
    assert ConversationRepository().get_tool_invocation(denied["id"]).model_dump(mode="json") == denied


@pytest.mark.parametrize("mode", ["selected", "whole_project"])
def test_revocation_after_actual_acquisition_does_not_accept_new_revision_or_derive_chunks(evidence_api, monkeypatch, mode):
    v = evidence_api
    grant_tester(v)
    before = deepcopy(read(v))
    policy(v, (v["member"]["id"],))
    before_facts = facts(v)
    before_manifest = SourceSnapshotRepository().latest_manifest(v["project_id"])
    old_revisions = revisions(v)
    v["path"].write_text("class Orders:\n    def submit(self):\n        return 'changed-private-body'\n")
    original_ingest = SourceIngestionService.ingest
    calls = []

    def revoke_after_acquisition(service, source):
        calls.append(source.id)
        acquired = original_ingest(service, source)
        policy(v)
        return acquired

    monkeypatch.setattr(SourceIngestionService, "ingest", revoke_after_acquisition)
    denied = submit(v, before, mode)
    assert len(calls) == 1
    assert denied["status"] == "failed", denied
    assert denied["result"]["followup_reason"] == "source_access_denied"
    assert "changed-private-body" not in denied["summary"]
    after_facts = facts(v)
    for field, value in vars(before_facts).items():
        if field != "raw_assets":
            assert getattr(after_facts, field) == value
    assert SourceSnapshotRepository().latest_manifest(v["project_id"]) == before_manifest
    assert revisions(v) == old_revisions
    assert not denied["result"]["evidence_refs"]


@pytest.mark.parametrize("mode", ["selected", "whole_project"])
def test_source_revocation_after_completion_hides_the_post_response_without_rewriting_history(evidence_api, monkeypatch, mode):
    v = evidence_api
    grant_tester(v)
    image = read(v)
    policy(v, (v["member"]["id"],))
    events = app.state.container.platform._tool_invocations._events
    emit_status = events.emit_tool_status
    completed = []

    async def revoke_after_completion(invocation_id, status, *args, **kwargs):
        await emit_status(invocation_id, status, *args, **kwargs)
        if status == "completed":
            completed.append(invocation_id)
            policy(v)

    monkeypatch.setattr(events, "emit_tool_status", revoke_after_completion)
    source = next(item for item in image["sources"] if item["source_type"] == "code")
    body = {"tool_id": "system_image.sources.ingest", "idempotency_key": uuid4().hex,
        "input": {"project_id": v["project_id"], **(selection(image, source["id"]) if mode == "selected" else {})}}
    response = v["client"].post("/v1/tool-invocations", headers=v["member_headers"], json=body)
    assert len(completed) == 1
    assert response.status_code == 403, response.text
    assert source["id"] not in response.text
    assert image["source_manifest"]["content_hash"] not in response.text
    from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
    repository = ConversationRepository()
    original = repository.get_tool_invocation(completed[0]).model_dump(mode="json")
    assert original["status"] == "completed"
    original_facts, original_revisions = facts(v), revisions(v)
    policy(v, (v["member"]["id"],))
    restored = v["client"].get(f"/v1/tool-invocations/{completed[0]}", headers=v["member_headers"])
    assert restored.status_code == 200 and restored.json() == original, restored.text
    assert repository.get_tool_invocation(completed[0]).model_dump(mode="json") == original
    assert facts(v) == original_facts and revisions(v) == original_revisions


def test_real_selected_optional_refresh_does_not_read_an_inaccessible_code_source(evidence_api, tmp_path, monkeypatch):
    v = evidence_api
    path, image, source = add_optional(v, tmp_path)
    original_facts = facts(v)
    code = next(item for item in original_facts.raw_assets if item.source_type == "code")
    grant_tester(v)
    policy(v)  # Code is restricted; the selected requirement remains project-readable.
    v["path"].unlink()
    path.write_text("# US-1\nUpdated project-readable requirement\n")
    acquire = SourceIngestionService.ingest
    calls = []

    def counted(service, item):
        calls.append(item.id)
        return acquire(service, item)

    monkeypatch.setattr(SourceIngestionService, "ingest", counted)
    result = refresh(v, selection(image, source["id"]), headers=v["member_headers"])
    assert result["status"] == "completed" and calls == [source["id"]]
    after = facts(v)
    assert next(item for item in after.raw_assets if item.id == code.id) == code
    assert [item for item in after.raw_asset_chunks if item.raw_asset_id == code.id] == [
        item for item in original_facts.raw_asset_chunks if item.raw_asset_id == code.id]
    assert after.knowledge_objects == original_facts.knowledge_objects
    denied = submit(v, image, "whole_project")
    assert denied["status"] == "failed" and denied["result"]["followup_reason"] == "source_access_denied"
    assert calls == [source["id"]]
