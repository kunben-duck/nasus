"""Exercise a real enriched exweb phase, not merely saving a revised draft."""
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from sqlalchemy import select

from apps.api.app.main import app
from apps.api.app.store import get_runtime_assembly
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.domain.agent.runtime_models import AgentGoalProposal
from apps.api.app.application.system_image.code_index_generations import CodeIndexGenerationApplicationService
from apps.api.app.infrastructure.config.code_graph_config import CodeGraphConfig
from apps.api.app.infrastructure.persistence.code_index_generation_repository import CodeIndexGenerationRepository
from apps.api.app.infrastructure.persistence.code_index_generation_models import CodeIndexGenerationRecord, CodeIndexProjectionRecord
from apps.api.app.infrastructure.persistence.code_analysis_models import CodeAnalysisRecord
from apps.api.app.infrastructure.persistence.document_projection_models import SourceDocumentRevisionRecord
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.image_revision_models import ImageObjectMemberRecord
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceBindingRecord
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.persistence.build_tool_budget_repository import BuildToolBudgetRepository
from apps.api.app.infrastructure.system_image.code_graph_process import CodeGraphProcessRunner
from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import CodebaseMemoryCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.composite_code_intelligence import CompositeCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.registered_code_intelligence import RegisteredCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_agent_investigation_continuation import replace_graph, start_structure, resume
from apps.api.tests.test_build_plan_revision_api import body, prepare, confirm, history
from apps.api.tests.test_image_plan_phase_api import activation, prepare_phase, phases, current_goal
from apps.api.tests.exweb_storage_evidence import verify_exweb_storage
from apps.api.tests.exweb_structural_evidence import verify_exweb_structural_evidence
from apps.api.tests.exweb_projection_dependencies import verify_projection_dependencies
from apps.api.tests.test_targeted_build_intent_api import fixed_request
from apps.api.tests.test_saved_build_intent_entries_api import create as saved_entry, require_initial, send_saved_chat
from apps.api.tests.test_natural_build_entries_api import send as send_natural_chat, require_prepared
from apps.api.tests.test_source_build_wait_api import fresh_project


def require_structural_review(goal, failures=()):
    diagnostics = {"goal_id": goal["id"], "status": goal["status"], "pause_reason": goal["pause_reason"]}
    if goal["pause_reason"] != "structural_candidate_review":
        diagnostics["structural_failures"] = list(failures)
        ids = [step["tool_invocation_id"] for step in goal["steps"] if step.get("tool_invocation_id")]
        with session_scope() as session:
            diagnostics["invocations"] = [{"tool_id": item.tool_id, "status": item.status, "summary": item.summary}
                for item in session.scalars(select(ToolInvocationRecord).where(ToolInvocationRecord.id.in_(ids)))]
    assert goal["pause_reason"] == "structural_candidate_review", json.dumps(diagnostics, ensure_ascii=False)


@pytest.mark.skipif(not os.getenv("EXWEB_CODE_CONTROL_SOURCE"), reason="requires explicit clean fixed exweb checkout")
@pytest.mark.parametrize("targeted,entry", [(False, "explicit"), (True, "explicit"), (True, "guided"), (True, "chat"),
    (True, "durable"), (True, "natural"), (True, "waiting")],
    ids=["legacy", "targeted", "guided", "chat", "durable-start-receipt", "natural-chat", "waiting-inputs-chat"])
