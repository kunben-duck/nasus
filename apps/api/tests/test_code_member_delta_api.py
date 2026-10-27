"""Fixed code membership through HTTP, canonical tools, real PG and archive ACL."""
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from apps.api.app.main import app
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_access_api import grant_member, policy
from apps.api.tests.test_image_revision_api import selected
from apps.api.tests.test_image_query_tools_api import invoke, completed, expansion


def fixed_pair(v):
    _, before, _ = selected(v)
    v["path"].write_text("# shifted\nclass Orders:\n    def process(self):\n        return 'updated'\nclass Extra:\n    pass\n")
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    url = f"/v1/projects/{v['project_id']}/system-image/revisions"
    after = next(item for item in v["client"].get(url, headers=v["headers"]).json()["items"]
                 if item["image_revision_id"] != before["image_revision_id"])
    params = {"before_image_revision_id": before["image_revision_id"], "before_image_hash": before["artifact_hash"],
        "after_image_revision_id": after["image_revision_id"], "after_image_hash": after["artifact_hash"]}
    return f"/v1/projects/{v['project_id']}/system-image/code-member-delta", params


def test_actual_http_membership_pagination_and_durable_canonical_replay(evidence_api):
    v = evidence_api
    url, params = fixed_pair(v)
    response = v["client"].get(url, headers=v["headers"], params={**params, "limit": 1})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    page = response.json()
    assert page["counts"]["revision_changed"] > 0 and page["counts"]["removed_member"] > 0
    assert page["counts"]["added_member"] > 0 and not page["source_deletions_verified"]
    changes, offset = list(page["items"]), page["next_offset"]
    while offset is not None:
        more = v["client"].get(url, headers=v["headers"], params={**params, "offset": offset, "limit": 1})
        assert more.status_code == 200 and more.json()["content_hash"] == page["content_hash"], more.text
        changes.extend(more.json()["items"])
        offset = more.json()["next_offset"]
    assert len(changes) == page["total"] == sum(page["counts"].values())
    assert len({item["entity_id"] for item in changes}) == len(changes)
    key = uuid4().hex
    result = completed(invoke(v, "code_delta", {**params, "limit": 1}, key=key))
    assert result["result"]["image_query"]["operation"] == "code_member_delta"
    assert expansion(v, result).json() == page
    assert completed(invoke(v, "code_delta", {**params, "limit": 1}, key=key))["id"] == result["id"]
    with session_scope() as session:
        stored = session.get(ToolInvocationRecord, result["id"])
        assert stored.result_payload["image_query"] == result["result"]["image_query"]
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == result["id"])).all()
        serialized = json.dumps(stored.result_payload) + json.dumps([item.event_payload for item in events])
    assert events
    for secret in ("Orders", "orders.py", "return 'updated'", "local-object://", "s3://"):
        assert secret not in response.text and secret not in serialized
    v["path"].write_text("class Unrelated:\n    pass\n")
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    v["path"].unlink()
    assert expansion(v, result).json() == page
    assert v["client"].get(url, headers=v["headers"], params={**params, "kind": "removed_member"}).json()["total"] == page["counts"]["removed_member"]


def test_pair_requires_both_hashes_project_and_current_full_source_access(evidence_api, monkeypatch):
    v = evidence_api
    url, params = fixed_pair(v)
    assert v["client"].get(url, params=params).status_code == 401
    assert v["client"].get(url, headers=v["member_headers"], params=params).status_code == 403
    assert v["client"].get(url, headers=v["headers"], params={**params, "after_image_hash": "sha256:" + "0" * 64}).status_code == 502
    assert v["client"].get(url, headers=v["headers"], params={**params, "limit": 101}).status_code == 422
    assert v["client"].get(url, headers=v["headers"], params={**params, "kind": "deleted"}).status_code == 422
    other = v["client"].post("/v1/projects", headers=v["headers"], json={"name": "Other"}).json()["id"]
    assert v["client"].get(url.replace(v["project_id"], other), headers=v["headers"], params=params).status_code == 404
    result = completed(invoke(v, "code_delta", params))
    grant_member(v)
    assert expansion(v, result, headers=v["member_headers"]).status_code == 200
    policy(v)
    assert expansion(v, result, headers=v["member_headers"]).status_code == 403
    reads = []
    monkeypatch.setattr(app.state.container.image_revisions.artifacts, "read", lambda *args: reads.append(args))
    assert v["client"].get(url, headers=v["member_headers"], params=params).status_code == 403
    assert not reads


@pytest.mark.parametrize("when", [1, 2])
def test_revocation_during_either_image_read_returns_no_member_ids(evidence_api, monkeypatch, when):
    v = evidence_api
    url, params = fixed_pair(v)
    grant_member(v)
    archive = app.state.container.image_revisions.artifacts
    original, reads = archive.read, []
    def revoke(*args):
        payload = original(*args)
        reads.append(args)
        if len(reads) == when:
            policy(v)
        return payload
    monkeypatch.setattr(archive, "read", revoke)
    response = v["client"].get(url, headers=v["member_headers"], params=params)
    assert response.status_code in {403, 409}, response.text
    assert "entity_id" not in response.text and "content_hash" not in response.text


@pytest.mark.parametrize("fault,status", [("corrupt", 502), ("offline", 503)])
def test_unavailable_or_corrupt_archive_does_not_return_partial_delta(evidence_api, monkeypatch, fault, status):
    v = evidence_api
    url, params = fixed_pair(v)
    storage = app.state.container.image_revisions.artifacts.storage
    def broken(*args, **kwargs):
        if fault == "corrupt":
            return b"private storage credentials"
        raise OSError("private storage credentials")
    monkeypatch.setattr(storage, "get_bytes", broken)
    result = v["client"].get(url, headers=v["headers"], params=params)
    assert result.status_code == status and "credentials" not in result.text
