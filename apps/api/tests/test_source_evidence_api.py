"""Real HTTP/authorization/storage tests; run with test-api-postgres.py."""
from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.domain.system_image.evidence import EvidenceIntegrityError, text_digest
from apps.api.app.infrastructure.persistence.source_evidence_repository import SourceEvidenceRepository
from apps.api.app.infrastructure.persistence.source_evidence_models import SourceEvidenceRecord
from apps.api.app.infrastructure.persistence.system_image_repository import SystemImageRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.main import app


@pytest.fixture
def evidence_api(tmp_path, monkeypatch):
    monkeypatch.setattr(app.state, "auth_config", replace(
        app.state.auth_config, mode="required", bearer_token=uuid4().hex,
    ))
    client = TestClient(app)

    def account():
        response = client.post("/v1/auth/register", json={
            "email": f"evidence-{uuid4().hex}@example.com", "name": "Evidence reviewer",
            "password": "evidence-test-password-123",
        })
        assert response.status_code == 200, response.text
        body = response.json()
        return body["user"], {"Authorization": f"Bearer {body['access_token']}"}

    owner, headers = account()
    member, member_headers = account()
    created = client.post("/v1/projects", headers=headers, json={"name": f"Evidence {uuid4().hex}"})
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    conversation = client.post("/v1/conversations", headers=headers, json={
        "space_type": "project", "space_id": project_id, "title": "Evidence ingestion",
    })
    assert conversation.status_code == 200, conversation.text

    def invoke(tool, payload=None):
        response = client.post("/v1/tool-invocations", headers=headers, json={
            "conversation_id": conversation.json()["id"], "tool_id": tool,
            "input": {"project_id": project_id, **(payload or {})},
        })
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "completed", response.text

    path = tmp_path / "orders.py"
    path.write_text("class Orders:\n    def submit(self):\n        return 'original'\n", encoding="utf-8")
    invoke("system_image.sources.register", {"source_specs": [{"source_type": "code", "source_uri": str(path)}]})
    invoke("system_image.sources.ingest")
    invoke("system_image.context.materialize")
    image = client.get(f"/v1/projects/{project_id}/system-image", headers=headers).json()
    revision = next(item["source_revision_id"] for item in image["source_manifest"]["members"] if item["status"] == "captured")
    obj = next(item for item in image["objects"] if item["name"].startswith("Orders"))
    assert obj["code_reference"]["source_revision_id"] == revision
    # Verify persistence independently of the extraction/runtime in-memory result.
    loaded = SystemImageRepository().load_knowledge_objects()[project_id]
    assert next(item.code_reference.model_dump() for item in loaded if item.id == obj["id"]) == obj["code_reference"]
    url = f"/v1/projects/{project_id}/system-image/evidence"
    params = {"source_revision_id": revision, "object_id": obj["id"],
              "entity_revision_id": obj["code_reference"]["entity_revision_id"]}
    listed = client.get(url, headers=headers, params=params)
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 1
    evidence = listed.json()[0]
    return locals()


def test_http_evidence_pages_preserve_old_source_and_explicit_revision(evidence_api):
    v = evidence_api
    client, headers, url = v["client"], v["headers"], v["url"]
    read_url = f"{url}/{v['evidence']['evidence_id']}"
    assert v["listed"].headers["cache-control"] == "private, no-store"
    page = client.get(read_url, headers=headers, params={"max_lines": 1})
    assert page.status_code == 200, page.text
    assert page.headers["cache-control"] == "private, no-store"
    assert page.json()["content"] == "class Orders:\n"
    assert page.json()["next_start_line"] == 2
    second = client.get(read_url, headers=headers, params={"start_line": 2})
    original = page.json()["content"] + second.json()["content"]
    assert text_digest(original) == v["evidence"]["snippet_hash"]
    assert second.json()["next_start_line"] is None
    assert second.json()["integrity"] == "verified"
    assert "object_ref" not in page.text and "local-object://" not in page.text

    v["path"].write_text("# shifted\nclass Orders:\n    def submit(self):\n        return 'updated'\n")
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    v["path"].unlink()
    assert client.get(read_url, headers=headers).json()["content"] == original
    assert client.get(url, headers=headers, params=v["params"]).json() == v["listed"].json()
    assert client.get(url, headers=headers, params={"object_id": v["obj"]["id"]}).status_code == 422
    assert client.get(url, headers=headers, params={**v["params"], "source_revision_id": "missing"}).status_code == 404
    assert client.get(url, headers=headers, params={**v["params"], "entity_revision_id": "missing"}).json() == []
    assert client.get(read_url, headers=headers, params={"max_lines": 201}).status_code == 422
    assert client.get(read_url, headers=headers, params={"start_line": 100}).status_code == 400


