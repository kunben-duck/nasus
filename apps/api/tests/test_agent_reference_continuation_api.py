"""Original-goal reference work uses PG CAS, archived evidence and canonical budgets."""
import pytest
from sqlalchemy import func, select

from apps.api.app.main import app
from apps.api.app.application.agent.graph import LocalAgentGraphRuntime
from apps.api.app.domain.agent.resume_checkpoint import AgentResumeCheckpoint
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.infrastructure.persistence.agent_resume_models import AgentResumeConsumptionRecord
from apps.api.app.infrastructure.persistence.build_tool_budget_repository import BuildToolBudgetRepository
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.reference_link_models import ReferenceAssertionRecord, ReferenceProposalRecord
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.store import get_runtime_assembly
from apps.api.tests.test_agent_investigation_continuation import acting, replace_graph, resume, start_structure
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_source_evidence_api import evidence_api


@pytest.fixture
def reference_review(documents, monkeypatch, request):
    v = documents
    options = getattr(request, "param", "local")
    kind = options["graph"] if isinstance(options, dict) else options
    if isinstance(options, dict):
        v["case_path"].write_text("".join(
            f"# TC-{index} Search validation {index}\n"
            + "References: US-17\n" * options["references_per_case"]
            + "Preconditions: Authenticated user\nSteps: POST /search with empty input\nExpected result: HTTP 400\n\n"
            for index in range(options["case_count"])))
        v["invoke"]("system_image.sources.ingest")
    replace_graph(monkeypatch, kind)
    manifest = SourceSnapshotRepository().latest_manifest(v["project_id"])
    v["image"] = {**v["image"], "source_manifest": {"manifest_id": manifest.manifest_id}}
    fixed, structural = start_structure(v, authorized=True)
    pending = resume(v, structural["id"], structural)
    assert pending["pause_reason"] == "waiting_confirmation"
    assert acting(pending)[-1]["selected_tool_id"] == "system_image.build.investigate"
    ledger = BuildToolBudgetRepository()
    before = ledger.inspect(structural["id"])
    for path in (v["path"], v["requirement_path"], v["case_path"]):
        path.unlink()
    replace_graph(monkeypatch, kind)
    goal = resume(v, pending["id"], pending)
    assert goal["pause_reason"] == "reference_candidate_review" and goal["model_calls_used"] == 0, goal
    proposal_step = acting(goal)[-1]
    assert proposal_step["status"] == "blocked" and proposal_step["selected_tool_id"] == "system_image.links.propose_references"
    command = v["client"].get(f"/v1/tool-invocations/{proposal_step['tool_invocation_id']}", headers=v["headers"]).json()
    assert command["status"] == "completed" and command["input_payload"]["agent_goal_id"] == goal["id"]
    current = ledger.inspect(goal["id"])
    assert current[0] == before[0] and current[1][:len(before[1])] == before[1]
    assert proposal_step["tool_invocation_id"] in {item["invocation_id"] for item in current[1]}
    v.update(graph_kind=kind, fixed=fixed, reference_goal=goal, reference_command=command,
        original_budget=before, review_budget=current)
    return v


