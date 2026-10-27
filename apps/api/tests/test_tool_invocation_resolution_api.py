"""Original actor-owned commands are resolved from PG, never a latest/list projection."""
import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import select

from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.platform.source_refresh_receipts import SourceRefreshReceiptAccess
from apps.api.app.application.platform.tool_models import EventPayload, ToolInvocation
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.main import app
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_access_api import policy


def source_receipt_authorization():
    resources = app.state.container.platform._tool_invocations._read_resources
    policies = [item for item in resources.policies if isinstance(item, SourceRefreshReceiptAccess)]
    assert len(policies) == 1
    return policies[0].sources


def original(v, headers=None, key=None, conversation_id=None):
    image = v["client"].get(f"/v1/projects/{v['project_id']}/system-image", headers=v["headers"]).json()
    source = next(item for item in image["sources"] if item["source_type"] == "code")
    request_key = key or uuid4().hex
    response = v["client"].post("/v1/tool-invocations", headers=headers or v["headers"], json={
        "tool_id": "system_image.sources.ingest", "idempotency_key": request_key, "conversation_id": conversation_id,
        "input": {"project_id": v["project_id"], "source_ids": [source["id"]],
            "expected_manifest_id": image["source_manifest"]["manifest_id"],
            "expected_manifest_hash": image["source_manifest"]["content_hash"]},
    })
    assert response.status_code == 200 and response.json()["status"] == "completed", response.text
    return request_key, response.json()


def resolve(v, key, headers=None, **overrides):
    return v["client"].get("/v1/tool-invocations/resolve", headers=headers or v["headers"], params={
        "project_id": v["project_id"], "tool_id": "system_image.sources.ingest", "request_key": key, **overrides,
    })


def test_resolution_reads_the_exact_pg_command_after_more_than_256_other_commands(evidence_api, monkeypatch):
    v = evidence_api
    key, receipt = original(v)
    repository = ConversationRepository()
    for index in range(260):
        repository.upsert_tool_invocation(ToolInvocation(id="noise_" + uuid4().hex,
            tool_id="system_image.sources.ingest", status="pending", summary="Synthetic history noise; never dispatched.",
            idempotency_scope=f"actor:{v['owner']['id']}", idempotency_key=f"noise-{index}-{key}",
            input_payload={"project_id": v["project_id"], "idempotency_key": f"noise-{index}-{key}"}))
    before = deepcopy(receipt)
    monkeypatch.setattr(repository.__class__, "load_tool_invocations", lambda _: pytest.fail("must not scan history"))
    monkeypatch.setattr(repository.__class__, "load_audit_events", lambda _: pytest.fail("must not sort audit history"))
    found = resolve(v, key)
    assert found.status_code == 200 and found.json() == before, found.text
    assert found.headers["cache-control"] == "private, no-store"
    assert repository.get_tool_invocation(receipt["id"]).model_dump(mode="json") == before
    assert resolve(v, key, project_id="other-project").json() is None
    assert resolve(v, key, tool_id="system_image.context.materialize").json() is None
    assert resolve(v, "missing").json() is None


def test_same_request_key_is_owned_by_the_authenticated_actor_not_the_project_member(evidence_api):
    v = evidence_api
    key, owner_receipt = original(v)
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "project_admin"}).status_code == 200
    member_missing = resolve(v, key, headers=v["member_headers"], actor_id=v["owner"]["id"])
    assert member_missing.status_code == 200 and member_missing.json() is None
    _, member_receipt = original(v, headers=v["member_headers"], key=key)
    assert member_receipt["id"] != owner_receipt["id"]
    assert resolve(v, key).json()["id"] == owner_receipt["id"]
    assert resolve(v, key, headers=v["member_headers"]).json()["id"] == member_receipt["id"]
    assert v["client"].delete(membership, headers=v["headers"]).status_code == 200
    denied = resolve(v, key, headers=v["member_headers"])
    assert denied.status_code == 403, denied.text
    assert member_receipt["input_payload"]["expected_manifest_hash"] not in denied.text
    assert ConversationRepository().get_tool_invocation(member_receipt["id"]).model_dump(mode="json") == member_receipt