def test_http_evidence_enforces_membership_and_revocation(evidence_api, monkeypatch):
    v = evidence_api
    client, headers, member_headers = v["client"], v["headers"], v["member_headers"]
    url = f"{v['url']}/{v['evidence']['evidence_id']}"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=member_headers).status_code == 403
    assert client.get(v["url"], headers=member_headers, params=v["params"]).status_code == 403
    membership_url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert client.put(membership_url, headers=headers, json={"role": "viewer"}).status_code == 200
    assert client.get(url, headers=member_headers).status_code == 200

    # Revoke with the real administration API while an authorized read is in flight.
    reader = app.state.container.evidence.reader
    original_read = reader.read

    def revoke_during_read(target):
        result = original_read(target)
        assert client.delete(membership_url, headers=headers).status_code == 200
        return result

    monkeypatch.setattr(reader, "read", revoke_during_read)
    denied = client.get(url, headers=member_headers)
    assert denied.status_code == 403, denied.text
    assert "original" not in denied.text
    monkeypatch.setattr(reader, "read", original_read)
    assert client.get(v["url"], headers=member_headers, params=v["params"]).status_code == 403
    other = client.post("/v1/projects", headers=headers, json={"name": f"Other {uuid4().hex}"}).json()["id"]
    assert client.get(f"/v1/projects/{other}/system-image/evidence/{v['evidence']['evidence_id']}", headers=headers).status_code == 404


def test_http_evidence_integrity_failure_does_not_leak_storage_or_secrets(evidence_api, monkeypatch):
    v = evidence_api
    target = SourceEvidenceRepository().get(v["project_id"], v["evidence"]["evidence_id"])
    reader = app.state.container.evidence.reader
    original_get = reader.storage.get_bytes

    def tamper(ref, **kwargs):
        return b"private-tampered-content" if ref == target.evidence.object_ref else original_get(ref, **kwargs)

    monkeypatch.setattr(reader.storage, "get_bytes", tamper)
    url = f"{v['url']}/{v['evidence']['evidence_id']}"
    response = v["client"].get(url, headers=v["headers"])
    assert response.status_code == 502, response.text
    assert response.json()["detail"]["error"]["code"] == "evidence_integrity_failed"
    assert "private-tampered-content" not in response.text
    assert target.evidence.object_ref not in response.text

    def unavailable(*args, **kwargs):
        raise OSError("secret-storage-endpoint:credentials")

    monkeypatch.setattr(reader.storage, "get_bytes", unavailable)
    response = v["client"].get(url, headers=v["headers"])
    assert response.status_code == 503, response.text
    assert "credentials" not in response.text


def test_real_persisted_spans_share_only_one_read_and_recheck_bytes_on_next_batch(evidence_api, monkeypatch):
    v = evidence_api
    with session_scope() as session:
        evidence_ids = session.scalars(select(SourceEvidenceRecord.evidence_id).where(
            SourceEvidenceRecord.project_id == v["project_id"],
            SourceEvidenceRecord.source_revision_id == v["revision"])).all()
    targets = SourceEvidenceRepository().get_many(v["project_id"], tuple(evidence_ids))
    assert len(targets) >= 2 and len({target.evidence.object_ref for target in targets}) == 1
    selection = tuple((target.evidence.source_revision_id, target.evidence.evidence_id) for target in targets)
    service = app.state.container.evidence
    original = service.reader.read
    reads = []
    def counted(target):
        reads.append(target.evidence.object_ref)
        return original(target)
    monkeypatch.setattr(service.reader, "read", counted)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        result = service.verify_many(v["project_id"], selection)
        assert {item.evidence_id for item in result} == set(evidence_ids) and len(reads) == 1
        original_get = service.reader.storage.get_bytes
        def corrupt(ref, **kwargs):
            return b"corrupted private source" if ref == reads[0] else original_get(ref, **kwargs)
        monkeypatch.setattr(service.reader.storage, "get_bytes", corrupt)
        with pytest.raises(EvidenceIntegrityError):
            service.verify_many(v["project_id"], selection)
        assert len(reads) == 2


def test_real_batch_source_revocation_during_shared_read_returns_no_metadata(evidence_api, monkeypatch):
    v = evidence_api
    membership_url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership_url, headers=v["headers"], json={"role": "viewer"}).status_code == 200
    with session_scope() as session:
        evidence_ids = session.scalars(select(SourceEvidenceRecord.evidence_id).where(
            SourceEvidenceRecord.project_id == v["project_id"],
            SourceEvidenceRecord.source_revision_id == v["revision"])).all()
    assert len(evidence_ids) >= 2
    selection = tuple((v["revision"], evidence_id) for evidence_id in evidence_ids)
    service = app.state.container.evidence
    original = service.reader.read
    reads = []
    def revoke(target):
        body = original(target)
        reads.append(target.evidence.evidence_id)
        assert v["client"].delete(membership_url, headers=v["headers"]).status_code == 200
        return body
    monkeypatch.setattr(service.reader, "read", revoke)
    with actor_scope(UserProfile.model_validate(v["member"])):
        with pytest.raises(PlatformApplicationError) as denied:
            service.verify_many(v["project_id"], selection)
    assert denied.value.status_code == 403 and denied.value.code == "project_access_denied"
    assert len(reads) == 1
