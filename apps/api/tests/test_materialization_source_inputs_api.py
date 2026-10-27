"""The compatibility materializer must consume archives, never acquire sources."""
from __future__ import annotations

from copy import deepcopy
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.quality_loop.quality_models import USItem
from apps.api.app.infrastructure.persistence.quality_loop_repository import QualityLoopRepository
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
from apps.api.app.main import app
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_access_api import policy
from apps.api.tests.test_source_ingestion_access_api import facts, grant_tester
from apps.api.tests.test_source_refresh_api import read
from apps.api.tests.test_document_projection_api import documents


def materialize(v, *, headers=None):
    response = v["client"].post("/v1/tool-invocations", headers=headers or v["headers"], json={
        "tool_id": "system_image.context.materialize", "idempotency_key": uuid4().hex,
        "input": {"project_id": v["project_id"]},
    })
    assert response.status_code == 200, response.text
    return response.json()


def count_acquisitions(monkeypatch):
    original = SourceIngestionService.ingest
    calls = []

    def counted(service, source):
        calls.append(source.id)
        return original(service, source)

    monkeypatch.setattr(SourceIngestionService, "ingest", counted)
    return calls


def running_materialization(v, monkeypatch, *, headers=None, tool="system_image.context.materialize"):
    registry = app.state.container.platform._tool_invocations._runtime.handlers
    resolve = registry.resolve

    async def deferred(invocation):
        assert invocation.tool_id == tool

    with monkeypatch.context() as patch:
        patch.setattr(registry, "resolve", lambda name: SimpleNamespace(handle=deferred) if name == tool else resolve(name))
        response = v["client"].post("/v1/tool-invocations", headers=headers or v["headers"], json={
            "tool_id": tool, "idempotency_key": uuid4().hex, "input": {"project_id": v["project_id"]},
        })
    assert response.status_code == 200 and response.json()["status"] == "running", response.text
    return response.json()


def test_original_materialization_command_cannot_adopt_a_later_manifest(evidence_api, monkeypatch):
    v = evidence_api
    command = running_materialization(v, monkeypatch)
    service = app.state.container.system_image.lifecycle._operations
    original = SourceSnapshotRepository().latest_manifest(v["project_id"])

    class Interrupted(BaseException):
        pass

    with monkeypatch.context() as fault:
        fault.setattr(service.candidate_preparation, "prepare", lambda *args, **kwargs: (_ for _ in ()).throw(Interrupted()))
        with actor_scope(UserProfile.model_validate(v["owner"])), pytest.raises(Interrupted):
            asyncio.run(service.materialize_context(v["project_id"], invocation_id=command["id"]))
    v["path"].write_text("class DifferentInput:\n    pass\n")
    v["invoke"]("system_image.sources.ingest")
    current = SourceSnapshotRepository().latest_manifest(v["project_id"])
    assert current != original
    before = facts(v)
    acquisitions = count_acquisitions(monkeypatch)
    with actor_scope(UserProfile.model_validate(v["owner"])), pytest.raises(PlatformApplicationError) as error:
        asyncio.run(service.materialize_context(v["project_id"], invocation_id=command["id"]))
    assert error.value.code == "materialization_sources_changed"
    assert not acquisitions and facts(v) == before
    assert SourceSnapshotRepository().latest_manifest(v["project_id"]) == current


def test_source_binding_queries_reload_committed_registration_outside_tool_scope(evidence_api, tmp_path, monkeypatch):
    v = evidence_api
    response = v["client"].post("/v1/projects", headers=v["headers"], json={"name": "Fresh binding queries " + uuid4().hex})
    assert response.status_code == 200
    project_id = response.json()["id"]
    service = app.state.container.system_image.lifecycle._operations
    workspace = service.workspace
    original_sources = deepcopy(workspace.list_raw_assets(project_id))
    assert original_sources and all(source.ingestion_status == "pending" for source in original_sources)
    inherited = workspace._request_snapshots.get()
    assert service.source_binding_incomplete(project_id)
    assert service.missing_source_types(project_id) == ["code"]
    source = tmp_path / "newly_bound.py"
    source.write_text("def newly_bound():\n    pass\n")
    calls = count_acquisitions(monkeypatch)
    registered = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "tool_id": "system_image.sources.register", "idempotency_key": uuid4().hex,
        "input": {"project_id": project_id, "source_specs": [{"source_type": "code", "source_uri": str(source)}]},
    })
    assert registered.status_code == 200 and registered.json()["status"] == "completed", registered.text
    assert service.source_binding_incomplete(project_id) is False
    assert service.missing_source_types(project_id) == []
    assert not calls and SourceSnapshotRepository().latest_manifest(project_id) is None
    assert workspace._request_snapshots.get() is inherited
    assert inherited[project_id].raw_assets == original_sources