def test_fixed_exweb_enriched_sources_execute_under_new_consent_on_original_goal(evidence_api, monkeypatch, tmp_path, targeted, entry):
    v = evidence_api
    root = Path(os.environ["EXWEB_CODE_CONTROL_SOURCE"]).resolve()
    revision = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    assert revision == "fe5827f6b76f77ef34918d8b452ee823142332dc"
    assert not subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout
    missing_inputs_goal = None
    if entry == "waiting":
        v = fresh_project(v)
        def invoke(tool, payload=None):
            response = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
                "conversation_id": v["conversation"].json()["id"], "tool_id": tool,
                "input": {"project_id": v["project_id"], **(payload or {})}})
            assert response.status_code == 200 and response.json()["status"] == "completed", response.text
        v["invoke"] = invoke
        missing_inputs_goal = send_natural_chat(v, "Build the system image")["agent_goals"][0]
        assert missing_inputs_goal["pause_reason"] == "missing_captured_code"
        assert missing_inputs_goal["active_started_at"] is None and missing_inputs_goal["active_runtime_ms"] >= 0
    v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "code", "source_uri": str(root)}]})
    v["invoke"]("system_image.sources.ingest")
    initial_manifest = SourceSnapshotRepository().latest_manifest(v["project_id"])
    v["image"] = {**v["image"], "source_manifest": {"manifest_id": initial_manifest.manifest_id}}
    calls, executable_commands = [], {}

    class Recorder(CodeGraphProcessRunner):
        def run(self, args, **kwargs):
            command = "mcp/negotiate" if kwargs.get("dialogue") is not None else args[2] if len(args) > 2 else "--version"
            executable = Path(args[0])
            assert executable.parent.name.startswith("nasus-cbm-exec-")
            assert executable.stat().st_mode & 0o777 == 0o500
            if executable not in executable_commands:
                assert native.projection_fingerprint(executable=executable) == native.projection_fingerprint()
            executable_commands.setdefault(executable, []).append(command)
            calls.append(command)
            return super().run(args, **kwargs)

    native = CodebaseMemoryCodeIntelligenceAdapter(replace(CodeGraphConfig.from_env(), mode="required",
        binary=str(Path(__file__).resolve().parents[3] / ".venv/bin/codebase-memory-mcp"), cache_dir=tmp_path / "native",
        timeout_seconds=180, max_entities=20000, max_relationships=50000), process_runner=Recorder())
    dependency_proof = verify_projection_dependencies(native)
    extraction = app.state.container.structure_builds.preparation.extraction
    generations = CodeIndexGenerationApplicationService(CodeIndexGenerationRepository(), extraction._source_reader, native)
    monkeypatch.setattr(extraction, "_source_code_intelligence", RegisteredCodeIntelligenceAdapter(
        CompositeCodeIntelligenceAdapter(TreeSitterCodeIntelligenceAdapter(), native, mode="required"), generations))
    structural_failures = []
    execute = app.state.container.structure_builds.execute

    def observe_execute(*args, **kwargs):
        try:
            return execute(*args, **kwargs)
        except Exception as exc:
            structural_failures.append({"exception": type(exc).__name__, "message": str(exc)})
            raise

    monkeypatch.setattr(app.state.container.structure_builds, "execute", observe_execute)
    replace_graph(monkeypatch, "langgraph_postgres")
    selected = fixed_request(v)[0] if targeted and entry not in {"natural", "waiting"} else None
    durable_replays = 0
    if entry == "explicit":
        fixed, original = start_structure(v, authorized=True, fixed=selected)
    else:
        fixed = selected
        if entry == "guided":
            response = saved_entry(v, fixed)
            assert response.status_code == 200, response.text
            initial = response.json()
            require_initial(initial, fixed)
        elif entry == "chat":
            initial = send_saved_chat(v, fixed)
        elif entry == "natural":
            initial, fixed = require_prepared(v, send_natural_chat(v,
                "Build the official system image from code, US docs, and tests"))
        elif entry == "waiting":
            initial, fixed = require_prepared(v, send_natural_chat(v, "Build the system image"), waited=True)
            assert initial["id"] == missing_inputs_goal["id"]
            assert initial["active_runtime_ms"] >= missing_inputs_goal["active_runtime_ms"] and initial["active_started_at"] is None
            assert missing_inputs_goal["target_refs"][-1] in initial["target_refs"]
        else:
            proposal = AgentGoalProposal(goal_template="system_image_build", title="exweb durable saved intent",
                summary="Fixed repository and target", goal_description="Build without transferring independent consent",
                target_refs=[f"project:{v['project_id']}", f"build_plan:{fixed['plan_id']}", f"build_plan_digest:{fixed['plan_digest']}"])
            loop = get_runtime_assembly().agent_loop_runtime
            with actor_scope(UserProfile.model_validate(v["owner"])):
                first = asyncio.run(loop.start_goal(v["conversation"].json()["id"], proposal, workflow_id="exweb-start-" + v["project_id"]))
                replay = asyncio.run(loop.start_goal(first.conversation_id, proposal, workflow_id=first.workflow_id))
            assert replay == first
            durable_replays += 1
            initial = first.model_dump(mode="json")
            require_initial(initial, fixed)
        assert calls == []  # Preparing either entry is not native provider consent.
        original = resume(v, initial["id"], expected=initial)
        require_structural_review(original, structural_failures)
    old_calls = list(calls)
    old_url = f"/v1/projects/{v['project_id']}/system-image/build-plans/{fixed['plan_id']}"
    old_plan = v["client"].get(old_url, headers=v["headers"]).json()
    if targeted:
        assert old_plan["proposal"]["policy_version"] == "nasus.image-investigation-plan.v3"
    sources = []
    for kind, name in (("us_doc", "exweb-requirements.md"), ("test_asset", "exweb-test-cases.csv")):
        destination = tmp_path / name
        shutil.copyfile(Path(__file__).resolve().parents[3] / "tests/fixtures/system-image" / name, destination)
        sources.append({"source_type": kind, "source_uri": str(destination)})
    v["invoke"]("system_image.sources.register", {"source_specs": sources})
    v["invoke"]("system_image.sources.ingest")
    enriched_manifest = SourceSnapshotRepository().latest_manifest(v["project_id"])
    saved_revision = confirm(v, prepare(v, body(v, fixed, original, enriched_manifest.manifest_id)))
    assert saved_revision["status"] == "completed", saved_revision
    saved_revision, = history(v, fixed, original).json()
    prepared_command = confirm(v, prepare_phase(v, activation(v, fixed, original, saved_revision)))
    assert prepared_command["status"] == "completed", prepared_command
    assert calls == old_calls  # Neither source-enrichment command is execution consent.
    prepared = current_goal(v, original)
    replace_graph(monkeypatch, "langgraph_postgres")
    waiting = resume(v, original["id"], expected=prepared)
    assert waiting["pause_reason"] == "waiting_confirmation" and calls == old_calls
    replace_graph(monkeypatch, "langgraph_postgres")
    enriched = resume(v, original["id"], expected=waiting)
    require_structural_review(enriched, structural_failures)
    assert enriched["active_runtime_ms"] >= original["active_runtime_ms"] and enriched["active_started_at"] is None
    assert enriched["started_at"] == original["started_at"]
    assert enriched["steps"][:len(original["steps"])] == original["steps"]
    assert enriched["model_calls_used"] == 0
    new_structure = next(step for step in enriched["steps"][len(original["steps"]):]
        if step["selected_tool_id"] == "system_image.build.structure")
    new_plan_id = saved_revision["revision"]["plan_id"]
    new_plan = v["client"].get(f"/v1/projects/{v['project_id']}/system-image/build-plans/{new_plan_id}", headers=v["headers"]).json()
    if targeted:
        assert new_plan["proposal"]["intent"]["target"] == old_plan["proposal"]["intent"]["target"]
        assert len(new_plan["proposal"]["intent"]["scope_binding_ids"]) == len(enriched_manifest.members)
    image_id = new_plan["structural_artifacts"][0]["image_revision_id"]
    assert new_plan["execution_authorizations"][0]["goal_id"] == original["id"]
    assert v["client"].get(old_url, headers=v["headers"]).json() == old_plan
    with session_scope() as session:
        generation = session.scalars(select(CodeIndexGenerationRecord).join(SourceBindingRecord,
            SourceBindingRecord.binding_id == CodeIndexGenerationRecord.binding_id).where(
                CodeIndexGenerationRecord.invocation_id == new_structure["tool_invocation_id"],
                SourceBindingRecord.external_identity == str(root))).one()
        projection = session.get(CodeIndexProjectionRecord, generation.generation_id)
        native_projection = {"entities": projection.entity_count, "relationships": projection.relationship_count,
                             "projection_hash": projection.projection_hash}
        kinds = session.scalars(select(SourceDocumentRevisionRecord.kind).join(ImageObjectMemberRecord,
            ImageObjectMemberRecord.document_revision_id == SourceDocumentRevisionRecord.document_revision_id).where(
                ImageObjectMemberRecord.image_revision_id == image_id)).all()
        analyses = session.scalars(select(CodeAnalysisRecord).where(
            CodeAnalysisRecord.project_id == v["project_id"],
            CodeAnalysisRecord.source_revision_id == generation.source_revision_id)).all()
        identity_gaps = []
        for analysis in analyses:
            assert snapshot_digest(analysis.payload) == analysis.report_hash
            metadata = analysis.payload.get("projection", {})
            for provider in metadata.get("providers", []):
                if provider["capabilities"]["provider"] != "codebase-memory":
                    continue
                gaps = {gap["reason"]: gap["count"] for gap in provider["gaps"]
                        if gap["reason"] in {"unresolved_symbol_identity", "ambiguous_symbol_identity"}}
                assert metadata["status"] == "partial" and gaps and sum(gaps.values()) > 0
                assert provider["entity_count"] == projection.entity_count
                identity_gaps.append({"analysis_id": analysis.analysis_id, "report_hash": analysis.report_hash,
                    "projection_status": metadata["status"], "observed_entities": provider["entity_count"], "gaps": gaps})
        assert identity_gaps, "unregistered native identities must remain explicit in the persisted analysis report"
    assert native_projection["entities"] == 755 and native_projection["relationships"] == 1425
    assert {"requirement", "acceptance_criterion", "test_case"} <= set(kinds)
    storage = verify_exweb_storage(v["project_id"], image_id)
    structural_evidence = verify_exweb_structural_evidence(v["project_id"], image_id, str(root))
    final_calls = list(calls)
    for _ in range(2):
        assert len(phases(v, fixed, enriched).json()) == 1
        assert history(v, fixed, enriched).json() == [saved_revision]
    assert calls == final_calls
    assert len(executable_commands) == final_calls.count("index_repository")
    for executable, commands in executable_commands.items():
        assert commands.count("--version") == commands.count("mcp/negotiate") == commands.count("index_repository") == 1
        assert not executable.exists()
    if entry == "durable":
        # The original start cannot confirm the later phase's independent gate.
        with actor_scope(UserProfile.model_validate(v["owner"])):
            replay = asyncio.run(get_runtime_assembly().agent_loop_runtime.start_goal(
                first.conversation_id, proposal, workflow_id=first.workflow_id))
        assert replay.model_dump(mode="json") == enriched and calls == final_calls
        durable_replays += 1
    tool_budget, tool_consumption = BuildToolBudgetRepository().inspect(enriched["id"])
    assert {item["invocation_id"] for item in tool_consumption} == {
        step["tool_invocation_id"] for step in enriched["steps"] if step["phase"] == "acting" and step["selected_tool_id"]
    } | {saved_revision["revision"]["invocation_id"], prepared_command["id"]}
    assert tool_budget.max_tool_calls == 80
    assert BuildToolBudgetRepository().inspect(enriched["id"]) == (tool_budget, tool_consumption)
    report = {"git_revision": revision, "targeted_build_intent": targeted, "agent_entry": entry,
        "plan_policy": old_plan["proposal"]["policy_version"], "goal_id": original["id"], "same_original_goal": True,
        "new_phase_executed": True, "original_steps_and_plan_unchanged": True,
        "cumulative_tool_work": {"budget_hash": tool_budget.digest, "used": len(tool_consumption),
            "max_tool_calls": tool_budget.max_tool_calls, "consumptions": tool_consumption,
            "full_plan_accounting_verified": False},
        "source_manifest_id": enriched_manifest.manifest_id, "image_revision_id": image_id,
        "native_projection": native_projection, "document_member_kinds": sorted(set(kinds)),
        "analysis_identity_gaps": identity_gaps,
        "initial_index_calls": old_calls.count("index_repository"), "initial_mcp_calls": old_calls.count("mcp/negotiate"),
        "enriched_index_calls": final_calls.count("index_repository") - old_calls.count("index_repository"),
        "enriched_mcp_calls": final_calls.count("mcp/negotiate") - old_calls.count("mcp/negotiate"),
        "replay_provider_calls": len(calls) - len(final_calls), "model_calls": enriched["model_calls_used"],
        "native_worker_executable_snapshots": len(executable_commands),
        "each_session_uses_one_verified_executable": True, "executable_snapshots_removed": True,
        "durable_start_readonly_replays": durable_replays,
        "missing_inputs_original_goal_kept": missing_inputs_goal is not None and missing_inputs_goal["id"] == original["id"],
        "active_runtime": {"initial_structure_ms": original["active_runtime_ms"], "enriched_structure_ms": enriched["active_runtime_ms"],
            "paused_interval_settled": enriched["active_started_at"] is None, "first_start_preserved": enriched["started_at"] == original["started_at"]},
        "target_repository_executed": False, "business_gold": False, "storage": storage,
        "structural_evidence": structural_evidence, "projection_dependencies": dependency_proof}
    if os.getenv("EXWEB_PLAN_PHASE_REPORT"):
        base = Path(os.environ["EXWEB_PLAN_PHASE_REPORT"])
        output = base.with_name(f"{base.stem}-{entry if entry != 'explicit' else 'targeted' if targeted else 'legacy'}{base.suffix}")
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
