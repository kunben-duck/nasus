from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from apps.api.app.main import app
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_access_api import grant_member, policy
from apps.api.tests.test_structure_build_api import request, confirm
from apps.api.tests.test_structure_jobs_api import queued, enqueue


def prepare(v, payload, *, headers=None):
    key = uuid4().hex
    response = v["client"].post("/v1/tool-invocations", headers=headers or v["headers"], json={
        "tool_id": "system_image.build.structure", "idempotency_key": key,
        "input": {**payload, "idempotency_key": key}})
    assert response.status_code == 200 and response.json()["status"] == "waiting_confirmation", response.text
    return response.json()["id"], key


def read(v, payload, **params):
    headers = params.pop("headers", v["headers"])
    url = f"/v1/projects/{payload['project_id']}/system-image/build-plans/{payload['plan_id']}/structure-commands"
    return v["client"].get(url, headers=headers, params={"plan_digest": payload["plan_digest"], **params})


def test_discovery_is_paged_read_only_actor_owned_and_fixed_to_plan(evidence_api):
    v = evidence_api
    payload = request(v)
    first, key = prepare(v, payload)
    second, _ = prepare(v, payload)
    unrelated, _ = prepare(v, request(v, plan_digest="wrong"))
    with session_scope() as session:
        before = session.scalar(select(func.count()).select_from(AuditEventRecord))
    response = read(v, payload, limit=1)
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store", response.text
    page = response.json()
    follow = read(v, payload, limit=1, after_id=page["next_after_id"]).json()
    assert page["next_after_id"] == page["items"][0]["invocation_id"] and follow["next_after_id"] is None
    assert [row["invocation_id"] for row in page["items"] + follow["items"]] == sorted([first, second])
    entry = next(row for row in page["items"] + follow["items"] if row["invocation_id"] == first)
    assert entry == {"invocation_id": first, "idempotency_key": key,
        "target_baseline_id": payload["target_baseline_id"], "status": "waiting_confirmation"}
    assert all(term not in response.text for term in ("source_uri", "artifact_ref", "Orders", unrelated))
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(AuditEventRecord)) == before
        assert session.get(ToolInvocationRecord, first).status == "waiting_confirmation"
    grant_member(v)
    assert read(v, payload, headers=v["member_headers"]).json()["items"] == []
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "project_admin"}).status_code == 200
    member_id, _ = prepare(v, payload, headers=v["member_headers"])
    assert [row["invocation_id"] for row in read(v, payload, headers=v["member_headers"]).json()["items"]] == [member_id]
    assert member_id not in str(read(v, payload).json())
    confirm(v, first)
    assert [row["invocation_id"] for row in read(v, payload).json()["items"]] == [second]
    assert read(v, payload, limit=51).status_code == 422
    assert read(v, payload, after_id="x" * 129).status_code == 422
    assert read(v, payload, plan_digest="changed").status_code == 502
    assert read(v, {**payload, "plan_id": "missing"}).status_code == 404
    assert read(v, payload, headers={}).status_code == 401


def test_discovery_recovers_legacy_input_key_without_inventing_a_new_command(evidence_api):
    v = evidence_api
    payload = request(v)
    response = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "tool_id": "system_image.build.structure", "input": {**payload, "idempotency_key": "legacy-input-key"}})
    assert response.json()["status"] == "waiting_confirmation"
    entries = read(v, payload).json()["items"]
    assert len(entries) == 1 and entries[0]["invocation_id"] == response.json()["id"]
    assert entries[0]["idempotency_key"] == "legacy-input-key"


def test_discovery_preserves_the_key_normalized_by_the_canonical_runtime(evidence_api):
    v = evidence_api
    payload = request(v)
    key = uuid4().hex
    response = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "tool_id": "system_image.build.structure", "idempotency_key": key, "input": payload})
    assert response.json()["status"] == "waiting_confirmation"
    assert response.json()["input_payload"]["idempotency_key"] == key
    entries = read(v, payload).json()["items"]
    assert entries == [{"invocation_id": response.json()["id"], "target_baseline_id": payload["target_baseline_id"],
        "idempotency_key": key, "status": "waiting_confirmation"}]


def test_discovery_observes_real_queued_intent_without_claim_or_redispatch(queued, monkeypatch):
    v = queued
    ident, payload = enqueue(v)
    def forbidden(*args, **kwargs):
        raise AssertionError("discovery must not execute or claim queued work")
    monkeypatch.setattr(v["jobs"].repository, "claim", forbidden)
    monkeypatch.setattr(v["jobs"].application, "execute", forbidden)
    assert read(v, payload).json()["items"] == [{"invocation_id": ident,
        "target_baseline_id": payload["target_baseline_id"], "status": "running", "idempotency_key": None}]
    assert v["dispatched"] == [ident]
    assert v["jobs"].repository.command(ident)[1] == "running"


def test_discovery_revocation_after_query_hides_previously_authorized_commands(evidence_api, monkeypatch):
    v = evidence_api
    payload = request(v)
    grant_member(v)
    policy(v, (v["member"]["id"],))
    repository = app.state.container.build_plans.commands
    original = repository.unfinished

    def revoke(**kwargs):
        rows = original(**kwargs)
        policy(v)
        return rows

    monkeypatch.setattr(repository, "unfinished", revoke)
    response = read(v, payload, headers=v["member_headers"])
    assert response.status_code in (403, 409) and "target_baseline_id" not in response.text


@pytest.mark.parametrize("corruption", ["status", "duplicate", "overflow", "cursor", "target", "key"])
def test_discovery_fails_closed_on_invalid_persistence(evidence_api, monkeypatch, corruption):
    v = evidence_api
    payload = request(v)
    ident, _ = prepare(v, payload)
    repository = app.state.container.build_plans.commands
    original = repository.unfinished
    if corruption == "key":
        with session_scope() as session:
            command = session.get(ToolInvocationRecord, ident)
            command.input_payload = {**command.input_payload, "idempotency_key": "different"}
    else:
        def invalid(**kwargs):
            rows = original(**kwargs)
            if corruption == "status": return (replace(rows[0], status="completed"),)
            if corruption == "duplicate": return (rows[0], rows[0])
            if corruption == "overflow": return tuple(rows[0] for _ in range(kwargs["limit"] + 1))
            if corruption == "target": return (replace(rows[0], target_baseline_id=""),)
            return (replace(rows[0], invocation_id=""),)
        monkeypatch.setattr(repository, "unfinished", invalid)
    response = read(v, payload)
    assert response.status_code == 502 and ident not in response.text