def test_materialization_reuses_fixed_sources_after_original_file_is_deleted(evidence_api, monkeypatch):
    v = evidence_api
    before = deepcopy(read(v))
    manifest = SourceSnapshotRepository().latest_manifest(v["project_id"])
    calls = count_acquisitions(monkeypatch)
    v["path"].unlink()
    result = materialize(v)
    assert not calls, "Materialization must not re-acquire an already captured source"
    assert result["status"] == "completed", result
    after = read(v)
    assert after["source_manifest"] == before["source_manifest"]
    assert SourceSnapshotRepository().latest_manifest(v["project_id"]) == manifest
    assert after["sources"] == before["sources"]
    assert {item["id"]: item["code_reference"] for item in after["objects"]} == {
        item["id"]: item["code_reference"] for item in before["objects"]}


def test_frozen_materialization_accepts_zero_native_edges_without_inventing_business_coverage(documents):
    from apps.api.tests.test_reference_links_api import proposal
    from apps.api.app.infrastructure.agent.sqlalchemy_application_ports import SQLAlchemyAgentPlanState
    from apps.api.app.infrastructure.persistence.project_repository import ProjectRepository
    from apps.api.app.infrastructure.persistence.system_image_repository import SystemImageRepository

    v = documents
    v["path"].write_text("# A module with no dependency edges.\n")
    v["invoke"]("system_image.sources.ingest")
    result = materialize(v)
    assert result["status"] == "completed", result
    image = read(v)
    assert image["build_state"]["status"] == "materialized"
    assert len([item for item in image["objects"] if item["code_reference"]]) == 1
    assert len([item for item in image["objects"] if item["document_reference"]]) == 3
    assert image["relationships"] == []
    metrics = {item["metric_group"]: item["metrics"] for item in image["metric_snapshots"]}
    assert metrics["code_quality"]["structural_relationship_count"] == 0
    assert metrics["us_completion_quality"]["requirements_count"] == 1
    assert metrics["us_completion_quality"]["acceptance_criterion_count"] == 1
    assert metrics["test_quality"]["test_case_count"] == 1 and metrics["test_quality"]["test_script_count"] == 0
    assert all(item["coverage_status"] == "unknown" for item in metrics.values())
    assert image["task_contexts"] and image["quality_profiles"] and image["embedding_records"]
    assert all(context["confidence"] is None for context in image["task_contexts"])
    assert all(profile[field] is None for profile in image["quality_profiles"]
        for field in ("risk_score", "coverage_score", "release_score", "automation_feasibility", "confidence"))
    plan_state = SQLAlchemyAgentPlanState(projects=ProjectRepository(), system_image=SystemImageRepository(),
        source_binding_incomplete=lambda _: False, tools=[])
    assert plan_state.has_materialized_context(v["project_id"])
    saved, _, _ = proposal(v)
    assert saved["assertion_count"] == 1 and saved["items"][0]["predicate"] == "references"
    assert saved["publication"] == "not_in_image_membership"
    assert read(v)["relationships"] == [], "A proposal must not silently become a business graph edge"


def test_materialization_refreshes_us_after_caller_workspace_cache_is_inherited(evidence_api, monkeypatch):
    v = evidence_api
    repository = QualityLoopRepository()
    workspace = app.state.container.system_image.lifecycle._operations.workspace
    first = USItem(id="us_first_" + uuid4().hex, title="First requirement", owner="QA", status="analysis",
        risk="low", progress=0, next_action="Generate scenarios")
    second = first.model_copy(update={"id": first.id + "_new", "title": "New requirement"})
    repository.replace_us_items(v["project_id"], None, [first])
    acquisitions = count_acquisitions(monkeypatch)
    assert materialize(v)["status"] == "completed"
    assert workspace.list_us_items(v["project_id"]) == [first]
    inherited = workspace._request_snapshots.get()
    repository.replace_us_items(v["project_id"], None, [first, second])
    before = read(v)
    v["path"].unlink()
    result = materialize(v)
    assert result["status"] == "completed", result
    after = read(v)
    assert {context["us_id"] for context in after["task_contexts"]} == {first.id, second.id}
    assert {profile["us_id"] for profile in after["quality_profiles"]} == {first.id, second.id}
    assert after["source_manifest"] == before["source_manifest"]
    assert after["sources"] == before["sources"] and not acquisitions
    assert workspace._request_snapshots.get() is inherited
    assert inherited[v["project_id"]].us_items == [first]


