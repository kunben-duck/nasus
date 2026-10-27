"""Bounded history is metadata, never a generation or egress authorization."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.tests.test_generation_execution_api import execution, queued
from apps.api.tests.test_test_design_scope_api import design_scope
from apps.api.tests.test_image_publications_api import publication
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_access_api import grant_member
from apps.api.tests.test_semantic_evaluations_api import invoke, completed


def query(v, **changes):
    return {"scope_revision_id": v["execution_request"].scope_revision_id,
        "scope_artifact_hash": v["execution_request"].scope_artifact_hash, **changes}


def read(v, *, headers=None, **changes):
    return v["client"].get(f"/v1/projects/{v['project_id']}/quality/test-design-jobs",
        params=query(v, **changes), headers=v["headers"] if headers is None else headers)


def history_id(v, suffix):
    return f"history-{v['project_id'][-10:]}-{suffix}"


def fixture_commands(v):
    original = v["execution_request"].model_dump(mode="json")
    original.update(confirmed_by_user=True, confirmed_actor_id=v["owner"]["id"], confirmed_at=datetime.now(timezone.utc).isoformat())
    with session_scope() as session:
        for index in range(105):
            session.add(ToolInvocationRecord(id=history_id(v, f"{index:03}"), tool_id="quality.test_design.generate",
                status="running" if index == 104 else "failed", summary="Explicit lifecycle pagination fixture",
                input_payload=deepcopy(original)))
        session.add(ToolInvocationRecord(id=history_id(v, "recovery"), tool_id="quality.test_design.recover", status="failed",
            summary="Explicit recovery metadata fixture, not a provider call", input_payload={
                "project_id": v["project_id"], "invocation_id": history_id(v, "000"), "request_hash": "sha256:" + "1" * 64,
                "reply_artifact_hash": "sha256:" + "2" * 64, "response_hash": "sha256:" + "3" * 64,
                "confirmed_by_user": True, "confirmed_actor_id": v["owner"]["id"], "confirmed_at": original["confirmed_at"]}))
        for ident, change in (("other-project", {"project_id": "unrelated-project"}),
                              ("other-scope", {"scope_revision_id": "unrelated-scope"}),
                              ("other-hash", {"scope_artifact_hash": "sha256:" + "0" * 64}),
                              ("legacy", {"execution": None}), ("unconfirmed", {"confirmed_by_user": False})):
            session.add(ToolInvocationRecord(id=history_id(v, ident), tool_id="quality.test_design.generate", status="running",
                summary="Excluded lifecycle fixture", input_payload={**original, **change}))


def test_generation_history_pages_exact_scope_without_global_payloads(execution):
    v = execution
    fixture_commands(v)
    ids, after_id = [], ""
    while True:
        response = read(v, limit=50, after_id=after_id)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        page = response.json()
        assert page["request"] == {"project_id": v["project_id"], **query(v, limit=50, after_id=after_id)}
        assert page["has_running"] is True and page["generation_authorized"] is False and page["execution_authorized"] is False
        assert len(page["items"]) <= 50
        for item in page["items"]:
            assert set(item) == {"invocation_id", "source_invocation_id", "tool_id", "status"}
            assert item["invocation_id"] not in ids
            ids.append(item["invocation_id"])
        if page["next_after_id"] is None:
            break
        assert page["next_after_id"] == ids[-1] and page["next_after_id"] > after_id
        after_id = page["next_after_id"]
    assert ids == [history_id(v, f"{index:03}") for index in range(105)] + [history_id(v, "recovery")]
    assert page["items"][-1]["source_invocation_id"] == history_id(v, "000")
    assert not v["native_calls"] and not v["workflow"].start.await_count
    for limit in (0, 51):
        assert read(v, limit=limit).status_code == 422
    assert read(v, after_id="x" * 129).status_code == 422


def test_generation_history_includes_confirmed_commands_but_never_runs_them(execution):
    v = execution
    ident = queued(v)
    response = read(v, limit=1)
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["items"] == [{"invocation_id": ident, "source_invocation_id": ident,
        "tool_id": "quality.test_design.generate", "status": "running"}]
    assert page["has_running"] is True and page["next_after_id"] is None
    assert not v["native_calls"] and v["workflow"].start.await_count == 1


def test_canonical_generation_history_receipt_is_revalidated_before_agent_use(execution):
    v = execution
    ident = queued(v)
    command = completed(invoke(v, "query.quality.test_design_jobs", {"project_id": v["project_id"], **query(v, limit=1)}))
    receipt = command["result"]["test_design_jobs"]
    assert receipt == read(v, limit=1).json()
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(command["id"], v["project_id"]) == receipt
        with session_scope() as session:
            session.get(ToolInvocationRecord, ident).status = "failed"
        with pytest.raises(PlatformApplicationError, match="history changed"):
            app.state.container.tool_evidence.describe(command["id"], v["project_id"])
    assert not v["native_calls"] and v["workflow"].start.await_count == 1


def test_generation_history_rechecks_scope_permissions_and_does_not_return_private_input(execution, monkeypatch):
    v = execution
    queued(v)
    assert read(v, headers={}).status_code == 401
    grant_member(v)
    assert read(v, headers=v["member_headers"]).status_code == 403
    assert read(v, scope_artifact_hash="sha256:" + "0" * 64).status_code == 502
    assert read(v, scope_revision_id="foreign-revision").status_code == 404
    original = v["jobs"].repository.history

    def revoke(request):
        page = original(request)
        repository = SourceAccessRepository()
        snapshot = repository.load_snapshot(v["project_id"])
        repository.set_policy(v["project_id"], snapshot.bindings[0].binding_id, SourceAccessRule("restricted"),
            expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="generation-history-revoke")
        return page

    monkeypatch.setattr(v["jobs"].repository, "history", revoke)
    response = read(v)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error"]["code"] == "source_access_changed"
    assert "items" not in response.json() and not v["native_calls"]


def test_generation_history_running_flag_covers_unloaded_pages_and_fails_closed_on_bad_commands(execution):
    v = execution
    fixture_commands(v)
    first = read(v, limit=1).json()
    assert first["items"][0]["status"] == "failed" and first["has_running"] is True
    with session_scope() as session:
        last = session.get(ToolInvocationRecord, history_id(v, "104"))
        last.status = "failed"
    assert read(v, limit=1).json()["has_running"] is False
    with session_scope() as session:
        first = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == history_id(v, "000")))
        payload = deepcopy(first.input_payload)
        del payload["input_digest"]
        first.input_payload = payload
    response = read(v, limit=1)
    assert response.status_code == 502, response.text
    assert response.json()["detail"]["error"]["code"] == "test_design_result_integrity_failed"
    assert "items" not in response.json() and "input_digest" not in response.text
