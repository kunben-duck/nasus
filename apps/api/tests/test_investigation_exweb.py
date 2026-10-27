"""Real exweb + CBM + LangGraph PG, optionally MinIO; not business gold."""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import subprocess

import pytest
from sqlalchemy import select

from apps.api.app.main import app
from apps.api.app.application.agent.graph import LangGraphAgentGraphRuntime
from apps.api.app.application.system_image.code_index_generations import CodeIndexGenerationApplicationService
from apps.api.app.application.system_image.investigations import INVESTIGATE_TOOL
from apps.api.app.domain.agent.resume_checkpoint import AgentResumeCheckpoint
from apps.api.app.infrastructure.config.agent_runtime_config import LangGraphGatewayConfig
from apps.api.app.infrastructure.config.code_graph_config import CodeGraphConfig
from apps.api.app.infrastructure.persistence.code_index_generation_models import CodeIndexGenerationRecord, CodeIndexProjectionRecord
from apps.api.app.infrastructure.persistence.agent_resume_models import AgentResumeConsumptionRecord
from apps.api.app.infrastructure.persistence.code_index_generation_repository import CodeIndexGenerationRepository
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceBindingRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.system_image.code_graph_process import CodeGraphProcessRunner
from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import CodebaseMemoryCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.composite_code_intelligence import CompositeCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.registered_code_intelligence import RegisteredCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.app.infrastructure.workflow.langgraph_agent_gateway import LangGraphAgentLoopGateway
from apps.api.app.store import get_runtime_assembly
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_structure_build_api import request, submit, confirm
from apps.api.tests.test_agent_build_plan_api import goal_request
from apps.api.tests.test_investigation_api import read
from apps.api.tests.test_build_authorization_api import BUDGET
from apps.api.tests.exweb_storage_evidence import verify_exweb_storage
from apps.api.tests.agent_chat_helpers import post_chat_turn
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.system_image.build_completions import COMPLETION_READ_TOOL
from apps.api.app.application.system_image.gap_ownership import ASSIGN_GAPS_TOOL
from apps.api.app.infrastructure.persistence.build_tool_budget_repository import BuildToolBudgetRepository
from apps.api.tests.completion_read_metrics import compare_completion_replays