def test_unknown_quality_is_preserved_through_canonical_release_assessment(evidence_api):
    from apps.api.app.infrastructure.persistence.system_image_repository import SystemImageRepository
    v = evidence_api
    us = USItem(id="unknown_quality_us_" + uuid4().hex, title="Independent quality requirement",
        owner="QA", status="analysis", risk="low", progress=0, next_action="Investigate")
    QualityLoopRepository().replace_us_items(v["project_id"], None, [us])
    assert materialize(v)["status"] == "completed"
    before = read(v)
    response = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "tool_id": "release.assess", "idempotency_key": uuid4().hex,
        "input": {"project_id": v["project_id"], "us_id": us.id}})
    assert response.status_code == 200 and response.json()["status"] == "completed", response.text
    assert "approval.request" not in response.json()["result"]["next_recommended_tools"]
    workspace = v["client"].get(f"/v1/projects/{v['project_id']}", headers=v["headers"])
    assert workspace.status_code == 200, workspace.text
    body = workspace.json()
    assert body["quality_loop_state"]["status"] == "blocked"
    assert "quality assessment is unknown" in " ".join(body["quality_loop_state"]["blockers"])
    assert next(item for item in body["us_items"] if item["id"] == us.id)["status"] == "blocked"
    pack = body["quality_asset_pack"]
    assert pack["status"] == "blocked"
    assert next(part for part in pack["parts"] if part["part_type"] == "release_assessment")["status"] == "blocked"
    profile = SystemImageRepository().list_quality_profiles(v["project_id"])[0]
    assert all(getattr(profile, field) is None for field in
        ("risk_score", "coverage_score", "release_score", "automation_feasibility", "confidence"))
    after = read(v)
    assert after["source_manifest"] == before["source_manifest"] and after["sources"] == before["sources"]


@pytest.mark.parametrize("tool", ["release.decision.submit", "baseline.promote"])
def test_approved_stale_decision_cannot_bypass_unknown_inventory(evidence_api, tool):
    from apps.api.app.application.quality_loop.quality_models import ReleaseDecision
    v = evidence_api
    us = USItem(id="stale_release_us_" + uuid4().hex, title="Unknown quality basis",
        owner="QA", status="analysis", risk="low", progress=0, next_action="Investigate")
    repository = QualityLoopRepository()
    repository.replace_us_items(v["project_id"], None, [us])
    assert materialize(v)["status"] == "completed"
    v["invoke"]("release.assess", {"us_id": us.id})
    release = v["client"].get(f"/v1/projects/{v['project_id']}/release-readiness", headers=v["headers"]).json()
    assert release["evidence_summary"]["quality_assessment_unknown"] == 1

    def command(name, payload):
        response = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
            "tool_id": name, "idempotency_key": uuid4().hex,
            "input": {"project_id": v["project_id"], **payload}})
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] == "waiting_confirmation":
            response = v["client"].post(f"/v1/tool-invocations/{body['id']}/confirm", headers=v["headers"])
            assert response.status_code == 200, response.text
            body = response.json()
        return body

    requested = command("approval.request", {"purpose": "release_decision",
        "target_ref": f"release_readiness:{release['version_id']}"})
    assert requested["status"] == "completed", requested
    approval_id = next(ref.split(":", 1)[1] for ref in requested["result"]["object_refs"] if ref.startswith("approval:"))
    approved = command("approval.decide", {"approval_id": approval_id, "decision": "approved",
        "rationale": "Permission does not certify unknown quality."})
    assert approved["status"] == "completed", approved
    # A historical ready record is an attack fixture, not new quality evidence.
    stale = ReleaseDecision(id="stale_release_" + uuid4().hex, project_id=v["project_id"],
        version_id=release["version_id"], us_id=us.id, status="ready", score=90,
        rationale="Historical ready decision", approval_ref=f"approval:{approval_id}",
        evidence_refs=[], created_at="2026-10-01T00:00:00Z")
    repository.upsert_release_decision(stale)
    before = read(v)
    denied = command(tool, {"version_id": release["version_id"], "us_id": us.id, "approval_id": approval_id})
    assert denied["status"] == "failed", denied
    assert "current release evidence" in denied["summary"]
    assert repository.find_release_decision(v["project_id"], us.id, release["version_id"]) == stale
    after = read(v)
    assert after["baselines"] == before["baselines"] and after["source_manifest"] == before["source_manifest"]
    assert after["sources"] == before["sources"]