def test_resolution_cannot_expand_a_conversation_scoped_request(evidence_api):
    v = evidence_api
    key = uuid4().hex
    response = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "conversation_id": v["conversation"].json()["id"], "tool_id": "system_image.sources.ingest",
        "idempotency_key": key, "input": {"project_id": v["project_id"]},
    })
    assert response.status_code == 200 and response.json()["status"] == "completed", response.text
    found = resolve(v, key)
    assert found.status_code == 200 and found.json() is None
    unauthenticated = v["client"].get("/v1/tool-invocations/resolve", params={
        "project_id": v["project_id"], "tool_id": "system_image.sources.ingest", "request_key": key})
    assert unauthenticated.status_code == 401


@pytest.mark.parametrize("field,value", [("project_id", ""), ("tool_id", "\x00"),
    ("request_key", " bad"), ("request_key", "x" * 129)])
def test_invalid_resolution_query_is_rejected_before_the_repository(evidence_api, monkeypatch, field, value):
    v = evidence_api
    monkeypatch.setattr(ConversationRepository, "find_idempotent_tool_invocation", lambda *args, **kwargs:
        pytest.fail("invalid request must not read command facts"))
    response = resolve(v, "original", **{field: value})
    assert response.status_code == 422, response.text


def test_resolution_rechecks_live_resource_policy_after_the_pg_lookup(evidence_api, monkeypatch):
    v = evidence_api
    key, receipt = original(v)
    access = app.state.container.platform._tool_invocations._authorization
    require = access.require_invocation_access
    checked = []

    def revoked(command, user=None):
        if command.id == receipt["id"]:
            checked.append(command.id)
            raise PlatformApplicationError("source_access_denied", "Source is no longer available.", 403)
        return require(command, user)

    monkeypatch.setattr(access, "require_invocation_access", revoked)
    response = resolve(v, key)
    assert response.status_code == 403 and checked == [receipt["id"]]
    assert receipt["input_payload"]["source_ids"][0] not in response.text
    assert ConversationRepository().get_tool_invocation(receipt["id"]).model_dump(mode="json") == receipt


def test_original_source_refresh_receipt_denies_real_source_revocation_without_rewriting_history(evidence_api):
    v = evidence_api
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "project_admin"}).status_code == 200
    key, receipt = original(v, headers=v["member_headers"])
    assert resolve(v, key, headers=v["member_headers"]).json()["id"] == receipt["id"]
    audit_url = "/v1/audit-events"
    audit_params = {"tool_invocation_id": receipt["id"]}
    original_audits = v["client"].get(audit_url, headers=v["member_headers"], params=audit_params)
    assert original_audits.status_code == 200 and original_audits.json()
    assert v["client"].put(membership, headers=v["headers"], json={"role": "viewer"}).status_code == 200
    policy(v)
    for url, params in [("/v1/tool-invocations/resolve", {"project_id": v["project_id"],
        "tool_id": "system_image.sources.ingest", "request_key": key}),
        (f"/v1/tool-invocations/{receipt['id']}", {})]:
        denied = v["client"].get(url, headers=v["member_headers"], params=params)
        assert denied.status_code == 403, denied.text
        assert receipt["input_payload"]["source_ids"][0] not in denied.text
    listed = v["client"].get("/v1/tool-invocations", headers=v["member_headers"],
        params={"tool_id": "system_image.sources.ingest"})
    assert listed.status_code == 200 and receipt["id"] not in {item["id"] for item in listed.json()}
    denied_audits = v["client"].get(audit_url, headers=v["member_headers"], params=audit_params)
    assert denied_audits.status_code == 200 and denied_audits.json() == [], denied_audits.text
    policy(v, (v["member"]["id"],))
    assert resolve(v, key, headers=v["member_headers"]).json() == receipt
    assert v["client"].get(audit_url, headers=v["member_headers"], params=audit_params).json() == original_audits.json()
    assert ConversationRepository().get_tool_invocation(receipt["id"]).model_dump(mode="json") == receipt


