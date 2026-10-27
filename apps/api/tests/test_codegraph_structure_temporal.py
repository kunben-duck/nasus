"""Real public SDK retry on replacement Temporal workers; no target execution."""
import asyncio
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Replayer, Worker

from apps.api.app.main import app
from apps.api.app.application.system_image.code_index_generations import CodeIndexGenerationApplicationService
from apps.api.app.domain.system_image.evidence import source_lines, text_digest
from apps.api.app.infrastructure.config.agent_runtime_config import TemporalGatewayConfig
from apps.api.app.infrastructure.config.code_graph_config import CodeGraphConfig
from apps.api.app.infrastructure.persistence.code_analysis_models import CodeAnalysisRecord
from apps.api.app.infrastructure.persistence.code_index_generation_models import (
    CodeIndexGenerationRecord, CodeIndexProjectionRecord, CodeIndexWorkerLeaseRecord,
)
from apps.api.app.infrastructure.persistence.code_index_generation_repository import CodeIndexGenerationRepository
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, SSEEventOutboxRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.build_tool_budget_repository import BuildToolBudgetRepository
from apps.api.app.infrastructure.persistence.image_revision_models import ImageObjectMemberRecord
from apps.api.app.infrastructure.persistence.image_publication_models import ImagePublicationHeadRecord
from apps.api.app.infrastructure.persistence.source_evidence_repository import SourceEvidenceRepository
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceBindingRecord
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.structure_build_models import StructureBuildArtifactRecord
from apps.api.app.infrastructure.persistence.structure_job_models import StructureJobRecord, StructureWorkLeaseRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage
from apps.api.app.infrastructure.system_image.code_intelligence_factory import configured_code_graph
from apps.api.app.infrastructure.system_image.code_observation_artifacts import ArchivedCodeObservations
from apps.api.app.infrastructure.system_image.composite_code_intelligence import CompositeCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.evidence_source_reader import ArchivedEvidenceSourceReader
from apps.api.app.infrastructure.system_image.registered_code_intelligence import RegisteredCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.app.infrastructure.workflow.nasus_structure_workflow import NasusStructureBuildWorkflow
from apps.api.app.infrastructure.workflow.structure_runtime import TemporalStructureRuntime, build_structure_activities
from apps.api.tests.test_codegraph_exweb import exweb_sdk_input
from apps.api.tests.test_codegraph_index_generations import NativeRunner
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_structure_build_api import request, submit, confirm
from apps.api.tests.test_agent_investigation_continuation import replace_graph, resume
from apps.api.tests.test_natural_build_entries_api import send, require_prepared


