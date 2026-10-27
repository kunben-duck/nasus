"""Native SDK, three source types and the actual Temporal AgentGoal lifecycle."""
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
from apps.api.app.application.agent.activities import AgentWorkflowActivityApplicationService
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.system_image.code_index_generations import CodeIndexGenerationApplicationService
from apps.api.app.domain.agent.resume_checkpoint import AgentResumeCheckpoint, AgentResumeCheckpointChanged
from apps.api.app.domain.system_image.evidence import source_lines, text_digest
from apps.api.app.infrastructure.config.agent_runtime_config import TemporalGatewayConfig
from apps.api.app.infrastructure.config.code_graph_config import CodeGraphConfig
from apps.api.app.infrastructure.persistence.agent_start_models import AgentGoalStartReceiptRecord
from apps.api.app.infrastructure.persistence.build_tool_budget_repository import BuildToolBudgetRepository
from apps.api.app.infrastructure.persistence.code_index_generation_models import CodeIndexGenerationRecord, CodeIndexProjectionRecord
from apps.api.app.infrastructure.persistence.code_index_generation_repository import CodeIndexGenerationRepository
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, SSEEventOutboxRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.image_publication_models import ImagePublicationHeadRecord
from apps.api.app.infrastructure.persistence.image_revision_models import ImageObjectMemberRecord
from apps.api.app.infrastructure.persistence.source_evidence_repository import SourceEvidenceRepository
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.structure_build_models import StructureBuildArtifactRecord
from apps.api.app.infrastructure.persistence.structure_job_models import StructureJobRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.system_image.code_intelligence_factory import configured_code_graph
from apps.api.app.infrastructure.system_image.composite_code_intelligence import CompositeCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.evidence_source_reader import ArchivedEvidenceSourceReader
from apps.api.app.infrastructure.system_image.registered_code_intelligence import RegisteredCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.app.infrastructure.workflow.agent_goal_workflow_worker import AgentGoalWorkflowActivityService, build_agent_goal_activity_definitions
from apps.api.app.infrastructure.workflow.nasus_agent_goal_workflow import NasusAgentGoalWorkflow
from apps.api.app.infrastructure.workflow.nasus_structure_workflow import NasusStructureBuildWorkflow
from apps.api.app.infrastructure.workflow.structure_runtime import TemporalStructureRuntime, build_structure_activities
from apps.api.app.infrastructure.workflow.temporal_agent_gateway import TemporalClientWorkflowGateway
from apps.api.app.store import get_runtime_assembly
from apps.api.tests.test_agent_investigation_continuation import replace_graph
from apps.api.tests.test_agent_start_receipts_temporal import close_handles
from apps.api.tests.test_codegraph_exweb import exweb_sdk_input
from apps.api.tests.test_codegraph_index_generations import NativeRunner
from apps.api.tests.test_natural_build_entries_api import require_prepared
from apps.api.tests.test_source_evidence_api import evidence_api


