"""Full HTTP + ToolRuntime checks against the isolated PostgreSQL test database."""
from dataclasses import asdict
import asyncio
from contextvars import ContextVar
from threading import Event
import pytest

from apps.api.app.main import app
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.image_revision_repository import ImageRevisionRepository
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_access_api import grant_member, policy


def selected(v):
    url = f"/v1/projects/{v['project_id']}/system-image/revisions"
    response = v["client"].get(url, headers=v["headers"])
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert len(response.json()["items"]) == 1
    summary = response.json()["items"][0]
    return url, summary, f"{url}/{summary['image_revision_id']}"


def test_tool_materialization_creates_replayable_candidate_and_keeps_history(evidence_api):
    v = evidence_api
    url, summary, read_url = selected(v)
    client, headers = v["client"], v["headers"]
    assert summary["status"] == "candidate" and summary["publication"] == "blocked_pending_revision_governance"
    first = client.get(read_url, headers=headers, params={"section": "members", "limit": 1})
    assert first.status_code == 200, first.text
    assert first.headers["cache-control"] == "private, no-store"
    pages = first.json()["items"]
    offset = first.json()["next_offset"]
    while offset is not None:
        page = client.get(read_url, headers=headers, params={"section": "members", "limit": 1, "offset": offset}).json()
        pages.extend(page["items"])
        offset = page["next_offset"]
    assert len(pages) == summary["object_count"]
    code = [item for item in pages if item["kind"] == "code_entity"]
    assert len(code) == summary["code_member_count"] and len(code) > 0
    assert all(item["source_revision_id"] == v["revision"] and item["evidence_ids"] for item in code)
    objects_before = client.get(read_url, headers=headers).json()
    v["invoke"]("system_image.context.materialize")
    assert client.get(url, headers=headers).json()["items"] == [summary]
    v["path"].write_text("class NewOrders:\n    def submit(self):\n        return 'changed'\n")
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    v["path"].unlink()
    listed = client.get(url, headers=headers, params={"limit": 1}).json()
    next_page = client.get(url, headers=headers, params={"limit": 1, "after_id": listed["next_after_id"]}).json()
    assert len(next_page["items"]) == 1 and next_page["next_after_id"] is None
    assert listed["items"][0]["manifest_id"] != next_page["items"][0]["manifest_id"]
    assert client.get(read_url, headers=headers).json() == objects_before
    assert "s3://" not in str(objects_before) and "local-object://" not in str(objects_before)
    assert client.get(read_url, headers=headers, params={"limit": 101}).status_code == 422
    assert client.get(read_url, headers=headers, params={"offset": 100000}).status_code == 400


def test_source_acl_filters_whole_candidate_and_revalidates_after_storage(evidence_api, monkeypatch):
    v = evidence_api
    url, _, read_url = selected(v)
    client, headers = v["client"], v["member_headers"]
    assert client.get(read_url).status_code == 401
    assert client.get(read_url, headers=headers).status_code == 403
    grant_member(v)
    assert client.get(read_url, headers=headers).status_code == 200
    policy(v)
    archive = app.state.container.image_revisions.artifacts
    original = archive.read
    calls = []

    def counted(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(archive, "read", counted)
    assert client.get(url, headers=headers).json()["items"] == []
    assert client.get(read_url, headers=headers).status_code == 403
    assert calls == []
    policy(v, (v["member"]["id"],))
    assert client.get(read_url, headers=headers).status_code == 200

    def revoke(*args):
        result = original(*args)
        policy(v)
        return result

    monkeypatch.setattr(archive, "read", revoke)
    denied = client.get(read_url, headers=headers)
    assert denied.status_code in (403, 409), denied.text
    assert "Orders" not in denied.text
    other = client.post("/v1/projects", headers=v["headers"], json={"name": "Other image"}).json()["id"]
    assert client.get(read_url.replace(v["project_id"], other), headers=v["headers"]).status_code == 404


def test_archive_failure_and_corruption_are_safe_http_errors(evidence_api, monkeypatch):
    v = evidence_api
    _, summary, url = selected(v)
    header, ref, _ = ImageRevisionRepository().get(v["project_id"], summary["image_revision_id"])
    archive = app.state.container.image_revisions.artifacts

    def fail(*args, **kwargs):
        raise OSError("private:endpoint:credentials")

    monkeypatch.setattr(archive.storage, "get_bytes", fail)
    response = v["client"].get(url, headers=v["headers"])
    assert response.status_code == 503, response.text
    assert "credentials" not in response.text and ref not in response.text
    monkeypatch.setattr(archive.storage, "get_bytes", lambda *args, **kwargs: b"tampered-private-source")
    response = v["client"].get(url, headers=v["headers"])
    assert response.status_code == 502, response.text
    assert "tampered-private-source" not in response.text
    assert "artifact_ref" not in asdict(header)


def test_one_hidden_input_excludes_the_whole_candidate_but_not_older_visible_images(evidence_api):
    v = evidence_api
    url, old, _ = selected(v)
    second_source = v["path"].parent / "payments.py"
    second_source.write_text("class Payments:\n    pass\n")
    v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "code", "source_uri": str(second_source)}]})
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    client = v["client"]
    all_images = client.get(url, headers=v["headers"]).json()["items"]
    assert len(all_images) == 2
    new = next(item for item in all_images if item["image_revision_id"] != old["image_revision_id"])
    grant_member(v)
    repo = SourceAccessRepository()
    snapshot = repo.load_snapshot(v["project_id"])
    source_members = client.get(f"{url}/{new['image_revision_id']}", headers=v["headers"], params={"section": "source_members"}).json()["items"]
    hidden = next(item["binding_id"] for item in source_members if item["source_type"] == "code"
                  and item["binding_id"] != v["evidence"]["binding_id"])
    repo.set_policy(v["project_id"], hidden, SourceAccessRule("restricted"), expected_epoch=snapshot.acl_epoch,
                    changed_by=v["owner"]["id"], invocation_id="hide-second-candidate-input")
    visible = client.get(url, headers=v["member_headers"], params={"limit": 1}).json()
    assert visible["items"] == [old] and visible["next_after_id"] is None
    assert client.get(f"{url}/{new['image_revision_id']}", headers=v["member_headers"]).status_code == 403