def test_materialization_does_not_implicitly_acquire_new_binding(evidence_api, tmp_path, monkeypatch):
    v = evidence_api
    optional = tmp_path / "requirements.md"
    optional.write_text("# US-1\nNew optional source not yet captured.\n")
    v["invoke"]("system_image.sources.register", {"source_specs": [
        {"source_type": "us_doc", "source_uri": str(optional)}]})
    before = facts(v)
    manifest = SourceSnapshotRepository().latest_manifest(v["project_id"])
    calls = count_acquisitions(monkeypatch)
    result = materialize(v)
    assert not calls, "A separate canonical ingestion must authorize new source capture"
    assert result["status"] == "failed", result
    assert result["result"]["followup_reason"] == "materialization_sources_changed"
    assert "system_image.sources.ingest" in result["result"]["next_recommended_tools"]
    assert facts(v) == before
    assert SourceSnapshotRepository().latest_manifest(v["project_id"]) == manifest


def test_failed_optional_source_remains_a_gap_in_frozen_materialization(evidence_api, tmp_path, monkeypatch):
    v = evidence_api
    missing = tmp_path / "missing-requirements.md"
    v["invoke"]("system_image.sources.register", {"source_specs": [
        {"source_type": "us_doc", "source_uri": str(missing)}]})
    v["invoke"]("system_image.sources.ingest")
    before = read(v)
    manifest = SourceSnapshotRepository().latest_manifest(v["project_id"])
    assert any(item.status == "failed" for item in manifest.members)
    extraction = app.state.container.system_image.lifecycle._operations.context_extraction
    extract = extraction.extract
    used = []

    def require_manifest(**kwargs):
        used.append(kwargs.get("source_manifest"))
        return extract(**kwargs)

    monkeypatch.setattr(extraction, "extract", require_manifest)
    calls = count_acquisitions(monkeypatch)
    result = materialize(v)
    assert not calls and used == [manifest]
    assert result["status"] == "completed", result
    after = read(v)
    assert after["source_manifest"] == before["source_manifest"]
    assert after["sources"] == before["sources"]
    assert all(item.get("code_reference") or item.get("document_reference") for item in after["objects"])
    assert any(item["ingestion_status"] == "failed" for item in after["sources"])


def test_materialization_requires_explicit_first_capture(evidence_api, tmp_path, monkeypatch):
    v = dict(evidence_api)
    response = v["client"].post("/v1/projects", headers=v["headers"], json={"name": "No implicit acquisition " + uuid4().hex})
    assert response.status_code == 200
    v["project_id"] = response.json()["id"]
    source = tmp_path / "uncaptured.py"
    source.write_text("def unacquired():\n    pass\n")
    response = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "tool_id": "system_image.sources.register", "input": {"project_id": v["project_id"],
            "source_specs": [{"source_type": "code", "source_uri": str(source)}]}})
    assert response.status_code == 200 and response.json()["status"] == "completed"
    before = facts(v)
    calls = count_acquisitions(monkeypatch)
    result = materialize(v)
    assert result["status"] == "failed" and not calls
    assert result["result"]["followup_reason"] == "materialization_source_manifest_required"
    assert facts(v) == before and SourceSnapshotRepository().latest_manifest(v["project_id"]) is None


@pytest.mark.parametrize("window", ["before_read", "after_read", "after_embedding"])
def test_materialization_rechecks_current_source_acl(evidence_api, monkeypatch, window):
    v = evidence_api
    grant_tester(v)
    policy(v, (v["member"]["id"],))
    before = facts(v)
    manifest = SourceSnapshotRepository().latest_manifest(v["project_id"])
    service = app.state.container.system_image.lifecycle._operations
    read_units = SourceIngestionService.extract_text_units
    embed = service.workspace.embed_texts
    reads, embeddings = [], []

    def counted_read(reader, source):
        reads.append(source.id)
        units = read_units(reader, source)
        if window == "after_read":
            policy(v)
        return units

    async def counted_embedding(*args, **kwargs):
        embeddings.append(kwargs.get("call_context"))
        result = await embed(*args, **kwargs)
        if window == "after_embedding":
            policy(v)
        return result

    monkeypatch.setattr(SourceIngestionService, "extract_text_units", counted_read)
    monkeypatch.setattr(service.workspace, "embed_texts", counted_embedding)
    acquisitions = count_acquisitions(monkeypatch)
    if window == "before_read":
        policy(v)
    result = materialize(v, headers=v["member_headers"])
    assert result["status"] == "failed" and result["result"]["followup_reason"] == "source_access_denied", result
    assert not acquisitions
    assert len(reads) == (0 if window == "before_read" else 1 if window == "after_read" else 2)
    assert len(embeddings) == (1 if window == "after_embedding" else 0)
    assert "orders.py" not in result["summary"]
    assert facts(v) == before and SourceSnapshotRepository().latest_manifest(v["project_id"]) == manifest


