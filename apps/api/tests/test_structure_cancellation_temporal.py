"""Real Temporal and archived exweb; stop never deletes a committed candidate."""
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from temporalio.client import Client
from temporalio.worker import Replayer, Worker

from apps.api.app.main import app
from apps.api.app.application.system_image.code_index_generations import CodeIndexGenerationApplicationService
from apps.api.app.infrastructure.config.agent_runtime_config import TemporalGatewayConfig
from apps.api.app.infrastructure.config.code_graph_config import CodeGraphConfig
from apps.api.app.infrastructure.persistence.code_index_generation_repository import CodeIndexGenerationRepository
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.structure_build_models import StructureBuildArtifactRecord
from apps.api.app.infrastructure.persistence.structure_cancel_models import StructureCancellationRecord
from apps.api.app.infrastructure.persistence.structure_job_models import StructureWorkLeaseRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import CodebaseMemoryCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.code_graph_process import CodeGraphProcessRunner
from apps.api.app.infrastructure.system_image.composite_code_intelligence import CompositeCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.registered_code_intelligence import RegisteredCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage
from apps.api.app.infrastructure.workflow.nasus_structure_workflow import NasusStructureBuildWorkflow
from apps.api.app.infrastructure.workflow.structure_runtime import TemporalStructureRuntime, build_structure_activities
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_structure_build_api import request, submit, confirm
from apps.api.tests.test_structure_cancellation_api import cancel
from apps.api.tests.exweb_structural_evidence import verify_exweb_structural_evidence


@pytest.mark.skipif(not os.getenv("TEST_TEMPORAL_ADDRESS") or not os.getenv("EXWEB_CODE_CONTROL_SOURCE"),
    reason="requires explicitly enabled Temporal and a fixed exweb checkout")
