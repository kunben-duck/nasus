from dataclasses import replace

import pytest
from sqlalchemy import func, select

from apps.api.app.main import app
from apps.api.app.domain.system_image.source_access import StaleSourceAccessScope
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.build_plan_models import BuildPlanRecord, BuildPlanInvocationRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_access_api import grant_member, policy


def submit(v, **changes):
    return v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "conversation_id": v["conversation"].json()["id"], "tool_id": "system_image.build.plan",
        "input": {"project_id": v["project_id"], "source_manifest_id": v["image"]["source_manifest"]["manifest_id"],
                  "objective": "Investigate private Orders behavior", **changes}})


def create(v, **changes):
    response = submit(v, **changes)
    assert response.status_code == 200 and response.json()["status"] == "completed", response.text
    result = response.json()["result"]
    assert result["requires_followup"] and result["followup_reason"] == "build_plan_review"
    assert "private Orders" not in str(result)
    ref, = result["object_refs"]
    assert ref.startswith("build_plan:")
    return ref.split(":", 1)[1]


def urls(v, plan_id):
    root = f"/v1/projects/{v['project_id']}/system-image/build-plans"
    return root, f"{root}/{plan_id}"


def test_real_tool_path_plan_view_and_immutable_history(evidence_api):
    v = evidence_api
    ident = create(v, idempotency_key="plan-one")
    assert create(v, idempotency_key="plan-one") == ident
    root, url = urls(v, ident)
    response = v["client"].get(url, headers=v["headers"])
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    first = response.json()
    intent = first["proposal"]["intent"]
    assert intent["source_manifest_id"] == v["image"]["source_manifest"]["manifest_id"]
    assert first["proposal"]["execution_ready"] is False
    assert first["proposal"]["state"] == "draft"
    assert "artifact_ref" not in response.text and "s3://" not in response.text
    v["path"].write_text("class Changed:\n    pass\n")
    v["invoke"]("system_image.sources.ingest")
    assert v["client"].get(url, headers=v["headers"]).json() == first
    assert create(v) == ident  # Explicit old manifest remains a valid planning input.
    second = create(v, objective="A different investigation", purpose="behavior")
    assert second != ident
    page = v["client"].get(root, headers=v["headers"], params={"limit": 1}).json()
    next_page = v["client"].get(root, headers=v["headers"], params={"limit": 1, "after_id": page["next_after_id"]}).json()
    assert next_page["next_after_id"] is None
    assert {p["plan_id"] for p in page["items"] + next_page["items"]} == {ident, second}
    assert "objective" not in str(page)
    assert v["client"].get(root, headers=v["headers"], params={"limit": 51}).status_code == 422
    assert v["client"].post(root, headers=v["headers"], json={}).status_code == 405


@pytest.mark.parametrize("change", [{"budget": {"max_tool_calls": True}}, {"purpose": "publish"},
    {"execution_ready": True}, {"objective": " "}, {"source_manifest_id": "missing"}, {"agent_goal_id": "forged-goal"}])
def test_invalid_or_forged_plan_never_creates_an_artifact(evidence_api, change):
    response = submit(evidence_api, **change)
    assert response.status_code == 200 and response.json()["status"] == "failed", response.text
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(BuildPlanRecord).where(
            BuildPlanRecord.project_id == evidence_api["project_id"])) == 0


def test_plan_reads_enforce_membership_source_acl_and_recheck_after_io(evidence_api, monkeypatch):
    v = evidence_api
    ident = create(v)
    root, url = urls(v, ident)
    client, headers = v["client"], v["member_headers"]
    assert client.get(url).status_code == 401
    assert client.get(url, headers=headers).status_code == 403
    grant_member(v)
    assert client.get(url, headers=headers).status_code == 200
    policy(v)
    assert client.get(root, headers=headers).json()["items"] == []
    assert client.get(url, headers=headers).status_code == 403
    policy(v, (v["member"]["id"],))
    repository = app.state.container.build_plans.repository
    original = repository.get

    def revoke(*args):
        result = original(*args)
        policy(v)
        return result

    monkeypatch.setattr(repository, "get", revoke)
    denied = client.get(url, headers=headers)
    assert denied.status_code in (403, 409) and "private Orders" not in denied.text
    other = client.post("/v1/projects", headers=v["headers"], json={"name": "Other plan"}).json()["id"]
    assert client.get(url.replace(v["project_id"], other), headers=v["headers"]).status_code == 404