@pytest.mark.skipif(not os.getenv("TEST_TEMPORAL_ADDRESS"), reason="explicit local Temporal opt-in required")
@pytest.mark.parametrize("entrypoint", ["tool", "natural-agent"])
def test_native_sdk_exweb_retries_original_generation_on_replacement_temporal_worker(
        evidence_api, exweb_sdk_input, monkeypatch, tmp_path, entrypoint):
    v = evidence_api
    source, capture, _, storage, initial, git = exweb_sdk_input
    v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "code", "source_uri": source.source_uri}]})
    v["invoke"]("system_image.sources.ingest")
    manifest = SourceSnapshotRepository().latest_manifest(v["project_id"])
    v["image"] = {**v["image"], "source_manifest": {"manifest_id": manifest.manifest_id}}
    jobs, runner = app.state.container.structure_jobs, NativeRunner()
    extraction = jobs.application.preparation.extraction
    operator = replace(CodeGraphConfig.from_env(), mode="required", provider="codegraph",
        sdk_package_path=initial.config.package_path, sdk_platform_path=initial.config.platform_path,
        sdk_runtime_hash=initial.config.expected_runtime_hash, timeout_seconds=180,
        max_entities=20000, max_relationships=50000)
    graphs = []

    def replace_provider():
        native = configured_code_graph(replace(operator, cache_dir=tmp_path / ("worker-" + str(len(graphs)))),
            max_files=extraction._source_reader.max_files, max_source_bytes=extraction._source_reader.max_bytes)
        native.runner = runner
        graphs.append(native)
        generations = CodeIndexGenerationApplicationService(CodeIndexGenerationRepository(), extraction._source_reader, native)
        monkeypatch.setattr(extraction, "_source_code_intelligence", RegisteredCodeIntelligenceAdapter(
            CompositeCodeIntelligenceAdapter(TreeSitterCodeIntelligenceAdapter(), native, mode="required"), generations))

    replace_provider()
    runtime = TemporalStructureRuntime(TemporalGatewayConfig(address=os.environ["TEST_TEMPORAL_ADDRESS"],
        task_queue="nasus-sdk-structure-test-" + uuid4().hex))
    monkeypatch.setattr(jobs, "workflow", runtime)
    monkeypatch.setattr(type(runtime), "enabled", property(lambda _: True))
    import apps.api.app.bootstrap as bootstrap
    monkeypatch.setattr(bootstrap, "get_application_container", lambda: app.state.container)
    goal = None
    if entrypoint == "natural-agent":
        replace_graph(monkeypatch, "langgraph_postgres")
        from apps.api.app.store import get_runtime_assembly
        async def reject_model(*args, **kwargs):
            pytest.fail("Source-pinned structural goals must not call a model")
        monkeypatch.setattr(get_runtime_assembly().llm, "generate_reply", reject_model)
        message = "基于代码、需求文档和测试用例构建当前项目的系统画像。"
        conversation = send(v, message)
        goal, payload = require_prepared(v, conversation)
        assert send(v, message)["agent_goals"][0] == goal and not runner.calls
        ident = None
    else:
        payload = request(v)
        ident = submit(v, payload)
    archive = jobs.application.preparation.candidates.artifacts
    put, failed_projections = archive.put, {}

    def interrupted_put(*args, **kwargs):
        value = put(*args, **kwargs)
        if not failed_projections:
            with session_scope() as session:
                rows = session.scalars(select(CodeIndexProjectionRecord).join(CodeIndexGenerationRecord,
                    CodeIndexGenerationRecord.generation_id == CodeIndexProjectionRecord.generation_id).where(
                        CodeIndexGenerationRecord.invocation_id == ident)).all()
                failed_projections.update((row.generation_id, row.projection_hash) for row in rows)
            assert len(failed_projections) == 2
            raise OSError("fixture acknowledgement lost after complete SDK projections")
        return value

    monkeypatch.setattr(archive, "put", interrupted_put)
    attempts = []

    async def verify():
        nonlocal ident, payload
        resumed, queued_work = None, None
        if goal is not None:
            resumed = asyncio.create_task(asyncio.to_thread(resume, v, goal["id"], goal))
            for _ in range(200):
                with session_scope() as session:
                    row = session.scalar(select(ToolInvocationRecord).join(StructureJobRecord,
                        StructureJobRecord.invocation_id == ToolInvocationRecord.id).where(
                            ToolInvocationRecord.input_payload["agent_goal_id"].as_string() == goal["id"]))
                    if row is not None:
                        ident = row.id
                        payload = session.get(StructureJobRecord, ident).request_payload.copy()
                        break
                assert not resumed.done(), "Original AgentGoal stopped before structural dispatch"
                await asyncio.sleep(.05)
            assert ident is not None and not resumed.done()
            response = await asyncio.to_thread(v["client"].get, f"/v1/tool-invocations/{ident}", headers=v["headers"])
            assert response.status_code == 200, response.text
            queued = response.json()
            queued_work = BuildToolBudgetRepository().inspect(goal["id"])
            assert sum(item["invocation_id"] == ident for item in queued_work[1]) == 1
        else:
            queued = await asyncio.to_thread(confirm, v, ident)
        assert queued["status"] == "running" and queued["result"] is None and not runner.calls
        with session_scope() as session:
            original_input = session.get(ToolInvocationRecord, ident).input_payload.copy()
            assert session.get(StructureJobRecord, ident).request_payload == payload
        # Recovery must read the confirmed archive, not a newer mutable source head.
        v["path"].write_text("class ChangedAfterConfirmation:\n    pass\n")
        await asyncio.to_thread(v["invoke"], "system_image.sources.ingest")
        assert SourceSnapshotRepository().latest_manifest(v["project_id"]).manifest_id != manifest.manifest_id
        v["path"].unlink()
        run, fail = build_structure_activities()
        first_failure = asyncio.Event()

        @activity.defn(name="run_structure_build")
        async def observed_run(invocation_id: str):
            attempts.append(activity.info().attempt)
            try:
                return await run(invocation_id)
            except Exception:
                first_failure.set()
                raise

        client = await Client.connect(os.environ["TEST_TEMPORAL_ADDRESS"])
        handle = client.get_workflow_handle("nasus-structure-build:" + ident)
        async with Worker(client, task_queue=runtime.task_queue, workflows=[NasusStructureBuildWorkflow],
                activities=[observed_run, fail], max_concurrent_activities=1):
            await asyncio.wait_for(first_failure.wait(), 180)
        assert attempts == [1] and len(runner.calls) == 2
        assert not list(graphs[0].config.cache_dir.iterdir())
        with session_scope() as session:
            assert session.get(StructureBuildArtifactRecord, ident) is None
            assert session.get(ToolInvocationRecord, ident).status == "running"
            for generation_id in failed_projections:
                lease = session.get(CodeIndexWorkerLeaseRecord, generation_id)
                assert lease.epoch == 1 and lease.owner_id is None
        replace_provider()
        assert graphs[0] is not graphs[1]
        async with Worker(client, task_queue=runtime.task_queue, workflows=[NasusStructureBuildWorkflow],
                activities=[observed_run, fail], max_concurrent_activities=1):
            assert await asyncio.wait_for(handle.result(), 180) == "completed"
            history = await handle.fetch_history()
        built = None
        if resumed is not None:
            built = await asyncio.wait_for(resumed, 10)
            assert built["id"] == goal["id"] and built["pause_reason"] == "structural_candidate_review", built
            structural_steps = [step for step in built["steps"] if step["phase"] == "acting"
                and step["selected_tool_id"] == "system_image.build.structure"]
            assert len(structural_steps) == 1 and structural_steps[0]["tool_invocation_id"] == ident
            assert BuildToolBudgetRepository().inspect(goal["id"]) == queued_work
        before = len(runner.calls)
        replay = await Replayer(workflows=[NasusStructureBuildWorkflow]).replay_workflow(history)
        assert replay.replay_failure is None and len(runner.calls) == before
        assert await runtime.start(ident) is False
        assert await jobs.run(ident) == "completed" and len(runner.calls) == before
        if goal is not None:
            assert BuildToolBudgetRepository().inspect(goal["id"]) == queued_work
        with session_scope() as session:
            assert session.get(ToolInvocationRecord, ident).input_payload == original_input
            assert session.get(StructureWorkLeaseRecord, ident).epoch == 2
            artifact = session.get(StructureBuildArtifactRecord, ident)
            assert artifact.plan_id == payload["plan_id"] and artifact.plan_digest == payload["plan_digest"]
            assert session.get(ImagePublicationHeadRecord, (v["project_id"], payload["target_baseline_id"])) is None
            assert len(session.scalars(select(AuditEventRecord).where(AuditEventRecord.tool_invocation_id == ident,
                AuditEventRecord.action == "tool.invocation.completed")).all()) == 1
            assert len(session.scalars(select(SSEEventOutboxRecord).where(
                SSEEventOutboxRecord.event_type == "system_image.build.structure.completed",
                SSEEventOutboxRecord.entity_id == payload["plan_id"])).all()) == 1
            rows = session.scalars(select(CodeIndexProjectionRecord).join(CodeIndexGenerationRecord,
                CodeIndexGenerationRecord.generation_id == CodeIndexProjectionRecord.generation_id).where(
                    CodeIndexGenerationRecord.invocation_id == ident)).all()
            assert {row.generation_id: row.projection_hash for row in rows} == failed_projections
            generations = session.scalars(select(CodeIndexGenerationRecord).join(SourceBindingRecord,
                SourceBindingRecord.binding_id == CodeIndexGenerationRecord.binding_id).where(
                    CodeIndexGenerationRecord.invocation_id == ident)).all()
            assert len(generations) == 2
            pins = [CodeIndexGenerationRepository._pin(row) for row in generations]
            exweb = next(pin for pin in pins if session.get(SourceBindingRecord, pin.binding_id).external_identity == source.source_uri)
            members = session.scalars(select(ImageObjectMemberRecord).where(
                ImageObjectMemberRecord.project_id == v["project_id"],
                ImageObjectMemberRecord.image_revision_id == artifact.image_revision_id)).all()
            reports = session.scalars(select(CodeAnalysisRecord).where(CodeAnalysisRecord.project_id == v["project_id"],
                CodeAnalysisRecord.source_revision_id == exweb.source_revision_id)).all()
            archived_reports = [(row.analysis_id, row.payload) for row in reports]
        statuses = [CodeIndexGenerationRepository().status(pin) for pin in pins]
        assert all(status.epoch == 2 and status.worker_state == "none" for status in statuses)
        assert all(status.protocol.schema == "nasus.code-provider-sdk-contract.v1" for status in statuses)
        status = next(status for status in statuses if status.pin == exweb)
        assert status.entity_count == 526 and status.relationship_count == 580
        header, ref, _ = app.state.container.image_revisions.repository.get(v["project_id"], artifact.image_revision_id)
        frozen = app.state.container.image_revisions.artifacts.read(v["project_id"], ref, header.artifact_hash)
        assert header.manifest_id == manifest.manifest_id
        assert "Orders" in str(frozen) and "ChangedAfterConfirmation" not in str(frozen)
        reader, evidence_repository = ArchivedEvidenceSourceReader(storage), SourceEvidenceRepository()
        verified_spans = 0
        with reader.verified_read_session():
            for member in members:
                assert member.kind == "code_entity" and member.evidence_ids
                for target in evidence_repository.get_many(v["project_id"], tuple(member.evidence_ids)):
                    evidence = target.evidence
                    assert evidence.source_revision_id == member.source_revision_id
                    data = reader.read(target)
                    lines = source_lines(data.decode("utf-8"))
                    assert text_digest("".join(lines[evidence.locator.start_line - 1:evidence.locator.end_line])) == evidence.snippet_hash
                    verified_spans += 1
        assert archived_reports and verified_spans > 0
        native_records = []
        for analysis_id, report in archived_reports:
            body = ArchivedCodeObservations(ObjectStorage()).read(report)
            for query in body["native_queries"]:
                if query["provider"] == "codegraph":
                    envelope = json.loads(query["response_json"])
                    assert envelope["schema"] == "nasus.codegraph-sdk-projection.v2"
                    assert len(envelope["nodes"]) == 1440 and len(envelope["edges"]) == 1962
                    native_records.append({"analysis_id": analysis_id, "artifact_hash": report["observation_archive"]["artifact_hash"]})
        assert native_records
        goal_report = None
        if built is not None:
            original_steps = [step for step in built["steps"] if step["phase"] == "acting"]
            replace_graph(monkeypatch, "langgraph_postgres")
            pending = await asyncio.to_thread(resume, v, goal["id"], built)
            assert pending["id"] == goal["id"] and pending["pause_reason"] == "waiting_confirmation"
            investigation = next(step for step in pending["steps"] if step["phase"] == "acting"
                and step["selected_tool_id"] == "system_image.build.investigate")
            assert investigation["tool_input_payload"]["image_revision_id"] == artifact.image_revision_id
            command = v["client"].get(f"/v1/tool-invocations/{investigation['tool_invocation_id']}", headers=v["headers"])
            assert command.status_code == 200 and command.json()["status"] == "waiting_confirmation"
            replace_graph(monkeypatch, "langgraph_postgres")
            final = await asyncio.to_thread(resume, v, goal["id"], pending)
            assert final["id"] == goal["id"] and final["pause_reason"] == "build_completion_review", final
            assert final["model_calls_used"] == 0
            final_steps = [step for step in final["steps"] if step["phase"] == "acting"]
            assert original_steps[-1]["selected_tool_id"] == "system_image.build.structure"
            assert original_steps[-1]["status"] == "blocked" and original_steps[-1]["decision"] == "pause"
            consumed_review = {**original_steps[-1], "status": "completed", "decision": "continue",
                "decision_rationale": "Continue the same goal with independently confirmed evidence investigation."}
            assert final_steps[:len(original_steps)] == [*original_steps[:-1], consumed_review]
            replayed = await asyncio.to_thread(resume, v, goal["id"], final)
            assert replayed == final and len(runner.calls) == before
            budget, consumptions = BuildToolBudgetRepository().inspect(goal["id"])
            assert consumptions[:len(queued_work[1])] == queued_work[1]
            assert len({item["invocation_id"] for item in consumptions}) == len(consumptions)
            with session_scope() as session:
                assert session.get(ImagePublicationHeadRecord, (v["project_id"], payload["target_baseline_id"])) is None
            goal_report = {"goal_id": goal["id"], "plan_id": payload["plan_id"],
                "structure_invocation_id": ident, "pause_reason": final["pause_reason"],
                "graph": "langgraph_postgres", "goal_workflow": "local_not_temporal",
                "structure_workflow": "real_temporal", "independent_investigation_consent": True,
                "model_calls": final["model_calls_used"], "tool_budget": asdict(budget),
                "tool_consumptions": list(consumptions), "retry_consumed_again": False,
                "completion_replay_changed_checkpoint": False, "publication_created": False}
        return {"generation": asdict(exweb), "status": asdict(status), "verified_member_spans": verified_spans,
            "image_member_count": len(members), "native_observation_archives": native_records,
            "entrypoint": entrypoint, "original_goal": goal_report}

    report = asyncio.run(verify())
    assert attempts == [1, 2] and len(runner.calls) == 4
    assert all(call["returncode"] == 0 and not Path(call["cwd"]).exists() for call in runner.calls)
    assert all(not list(graph.config.cache_dir.iterdir()) for graph in graphs)
    assert git("rev-parse", "HEAD") == capture.snapshot.external_revision and not git("status", "--porcelain")
    output = os.environ.get("EXWEB_CODEGRAPH_TEMPORAL_REPORT")
    if output:
        path = Path(output)
        if goal is not None:
            path = path.with_name(path.stem + "-natural-agent" + path.suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        assert not path.exists()
        path.write_text(json.dumps({"schema": "nasus.exweb-sdk-temporal-replacement.v1",
            "source_revision": capture.snapshot.external_revision, "source_files": 126, "source_bytes": 180868,
            **report, "temporal_attempts": attempts, "native_preparations": len(runner.calls),
            "workers_replaced": True, "replacement_scope": "graceful_temporal_worker_objects_not_os_process_kill",
            "original_source_and_confirmation_retained": True, "projection_identical_after_retry": True,
            "history_replay_started_provider": False, "target_executed": False, "external_model_called": False,
            "business_gold": False, "production_default_changed": False,
            "storage": "isolated_postgresql_and_private_minio"}, indent=2) + "\n")