@pytest.mark.parametrize("phase", ["queued", "native-session", "candidate-committed"])
def test_real_exweb_structure_stop_replays_without_provider(evidence_api, monkeypatch, tmp_path, phase):
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
    calls, receipts = [], []
    entered, cleaning, release, exited = Event(), Event(), Event(), Event()

    class Recorder(CodeGraphProcessRunner):
        def run(self, args, **kwargs):
            operation = "mcp/negotiate" if kwargs.get("dialogue") is not None else args[2] if len(args) > 2 else "--version"
            calls.append(operation)
            result = super().run(args, **kwargs)
            if phase == "native-session" and operation == "index_repository" and calls.count(operation) == 2:
                entered.set()
                try:
                    while not release.wait(.01):
                        kwargs["check_current"]()
                finally:
                    cleaning.set()
                    assert release.wait(20), "test must release worker cleanup"
                    exited.set()
            return result

    native = CodebaseMemoryCodeIntelligenceAdapter(replace(CodeGraphConfig.from_env(), mode="required",
        binary=str(Path(__file__).resolve().parents[3] / ".venv/bin/codebase-memory-mcp"), cache_dir=tmp_path / "native",
        timeout_seconds=180, max_entities=20000, max_relationships=50000), process_runner=Recorder())
    jobs = app.state.container.structure_jobs
    extraction = jobs.application.preparation.extraction
    generations = CodeIndexGenerationApplicationService(CodeIndexGenerationRepository(), extraction._source_reader, native)
    monkeypatch.setattr(extraction, "_source_code_intelligence", RegisteredCodeIntelligenceAdapter(
        CompositeCodeIntelligenceAdapter(TreeSitterCodeIntelligenceAdapter(), native, mode="required"), generations))
    runtime = TemporalStructureRuntime(TemporalGatewayConfig(address=os.environ["TEST_TEMPORAL_ADDRESS"],
        task_queue="nasus-structure-stop-exweb-" + uuid4().hex))
    monkeypatch.setattr(jobs, "workflow", runtime)
    monkeypatch.setattr(type(runtime), "enabled", property(lambda _: True))
    import apps.api.app.bootstrap as bootstrap
    monkeypatch.setattr(bootstrap, "get_application_container", lambda: app.state.container)
    payload = request(v)
    ident = submit(v, payload)
    finish = jobs.repository.finish
    if phase == "candidate-committed":
        def stop_after_commit(*args, **kwargs):
            receipts.append(cancel(v, ident, payload))
            return finish(*args, **kwargs)
        monkeypatch.setattr(jobs.repository, "finish", stop_after_commit)
    run, fail = build_structure_activities()

    async def verify():
        result = await asyncio.to_thread(confirm, v, ident)
        assert result["status"] == "running" and result["result"] is None
        assert "index_repository" not in calls
        with session_scope() as session:
            original_input = session.get(ToolInvocationRecord, ident).input_payload.copy()
        if phase == "queued":
            receipts.append(await asyncio.to_thread(cancel, v, ident, payload))
            assert receipts[-1]["result"]["structure_cancel"]["outcome"] == "cancelled"
        client = await Client.connect(os.environ["TEST_TEMPORAL_ADDRESS"])
        handle = client.get_workflow_handle("nasus-structure-build:" + ident)
        async with Worker(client, task_queue=runtime.task_queue, workflows=[NasusStructureBuildWorkflow],
                activities=[run, fail], max_concurrent_activities=1):
            if phase == "native-session":
                try:
                    assert await asyncio.to_thread(entered.wait, 30)
                    receipts.append(await asyncio.to_thread(cancel, v, ident, payload))
                    assert receipts[-1]["result"]["structure_cancel"]["outcome"] == "cancel_requested"
                    assert await asyncio.to_thread(cleaning.wait, 10)
                    with session_scope() as session:
                        assert session.get(ToolInvocationRecord, ident).status == "running"
                        assert session.get(StructureWorkLeaseRecord, ident).expires_at > session.scalar(select(func.clock_timestamp()))
                        assert session.get(StructureBuildArtifactRecord, ident) is None
                    assert not exited.is_set()
                finally:
                    release.set()
            outcome = await asyncio.wait_for(handle.result(), 180)
            assert outcome == ("completed" if phase == "candidate-committed" else "cancelled")
            history = await handle.fetch_history()
        before = tuple(calls)
        replay = await Replayer(workflows=[NasusStructureBuildWorkflow]).replay_workflow(history)
        assert replay.replay_failure is None and tuple(calls) == before
        assert await jobs.run(ident) == outcome and tuple(calls) == before
        with session_scope() as session:
            assert session.get(ToolInvocationRecord, ident).input_payload == original_input
            artifact = session.get(StructureBuildArtifactRecord, ident)
            intent = session.get(StructureCancellationRecord, ident)
            assert bool(artifact) == (phase == "candidate-committed")
            assert bool(intent) == (phase != "candidate-committed")
            assert session.scalar(select(func.count()).select_from(AuditEventRecord).where(
                AuditEventRecord.tool_invocation_id == ident, AuditEventRecord.action == f"tool.invocation.{outcome}")) == 1
        structural_evidence = await asyncio.to_thread(verify_exweb_structural_evidence,
            v["project_id"], artifact.image_revision_id, str(root)) if artifact else None
        return {"outcome": outcome, "history_events": len(history.events), "original_input_unchanged": True,
            "candidate_retained": bool(artifact), "replay_without_provider": True,
            "structural_evidence": structural_evidence}

    report = asyncio.run(verify())
    assert receipts[0]["result"]["structure_cancel"]["outcome"] == {
        "queued": "cancelled", "native-session": "cancel_requested", "candidate-committed": "already_committed"}[phase]
    assert calls.count("index_repository") == (0 if phase == "queued" else 2)
    assert calls.count("mcp/negotiate") == (0 if phase == "queued" else 2)
    assert not list((tmp_path / "native").rglob("*.db"))
    output = os.environ.get("EXWEB_STRUCTURE_JOB_REPORT")
    if output:
        path = Path(output)
        path = path.with_name(path.stem + "-stop-" + phase + path.suffix)
        path.write_text(json.dumps({"schema": "nasus.exweb-structure-stop.v1", "git_revision": revision,
            "phase": phase, "calls": calls, "receipt": receipts[0]["result"]["structure_cancel"], **report,
            "object_store": "minio_s3" if ObjectStorage().config.s3_enabled else "isolated_local_adapter",
            "target_code_executed": False,
            "external_model_called": False, "business_gold": False,
            "native_process_kill_verified": False, "native_session_cleanup_waited": phase == "native-session"}, indent=2))