@pytest.mark.parametrize("reference_review", [
    {"graph": "local", "case_count": 51, "references_per_case": 30},
], ids=["real-oversized-reference-page"], indirect=True)
def test_real_byte_limited_pages_keep_every_archived_candidate_and_original_goal_budget(reference_review):
    v = reference_review
    goal = v["reference_goal"]
    proposal_id = v["reference_command"]["result"]["object_refs"][0].split(":", 1)[1]
    url = f"{v['image_url']}/reference-proposals/{proposal_id}"
    first = v["client"].get(url, headers=v["headers"], params={"limit": 1})
    assert first.status_code == 200, first.text
    original = first.json()
    assert original["assertion_count"] == 51 and original["gap_count"] == 0
    oversized = v["client"].get(url, headers=v["headers"], params={"limit": 50})
    assert oversized.status_code == 413, oversized.text
    assert oversized.json()["detail"]["error"]["code"] == "image_page_too_large"
    assert v["client"].get(f"/v1/agent-goals/{goal['id']}", headers=v["headers"]).json() == goal
    final = resume(v, goal["id"], goal)
    assert final["id"] == goal["id"] and final["pause_reason"] == "build_completion_review"
    assert final["status"] == "paused" and final["model_calls_used"] == 0
    reads = [step for step in acting(final) if step["selected_tool_id"] == "query.system_image.references.read"]
    candidate_reads = [step for step in reads if step["tool_input_payload"]["section"] == "assertions"]
    assert len(candidate_reads) > 1 and all(step["tool_input_payload"]["limit"] < 50 for step in candidate_reads)
    assert sum(step["tool_input_payload"]["section"] == "gaps" for step in reads) == 1
    seen, offset = set(), 0
    for step in candidate_reads:
        body = step["tool_input_payload"]
        assert body["proposal_id"] == proposal_id and body["offset"] == offset and step["status"] == "completed"
        page = v["client"].get(url, headers=v["headers"], params={
            key: body[key] for key in ("section", "offset", "limit")})
        assert page.status_code == 200, page.text
        current = page.json()
        assert current["digest"] == original["digest"] and current["publication"] == "not_in_image_membership"
        ids = {item["assertion_id"] for item in current["items"]}
        assert len(ids) == len(current["items"]) and not seen.intersection(ids)
        assert all(item["status"] == "proposed" and len(item["subject_evidence_ids"]) == 30 for item in current["items"])
        seen.update(ids)
        offset += len(ids)
        assert current["next_offset"] == (offset if offset < 51 else None)
    assert offset == len(seen) == 51
    ledger = BuildToolBudgetRepository().inspect(goal["id"])
    assert ledger[0] == v["review_budget"][0] and ledger[1][:-len(reads)] == v["review_budget"][1]
    assert {item["invocation_id"] for item in ledger[1][-len(reads):]} == {step["tool_invocation_id"] for step in reads}
    assert resume(v, goal["id"], goal) == final
    assert BuildToolBudgetRepository().inspect(goal["id"]) == ledger
    assert v["client"].get(url, headers=v["headers"], params={"limit": 1}).json() == original
    with session_scope() as session:
        persisted = set(session.scalars(select(ReferenceAssertionRecord.assertion_id).where(
            ReferenceAssertionRecord.project_id == v["project_id"])))
    assert seen == persisted


@pytest.mark.parametrize("reference_review", ["local", "langgraph_postgres"], indirect=True)
def test_same_goal_inspects_complete_reference_report_without_approval_or_duplicate_work(reference_review, monkeypatch):
    v = reference_review
    goal = v["reference_goal"]
    proposal_id = v["reference_command"]["result"]["object_refs"][0].split(":", 1)[1]
    url = f"{v['image_url']}/reference-proposals/{proposal_id}"
    saved = v["client"].get(url, headers=v["headers"]).json()
    assert saved["assertion_count"] == 1 and saved["gap_count"] == 0
    assert saved["items"][0]["reference_id"] == "US-17" and saved["items"][0]["status"] == "proposed"
    assert saved["publication"] == "not_in_image_membership"
    # A new source head is not a reason to replace the fixed proposal or its evidence.
    v["path"].write_text("class LaterUnapprovedSource:\n    pass\n")
    v["invoke"]("system_image.sources.ingest")
    v["path"].unlink()
    replace_graph(monkeypatch, v["graph_kind"])
    final = resume(v, goal["id"], goal)
    assert final["id"] == goal["id"] and final["pause_reason"] == "build_completion_review"
    reads = [step for step in acting(final) if step["selected_tool_id"] == "query.system_image.references.read"]
    assert [step["tool_input_payload"]["section"] for step in reads] == ["assertions", "gaps"]
    assert all(step["tool_input_payload"]["proposal_id"] == proposal_id and step["status"] == "completed" for step in reads)
    ledger = BuildToolBudgetRepository().inspect(goal["id"])
    assert ledger[0] == v["review_budget"][0] and ledger[1][:-2] == v["review_budget"][1]
    assert {item["invocation_id"] for item in ledger[1][-2:]} == {step["tool_invocation_id"] for step in reads}
    assert resume(v, goal["id"], goal) == final  # Same review pin is consumed, not executed again.
    assert resume(v, goal["id"], final) == final  # Completion is still a non-executable review.
    assert BuildToolBudgetRepository().inspect(goal["id"]) == ledger
    assert v["client"].get(url, headers=v["headers"]).json() == saved
    with session_scope() as session:
        pin = AgentResumeCheckpoint.capture(goal)
        assert session.get(AgentResumeConsumptionRecord, (goal["id"], pin.digest)) is not None
        assert session.scalar(select(func.count()).select_from(ReferenceProposalRecord).where(
            ReferenceProposalRecord.project_id == v["project_id"])) == 1
        assert session.scalar(select(func.count()).select_from(ReferenceAssertionRecord).where(
            ReferenceAssertionRecord.project_id == v["project_id"])) == 1