def test_head_change_during_extraction_does_not_overwrite_new_source_projection(evidence_api, monkeypatch):
    v = evidence_api
    service = app.state.container.system_image.lifecycle._operations
    extract = service.context_extraction.extract
    saved = []

    def advance_after_extract(**kwargs):
        context = extract(**kwargs)
        v["path"].write_text("class IndependentlyCaptured:\n    pass\n")
        v["invoke"]("system_image.sources.ingest")
        saved.append((facts(v), SourceSnapshotRepository().latest_manifest(v["project_id"])))
        return context

    monkeypatch.setattr(service.context_extraction, "extract", advance_after_extract)
    result = materialize(v)
    assert result["status"] == "failed", result
    assert result["result"]["followup_reason"] == "materialization_sources_changed"
    assert len(saved) == 1 and facts(v) == saved[0][0]
    assert SourceSnapshotRepository().latest_manifest(v["project_id"]) == saved[0][1]


@pytest.mark.parametrize("fault", ["changed_scope", "provider_failure"])
def test_new_binding_during_embedding_does_not_roll_back_independent_capture(evidence_api, monkeypatch, fault):
    v = evidence_api
    service = app.state.container.system_image.lifecycle._operations
    embed = service.workspace.embed_texts
    source = v["path"].parent / "independent.py"
    source.write_text("class IndependentlyCaptured:\n    pass\n")
    saved = []

    async def capture_after_embedding(*args, **kwargs):
        result = await embed(*args, **kwargs)
        assert not saved, "The failed materialization must not continue embedding"
        v["invoke"]("system_image.sources.register", {"source_specs": [
            {"source_type": "code", "source_uri": str(source)}]})
        v["invoke"]("system_image.sources.ingest")
        saved.append((facts(v), SourceSnapshotRepository().latest_manifest(v["project_id"])))
        if fault == "provider_failure":
            raise RuntimeError("Embedding response was interrupted.")
        return result

    monkeypatch.setattr(service.workspace, "embed_texts", capture_after_embedding)
    result = materialize(v)
    assert result["status"] == "failed", result
    if fault == "changed_scope":
        assert result["result"]["followup_reason"] == "source_access_denied", result
    assert len(saved) == 1
    assert facts(v) == saved[0][0]
    assert SourceSnapshotRepository().latest_manifest(v["project_id"]) == saved[0][1]


@pytest.mark.parametrize("fault", ["tampered", "unavailable"])
def test_bad_archive_does_not_fall_back_to_mutable_source(evidence_api, monkeypatch, fault):
    v = evidence_api
    service = app.state.container.system_image.lifecycle._operations
    before = facts(v)
    ref = next(source.content_ref for source in before.raw_assets if source.source_type == "code")
    storage = service.source_ingestion.snapshots.storage
    get_bytes = storage.get_bytes

    def damaged(ident, **kwargs):
        if ident == ref:
            if fault == "unavailable":
                raise OSError("credentials/private-endpoint must not appear in the receipt")
            return b'{"untrusted":"corrupt archive"}'
        return get_bytes(ident, **kwargs)

    monkeypatch.setattr(storage, "get_bytes", damaged)
    calls = count_acquisitions(monkeypatch)
    result = materialize(v)
    assert result["status"] == "failed" and not calls
    assert result["result"]["followup_reason"] == (
        "materialization_source_integrity_failed" if fault == "tampered" else "materialization_candidate_preparation_failed")
    assert "credentials" not in result["summary"] and "corrupt archive" not in result["summary"]
    assert facts(v) == before


