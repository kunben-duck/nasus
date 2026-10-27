"""Real Temporal retry and archived exweb; no target code or external LLM runs."""
import asyncio
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest
from sqlalchemy import select
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Replayer, Worker

from apps.api.app.main import app
from apps.api.app.application.system_image.code_index_generations import CodeIndexGenerationApplicationService
from apps.api.app.infrastructure.config.agent_runtime_config import TemporalGatewayConfig
from apps.api.app.infrastructure.config.code_graph_config import CodeGraphConfig
from apps.api.app.infrastructure.persistence.code_index_generation_models import CodeIndexGenerationRecord, CodeIndexProjectionRecord
from apps.api.app.infrastructure.persistence.code_index_generation_repository import CodeIndexGenerationRepository
from apps.api.app.infrastructure.persistence.build_tool_budget_repository import BuildToolBudgetRepository
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceBindingRecord
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.structure_build_models import StructureBuildArtifactRecord
from apps.api.app.infrastructure.persistence.structure_job_models import StructureJobRecord, StructureWorkLeaseRecord
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, SSEEventOutboxRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import CodebaseMemoryCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.code_graph_process import CodeGraphProcessRunner
from apps.api.app.infrastructure.system_image.composite_code_intelligence import CompositeCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.registered_code_intelligence import RegisteredCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.app.infrastructure.workflow.nasus_structure_workflow import NasusStructureBuildWorkflow
from apps.api.app.infrastructure.workflow.structure_runtime import TemporalStructureRuntime, build_structure_activities
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_structure_build_api import request, submit, confirm
from apps.api.tests.test_agent_build_plan_api import goal_request
from apps.api.tests.exweb_structural_evidence import verify_exweb_structural_evidence
from apps.api.app.application.system_image.build_plan_queries import READ_BUILD_PLAN_TOOL


@pytest.mark.skipif(not os.getenv("TEST_TEMPORAL_ADDRESS") or not os.getenv("EXWEB_CODE_CONTROL_SOURCE"),
    reason="requires explicitly enabled Temporal and a fixed exweb checkout")
