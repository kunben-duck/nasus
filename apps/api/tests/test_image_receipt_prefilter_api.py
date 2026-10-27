"""Actual completed image commands cannot vanish when their verifier fails."""
import pytest

from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.infrastructure.platform.project_access_read_model import SQLAlchemyProjectAccessReadModel
from apps.api.app.store import get_runtime_assembly
from apps.api.app.domain.system_image.build_plan import BuildPlanIntegrityError
from apps.api.tests.test_agent_investigation_continuation import acting, resume, start_structure
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_ingestion_access_api import facts, revisions


@pytest.mark.parametrize("family", ["investigation", "completion"])
@pytest.mark.parametrize("failure,status", [(RuntimeError("private source URI"), 503),
    (BuildPlanIntegrityError("private original hash"), 502)])
def test_image_receipt_verifier_failure_aborts_http_history_and_explanation(
        evidence_api, monkeypatch, family, failure, status):
    v = evidence_api
    _, structural = start_structure(v)
    pending = resume(v, structural["id"])
    goal = resume(v, pending["id"])
    assert goal["pause_reason"] == "build_completion_review"
    tool = "system_image.build.investigate" if family == "investigation" else "query.system_image.build_completion.read"
    repository = ConversationRepository()
    step = next(item for item in acting(goal) if item["selected_tool_id"] == "system_image.build.investigate")
    ident = step["tool_invocation_id"]
    if family == "completion":
        receipt = repository.get_tool_invocation(ident).result.investigation
        created = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
            "tool_id": tool, "conversation_id": goal["conversation_id"], "input": {
                "project_id": v["project_id"],
                "investigation_revision_id": receipt.revision_id, "investigation_revision_hash": receipt.revision_hash,
                "expected_goal": goal, "analysis_policy": "committed_build"}})
        assert created.status_code == 200 and created.json()["status"] == "completed", created.text
        ident = created.json()["id"]
    before = repository.get_tool_invocation(ident).model_dump(mode="json")
    assert before["status"] == "completed"
    audit_scope = SQLAlchemyProjectAccessReadModel().invocation_scope(ident)
    assert audit_scope.status == before["status"] and audit_scope.result.model_dump(mode="json") == before["result"]
    source_facts, source_revisions = facts(v), revisions(v)
    reads = (
        (f"/v1/tool-invocations/{ident}", {}),
        ("/v1/tool-invocations", {"agent_goal_id": goal["id"]} if family == "investigation" else {"tool_id": tool}),
        ("/v1/audit-events", {"agent_goal_id": goal["id"]} if family == "investigation" else {"tool_invocation_id": ident}),
        (f"/v1/agent-goals/{goal['id']}/explanation" if family == "investigation" else
            f"/v1/projects/{v['project_id']}/system-image/build-completions/{ident}", {}),
    )
    baselines = []
    for url, params in reads:
        baseline = v["client"].get(url, headers=v["headers"], params=params)
        assert baseline.status_code == 200, baseline.text
        baselines.append(baseline.json())
    runtime = get_runtime_assembly()
    application = runtime.investigations if family == "investigation" else runtime.build_completions
    authorize = application.require_access
    checked = []

    def fail_original_verification(request):
        if request.project_id != v["project_id"]:
            return authorize(request)
        checked.append(request.project_id)
        raise failure

    monkeypatch.setattr(application, "require_access", fail_original_verification)
    for url, params in reads:
        failed = v["client"].get(url, headers=v["headers"], params=params)
        assert failed.status_code == status, (url, failed.text)
        assert "private source URI" not in failed.text and "private original hash" not in failed.text
        assert ident not in failed.text and v["project_id"] not in failed.text
    assert checked
    assert repository.get_tool_invocation(ident).model_dump(mode="json") == before
    assert facts(v) == source_facts and revisions(v) == source_revisions
    assert v["client"].get(f"/v1/agent-goals/{goal['id']}", headers=v["headers"]).json() == goal
    monkeypatch.setattr(application, "require_access", authorize)
    for (url, params), baseline in zip(reads, baselines):
        restored = v["client"].get(url, headers=v["headers"], params=params)
        assert restored.status_code == 200 and restored.json() == baseline
    assert repository.get_tool_invocation(ident).model_dump(mode="json") == before