def test_late_projection_failure_keeps_candidate_receipt_and_old_published_projection(evidence_api, monkeypatch):
    v = evidence_api
    url, old, read_url = selected(v)
    client, headers = v["client"], v["headers"]
    old_payload = client.get(read_url, headers=headers).json()
    operations = app.state.container.system_image.lifecycle._operations
    old_objects = [item.model_dump() for item in operations.workspace.list_knowledge_objects(v["project_id"])]
    v["path"].write_text("class ChangedOrders:\n    pass\n")
    v["invoke"]("system_image.sources.ingest")

    async def fail(*args, **kwargs):
        raise RuntimeError("downstream embedding unavailable")

    monkeypatch.setattr(operations.quality_contexts, "materialize", fail)
    response = client.post("/v1/tool-invocations", headers=headers, json={
        "conversation_id": v["conversation"].json()["id"], "tool_id": "system_image.context.materialize",
        "input": {"project_id": v["project_id"]}})
    assert response.status_code == 200 and response.json()["status"] == "failed", response.text
    listed = client.get(url, headers=headers).json()["items"]
    assert len(listed) == 2 and old in listed
    assert all(item["status"] == "candidate" for item in listed)
    assert client.get(read_url, headers=headers).json() == old_payload
    assert [item.model_dump() for item in operations.workspace.list_knowledge_objects(v["project_id"])] == old_objects
    from sqlalchemy import select
    from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
    from apps.api.app.infrastructure.persistence.image_revision_models import ImageRevisionInvocationRecord
    with session_scope() as session:
        row = session.scalar(select(ImageRevisionInvocationRecord).where(
            ImageRevisionInvocationRecord.invocation_id == response.json()["id"]))
        assert row is not None and row.image_revision_id != old["image_revision_id"]


def test_frozen_preparation_does_not_block_event_loop_and_preserves_context(evidence_api, monkeypatch):
    from apps.api.tests.test_materialization_source_inputs_api import running_materialization
    v = evidence_api
    operations = app.state.container.system_image.lifecycle._operations
    original = operations.candidate_preparation.prepare
    started, release = Event(), Event()
    trace = ContextVar("candidate-test-trace")

    def paused(*args, **kwargs):
        assert trace.get() == "caller-context"
        started.set()
        assert release.wait(3), "event loop could not run while candidate preparation was waiting"
        return original(*args, **kwargs)

    monkeypatch.setattr(operations.candidate_preparation, "prepare", paused)
    command = running_materialization(v, monkeypatch)

    async def run():
        trace.set("caller-context")
        task = asyncio.create_task(operations.materialize_context(v["project_id"], invocation_id=command["id"]))
        try:
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(0.01)
            assert started.is_set() and not task.done()
        finally:
            release.set()
        assert (await task).candidate_revision is not None

    with actor_scope(UserProfile.model_validate(v["owner"])):
        asyncio.run(run())


@pytest.mark.parametrize("change", ["revision", "pending_binding"])
def test_source_change_after_candidate_commit_prevents_stale_projection_apply(evidence_api, monkeypatch, change):
    v = evidence_api
    _, old, read_url = selected(v)
    operations = app.state.container.system_image.lifecycle._operations
    original = operations.candidate_preparation.prepare

    def change_after_commit(*args, **kwargs):
        prepared = original(*args, **kwargs)
        if change == "revision":
            v["path"].write_text("class NewInputArrived:\n    pass\n")
            v["invoke"]("system_image.sources.ingest")
        else:
            v["invoke"]("system_image.sources.register", {"source_specs": [
                {"source_type": "code", "source_uri": str(v["path"].parent / "new.py")} ]})
        return prepared

    monkeypatch.setattr(operations.candidate_preparation, "prepare", change_after_commit)
    result = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "conversation_id": v["conversation"].json()["id"], "tool_id": "system_image.context.materialize",
        "input": {"project_id": v["project_id"]}})
    assert result.status_code == 200 and result.json()["status"] == "failed", result.text
    assert result.json()["result"]["followup_reason"] == (
        "materialization_sources_changed" if change == "revision" else "source_access_denied")
    current = operations.source_snapshots.latest_manifest(v["project_id"])
    assert current.manifest_id != old["manifest_id"] or not operations.source_snapshots.is_current_materialization_input(current)
    assert v["client"].get(read_url, headers=v["headers"]).json()["revision"] == old