def test_create_rolls_back_when_scope_changes_before_commit(evidence_api, monkeypatch):
    application = app.state.container.build_plans
    original = application.repository.record

    def commit_after_revocation(*args, **kwargs):
        def changed():
            raise StaleSourceAccessScope("private access details")
        return original(*args, **{**kwargs, "require_current_scope": changed})

    monkeypatch.setattr(application.repository, "record", commit_after_revocation)
    response = submit(evidence_api)
    assert response.json()["status"] == "failed" and "private access details" not in response.text
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(BuildPlanRecord).where(
            BuildPlanRecord.project_id == evidence_api["project_id"])) == 0
        assert session.scalar(select(func.count()).select_from(BuildPlanInvocationRecord).where(
            BuildPlanInvocationRecord.project_id == evidence_api["project_id"])) == 0


def test_misbehaving_repository_cannot_return_another_project_or_digest(evidence_api, monkeypatch):
    v = evidence_api
    ident = create(v)
    _, url = urls(v, ident)
    repository = app.state.container.build_plans.repository
    original = repository.get
    for change in ({"project_id": "other"}, {"plan_digest": "corrupt"}, {"plan_id": "other"}):
        monkeypatch.setattr(repository, "get", lambda *args: replace(original(*args), **change))
        response = v["client"].get(url, headers=v["headers"])
        assert response.status_code == 502 and "private Orders" not in response.text


def test_hidden_input_is_excluded_before_plan_pagination(evidence_api):
    v = evidence_api
    old = create(v)
    other = v["path"].parent / "another.py"
    other.write_text("class OtherSource:\n    pass\n")
    v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "code", "source_uri": str(other)}]})
    v["invoke"]("system_image.sources.ingest")
    image = v["client"].get(f"/v1/projects/{v['project_id']}/system-image", headers=v["headers"]).json()
    new = create(v, source_manifest_id=image["source_manifest"]["manifest_id"])
    grant_member(v)
    repository = SourceAccessRepository()
    snapshot = repository.load_snapshot(v["project_id"])
    hidden = next(member["binding_id"] for member in image["source_manifest"]["members"]
                  if member["binding_id"] != v["evidence"]["binding_id"])
    repository.set_policy(v["project_id"], hidden, SourceAccessRule("restricted"), expected_epoch=snapshot.acl_epoch,
                          changed_by=v["owner"]["id"], invocation_id="hide-plan-input")
    root, url = urls(v, new)
    response = v["client"].get(root, headers=v["member_headers"], params={"limit": 1}).json()
    assert [item["plan_id"] for item in response["items"]] == [old] and response["next_after_id"] is None
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 403


def test_viewer_cannot_create_or_forge_a_foreign_conversation_scope(evidence_api):
    v = evidence_api
    grant_member(v)
    response = v["client"].post("/v1/tool-invocations", headers=v["member_headers"], json={
        "tool_id": "system_image.build.plan", "input": {"project_id": v["project_id"],
            "source_manifest_id": v["image"]["source_manifest"]["manifest_id"], "objective": "viewer cannot write"}})
    assert response.status_code == 200 and response.json()["status"] == "failed", response.text
    assert response.json()["result"]["followup_reason"] == "authorization_denied"
    assert response.json()["result"]["object_refs"] == []
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(BuildPlanRecord).where(
            BuildPlanRecord.project_id == v["project_id"])) == 0
    other = v["client"].post("/v1/projects", headers=v["headers"], json={"name": "Foreign scope"}).json()["id"]
    response = submit(v, project_id=other)
    assert response.status_code == 403 or (response.status_code == 200 and response.json()["status"] == "failed"), response.text
