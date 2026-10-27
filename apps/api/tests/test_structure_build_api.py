import pytest
import os
import sys
import time
from sqlalchemy import func, select, update, delete
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.infrastructure.persistence.db_models import BaselineRecord, ToolInvocationRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.image_revision_models import ImageRevisionRecord
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.structure_build_models import StructureBuildArtifactRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_build_plan_api import create, urls


def request(v, **changes):
    ident = create(v)
    plan = v["client"].get(urls(v, ident)[1], headers=v["headers"]).json()
    with session_scope() as session:
        baseline = session.scalar(select(BaselineRecord).where(BaselineRecord.project_id == v["project_id"]))
        target = baseline.id
    return {"project_id": v["project_id"], "plan_id": ident, "plan_digest": plan["plan_digest"],
            "target_baseline_id": target, **changes}


def submit(v, payload):
    response = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "tool_id": "system_image.build.structure", "conversation_id": v["conversation"].json()["id"], "input": payload})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "waiting_confirmation", response.text
    return response.json()["id"]


def confirm(v, invocation):
    response = v["client"].post(f"/v1/tool-invocations/{invocation}/confirm", headers=v["headers"])
    assert response.status_code == 200, response.text
    return response.json()


def test_confirmed_work_builds_archived_plan_after_source_head_moves(evidence_api, monkeypatch):
    v = evidence_api
    payload = request(v)
    invocation = submit(v, {**payload, "confirmed_by_user": True, "confirmed_at": "forged"})
    with session_scope() as session:
        assert session.get(StructureBuildArtifactRecord, invocation) is None
    old_manifest = v["image"]["source_manifest"]["manifest_id"]
    v["path"].write_text("class Replacement:\n    pass\n")
    v["invoke"]("system_image.sources.ingest")
    head = SourceSnapshotRepository().latest_manifest(v["project_id"])
    assert head.manifest_id != old_manifest
    v["path"].unlink()

    def no_mutable_ingestion(*args, **kwargs):
        raise AssertionError("fixed-input execution must never recapture the workspace")

    from apps.api.app.application.system_image.service import SystemImageService
    monkeypatch.setattr(SystemImageService, "ingest_sources", no_mutable_ingestion)
    result = confirm(v, invocation)
    assert result["status"] == "completed", result
    revision_id = next(ref.split(":", 1)[1] for ref in result["result"]["object_refs"] if ref.startswith("image_revision:"))
    with session_scope() as session:
        receipt = session.get(StructureBuildArtifactRecord, invocation)
        assert receipt.plan_id == payload["plan_id"] and receipt.image_revision_id == revision_id
        image = session.get(ImageRevisionRecord, revision_id)
        assert image.manifest_id == old_manifest and image.status == "candidate"
    assert SourceSnapshotRepository().latest_manifest(v["project_id"]) == head
    assert confirm(v, invocation) == result
    revision, ref, _ = app.state.container.image_revisions.repository.get(v["project_id"], revision_id)
    artifact = app.state.container.image_revisions.artifacts.read(v["project_id"], ref, revision.artifact_hash)
    assert "Orders" in str(artifact) and "Replacement" not in str(artifact)
    plan = v["client"].get(urls(v, payload["plan_id"])[1], headers=v["headers"]).json()
    assert plan["structural_artifacts"][0]["image_revision_id"] == revision_id
    with session_scope() as session:
        events = session.scalars(select(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.event_type == "system_image.build.structure.completed",
            SSEEventOutboxRecord.entity_id == payload["plan_id"])).all()
        assert len(events) == 1 and "Orders" not in str(events[0].event_payload)
    for statement in (update(StructureBuildArtifactRecord).values(plan_digest="changed"), delete(StructureBuildArtifactRecord)):
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as session:
                session.execute(statement.where(StructureBuildArtifactRecord.invocation_id == invocation))


@pytest.mark.parametrize("changes", [{"plan_digest": "wrong"}, {"target_baseline_id": "foreign"},
    {"agent_goal_id": "forged"}, {"execute_repository": True}])
def test_invalid_work_cannot_commit(evidence_api, changes):
    v = evidence_api
    invocation = submit(v, request(v, **changes))
    result = confirm(v, invocation)
    assert result["status"] == "failed", result
    with session_scope() as session:
        assert session.get(StructureBuildArtifactRecord, invocation) is None


def test_late_access_change_rolls_back_structural_candidate(evidence_api, monkeypatch):
    from apps.api.app.domain.system_image.source_access import StaleSourceAccessScope
    from apps.api.app.infrastructure.persistence.structure_build_repository import StructureBuildRepository
    v = evidence_api
    invocation = submit(v, request(v))
    original = StructureBuildRepository.attach
    with session_scope() as session:
        before = session.scalar(select(func.count()).select_from(ImageRevisionRecord).where(ImageRevisionRecord.project_id == v["project_id"]))

    def rejected(session, commit, candidate):
        original(session, commit, candidate)
        raise StaleSourceAccessScope("private ACL detail")

    monkeypatch.setattr(StructureBuildRepository, "attach", rejected)
    result = confirm(v, invocation)
    assert result["status"] == "failed" and "private ACL" not in str(result)
    with session_scope() as session:
        assert session.get(StructureBuildArtifactRecord, invocation) is None
        assert session.scalar(select(func.count()).select_from(ImageRevisionRecord).where(ImageRevisionRecord.project_id == v["project_id"])) == before


