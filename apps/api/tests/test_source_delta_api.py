"""Actual HTTP, PostgreSQL, snapshot archive and ACL; no model calls or target execution."""
from dataclasses import replace
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.main import app


@pytest.fixture
def delta_api(tmp_path, monkeypatch):
    monkeypatch.setattr(app.state, "auth_config", replace(app.state.auth_config, mode="required", bearer_token=uuid4().hex))
    client = TestClient(app)
    def account():
        response = client.post("/v1/auth/register", json={"email": f"delta-{uuid4().hex}@example.com",
            "name": "Delta reviewer", "password": "delta-test-password-123"})
        assert response.status_code == 200, response.text
        value = response.json()
        return value["user"], {"Authorization": f"Bearer {value['access_token']}"}
    owner, headers = account()
    member, member_headers = account()
    project = client.post("/v1/projects", headers=headers, json={"name": f"Delta {uuid4().hex}"})
    assert project.status_code == 200, project.text
    project_id = project.json()["id"]
    conversation = client.post("/v1/conversations", headers=headers,
        json={"space_type": "project", "space_id": project_id, "title": "Delta snapshots"})
    assert conversation.status_code == 200, conversation.text
    def invoke(tool, payload=None):
        response = client.post("/v1/tool-invocations", headers=headers, json={
            "conversation_id": conversation.json()["id"], "tool_id": tool,
            "input": {"project_id": project_id, **(payload or {})}})
        assert response.status_code == 200 and response.json()["status"] == "completed", response.text
    root = tmp_path / "code"
    root.mkdir()
    (root / "keep.py").write_text("keep = 1\n")
    (root / "old.py").write_text("rename = 2\n")
    (root / "edit.py").write_text("before = 3\n")
    invoke("system_image.sources.register", {"source_specs": [{"source_type": "code", "source_uri": str(root)}]})
    invoke("system_image.sources.ingest")
    repository = SourceSnapshotRepository()
    before = repository.latest_manifest(project_id).members[0]
    (root / "old.py").rename(root / "new.py")
    (root / "edit.py").write_text("after = 4\n")
    invoke("system_image.sources.ingest")
    after = repository.latest_manifest(project_id).members[0]
    assert before.source_revision_id != after.source_revision_id and before.binding_id == after.binding_id
    url = f"/v1/projects/{project_id}/system-image/source-delta"
    params = {"before_revision_id": before.source_revision_id, "after_revision_id": after.source_revision_id}
    return locals()


def test_http_delta_uses_archived_revisions_and_preserves_full_pagination(delta_api):
    v = delta_api
    first = v["client"].get(v["url"], headers=v["headers"], params={**v["params"], "limit": 1})
    assert first.status_code == 200, first.text
    assert first.headers["cache-control"] == "private, no-store"
    body = first.json()
    assert body["complete"] and body["integrity"] == "verified_manifests"
    assert body["counts"] == {"added": 1, "deleted": 1, "modified": 1, "unchanged": 1, "unresolved": 0}
    assert body["total"] == 4 and body["next_offset"] == 1
    assert not body["file_bodies_verified"] and not body["impact_complete"] and not body["publication_authorized"]
    for file in v["root"].iterdir():
        file.unlink()
    rest = v["client"].get(v["url"], headers=v["headers"], params={**v["params"], "offset": 1}).json()
    assert rest["content_hash"] == body["content_hash"] and rest["next_offset"] is None
    rename = v["client"].get(v["url"], headers=v["headers"], params={**v["params"], "section": "rename_candidates"})
    assert rename.status_code == 200, rename.text
    assert rename.json()["items"] == [{"before_path": "old.py", "after_path": "new.py",
        "content_hash": next(item["after_hash"] for item in rest["items"] if item["path"] == "new.py"),
        "identity_preserved": False}]
    assert rename.json()["content_hash"] == body["content_hash"]
    assert not any(secret in first.text + rename.text for secret in
        ("manifest_ref", "s3://", "local-object://", "after = 4", str(v["root"])))