@pytest.mark.parametrize("method", ["replay", "confirm"])
def test_source_revocation_also_blocks_canonical_replay_with_an_otherwise_allowed_tool_role(evidence_api, method):
    v = evidence_api
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "project_admin"}).status_code == 200
    key, receipt = original(v, headers=v["member_headers"])
    assert v["client"].put(membership, headers=v["headers"], json={"role": "tester"}).status_code == 200
    policy(v)
    body = {"tool_id": receipt["tool_id"], "idempotency_key": key,
        "input": {field: value for field, value in receipt["input_payload"].items() if field != "idempotency_key"}}
    if method == "replay":
        response = v["client"].post("/v1/tool-invocations", headers=v["member_headers"], json=body)
    else:
        response = v["client"].post(f"/v1/tool-invocations/{receipt['id']}/confirm", headers=v["member_headers"])
    assert response.status_code == 403, response.text
    assert receipt["input_payload"]["source_ids"][0] not in response.text
    assert ConversationRepository().get_tool_invocation(receipt["id"]).model_dump(mode="json") == receipt
    policy(v, (v["member"]["id"],))
    restored = (v["client"].post("/v1/tool-invocations", headers=v["member_headers"], json=body)
        if method == "replay" else v["client"].post(
            f"/v1/tool-invocations/{receipt['id']}/confirm", headers=v["member_headers"]))
    assert restored.status_code == 200 and restored.json() == receipt, restored.text
    assert ConversationRepository().get_tool_invocation(receipt["id"]).model_dump(mode="json") == receipt


@pytest.mark.parametrize("method", ["get", "resolve", "list", "audit", "replay", "confirm"])
def test_real_source_revocation_during_receipt_authorization_discards_the_response(evidence_api, monkeypatch, method):
    v = evidence_api
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "project_admin"}).status_code == 200
    key, receipt = original(v, headers=v["member_headers"])
    assert v["client"].put(membership, headers=v["headers"], json={"role": "tester"}).status_code == 200
    policy(v, (v["member"]["id"],))
    sources = source_receipt_authorization()
    require_current = sources.require_current
    rechecks = []

    def revoke_before_recheck(scope):
        rechecks.append(scope)
        if len(rechecks) == 1:
            policy(v)
        return require_current(scope)

    monkeypatch.setattr(sources, "require_current", revoke_before_recheck)
    if method == "get":
        response = v["client"].get(f"/v1/tool-invocations/{receipt['id']}", headers=v["member_headers"])
    elif method == "resolve":
        response = resolve(v, key, headers=v["member_headers"])
    elif method == "list":
        response = v["client"].get("/v1/tool-invocations", headers=v["member_headers"],
            params={"tool_id": receipt["tool_id"]})
    elif method == "audit":
        response = v["client"].get("/v1/audit-events", headers=v["member_headers"],
            params={"tool_invocation_id": receipt["id"]})
    elif method == "replay":
        response = v["client"].post("/v1/tool-invocations", headers=v["member_headers"], json={
            "tool_id": receipt["tool_id"], "idempotency_key": key,
            "input": {field: value for field, value in receipt["input_payload"].items() if field != "idempotency_key"}})
    else:
        response = v["client"].post(f"/v1/tool-invocations/{receipt['id']}/confirm", headers=v["member_headers"])
    assert len(rechecks) == 1
    if method in {"list", "audit"}:
        assert response.status_code == 200 and response.json() == [], response.text
    else:
        assert response.status_code == 403, response.text
    assert receipt["input_payload"]["source_ids"][0] not in response.text
    assert receipt["input_payload"]["expected_manifest_hash"] not in response.text
    assert ConversationRepository().get_tool_invocation(receipt["id"]).model_dump(mode="json") == receipt


