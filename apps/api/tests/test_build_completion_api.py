import json

import pytest
from sqlalchemy import select, update

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.system_image.build_completions import COMPLETION_READ_TOOL
from apps.api.app.infrastructure.persistence.db_models import AgentGoalRecord, ToolInvocationRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_investigation_api import investigation, investigate
from apps.api.tests.test_source_access_api import grant_member, policy


@pytest.fixture
def completion(investigation):
    v = investigation
    result = investigate(v)
    assert result["status"] == "completed", result
    receipt = result["result"]["investigation"]
    goal = v["client"].get(f"/v1/agent-goals/{v['investigation_input']['goal_id']}", headers=v["headers"])
    assert goal.status_code == 200, goal.text
    with actor_scope(UserProfile.model_validate(v["owner"])):
        page = app.state.container.code_analysis.list_for_revision(v["project_id"], v["revision"])
    analysis = page.items[0]
    v["completion_input"] = {"project_id": v["project_id"], "investigation_revision_id": receipt["revision_id"],
        "investigation_revision_hash": receipt["revision_hash"], "expected_goal": goal.json(),
        "analyses": [{"source_revision_id": analysis.source_revision_id, "analysis_id": analysis.analysis_id,
                      "report_hash": analysis.report_hash}]}
    return v


def submit(v, body=None, headers=None, key=None):
    return v["client"].post("/v1/tool-invocations", headers=headers or v["headers"], json={
        "tool_id": COMPLETION_READ_TOOL, "conversation_id": v["conversation"].json()["id"],
        "input": body or v["completion_input"], "idempotency_key": key})


def report(v, invocation_id, headers=None):
    return v["client"].get(f"/v1/projects/{v['project_id']}/system-image/build-completions/{invocation_id}",
                           headers=headers or v["headers"])


def test_real_completion_receipt_replay_and_no_goal_mutation(completion):
    v = completion
    item = submit(v, key="completion-fixed-inputs")
    assert item.status_code == 200 and item.json()["status"] == "completed", item.text
    ident = item.json()["id"]
    receipt = item.json()["result"]["build_completion"]
    saved = report(v, ident)
    assert saved.status_code == 200 and saved.headers["cache-control"] == "private, no-store", saved.text
    body = saved.json()
    assert body["state"] == "blocked" and not body["goal_completed"]
    assert body["readiness"]["structure"]["verified_evidence_count"] > 0
    assert body["source_scans"][0]["enumeration_complete"]
    assert all(scan["file_bodies_verified"] and scan["verified_file_count"] == scan["file_count"]
               and scan["body_verification_hash"].startswith("sha256:") for scan in body["source_scans"])
    assert "full_source_bytes_unverified" not in body["blockers"]
    assert body["code_analyses"][0]["report_hash"] == v["completion_input"]["analyses"][0]["report_hash"]
    assert body["goal_checkpoint"]["goal_id"] == v["completion_input"]["expected_goal"]["id"]
    goal_url = f"/v1/agent-goals/{body['goal_checkpoint']['goal_id']}"
    assert v["client"].get(goal_url, headers=v["headers"]).json() == v["completion_input"]["expected_goal"]
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(ident, v["project_id"]) == body
    assert submit(v, key="completion-fixed-inputs").json()["id"] == ident
    with session_scope() as session:
        record = session.get(ToolInvocationRecord, ident)
        assert record.result_payload["build_completion"] == receipt
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == ident)).all()
        stored = json.dumps(record.result_payload) + json.dumps([event.event_payload for event in events])
    for secret in ("orders.py", "class Orders", "s3://", "local-object://", '"source_scans":', '"readiness":'):
        assert secret not in item.text + stored
    v["path"].write_text("class Later:\n    pass\n")
    v["invoke"]("system_image.sources.ingest")
    v["path"].unlink()
    with session_scope() as session:
        session.execute(update(AgentGoalRecord).where(AgentGoalRecord.id == body["goal_checkpoint"]["goal_id"]).values(summary="Later goal state"))
    assert report(v, ident).json() == body
    stale = submit(v)
    assert stale.status_code == 200 and stale.json()["status"] == "failed", stale.text