@pytest.mark.parametrize("failure", ["cancelled", "expired", "target_changed"])
def test_cancel_expiry_and_target_race_prevent_commit(evidence_api, monkeypatch, failure):
    v = evidence_api
    invocation = submit(v, request(v))
    archive = app.state.container.structure_builds.preparation.candidates.artifacts
    original = archive.put
    with session_scope() as session:
        before = session.scalar(select(func.count()).select_from(ImageRevisionRecord).where(ImageRevisionRecord.project_id == v["project_id"]))

    def interrupt(*args, **kwargs):
        artifact = original(*args, **kwargs)
        with session_scope() as session:
            row = session.get(ToolInvocationRecord, invocation)
            if failure == "cancelled":
                row.status = "cancelled"
            elif failure == "expired":
                row.input_payload = {**row.input_payload, "confirmed_at": "2000-01-01T00:00:00+00:00"}
            else:
                target = session.get(BaselineRecord, row.input_payload["target_baseline_id"])
                target.project_id = "different-project"
        return artifact

    monkeypatch.setattr(archive, "put", interrupt)
    result = confirm(v, invocation)
    assert result["status"] == ("cancelled" if failure == "cancelled" else "failed"), result
    with session_scope() as session:
        assert session.get(StructureBuildArtifactRecord, invocation) is None
        assert session.scalar(select(func.count()).select_from(ImageRevisionRecord).where(ImageRevisionRecord.project_id == v["project_id"])) == before


def test_failed_optional_document_does_not_block_code_structure(evidence_api):
    v = evidence_api
    v["invoke"]("system_image.sources.register", {"source_specs": [
        {"source_type": "us_doc", "source_uri": str(v["path"].parent / "missing.md")}]})
    v["invoke"]("system_image.sources.ingest")
    v["image"] = v["client"].get(f"/v1/projects/{v['project_id']}/system-image", headers=v["headers"]).json()
    payload = request(v)
    result = confirm(v, submit(v, payload))
    assert result["status"] == "completed", result
    plan = v["client"].get(urls(v, payload["plan_id"])[1], headers=v["headers"]).json()
    assert "us_doc_unavailable" in str(plan["proposal"]["gaps"])
    assert any(item["source_type"] == "us_doc" and item["status"] == "failed" for item in plan["proposal"]["intent"]["sources"])


@pytest.mark.parametrize("failure", ["cancelled", "access_changed"])
def test_live_native_process_stops_on_canonical_or_source_access_change(evidence_api, monkeypatch, tmp_path, failure):
    from apps.api.app.infrastructure.system_image.code_graph_process import CodeGraphProcessRunner
    from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import CodebaseMemoryCodeIntelligenceAdapter
    from apps.api.app.infrastructure.system_image.composite_code_intelligence import CompositeCodeIntelligenceAdapter
    from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
    from apps.api.tests.test_code_graph_enrichment import _config
    v = evidence_api
    invocation = submit(v, request(v))
    extraction = app.state.container.structure_builds.preparation.extraction
    marker = tmp_path / "native-pid"
    binary = tmp_path / "stalled-contract-provider"
    binary.write_text(f"#!{sys.executable}\nimport os,pathlib,sys,time\n"
        "if sys.argv[1:] == ['--version']: print('contract-fixture'); raise SystemExit(0)\n"
        f"pathlib.Path({str(marker)!r}).write_text(str(os.getpid()))\ntime.sleep(30)\n")
    binary.chmod(0o755)
    changed = []
    class ControlledRunner(CodeGraphProcessRunner):
        def run(self, args, *, check_current=None, **kwargs):
            def live_check():
                if marker.exists() and not changed:
                    changed.append(True)
                    if failure == "cancelled":
                        with session_scope() as session:
                            session.get(ToolInvocationRecord, invocation).status = "cancelled"
                    else:
                        from apps.api.tests.test_source_access_api import policy
                        policy(v)
                check_current()
            return super().run(args, check_current=live_check, **kwargs)

    native = CodebaseMemoryCodeIntelligenceAdapter(_config(binary), process_runner=ControlledRunner())
    monkeypatch.setattr(extraction, "_code_intelligence",
        CompositeCodeIntelligenceAdapter(TreeSitterCodeIntelligenceAdapter(), native, mode="optional"))
    with session_scope() as session:
        before = session.scalar(select(func.count()).select_from(ImageRevisionRecord).where(ImageRevisionRecord.project_id == v["project_id"]))
    started = time.monotonic()
    result = confirm(v, invocation)
    assert changed and time.monotonic() - started < 10
    assert result["status"] == ("cancelled" if failure == "cancelled" else "failed"), result
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)
    with session_scope() as session:
        assert session.get(StructureBuildArtifactRecord, invocation) is None
        assert session.scalar(select(func.count()).select_from(ImageRevisionRecord).where(ImageRevisionRecord.project_id == v["project_id"])) == before
        assert session.scalar(select(func.count()).select_from(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.event_type == "system_image.build.structure.completed",
            SSEEventOutboxRecord.event_payload["patch"]["invocation_id"].as_string() == invocation)) == 0