def test_http_delta_missing_foreign_or_restricted_sources_never_read_archives(delta_api, monkeypatch):
    v = delta_api
    reader = app.state.container.source_deltas.reader
    calls = []
    monkeypatch.setattr(reader, "read", lambda target: calls.append(target))
    client, url, params = v["client"], v["url"], v["params"]
    assert client.get(url, params=params).status_code == 401
    assert client.get(url, headers=v["member_headers"], params=params).status_code == 403
    assert client.get(url, headers=v["headers"], params={**params, "after_revision_id": "missing"}).status_code == 404
    other = client.post("/v1/projects", headers=v["headers"], json={"name": f"Other {uuid4().hex}"}).json()["id"]
    assert client.get(f"/v1/projects/{other}/system-image/source-delta", headers=v["headers"], params=params).status_code == 404
    member_url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert client.put(member_url, headers=v["headers"], json={"role": "viewer"}).status_code == 200
    repo = SourceAccessRepository()
    policy = repo.load_snapshot(v["project_id"])
    repo.set_policy(v["project_id"], v["before"].binding_id, SourceAccessRule("restricted"),
        expected_epoch=policy.acl_epoch, changed_by=v["owner"]["id"], invocation_id="fixture-" + uuid4().hex)
    denied = client.get(url, headers=v["member_headers"], params=params)
    assert denied.status_code == 404 and "keep.py" not in denied.text
    assert not calls


@pytest.mark.parametrize("when", [0, 1, 2])
def test_http_delta_discards_paths_when_membership_changes_during_read(delta_api, monkeypatch, when):
    v = delta_api
    client = v["client"]
    member_url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert client.put(member_url, headers=v["headers"], json={"role": "viewer"}).status_code == 200
    reader = app.state.container.source_deltas.reader
    original, calls = reader.read, []
    if when == 0:
        repository = app.state.container.source_deltas.repository
        original_pair = repository.get_pair
        def revoke_after_query(*args, **kwargs):
            result = original_pair(*args, **kwargs)
            assert client.delete(member_url, headers=v["headers"]).status_code == 200
            return result
        monkeypatch.setattr(repository, "get_pair", revoke_after_query)
    def revoke(target):
        result = original(target)
        calls.append(target)
        if len(calls) == when:
            assert client.delete(member_url, headers=v["headers"]).status_code == 200
        return result
    monkeypatch.setattr(reader, "read", revoke)
    denied = client.get(v["url"], headers=v["member_headers"], params=v["params"])
    assert denied.status_code == 403, denied.text
    assert len(calls) == when and "keep.py" not in denied.text and "content_hash" not in denied.text


@pytest.mark.parametrize("failure,status,code", [("tamper", 502, "source_delta_integrity_failed"),
                                               ("offline", 503, "source_delta_unavailable")])
def test_http_delta_storage_failures_are_sanitized(delta_api, monkeypatch, failure, status, code):
    v = delta_api
    storage = app.state.container.source_deltas.reader.archive.storage
    def fail(*args, **kwargs):
        if failure == "tamper":
            return b'{"secret": "private-ref-with-password"}'
        raise RuntimeError("private-ref-with-password")
    monkeypatch.setattr(storage, "get_bytes", fail)
    response = v["client"].get(v["url"], headers=v["headers"], params=v["params"])
    assert response.status_code == status, response.text
    assert response.json()["detail"]["error"]["code"] == code
    assert "private-ref-with-password" not in response.text


def test_http_delta_validation_filters_and_same_revision_are_explicit(delta_api):
    v = delta_api
    def get(**extra):
        return v["client"].get(v["url"], headers=v["headers"], params={**v["params"], **extra})
    assert get(limit=101).status_code == 422
    assert get(kind="accepted").status_code == 400
    assert get(offset=5).status_code == 400
    deleted = get(kind="deleted")
    assert deleted.status_code == 200 and deleted.json()["items"][0]["path"] == "old.py"
    same = get(after_revision_id=v["before"].source_revision_id)
    assert same.status_code == 200 and same.json()["counts"]["unchanged"] == 3
    assert not same.json()["full_validation_required"]