def test_exweb_materializes_exact_fixed_archive_without_source_reacquisition(evidence_api, tmp_path, monkeypatch):
    root = os.getenv("EXWEB_SOURCE_REFRESH_GIT_ROOT")
    if not root:
        pytest.skip("explicit reviewed exweb Git export required")
    from apps.api.tests.exweb_git_trees import AFTER, read_git_tree
    files, tree_hash, _ = read_git_tree(Path(root), AFTER)
    assert len(files) == 126
    exported = tmp_path / "exweb-materialization-source"
    exported.mkdir()
    for name, body in files:
        path = exported / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    v = evidence_api
    v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "code", "source_uri": str(exported)}]})
    v["invoke"]("system_image.sources.ingest")
    before = deepcopy(read(v))
    source = next(item for item in before["sources"] if item["source_uri"] == str(exported))
    assert source["file_count"] == 126 and source["content_hash"] == tree_hash
    manifest = SourceSnapshotRepository().latest_manifest(v["project_id"])
    service = app.state.container.system_image.lifecycle._operations
    monkeypatch.setattr(service.source_ingestion.snapshots, "cache_dir", tmp_path / "fresh-materialization-cache")
    shutil.rmtree(exported)
    calls = count_acquisitions(monkeypatch)
    result = materialize(v)
    assert result["status"] == "completed" and not calls, result
    after = read(v)
    assert after["sources"] == before["sources"] and after["source_manifest"] == before["source_manifest"]
    code_ids = {item["id"] for item in after["objects"] if item["code_reference"]}
    assert all(edge["relationship_type"] in {"belongs_to", "depends_on"}
        and edge["from_object_id"] in code_ids and edge["to_object_id"] in code_ids for edge in after["relationships"])
    assert all(item["metrics"]["coverage_status"] == "unknown" for item in after["metric_snapshots"])
    assert after["quality_profiles"] and after["task_contexts"]
    assert all(context["confidence"] is None for context in after["task_contexts"])
    assert all(profile[field] is None for profile in after["quality_profiles"]
        for field in ("risk_score", "coverage_score", "release_score", "automation_feasibility", "confidence"))
    archive = service.source_ingestion.snapshots.materialize(source["content_ref"], project_id=v["project_id"], source_id=source["id"],
        content_hash=tree_hash, max_files=5000, max_bytes=100 * 1024 * 1024, max_file_bytes=10 * 1024 * 1024)
    assert all((archive / name).read_bytes() == body for name, body in files)
    image_id = next(ref.split(":", 1)[1] for ref in result["result"]["object_refs"] if ref.startswith("image_revision:"))
    with actor_scope(UserProfile.model_validate(v["owner"])):
        header, payload = app.state.container.image_revisions.frozen_snapshot(v["project_id"], image_id)
    assert header.manifest_id == manifest.manifest_id and payload["manifest_hash"] == manifest.content_hash
    from apps.api.app.infrastructure.persistence.materialization_command_models import MaterializationCommandInputRecord
    from apps.api.app.infrastructure.persistence.materialization_command_repository import MaterializationCommandInputRepository
    from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
    from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
    with session_scope() as session:
        original_input = MaterializationCommandInputRepository._from_row(session.get(MaterializationCommandInputRecord, result["id"]))
        assert (original_input.manifest_id, original_input.manifest_hash) == (manifest.manifest_id, manifest.content_hash)
        assert session.get(ToolInvocationRecord, result["id"]).materialization_input_hash == original_input.content_hash
    report = os.getenv("EXWEB_MATERIALIZATION_INPUT_REPORT")
    if report:
        with Path(report).open("x") as output:
            json.dump({"schema": "nasus.exweb-frozen-materialization-input.v1", "verified_at": datetime.now(timezone.utc).isoformat(),
                "repository": "https://github.com/kunben-duck/exweb.git", "commit": AFTER, "tree_hash": tree_hash,
                "file_count": 126, "source_export_deleted": True, "fresh_archive_cache": True,
                "reacquisition_count": len(calls), "exact_archive_file_bytes_verified": True,
                "manifest_unchanged": True, "source_facts_unchanged": True,
                "original_canonical_source_input_verified": True,
                "materialization_input_hash": original_input.content_hash,
                "unaudited_business_edges_absent": True, "inventory_does_not_claim_quality_coverage": True,
                "compatibility_profile_scores_and_confidence_are_unknown": True,
                "postgres_private_minio": True, "native_provider_verified": False,
                "external_model_or_target_execution_verified": False,
                "automatic_recovery_or_full_quality_closure_verified": False}, output, indent=2)