def test_reference_continuation_rejects_concurrent_goal_change_before_any_query(reference_review, monkeypatch):
    v = reference_review
    goal = v["reference_goal"]
    compiler = get_runtime_assembly().agent_goal_plan_compiler
    original = compiler.compile_reference_continuation
    changed = {}

    def concurrent(preparing):
        continuation = original(preparing)
        persisted = ConversationRepository().get_agent_goal(preparing.id)
        persisted.pause_reason = "user_interrupt"
        ConversationRepository().upsert_goal(persisted)
        changed["goal"] = persisted.model_dump(mode="json")
        return continuation

    monkeypatch.setattr(compiler, "compile_reference_continuation", concurrent)
    denied = v["client"].post(f"/v1/agent-goals/{goal['id']}/resume", headers=v["headers"], json={"expected_goal": goal})
    assert denied.status_code == 409 and denied.json()["error"]["code"] == "agent_checkpoint_changed", denied.text
    assert v["client"].get(f"/v1/agent-goals/{goal['id']}", headers=v["headers"]).json() == changed["goal"]
    assert BuildToolBudgetRepository().inspect(goal["id"]) == v["review_budget"]


@pytest.mark.parametrize("reference_review", ["local", "langgraph_postgres"], indirect=True)
def test_reference_resume_commit_survives_gateway_reconstruction_without_repeating_proposal(reference_review, monkeypatch):
    v = reference_review
    goal = v["reference_goal"]
    update = LocalAgentGraphRuntime._update_goal

    async def lost_ack(self, value, *, patch, expected_resume=None):
        await update(self, value, patch=patch, expected_resume=expected_resume)
        if value.id == goal["id"] and patch.get("resume_mode") == "reference_candidate_inspection":
            raise RuntimeError("injected reference continuation acknowledgement loss")

    monkeypatch.setattr(LocalAgentGraphRuntime, "_update_goal", lost_ack)
    with pytest.raises(RuntimeError, match="acknowledgement loss"):
        resume(v, goal["id"], goal)
    monkeypatch.setattr(LocalAgentGraphRuntime, "_update_goal", update)
    persisted = v["client"].get(f"/v1/agent-goals/{goal['id']}", headers=v["headers"]).json()
    assert persisted["status"] == "running"
    assert len(acting(persisted)) == len(acting(goal)) + 2
    assert acting(persisted)[-3]["tool_invocation_id"] == v["reference_command"]["id"]
    assert BuildToolBudgetRepository().inspect(goal["id"]) == v["review_budget"]
    replace_graph(monkeypatch, v["graph_kind"])
    final = resume(v, goal["id"], goal)
    assert final["pause_reason"] == "build_completion_review"
    assert len(acting(final)) == len(acting(persisted)) and all(step["status"] == "completed" for step in acting(final))
    assert len(BuildToolBudgetRepository().inspect(goal["id"])[1]) == len(v["review_budget"][1]) + 2


def test_reference_review_rechecks_live_source_permission_without_advancing_goal(reference_review, monkeypatch):
    v = reference_review
    goal = v["reference_goal"]

    def denied(*args, **kwargs):
        raise SourceAccessDenied("do not expose private source details")

    monkeypatch.setattr(app.state.container.reference_links, "read", denied)
    response = v["client"].post(f"/v1/agent-goals/{goal['id']}/resume", headers=v["headers"], json={"expected_goal": goal})
    assert response.status_code == 403 and "private source details" not in response.text
    assert v["client"].get(f"/v1/agent-goals/{goal['id']}", headers=v["headers"]).json() == goal
    assert BuildToolBudgetRepository().inspect(goal["id"]) == v["review_budget"]