@pytest.mark.skipif(not os.getenv("EXWEB_CODE_CONTROL_SOURCE"), reason="requires explicitly enabled clean fixed exweb checkout")
@pytest.mark.parametrize("entry", ["direct_investigation", "original_authorized_structure_goal"])
def test_real_exweb_native_candidate_drives_same_goal_investigation_and_private_replay(evidence_api, monkeypatch, tmp_path, entry):
    v = evidence_api
    root = Path(os.environ["EXWEB_CODE_CONTROL_SOURCE"]).resolve()
    git_revision = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    assert git_revision == "fe5827f6b76f77ef34918d8b452ee823142332dc"
    assert not subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout
    v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "code", "source_uri": str(root)}]})
    v["invoke"]("system_image.sources.ingest")
    manifest = SourceSnapshotRepository().latest_manifest(v["project_id"])
    v["image"] = {**v["image"], "source_manifest": {"manifest_id": manifest.manifest_id}}
    calls = []

    class Recorder(CodeGraphProcessRunner):
        def run(self, args, **kwargs):
            calls.append("mcp/negotiate" if kwargs.get("dialogue") is not None else args[2] if len(args) > 2 else "--version")
            return super().run(args, **kwargs)

    native = CodebaseMemoryCodeIntelligenceAdapter(replace(CodeGraphConfig.from_env(), mode="required",
        binary=str(Path(__file__).resolve().parents[3] / ".venv/bin/codebase-memory-mcp"), cache_dir=tmp_path / "native",
        timeout_seconds=180, max_entities=20000, max_relationships=50000), process_runner=Recorder())
    extraction = app.state.container.structure_builds.preparation.extraction
    generations = CodeIndexGenerationApplicationService(CodeIndexGenerationRepository(), extraction._source_reader, native)
    monkeypatch.setattr(extraction, "_source_code_intelligence", RegisteredCodeIntelligenceAdapter(
        CompositeCodeIntelligenceAdapter(TreeSitterCodeIntelligenceAdapter(), native, mode="required"), generations))
    fixed = request(v)
    assembly = get_runtime_assembly()

    def gateway():
        return LangGraphAgentLoopGateway(assembly.agent_application_ports.graph_state, assembly.agent_goal_state_machine,
            assembly.agent_goal_plan_compiler, config=LangGraphGatewayConfig(graph_name="exweb-gap-investigation",
                checkpoint_backend="postgres", database_url=os.environ["NASUS_DATABASE_URL"]))

    monkeypatch.setattr(assembly.agent_loop_runtime, "graph_runtime", LangGraphAgentGraphRuntime(gateway()))
    prefix = []
    resume_control = None
    if entry == "original_authorized_structure_goal":
        initial = goal_request(v, fixed, [("system_image.build.authorize", {**fixed, "budget": BUDGET}),
                                         ("system_image.build.structure", fixed)])
        assert initial.status_code == 200, initial.text
        goal = initial.json()
        assert goal["pause_reason"] == "waiting_confirmation", goal
        structural = v["client"].post(f"/v1/agent-goals/{goal['id']}/resume", headers=v["headers"], json={"expected_goal": goal})
        assert structural.status_code == 200, structural.text
        structural_goal = structural.json()
        assert structural_goal["pause_reason"] == "structural_candidate_review", structural_goal
        prefix = [step for step in structural_goal["steps"] if step["phase"] == "acting"]
        ident = prefix[-1]["tool_invocation_id"]
        built = v["client"].get(f"/v1/tool-invocations/{ident}", headers=v["headers"]).json()
        # The next explicit resume proposes investigation; it does not confirm
        # it using the structural authorization or create another AgentGoal.
        monkeypatch.setattr(assembly.agent_loop_runtime, "graph_runtime", LangGraphAgentGraphRuntime(gateway()))
        continued = v["client"].post(f"/v1/agent-goals/{goal['id']}/resume", headers=v["headers"], json={"expected_goal": structural_goal})
        assert continued.status_code == 200, continued.text
        goal = continued.json()
        assert goal["id"] == initial.json()["id"]
        duplicate = v["client"].post(f"/v1/agent-goals/{goal['id']}/resume", headers=v["headers"], json={"expected_goal": structural_goal})
        assert duplicate.status_code == 200 and duplicate.json() == goal
        pending_command = next(step for step in goal["steps"] if step["status"] == "blocked")["tool_invocation_id"]
        assert v["client"].get(f"/v1/tool-invocations/{pending_command}", headers=v["headers"]).json()["status"] == "waiting_confirmation"
    else:
        ident = submit(v, fixed)
        built = confirm(v, ident)
        image_id = next(ref.split(":", 1)[1] for ref in built["result"]["object_refs"] if ref.startswith("image_revision:"))
        header, _, _ = app.state.container.image_revisions.repository.get(v["project_id"], image_id)
        body = {"project_id": v["project_id"], "plan_id": fixed["plan_id"], "plan_digest": fixed["plan_digest"],
            "image_revision_id": image_id, "image_artifact_hash": header.artifact_hash}
        initial = goal_request(v, fixed, [(INVESTIGATE_TOOL, body)])
        assert initial.status_code == 200, initial.text
        goal = initial.json()
    assert built["status"] == "completed", built
    assert goal["pause_reason"] == "waiting_confirmation", goal
    before = tuple(calls)
    # Reconstruct the gateway and delete the live fixture workspace. All reads
    # below must use immutable archives, never invoke/reindex the target.
    v["path"].unlink()
    monkeypatch.setattr(assembly.agent_loop_runtime, "graph_runtime", LangGraphAgentGraphRuntime(gateway()))
    if entry == "original_authorized_structure_goal":
        turn = post_chat_turn(v, goal["conversation_id"], f"确认 {pending_command}")
        assert turn["status"] == "completed", turn
        assert turn["result"]["tool_invocation"]["id"] == pending_command
        final = turn["result"]["agent_goal"]
        confirmation_channel = "chat_public_turn"
    else:
        resumed = v["client"].post(f"/v1/agent-goals/{goal['id']}/resume", headers=v["headers"], json={"expected_goal": goal})
        assert resumed.status_code == 200, resumed.text
        final = resumed.json()
        confirmation_channel = "explicit_goal_resume"
    assert final["status"] == "paused" and final["pause_reason"] == "build_completion_review", final
    steps = [step for step in final["steps"] if step["phase"] == "acting"]
    position = len(prefix)
    assert [step["tool_invocation_id"] for step in steps[:position]] == [step["tool_invocation_id"] for step in prefix]
    assert steps[position]["selected_tool_id"] == INVESTIGATE_TOOL and len(steps) > position + 1
    assert all(step["status"] == "completed" for step in steps)
    command = v["client"].get(f"/v1/tool-invocations/{steps[position]['tool_invocation_id']}", headers=v["headers"]).json()
    saved = read(v, command["result"]["investigation"]["revision_id"]).json()
    assert [step["selected_tool_id"] for step in steps[position + 1:]] == [task["tool_id"] for task in saved["review"]["work_items"]]
    assert saved["request"]["goal_id"] == goal["id"] and len(saved["review"]["verified_evidence"]) == 8
    assert all(value["coverage"] is None for value in saved["review"]["readiness"].values())
    assert not saved["review"]["publication_allowed"]
    assert {gap["code"] for gap in saved["review"]["gaps"]} >= {
        "evidence_inspection_partial", "us_doc_unavailable", "test_asset_unavailable", "business_oracle_authority_unresolved"}
    monkeypatch.setattr(assembly.agent_loop_runtime, "graph_runtime", LangGraphAgentGraphRuntime(gateway()))
    replay = v["client"].post(f"/v1/agent-goals/{goal['id']}/resume", headers=v["headers"], json={"expected_goal": final}).json()
    assert replay["pause_reason"] == "build_completion_review"
    assert [step["tool_invocation_id"] for step in replay["steps"] if step["phase"] == "acting"] == [step["tool_invocation_id"] for step in steps]
    assert read(v, saved["revision_id"]).json() == saved and tuple(calls) == before
    if entry == "original_authorized_structure_goal":
        duplicate_final = v["client"].post(f"/v1/agent-goals/{goal['id']}/resume", headers=v["headers"],
            json={"expected_goal": structural_goal})
        assert duplicate_final.status_code == 200 and duplicate_final.json() == final
        checkpoint = AgentResumeCheckpoint.capture(structural_goal)
        with session_scope() as session:
            receipt = session.get(AgentResumeConsumptionRecord, (goal["id"], checkpoint.digest))
            assert receipt is not None
            checkpoint.require_scope({"id": receipt.goal_id, "conversation_id": receipt.conversation_id,
                "project_id": receipt.project_id, "workflow_id": receipt.workflow_id})
            checkpoint.require_consumption(receipt.transition_digest, receipt.receipt_hash)
            resume_control = {"checkpoint": checkpoint.payload(), "transition_digest": receipt.transition_digest,
                "receipt_hash": receipt.receipt_hash, "duplicate_before_confirmation_preserved_gate": True,
                "duplicate_after_investigation_preserved_state": True}
        assert tuple(calls) == before
    with session_scope() as session:
        generation = session.scalars(select(CodeIndexGenerationRecord).join(SourceBindingRecord,
            SourceBindingRecord.binding_id == CodeIndexGenerationRecord.binding_id).where(
                CodeIndexGenerationRecord.invocation_id == ident, SourceBindingRecord.external_identity == str(root))).one()
        projection = session.get(CodeIndexProjectionRecord, generation.generation_id)
        native_report = {"generation": asdict(CodeIndexGenerationRepository._pin(generation)),
            "projection_hash": projection.projection_hash, "entity_count": projection.entity_count,
            "relationship_count": projection.relationship_count}
    storage_evidence = verify_exweb_storage(v["project_id"], saved["request"]["image_revision_id"])
    with actor_scope(UserProfile.model_validate(v["owner"])):
        _, completed_payload = app.state.container.image_revisions.frozen_snapshot(
            v["project_id"], saved["request"]["image_revision_id"])
        expected_evidence = {(member["object_id"], evidence_id) for member in completed_payload["members"]
                             if member["kind"] in {"code_entity", "source_document"}
                             for evidence_id in member["evidence_ids"]}
    assessment = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "tool_id": COMPLETION_READ_TOOL, "conversation_id": final["conversation_id"],
        "input": {"project_id": v["project_id"], "investigation_revision_id": saved["revision_id"],
            "investigation_revision_hash": saved["revision_hash"], "expected_goal": final, "analysis_policy": "committed_build"}})
    assert assessment.status_code == 200 and assessment.json()["status"] == "completed", assessment.text
    receipt = assessment.json()["result"]["build_completion"]
    completion_url = f"/v1/projects/{v['project_id']}/system-image/build-completions/{assessment.json()['id']}"
    completion_response = v["client"].get(completion_url, headers=v["headers"])
    assert completion_response.status_code == 200, completion_response.text
    completion = completion_response.json()
    assert completion["state"] == "blocked" and not completion["goal_completed"]
    assert completion["readiness"]["structure"]["verified_evidence_count"] == len(expected_evidence)
    assert all(item["enumeration_complete"] for item in completion["source_scans"])
    assert all(item["file_bodies_verified"] and item["verified_file_count"] == item["file_count"]
               for item in completion["source_scans"])
    assert "full_source_bytes_unverified" not in completion["blockers"]
    assert completion["schema"] == "nasus.image-build-completion.v2"
    assert "analysis_build_lineage_unverified" not in completion["blockers"]
    assert len(completion["build_lineages"]) == 1
    lineage = completion["build_lineages"][0]
    assert lineage["invocation_id"] == ident
    assert {item["source_revision_id"] for item in lineage["analyses"]} == {
        source.source_revision_id for source in manifest.members if source.source_type == "code"}
    exweb_analysis = next(item for item in lineage["analyses"] if item["native"]["generation"]["generation_id"] == generation.generation_id)
    assert exweb_analysis["native"]["projection_hash"] == native_report["projection_hash"]
    assert all(item["build_lineage_verified"] for item in completion["code_analyses"])
    assert {"code_analysis_partial", "full_plan_budget_unverified", "gap_ownership_unassigned"} <= set(completion["blockers"])
    assert v["client"].get(completion_url, headers=v["headers"]).json() == completion
    ownership_response = v["client"].get(completion_url + "/gap-ownership", headers=v["headers"])
    assert ownership_response.status_code == 200, ownership_response.text
    assignments = [{"gap_id": gap["gap_id"], "owner_actor_id": v["owner"]["id"],
        "reason": "Explicit reviewer responsibility for the fixed exweb build gap; not gap resolution."}
        for gap in ownership_response.json()["gaps"]]
    pending = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "tool_id": ASSIGN_GAPS_TOOL, "conversation_id": final["conversation_id"],
        "input": {"project_id": v["project_id"], "completion_invocation_id": assessment.json()["id"],
            "completion_report_hash": receipt["report_hash"], "expected_goal": final, "assignments": assignments}})
    assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
    assert not v["client"].get(completion_url + "/gap-ownership", headers=v["headers"]).json()["history"]
    assigned = confirm(v, pending.json()["id"])
    assert assigned["status"] == "completed", assigned
    ownership_response = v["client"].get(completion_url + "/gap-ownership", headers=v["headers"])
    assert ownership_response.status_code == 200, ownership_response.text
    ownership = ownership_response.json()
    assert len(ownership["history"]) == 1
    assert all(gap["ownership_status"] == "confirmed" and gap["resolution_status"] == "unresolved"
               and gap["owner_actor_id"] == v["owner"]["id"] for gap in ownership["gaps"])
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(assigned["id"], v["project_id"]) == ownership
    assert v["client"].get(completion_url, headers=v["headers"]).json() == completion
    assert v["client"].get(f"/v1/agent-goals/{final['id']}", headers=v["headers"]).json() == final
    assert tuple(calls) == before
    assigned_receipt = assigned["result"]["build_gap_ownership"]
    owned_response = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "tool_id": COMPLETION_READ_TOOL, "conversation_id": final["conversation_id"],
        "input": {"project_id": v["project_id"], "investigation_revision_id": saved["revision_id"],
            "investigation_revision_hash": saved["revision_hash"], "expected_goal": final, "analysis_policy": "committed_build",
            "ownership_pin": {key: assigned_receipt[key] for key in
                ("completion_invocation_id", "completion_report_hash", "revision_id", "revision_hash")}}})
    assert owned_response.status_code == 200 and owned_response.json()["status"] == "completed", owned_response.text
    owned_command = owned_response.json()
    owned_url = f"/v1/projects/{v['project_id']}/system-image/build-completions/{owned_command['id']}"
    owned_read = v["client"].get(owned_url, headers=v["headers"])
    assert owned_read.status_code == 200, owned_read.text
    owned = owned_read.json()
    assert owned["schema"] == "nasus.image-build-completion.v3" and owned["state"] == "blocked"
    assert owned["ownership"]["revision_id"] == ownership["revision_id"]
    assert "gap_ownership_unassigned" not in owned["blockers"]
    assert {"code_analysis_partial", "full_plan_budget_unverified", "critical_conflicts_unverified"} <= set(owned["blockers"])
    assert all(gap["owner_actor_id"] == v["owner"]["id"] and gap["resolution_status"] == "unresolved" for gap in owned["gaps"])
    for key in ("source_scans", "code_analyses", "build_lineages", "budget", "readiness", "goal_checkpoint"):
        assert owned[key] == completion[key]
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(owned_command["id"], v["project_id"]) == owned
    assert v["client"].get(owned_url, headers=v["headers"]).json() == owned
    assert v["client"].get(completion_url, headers=v["headers"]).json() == completion
    assert v["client"].get(f"/v1/agent-goals/{final['id']}", headers=v["headers"]).json() == final
    assert tuple(calls) == before
    live_access_metrics = {
        "original_v2": compare_completion_replays(v, completion_url, completion, monkeypatch),
        "owned_v3": compare_completion_replays(v, owned_url, owned, monkeypatch),
    }
    assert tuple(calls) == before
    assert v["client"].get(f"/v1/agent-goals/{final['id']}", headers=v["headers"]).json() == final
    limitations = ["no external model calls", "no target execution", "not business gold",
        "bounded evidence sample, not structural or business coverage"]
    tool_budget, tool_consumption = BuildToolBudgetRepository().inspect(final["id"])
    assert len(tool_consumption) == len(steps)
    assert {item["invocation_id"] for item in tool_consumption} == {step["tool_invocation_id"] for step in steps}
    assert tool_budget.max_tool_calls == 80
    assert BuildToolBudgetRepository().inspect(final["id"]) == (tool_budget, tool_consumption)
    if storage_evidence["backend"] == "local_isolated_adapter":
        limitations.insert(0, "local isolated object adapter, not MinIO deployment test")
    report = {"entry": entry, "source_git_revision": git_revision, "native": native_report,
        "storage": storage_evidence,
        "live_access_read_metrics": live_access_metrics,
        "cumulative_tool_work": {"budget": asdict(tool_budget), "consumptions": tool_consumption,
            "used": len(tool_consumption), "model_cost_verified": False, "full_plan_accounting_verified": False},
        "native_index_calls": calls.count("index_repository"), "native_negotiations": calls.count("mcp/negotiate"),
        "goal_id": goal["id"], "goal_state": final["pause_reason"], "investigation": saved,
        "completion_assessment": completion, "completion_receipt": receipt,
        "gap_ownership": ownership, "gap_ownership_receipt": assigned["result"]["build_gap_ownership"],
        "owned_completion_assessment": owned, "owned_completion_receipt": owned_command["result"]["build_completion"],
        "independent_confirmation_channel": confirmation_channel,
        "resume_control": resume_control,
        "canonical_tool_ids": [step["selected_tool_id"] for step in steps], "replay_started_provider": False,
        "limitations": limitations}
    assert report["native_index_calls"] == report["native_negotiations"] == 2
    output = os.getenv("EXWEB_INVESTIGATION_REPORT")
    if output:
        destination = Path(output).resolve()
        if entry != "direct_investigation":
            destination = destination.with_name(destination.stem + "-original-goal" + destination.suffix)
        assert destination.is_relative_to(Path(__file__).resolve().parents[3] / ".nasus/validation")
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