def test_whole_project_receipts_cannot_bypass_source_revocation_or_mutate_original_history(evidence_api):
    v = evidence_api
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "project_admin"}).status_code == 200
    key = uuid4().hex
    body = {"tool_id": "system_image.sources.ingest", "idempotency_key": key, "input": {"project_id": v["project_id"]}}
    response = v["client"].post("/v1/tool-invocations", headers=v["member_headers"], json=body)
    assert response.status_code == 200 and response.json()["status"] == "completed", response.text
    receipt = response.json()
    assert v["client"].put(membership, headers=v["headers"], json={"role": "tester"}).status_code == 200
    policy(v)
    denied = [resolve(v, key, headers=v["member_headers"]),
        v["client"].get(f"/v1/tool-invocations/{receipt['id']}", headers=v["member_headers"]),
        v["client"].post("/v1/tool-invocations", headers=v["member_headers"], json=body),
        v["client"].post(f"/v1/tool-invocations/{receipt['id']}/confirm", headers=v["member_headers"])]
    assert all(item.status_code == 403 for item in denied), [item.text for item in denied]
    assert v["client"].get("/v1/tool-invocations", headers=v["member_headers"],
        params={"tool_id": receipt["tool_id"]}).json() == []
    assert v["client"].get("/v1/audit-events", headers=v["member_headers"],
        params={"tool_invocation_id": receipt["id"]}).json() == []
    policy(v, (v["member"]["id"],))
    assert resolve(v, key, headers=v["member_headers"]).json() == receipt
    assert v["client"].post("/v1/tool-invocations", headers=v["member_headers"], json=body).json() == receipt
    assert ConversationRepository().get_tool_invocation(receipt["id"]).model_dump(mode="json") == receipt


@pytest.mark.parametrize("receipt_mode", ["targeted", "whole_project"])
def test_shared_source_receipt_snapshot_and_historical_outbox_replay_only_expose_lifecycle(evidence_api, receipt_mode):
    v = evidence_api
    conversation_id = v["conversation"].json()["id"]
    if receipt_mode == "targeted":
        _, receipt = original(v, conversation_id=conversation_id)
    else:
        response = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
            "tool_id": "system_image.sources.ingest", "conversation_id": conversation_id,
            "input": {"project_id": v["project_id"]}})
        assert response.status_code == 200 and response.json()["status"] == "completed", response.text
        receipt = response.json()
    with session_scope() as session:
        rows = session.scalars(select(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.entity_id == receipt["id"],
            SSEEventOutboxRecord.event_type == "tool.invocation.updated").order_by(SSEEventOutboxRecord.sequence)).all()
        assert rows
        for row in rows:
            view = row.event_payload["payload"]["tool_invocation"]
            assert view["input_payload"] == {} and view["result"] is None
            assert row.event_payload["patch"] == {"status": view["status"], "summary": view["summary"], "tool_id": view["tool_id"]}
        event = EventPayload.model_validate(rows[-1].event_payload)
    historical = event.model_copy(update={"event_id": "evt_" + uuid4().hex,
        "patch": {"summary": "private-original-source-uri", "result": deepcopy(receipt["result"])},
        "payload": {"tool_invocation": deepcopy(receipt)}}, deep=True)
    EventOutboxRepository().append(historical)
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "viewer"}).status_code == 200
    policy(v)
    for path in (f"/v1/conversations/{conversation_id}", "/v1/conversations"):
        response = v["client"].get(path, headers=v["member_headers"])
        assert response.status_code == 200, response.text
        items = response.json() if isinstance(response.json(), list) else [response.json()]
        view = next(command for conversation in items for command in conversation["tool_invocations"]
            if command["id"] == receipt["id"])
        assert view["input_payload"] == {} and view["result"] is None

    async def replay():
        stream = app.state.container.agent._events.stream_conversation_events(conversation_id, event.event_id)
        try:
            while True:
                replayed = await asyncio.wait_for(stream.__anext__(), timeout=5)
                if replayed is not None and replayed.event_id == historical.event_id:
                    return replayed
        finally:
            await stream.aclose()

    replayed = asyncio.run(replay())
    assert replayed.entity_version == historical.entity_version
    assert replayed.payload["tool_invocation"]["input_payload"] == {}
    assert replayed.payload["tool_invocation"]["result"] is None
    assert "private-original-source-uri" not in str(replayed.model_dump())
    assert replayed.patch == replayed.payload["patch"] == {
        "status": receipt["status"], "summary": "Source ingestion status: completed.", "tool_id": receipt["tool_id"]}
    assert v["evidence"]["binding_id"] not in str(replayed.payload)
    with session_scope() as session:
        stored = session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_id == historical.event_id))
        assert stored.event_payload["payload"]["tool_invocation"] == receipt
        assert stored.event_payload["patch"] == historical.patch
    assert v["client"].get(f"/v1/tool-invocations/{receipt['id']}", headers=v["headers"]).json() == receipt
