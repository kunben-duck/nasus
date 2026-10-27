"""Source policy fixtures are internal writes, not a prematurely exposed ACL API."""
from __future__ import annotations

from uuid import uuid4

import pytest

from apps.api.app.main import app
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.tests.test_evidence_tools_api import invoke, LIST_TOOL
from apps.api.tests.test_source_evidence_api import evidence_api


def policy(v, readers=()):
    repo = SourceAccessRepository()
    snapshot = repo.load_snapshot(v["project_id"])
    return repo.set_policy(v["project_id"], v["evidence"]["binding_id"], SourceAccessRule("restricted", readers),
                           expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="fixture-" + uuid4().hex)


def grant_member(v):
    url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(url, headers=v["headers"], json={"role": "viewer"}).status_code == 200


def test_source_restriction_blocks_http_tools_and_old_expansion_before_storage(evidence_api, monkeypatch):
    v = evidence_api
    grant_member(v)
    client, member_headers = v["client"], v["member_headers"]
    invocation = invoke(v, headers=member_headers).json()
    assert invocation["status"] == "completed"
    expansion_url = f"/v1/tool-invocations/{invocation['id']}/evidence"
    url = f"{v['url']}/{v['evidence']['evidence_id']}"
    assert client.get(url, headers=member_headers).status_code == 200
    policy(v)
    calls = []
    reader = app.state.container.evidence.reader
    original = reader.read
    def counted(target):
        calls.append(target)
        return original(target)
    monkeypatch.setattr(reader, "read", counted)
    assert client.get(url, headers=member_headers).status_code == 403
    assert client.get(expansion_url, headers=member_headers).status_code == 403
    for params in (v["params"], {**v["params"], "object_id": "unknown"}):
        result = client.get(v["url"], headers=member_headers, params=params)
        assert result.status_code == 403 and "orders.py" not in result.text
    for tool in ("query.system_image.evidence.read", LIST_TOOL):
        result = invoke(v, headers=member_headers, tool=tool)
        assert result.status_code == 200 and result.json()["status"] == "failed", result.text
        assert result.json()["result"]["evidence_query"] is None
    assert not calls
    # Administrators can inspect restricted sources; named readers are additional
    # to membership, not a replacement for it. Original archived IDs stay fixed.
    assert client.get(url, headers=v["headers"]).status_code == 200
    policy(v, (v["member"]["id"],))
    assert client.get(expansion_url, headers=member_headers).status_code == 200
    membership_url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert client.delete(membership_url, headers=v["headers"]).status_code == 200
    assert client.get(url, headers=member_headers).status_code == 403


def test_source_revocation_during_object_read_discards_body(evidence_api, monkeypatch):
    v = evidence_api
    grant_member(v)
    policy(v, (v["member"]["id"],))
    reader = app.state.container.evidence.reader
    original = reader.read
    def revoke(target):
        body = original(target)
        policy(v)
        return body
    monkeypatch.setattr(reader, "read", revoke)
    result = v["client"].get(f"{v['url']}/{v['evidence']['evidence_id']}", headers=v["member_headers"])
    assert result.status_code == 403 and "class Orders" not in result.text


@pytest.mark.parametrize("change", ["revoke", "demote"])
def test_membership_change_during_object_read_discards_body(evidence_api, monkeypatch, change):
    v = evidence_api
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "project_admin"}).status_code == 200
    policy(v)  # Only the project administrator role grants this restricted source.
    reader = app.state.container.evidence.reader
    original = reader.read
    calls = []
    def change_membership(target):
        calls.append(target)
        body = original(target)
        if change == "revoke":
            response = v["client"].delete(membership, headers=v["headers"])
        else:
            response = v["client"].put(membership, headers=v["headers"], json={"role": "viewer"})
        assert response.status_code == 200
        return body
    monkeypatch.setattr(reader, "read", change_membership)
    result = v["client"].get(f"{v['url']}/{v['evidence']['evidence_id']}", headers=v["member_headers"])
    assert len(calls) == 1
    assert result.status_code == 403 and "class Orders" not in result.text