@pytest.mark.parametrize("entrypoint", ["tool", "agent"])
def test_real_temporal_retries_original_exweb_work_and_replays_without_provider(evidence_api, monkeypatch, tmp_path, entrypoint):
    v = evidence_api
    root = Path(os.environ["EXWEB_CODE_CONTROL_SOURCE"]).resolve()
    revision = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True).stdout.strip()
    assert revision == "fe5827f6b76f77ef34918d8b452ee823142332dc"
    assert not subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
        capture_output=True, text=True, check=True).stdout
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
    jobs = app.state.container.structure_jobs
    extraction = jobs.application.preparation.extraction
    generations = CodeIndexGenerationApplicationService(CodeIndexGenerationRepository(), extraction._source_reader, native)
    monkeypatch.setattr(extraction, "_source_code_intelligence", RegisteredCodeIntelligenceAdapter(
        CompositeCodeIntelligenceAdapter(TreeSitterCodeIntelligenceAdapter(), native, mode="required"), generations))
    runtime = TemporalStructureRuntime(TemporalGatewayConfig(address=os.environ["TEST_TEMPORAL_ADDRESS"],
        task_queue="nasus-structure-exweb-test-" + uuid4().hex))
    monkeypatch.setattr(jobs, "workflow", runtime)
    monkeypatch.setattr(type(runtime), "enabled", property(lambda _: True))
    import apps.api.app.bootstrap as bootstrap
    monkeypatch.setattr(bootstrap, "get_application_container", lambda: app.state.container)
    payload = request(v)
    goal_id = None
    if entrypoint == "agent":
        from apps.api.app.application.agent.graph import LangGraphAgentGraphRuntime
        from apps.api.app.infrastructure.config.agent_runtime_config import LangGraphGatewayConfig
        from apps.api.app.infrastructure.workflow.langgraph_agent_gateway import LangGraphAgentLoopGateway
        from apps.api.app.store import get_runtime_assembly
        assembly = get_runtime_assembly()
        gateway = LangGraphAgentLoopGateway(assembly.agent_application_ports.graph_state,
            assembly.agent_goal_state_machine, assembly.agent_goal_plan_compiler,
            config=LangGraphGatewayConfig(graph_name="structure-temporal-agent-test", checkpoint_backend="postgres",
                database_url=os.environ["NASUS_DATABASE_URL"]))
        monkeypatch.setattr(assembly.agent_loop_runtime, "graph_runtime", LangGraphAgentGraphRuntime(gateway))
        response = goal_request(v, payload, [(READ_BUILD_PLAN_TOOL, {"project_id": v["project_id"], "plan_id": payload["plan_id"]}),
            ("system_image.build.structure", payload)])
        assert response.status_code == 200, response.text
        goal = response.json()
        assert goal["status"] == "paused" and goal["pause_reason"] == "waiting_confirmation", goal
        goal_id = goal["id"]
        ident = next(step["tool_invocation_id"] for step in goal["steps"]
            if step["phase"] == "acting" and step["selected_tool_id"] == "system_image.build.structure")
        limited = v["client"].patch(f"/v1/agent-goals/{goal_id}/budget", headers=v["headers"],
            json={"max_runtime_seconds": 180})
        assert limited.status_code == 200, limited.text
    else:
        ident = submit(v, payload)
    archive = jobs.application.preparation.candidates.artifacts
    put = archive.put
    failed_projections = []

    def interrupted_put(*args, **kwargs):
        value = put(*args, **kwargs)
        if not failed_projections:
            with session_scope() as session:
                rows = session.scalars(select(CodeIndexProjectionRecord).join(CodeIndexGenerationRecord,
                    CodeIndexGenerationRecord.generation_id == CodeIndexProjectionRecord.generation_id).where(
                        CodeIndexGenerationRecord.invocation_id == ident)).all()
                failed_projections.extend((row.generation_id, row.projection_hash) for row in rows)
            assert len(failed_projections) == 2 and all(digest for _, digest in failed_projections)
            raise OSError("fixture archive acknowledgement lost after full native projection")
        return value

    monkeypatch.setattr(archive, "put", interrupted_put)
    attempts = []
    failures = []
    profile_output = os.environ.get("EXWEB_STRUCTURE_PROFILE_REPORT")
    if profile_output:
        import cProfile
        import io
        import pstats
        import traceback
        execute = jobs.application.execute
        execution_profiles = []

        def profiled_execute(*args, **kwargs):
            profile, output = cProfile.Profile(), io.StringIO()
            execution_profiles.append(profile)
            profile.enable()
            try:
                return execute(*args, **kwargs)
            except BaseException:
                traceback.print_exc(file=output)
                raise
            finally:
                profile.disable()
                pstats.Stats(profile, stream=output).sort_stats("cumtime").print_stats(45)
                path = Path(profile_output)
                path.with_name(path.stem + "-" + entrypoint + "-" + str(len(execution_profiles)) + path.suffix).write_text(output.getvalue())

        monkeypatch.setattr(jobs.application, "execute", profiled_execute)
    job_run = jobs.run
    async def diagnosed_run(invocation_id):
        try:
            return await job_run(invocation_id)
        except Exception as exc:
            failures.append(type(exc).__name__)
            raise
    monkeypatch.setattr(jobs, "run", diagnosed_run)
    run, fail = build_structure_activities()

    @activity.defn(name="run_structure_build")
    async def observed_run(invocation_id: str):
        attempts.append(activity.info().attempt)
        return await run(invocation_id)

    async def verify():
        resumed = None
        queued_tool_work = None
        if goal_id:
            checkpoint = v["client"].get(f"/v1/agent-goals/{goal_id}", headers=v["headers"]).json()
            resumed = asyncio.create_task(asyncio.to_thread(v["client"].post,
                f"/v1/agent-goals/{goal_id}/resume", headers=v["headers"], json={"expected_goal": checkpoint}))
            for _ in range(200):
                with session_scope() as session:
                    registered = session.get(StructureJobRecord, ident) is not None
                if registered:
                    break
                assert not resumed.done(), "Agent stopped before structural dispatch"
                await asyncio.sleep(0.05)
            assert registered and not resumed.done()
            queued = await asyncio.to_thread(v["client"].get, f"/v1/tool-invocations/{ident}", headers=v["headers"])
            assert queued.status_code == 200, queued.text
            queued = queued.json()
            observed_goal = await asyncio.to_thread(v["client"].get, f"/v1/agent-goals/{goal_id}", headers=v["headers"])
            assert observed_goal.status_code == 200 and observed_goal.json()["status"] == "running", observed_goal.text
            queued_tool_work = BuildToolBudgetRepository().inspect(goal_id)
            assert sum(item["invocation_id"] == ident for item in queued_tool_work[1]) == 1
        else:
            queued = await asyncio.to_thread(confirm, v, ident)
        assert queued["status"] == "running" and queued["result"] is None
        assert "index_repository" not in calls
        with session_scope() as session:
            original_input = session.get(ToolInvocationRecord, ident).input_payload.copy()
            assert session.get(StructureJobRecord, ident).request_payload == payload
            assert session.get(StructureBuildArtifactRecord, ident) is None
        # Move the source head before a worker exists; recovery must use the plan's archive.
        v["path"].write_text("class ChangedAfterConfirmation:\n    pass\n")
        await asyncio.to_thread(v["invoke"], "system_image.sources.ingest")
        assert SourceSnapshotRepository().latest_manifest(v["project_id"]).manifest_id != manifest.manifest_id
        v["path"].unlink()
        client = await Client.connect(os.environ["TEST_TEMPORAL_ADDRESS"])
        handle = client.get_workflow_handle("nasus-structure-build:" + ident)
        async with Worker(client, task_queue=runtime.task_queue, workflows=[NasusStructureBuildWorkflow],
                activities=[observed_run, fail], max_concurrent_activities=1):
            assert await asyncio.wait_for(handle.result(), 180) == "completed", failures
            history = await handle.fetch_history()
        if resumed is not None:
            finished = await asyncio.wait_for(resumed, 10)
            assert finished.status_code == 200, finished.text
            goal = finished.json()
            assert goal["status"] == "paused" and goal["pause_reason"] == "structural_candidate_review", goal
            steps = [step for step in goal["steps"] if step["phase"] == "acting"
                and step["selected_tool_id"] == "system_image.build.structure"]
            assert len(steps) == 1 and steps[0]["tool_invocation_id"] == ident
            assert BuildToolBudgetRepository().inspect(goal_id) == queued_tool_work
            with session_scope() as session:
                linked = session.scalars(select(ToolInvocationRecord.id).where(
                    ToolInvocationRecord.tool_id == "system_image.build.structure",
                    ToolInvocationRecord.input_payload["agent_goal_id"].as_string() == goal_id)).all()
                assert linked == [ident]
        before = tuple(calls)
        replay = await Replayer(workflows=[NasusStructureBuildWorkflow]).replay_workflow(history)
        assert replay.replay_failure is None and tuple(calls) == before
        assert await runtime.start(ident) is False
        assert await jobs.run(ident) == "completed" and tuple(calls) == before
        if goal_id:
            assert BuildToolBudgetRepository().inspect(goal_id) == queued_tool_work
        with session_scope() as session:
            assert session.get(ToolInvocationRecord, ident).input_payload == original_input
            assert session.get(StructureWorkLeaseRecord, ident).epoch == 2
            artifact = session.get(StructureBuildArtifactRecord, ident)
            assert artifact.plan_id == payload["plan_id"] and artifact.plan_digest == payload["plan_digest"]
            assert len(session.scalars(select(AuditEventRecord).where(
                AuditEventRecord.tool_invocation_id == ident, AuditEventRecord.action == "tool.invocation.completed")).all()) == 1
            assert len(session.scalars(select(SSEEventOutboxRecord).where(
                SSEEventOutboxRecord.event_type == "system_image.build.structure.completed",
                SSEEventOutboxRecord.entity_id == payload["plan_id"])).all()) == 1
            rows = session.scalars(select(CodeIndexProjectionRecord).join(CodeIndexGenerationRecord,
                CodeIndexGenerationRecord.generation_id == CodeIndexProjectionRecord.generation_id).where(
                    CodeIndexGenerationRecord.invocation_id == ident)).all()
            assert {(row.generation_id, row.projection_hash) for row in rows} == set(failed_projections)
            exweb = session.scalars(select(CodeIndexGenerationRecord).join(SourceBindingRecord,
                SourceBindingRecord.binding_id == CodeIndexGenerationRecord.binding_id).where(
                    CodeIndexGenerationRecord.invocation_id == ident, SourceBindingRecord.external_identity == str(root))).one()
            pin = CodeIndexGenerationRepository._pin(exweb)
            projection = session.get(CodeIndexProjectionRecord, exweb.generation_id)
            report = {"generation": asdict(pin), "projection_hash": projection.projection_hash,
                "entity_count": projection.entity_count, "relationship_count": projection.relationship_count}
        header, ref, _ = app.state.container.image_revisions.repository.get(v["project_id"], artifact.image_revision_id)
        frozen = app.state.container.image_revisions.artifacts.read(v["project_id"], ref, header.artifact_hash)
        assert header.manifest_id == manifest.manifest_id
        assert "Orders" in str(frozen) and "ChangedAfterConfirmation" not in str(frozen)
        report["structural_evidence"] = await asyncio.to_thread(
            verify_exweb_structural_evidence, v["project_id"], artifact.image_revision_id, str(root))
        report["cumulative_tool_work"] = ({"budget": asdict(queued_tool_work[0]),
            "consumptions": list(queued_tool_work[1]), "canonical_replay_consumed_again": False,
            "model_cost_verified": False, "full_plan_accounting_verified": False} if queued_tool_work else None)
        return report

    report = asyncio.run(verify())
    assert failures == ["OSError"] and attempts == [1, 2]
    assert calls.count("index_repository") == 4 and calls.count("mcp/negotiate") == 4
    assert report["entity_count"] > 500 and report["relationship_count"] > 1000
    assert not list((tmp_path / "native").rglob("*.db"))
    output = os.environ.get("EXWEB_STRUCTURE_JOB_REPORT")
    if output:
        path = Path(output)
        path = path.with_name(path.stem + "-" + entrypoint + path.suffix)
        path.write_text(json.dumps({"schema": "nasus.exweb-structure-job.v1", "git_revision": revision,
            "entrypoint": entrypoint, "agent_goal_id": goal_id,
            "agent_waited_for_queued_tool": entrypoint == "agent",
            "agent_retained_structural_review_gate": entrypoint == "agent",
            **report, "temporal_attempts": attempts, "worker_epochs": [1, 2], "projection_identical_after_retry": True,
            "native_index_calls": calls.count("index_repository"), "native_negotiations": calls.count("mcp/negotiate"),
            "canonical_invocation_reused": True, "original_confirmation_unchanged": True,
            "history_replay_called_provider": False, "target_executed": False, "external_model_called": False,
            "business_gold": False, "object_storage": report["structural_evidence"]["storage_backend"]}, indent=2) + "\n")