@pytest.mark.skipif(not os.getenv("TEST_TEMPORAL_ADDRESS"), reason="explicit local Temporal opt-in required")
def test_native_sdk_three_sources_keep_original_temporal_goal_and_reference_evidence(
        evidence_api, exweb_sdk_input, monkeypatch, tmp_path):
    v = evidence_api
    source, capture, _, storage, initial, git = exweb_sdk_input
    companions = []
    specs = [{"source_type": "code", "source_uri": source.source_uri}]
    for kind, filename in (("us_doc", "exweb-requirements.md"), ("test_asset", "exweb-test-cases.csv")):
        path = tmp_path / filename
        path.write_bytes(Path("tests/fixtures/system-image", filename).read_bytes())
        companions.append(path)
        specs.append({"source_type": kind, "source_uri": str(path)})
    v["invoke"]("system_image.sources.register", {"source_specs": specs})
    v["invoke"]("system_image.sources.ingest")
    manifest = SourceSnapshotRepository().latest_manifest(v["project_id"])
    assert len(manifest.members) == 4 and all(item.status == "captured" for item in manifest.members)
    assert {item.source_type for item in manifest.members} == {"code", "us_doc", "test_asset"}
    v["image"] = {**v["image"], "source_manifest": {"manifest_id": manifest.manifest_id}}
    v["image_url"] = f"/v1/projects/{v['project_id']}/system-image"
    replace_graph(monkeypatch, "langgraph_postgres")
    assembly = get_runtime_assembly()
    state = assembly.agent_application_ports.workflow_state

    async def reject_model(*args, **kwargs):
        pytest.fail("Structural and field-evidence investigation must not call a model")

    monkeypatch.setattr(assembly.llm, "generate_reply", reject_model)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        conversation = assembly.agent_application_ports.loop_state.get_conversation(v["conversation"].json()["id"])
        planned = assembly.saved_build_intents.plan(conversation,
            "Build the official system image from code, US docs, and tests").agent_goal
    activities = AgentWorkflowActivityApplicationService(loop_runtime=assembly.agent_loop_runtime,
        goal_projector=assembly.agent_goal_projection)
    definitions = build_agent_goal_activity_definitions(AgentGoalWorkflowActivityService(
        activity_application_provider=lambda: activities))
    jobs, runner = app.state.container.structure_jobs, NativeRunner()
    extraction = jobs.application.preparation.extraction
    operator = replace(CodeGraphConfig.from_env(), mode="required", provider="codegraph",
        sdk_package_path=initial.config.package_path, sdk_platform_path=initial.config.platform_path,
        sdk_runtime_hash=initial.config.expected_runtime_hash, timeout_seconds=180,
        max_entities=20000, max_relationships=50000)
    graphs = []

    def replace_provider():
        native = configured_code_graph(replace(operator, cache_dir=tmp_path / ("sdk-worker-" + str(len(graphs)))),
            max_files=extraction._source_reader.max_files, max_source_bytes=extraction._source_reader.max_bytes)
        native.runner = runner
        graphs.append(native)
        generations = CodeIndexGenerationApplicationService(CodeIndexGenerationRepository(), extraction._source_reader, native)
        monkeypatch.setattr(extraction, "_source_code_intelligence", RegisteredCodeIntelligenceAdapter(
            CompositeCodeIntelligenceAdapter(TreeSitterCodeIntelligenceAdapter(), native, mode="required"), generations))

    replace_provider()
    config = TemporalGatewayConfig(address=os.environ["TEST_TEMPORAL_ADDRESS"],
        task_queue="nasus-sdk-three-source-goal-" + uuid4().hex, query_timeout_seconds=600)
    structure = TemporalStructureRuntime(config)
    monkeypatch.setattr(jobs, "workflow", structure)
    monkeypatch.setattr(type(structure), "enabled", property(lambda _: True))
    import apps.api.app.bootstrap as bootstrap
    monkeypatch.setattr(bootstrap, "get_application_container", lambda: app.state.container)
    archive = jobs.application.preparation.candidates.artifacts
    put, failed_projections, attempts = archive.put, {}, []
    structural_id = None

    def interrupted_put(*args, **kwargs):
        value = put(*args, **kwargs)
        if not failed_projections:
            with session_scope() as session:
                rows = session.scalars(select(CodeIndexProjectionRecord).join(CodeIndexGenerationRecord,
                    CodeIndexGenerationRecord.generation_id == CodeIndexProjectionRecord.generation_id).where(
                        CodeIndexGenerationRecord.invocation_id == structural_id)).all()
                failed_projections.update((row.generation_id, row.projection_hash) for row in rows)
            assert len(failed_projections) == 2
            raise OSError("injected lost acknowledgement after native projections and private image put")
        return value

    monkeypatch.setattr(archive, "put", interrupted_put)

    async def verify():
        nonlocal structural_id
        client = await Client.connect(config.address)
        handles, worker_count, building = [], 0, None

        async def factory(_):
            return client

        def goal_gateway():
            return TemporalClientWorkflowGateway(config, client_factory=factory,
                workflow_id_provider=state.workflow_id_for_goal, goal_state_reader=state.get_goal,
                resume_replay_reader=state.is_resume_consumed)

        def goal_worker():
            nonlocal worker_count
            worker_count += 1
            return Worker(client, task_queue=config.task_queue, workflows=[NasusAgentGoalWorkflow], activities=definitions)

        async def resume_goal(goal):
            with actor_scope(UserProfile.model_validate(v["owner"])):
                return await goal_gateway().resume_goal(goal.id,
                    expected_resume=AgentResumeCheckpoint.capture(goal.model_dump(mode="json")))

        try:
            async with goal_worker():
                with actor_scope(UserProfile.model_validate(v["owner"])):
                    started = await goal_gateway().start_goal(conversation.id, planned)
                handle = client.get_workflow_handle(started.workflow_id)
                handles.append(handle)
                original, fixed = require_prepared(v, {"agent_goals": [started.model_dump(mode="json")]})
                with session_scope() as session:
                    receipt = session.scalar(select(AgentGoalStartReceiptRecord).where(
                        AgentGoalStartReceiptRecord.goal_id == started.id))
                    assert receipt.workflow_id == started.workflow_id
                assert not runner.calls
            replace_graph(monkeypatch, "langgraph_postgres")
            async with goal_worker():
                building = asyncio.create_task(resume_goal(started))
                for _ in range(400):
                    with session_scope() as session:
                        row = session.scalar(select(StructureJobRecord).join(ToolInvocationRecord,
                            ToolInvocationRecord.id == StructureJobRecord.invocation_id).where(
                            ToolInvocationRecord.input_payload["agent_goal_id"].as_string() == started.id))
                        if row is not None:
                            structural_id = row.invocation_id
                            break
                    assert not building.done(), "Goal exited before its canonical structure task was dispatched"
                    await asyncio.sleep(.05)
                assert structural_id and not building.done()
                budget_before = BuildToolBudgetRepository().inspect(started.id)
                assert sum(item["invocation_id"] == structural_id for item in budget_before[1]) == 1
                with session_scope() as session:
                    original_input = session.get(ToolInvocationRecord, structural_id).input_payload.copy()
                # Both code and documents change after consent; no later head may replace the plan.
                v["path"].write_text("class LaterSourceHead:\n    pass\n")
                for path in companions:
                    path.write_text("Later unapproved document, not the confirmed input.\n")
                await asyncio.to_thread(v["invoke"], "system_image.sources.ingest")
                assert SourceSnapshotRepository().latest_manifest(v["project_id"]).manifest_id != manifest.manifest_id
                for path in [v["path"], *companions]:
                    path.unlink()
                run, fail = build_structure_activities()
                first_failure = asyncio.Event()

                @activity.defn(name="run_structure_build")
                async def observed_run(invocation_id):
                    attempts.append(activity.info().attempt)
                    try:
                        return await run(invocation_id)
                    except Exception:
                        first_failure.set()
                        raise

                structure_handle = client.get_workflow_handle("nasus-structure-build:" + structural_id)
                async with Worker(client, task_queue=structure.task_queue, workflows=[NasusStructureBuildWorkflow],
                        activities=[observed_run, fail], max_concurrent_activities=1):
                    await asyncio.wait_for(first_failure.wait(), 240)
                assert attempts == [1] and len(runner.calls) == 2
                with session_scope() as session:
                    assert session.get(StructureBuildArtifactRecord, structural_id) is None
                replace_provider()
                async with Worker(client, task_queue=structure.task_queue, workflows=[NasusStructureBuildWorkflow],
                        activities=[observed_run, fail], max_concurrent_activities=1):
                    assert await asyncio.wait_for(structure_handle.result(), 240) == "completed"
                    built = await asyncio.wait_for(building, 30)
                    structure_history = await structure_handle.fetch_history()
                assert built.id == started.id and built.pause_reason == "structural_candidate_review"
                assert BuildToolBudgetRepository().inspect(started.id) == budget_before
                with pytest.raises(AgentResumeCheckpointChanged):
                    await goal_gateway().resume_goal(started.id,
                        expected_resume=AgentResumeCheckpoint.capture(original))
                assert state.get_goal(started.id) == built
                assert BuildToolBudgetRepository().inspect(started.id) == budget_before
            replace_graph(monkeypatch, "langgraph_postgres")
            async with goal_worker():
                pending = await resume_goal(built)
                assert pending.id == started.id and pending.pause_reason == "waiting_confirmation"
                investigation = next(step for step in pending.steps if step.phase == "acting"
                    and step.selected_tool_id == "system_image.build.investigate")
                command = await asyncio.to_thread(v["client"].get,
                    f"/v1/tool-invocations/{investigation.tool_invocation_id}", headers=v["headers"])
                assert command.status_code == 200 and command.json()["status"] == "waiting_confirmation"
                assert await goal_gateway().resume_goal(started.id,
                    expected_resume=AgentResumeCheckpoint.capture(built.model_dump(mode="json"))) == pending
            replace_graph(monkeypatch, "langgraph_postgres")
            async with goal_worker():
                reference_review = await resume_goal(pending)
                assert reference_review.id == started.id and reference_review.pause_reason == "reference_candidate_review"
                reference_step = next(step for step in reference_review.steps if step.phase == "acting"
                    and step.selected_tool_id == "system_image.links.propose_references")
                with actor_scope(UserProfile.model_validate(v["owner"])):
                    reference_command = assembly.tool_invocations_app.get_tool_invocation(reference_step.tool_invocation_id)
                assert reference_command.status == "completed" and reference_step.status == "blocked"
                assert reference_command.input_payload["agent_goal_id"] == started.id
                reference_budget = BuildToolBudgetRepository().inspect(started.id)
                assert reference_command.id in {item["invocation_id"] for item in reference_budget[1]}
                assert await goal_gateway().resume_goal(started.id,
                    expected_resume=AgentResumeCheckpoint.capture(built.model_dump(mode="json"))) == reference_review
                assert BuildToolBudgetRepository().inspect(started.id) == reference_budget
            replace_graph(monkeypatch, "langgraph_postgres")
            async with goal_worker():
                final = await resume_goal(reference_review)
                assert final.id == started.id and final.pause_reason == "build_completion_review"
                assert final.status == "paused" and final.model_calls_used == 0 and final.active_started_at is None
                before = len(runner.calls)
                assert await resume_goal(final) == final
                assert len(runner.calls) == before
                for workflow, history in ((NasusAgentGoalWorkflow, await handle.fetch_history()),
                        (NasusStructureBuildWorkflow, structure_history)):
                    replay = await Replayer(workflows=[workflow]).replay_workflow(history)
                    assert replay.replay_failure is None and len(runner.calls) == before
                assert await jobs.run(structural_id) == "completed" and len(runner.calls) == before
            with session_scope() as session:
                artifact = session.get(StructureBuildArtifactRecord, structural_id)
                image_id = artifact.image_revision_id
                assert artifact.plan_id == fixed["plan_id"] and artifact.plan_digest == fixed["plan_digest"]
                assert session.get(ToolInvocationRecord, structural_id).input_payload == original_input
                assert session.get(ImagePublicationHeadRecord, (v["project_id"], fixed["target_baseline_id"])) is None
                rows = session.scalars(select(CodeIndexProjectionRecord).join(CodeIndexGenerationRecord,
                    CodeIndexGenerationRecord.generation_id == CodeIndexProjectionRecord.generation_id).where(
                        CodeIndexGenerationRecord.invocation_id == structural_id)).all()
                assert {row.generation_id: row.projection_hash for row in rows} == failed_projections
                assert len(session.scalars(select(AuditEventRecord).where(
                    AuditEventRecord.tool_invocation_id == structural_id,
                    AuditEventRecord.action == "tool.invocation.completed")).all()) == 1
                assert len(session.scalars(select(SSEEventOutboxRecord).where(
                    SSEEventOutboxRecord.event_type == "system_image.build.structure.completed",
                    SSEEventOutboxRecord.entity_id == fixed["plan_id"])).all()) == 1
                members = session.scalars(select(ImageObjectMemberRecord).where(
                    ImageObjectMemberRecord.image_revision_id == image_id)).all()
            header, ref, _ = app.state.container.image_revisions.repository.get(v["project_id"], image_id)
            frozen = app.state.container.image_revisions.artifacts.read(v["project_id"], ref, header.artifact_hash)
            assert header.manifest_id == manifest.manifest_id
            assert len(frozen["source_members"]) == 4
            documents = [member for member in members if member.kind == "source_document"]
            assert len(documents) == 4
            reader, evidence, spans = ArchivedEvidenceSourceReader(storage), SourceEvidenceRepository(), 0
            with reader.verified_read_session():
                for member in members:
                    assert member.kind in {"code_entity", "source_document"} and member.evidence_ids
                    for target in evidence.get_many(v["project_id"], tuple(member.evidence_ids)):
                        locator = target.evidence.locator
                        assert target.evidence.source_revision_id == member.source_revision_id
                        lines = source_lines(reader.read(target).decode("utf-8"))
                        assert text_digest("".join(lines[locator.start_line - 1:locator.end_line])) == target.evidence.snippet_hash
                        spans += 1
            proposal_id = reference_command.result.object_refs[0].split(":", 1)[1]
            url = f"{v['image_url']}/reference-proposals/{proposal_id}"
            response = await asyncio.to_thread(v["client"].get, url, headers=v["headers"])
            assert response.status_code == 200, response.text
            proposal = response.json()
            assert proposal["assertion_count"] == 1 and proposal["gap_count"] == 0
            reference, = proposal["items"]
            assert reference["reference_id"] == "US-EXWEB-CHAT" and reference["predicate"] == "references"
            assert reference["status"] == "proposed" and proposal["publication"] == "not_in_image_membership"
            reread = await asyncio.to_thread(v["client"].get, url, headers=v["headers"])
            assert reread.status_code == 200 and reread.json() == proposal
            budget, consumptions = BuildToolBudgetRepository().inspect(started.id)
            assert consumptions[:len(budget_before[1])] == budget_before[1]
            assert len({item["invocation_id"] for item in consumptions}) == len(consumptions)
            reads = [step for step in final.steps if step.phase == "acting"
                and step.selected_tool_id == "query.system_image.references.read"]
            assert {step.tool_input_payload["section"] for step in reads} == {"assertions", "gaps"}
            assert all(step.tool_input_payload["proposal_id"] == proposal_id
                and step.tool_invocation_id in {item["invocation_id"] for item in consumptions} for step in reads)
            assert all(step.status == "completed" for step in final.steps if step.phase == "acting")
            return {"goal_id": started.id, "workflow_id": started.workflow_id, "plan_id": fixed["plan_id"],
                "source_manifest_id": manifest.manifest_id, "source_manifest_hash": manifest.content_hash,
                "image_revision_id": image_id, "image_artifact_hash": header.artifact_hash,
                "source_types": sorted({item.source_type for item in manifest.members}),
                "source_count": len(manifest.members), "document_members": len(documents),
                "image_member_count": len(members), "verified_member_spans": spans,
                "reference_proposal": proposal, "reference_entrypoint": "original_goal_canonical_investigation_followup",
                "goal_worker_instances": worker_count, "goal_recovery_scope": "between_confirmation_gates_not_mid_activity_kill",
                "goal_workflow": "real_temporal", "structure_workflow": "real_temporal",
                "graph": "langgraph_postgres", "pause_reason": final.pause_reason,
                "model_calls": final.model_calls_used, "tool_budget": asdict(budget),
                "tool_consumptions": list(consumptions), "generation_projection_hashes": failed_projections,
                "goal_and_structure_history_replayed": True, "replay_started_provider": False,
                "candidate_delivered": False, "publication_created": False}
        finally:
            if building is not None and not building.done():
                building.cancel()
                await asyncio.gather(building, return_exceptions=True)
            async with Worker(client, task_queue=config.task_queue, workflows=[NasusAgentGoalWorkflow], activities=definitions):
                await close_handles(handles)

    report = asyncio.run(verify())
    assert attempts == [1, 2] and len(runner.calls) == 4
    assert all(call["returncode"] == 0 and not Path(call["cwd"]).exists() for call in runner.calls)
    assert all(not list(graph.config.cache_dir.iterdir()) for graph in graphs)
    assert git("rev-parse", "HEAD") == capture.snapshot.external_revision and not git("status", "--porcelain")
    output = os.environ.get("EXWEB_CODEGRAPH_AGENT_TEMPORAL_REPORT")
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        assert not path.exists()
        path.write_text(json.dumps({"schema": "nasus.exweb-sdk-three-source-agent.v1",
            "source_revision": capture.snapshot.external_revision, "exweb_files": 126, "exweb_bytes": 180868,
            "companion_sources": "explicit_synthetic_contract_fixtures_not_business_authority",
            "sdk_runtime_hash": operator.sdk_runtime_hash, **report, "temporal_structure_attempts": attempts,
            "native_preparations": len(runner.calls), "target_executed": False,
            "external_model_called": False, "business_gold": False,
            "storage": "isolated_postgresql_and_private_minio"}, indent=2) + "\n")