@pytest.mark.parametrize("kind", ["investigation_hash", "goal", "analysis_hash", "analysis_revision", "duplicate_analysis", "unknown_field"])
def test_unverified_pins_never_produce_completion_receipt(completion, kind):
    v = completion
    body = json.loads(json.dumps(v["completion_input"]))
    if kind == "investigation_hash":
        body["investigation_revision_hash"] = "sha256:" + "0" * 64
    elif kind == "goal":
        body["expected_goal"]["summary"] = "invented checkpoint"
    elif kind == "analysis_hash":
        body["analyses"][0]["report_hash"] = "sha256:" + "0" * 64
    elif kind == "analysis_revision":
        body["analyses"][0]["source_revision_id"] = "foreign"
    elif kind == "duplicate_analysis":
        body["analyses"] *= 2
    else:
        body["publish"] = True
    response = submit(v, body)
    assert response.status_code == 403 or response.status_code == 200 and response.json()["status"] == "failed", response.text
    if response.status_code == 200:
        assert response.json()["result"].get("build_completion") is None


def test_completion_history_and_receipt_recheck_source_access(completion):
    v = completion
    item = submit(v).json()
    assert item["status"] == "completed", item
    grant_member(v)
    policy(v, (v["member"]["id"],))
    assert report(v, item["id"], v["member_headers"]).status_code == 200
    policy(v)
    denied = report(v, item["id"], v["member_headers"])
    assert denied.status_code == 403 and "source_scans" not in denied.text
    assert v["client"].get(f"/v1/tool-invocations/{item['id']}", headers=v["member_headers"]).status_code == 403


def test_completion_history_rejects_corrupt_receipt_without_repair(completion):
    v = completion
    item = submit(v).json()
    assert item["status"] == "completed", item
    with session_scope() as session:
        record = session.get(ToolInvocationRecord, item["id"])
        record.result_payload = {**record.result_payload, "build_completion": {
            **record.result_payload["build_completion"], "report_hash": "sha256:" + "0" * 64}}
    response = report(v, item["id"])
    assert response.status_code == 409 and "source_scans" not in response.text


def test_completion_history_maps_archive_failure_without_source_leak(completion, monkeypatch):
    v = completion
    item = submit(v).json()
    assert item["status"] == "completed", item
    from apps.api.app.domain.system_image.source_delta import SourceDeltaUnavailable
    monkeypatch.setattr(app.state.container.source_deltas.reader, "read",
        lambda target: (_ for _ in ()).throw(SourceDeltaUnavailable("secret-storage-endpoint:credentials")))
    response = report(v, item["id"])
    assert response.status_code == 503 and "credentials" not in response.text


@pytest.mark.parametrize("failure,status", [("bytes", 502), ("offline", 503)])
def test_completion_history_verifies_actual_bodies_and_never_exposes_storage_errors(completion, monkeypatch, failure, status):
    v = completion
    item = submit(v).json()
    assert item["status"] == "completed", item
    storage = app.state.container.source_deltas.reader.archive.storage
    original = storage.get_bytes
    def read(ref, **kwargs):
        if "/files/" not in ref:
            return original(ref, **kwargs)
        if failure == "offline":
            raise RuntimeError("private-endpoint:credentials")
        return b"private-body-not-the-captured-bytes"
    monkeypatch.setattr(storage, "get_bytes", read)
    response = report(v, item["id"])
    assert response.status_code == status, response.text
    assert not any(secret in response.text for secret in ("private-body", "private-endpoint", "credentials", "source_scans"))
    assert submit(v).json()["result"].get("build_completion") is None


def test_completion_history_classifies_corrupt_analysis_as_integrity_failure(completion, monkeypatch):
    v = completion
    item = submit(v).json()
    assert item["status"] == "completed", item
    from apps.api.app.application.system_image.code_analysis_queries import CodeAnalysisIntegrityError
    monkeypatch.setattr(app.state.container.code_analysis, "read",
        lambda *args, **kwargs: (_ for _ in ()).throw(CodeAnalysisIntegrityError("private-analysis-content")))
    response = report(v, item["id"])
    assert response.status_code == 502 and "private-analysis-content" not in response.text


def test_completion_history_discards_verified_bodies_after_source_acl_changes(completion, monkeypatch):
    v = completion
    item = submit(v).json()
    assert item["status"] == "completed", item
    grant_member(v)
    policy(v, (v["member"]["id"],))
    sources = app.state.container.source_deltas
    original = sources.reader.verify_bodies
    def revoke(*args, **kwargs):
        verified = original(*args, **kwargs)
        policy(v)
        return verified
    monkeypatch.setattr(sources.reader, "verify_bodies", revoke)
    response = report(v, item["id"], v["member_headers"])
    assert response.status_code == 409 and "source_scans" not in response.text, response.text
