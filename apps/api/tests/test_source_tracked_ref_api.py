"""Canonical ref registration and capture with real Git, PG and private storage."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from apps.api.app.application.agent.orchestrator import ConversationOrchestrator
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceBindingRecord, SourceRevisionRecord
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.system_image_repository import SystemImageRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.system_image.git_source_connector import GitSourceConnector
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
from apps.api.app.main import app
from apps.api.tests.exweb_git_trees import AFTER, git_bytes, read_git_tree
from apps.api.tests.test_git_source_connector import _git, _create_repository
from apps.api.tests.test_source_refresh_api import evidence_api, read, refresh, selection


def install_connector(monkeypatch, tmp_path):
    ingestion = app.state.container.system_image.lifecycle._operations.source_ingestion
    connector = GitSourceConnector(cache_dir=tmp_path / "git-cache", allowed_schemes={"file"})
    monkeypatch.setattr(ingestion, "connectors", (connector, *ingestion.connectors))
    return connector


def register_refs(v, origin, refs):
    v["invoke"]("system_image.sources.register", {"source_specs": [
        {"source_type": "code", "source_uri": origin.as_uri(), "tracked_ref": ref} for ref in refs]})


def revision_for(project_id, source_id, manifest):
    with session_scope() as session:
        binding = session.scalar(select(SourceBindingRecord).where(
            SourceBindingRecord.project_id == project_id, SourceBindingRecord.legacy_source_id == source_id))
        member = next(item for item in manifest.members if item.binding_id == binding.binding_id)
        return session.get(SourceRevisionRecord, member.source_revision_id).external_revision


def test_same_git_uri_ref_registration_capture_selected_refresh_and_replay(evidence_api, tmp_path, monkeypatch):
    v = evidence_api
    origin = tmp_path / "origin"
    original_commit = _create_repository(origin)
    _git(origin, "branch", "-M", "main")
    _git(origin, "branch", "release")
    _git(origin, "tag", "-a", "v1", "-m", "annotated release")
    install_connector(monkeypatch, tmp_path)
    refs = ("refs/heads/main", "refs/heads/release", "refs/tags/v1")
    register_refs(v, origin, refs)
    v["invoke"]("system_image.sources.ingest")
    before = read(v)
    sources = [item for item in before["sources"] if item["source_uri"] == origin.as_uri()]
    assert len(sources) == 3 and {item["tracked_ref"] for item in sources} == set(refs)
    persisted = SystemImageRepository().load_raw_assets()[v["project_id"]]
    assert {item.tracked_ref for item in persisted if item.source_uri == origin.as_uri()} == set(refs)
    repo = SourceSnapshotRepository()
    historical = repo.get_manifest(v["project_id"], before["source_manifest"]["manifest_id"])
    assert all(revision_for(v["project_id"], item["id"], historical) == original_commit for item in sources)
    register_refs(v, origin, refs)
    repeated = read(v)
    assert repeated["sources"] == before["sources"] and repeated["source_manifest"] == before["source_manifest"]
    selected = next(item for item in sources if item["tracked_ref"] == refs[0])
    (origin / "checkout.py").write_text("def changed_main():\n    return 2\n")
    _git(origin, "add", ".")
    _git(origin, "commit", "-m", "controlled main change")
    after_commit = _git(origin, "rev-parse", "HEAD")
    refresh(v, selection(before, selected["id"]))
    after = read(v)
    current = repo.get_manifest(v["project_id"], after["source_manifest"]["manifest_id"])
    assert revision_for(v["project_id"], selected["id"], current) == after_commit
    assert [item for item in after["sources"] if item["id"] != selected["id"]] == [
        item for item in before["sources"] if item["id"] != selected["id"]]
    assert after["objects"] == before["objects"] and after["candidate_revision"] == before["candidate_revision"]
    old = next(item for item in repo.materialization_sources(historical) if item.id == selected["id"])
    assert old.tracked_ref == refs[0]
    assert "def checkout" in SourceIngestionService().extract_text_units(old)[0].text
    register_refs(v, origin, ["refs/heads/not-present"])
    selected_missing = next(item for item in read(v)["sources"] if item["tracked_ref"] == "refs/heads/not-present")
    failed = refresh(v, selection(after, selected_missing["id"]), status="failed")
    assert failed["result"]["followup_reason"] == "required_source_ingestion_failed"
    assert repo.get_manifest(v["project_id"], historical.manifest_id) == historical


@pytest.mark.parametrize("ref", ["HEAD", "main", "refs/heads/a:b", "--upload-pack=evil"])
def test_invalid_ref_does_not_write_or_fall_back_to_default(evidence_api, ref):
    v = evidence_api
    before = deepcopy(read(v)["sources"])
    response = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "conversation_id": v["conversation"].json()["id"], "tool_id": "system_image.sources.register",
        "input": {"project_id": v["project_id"], "source_specs": [
            {"source_type": "code", "source_uri": "https://example.com/repo.git", "tracked_ref": ref}]}})
    assert response.status_code == 200 and response.json()["status"] == "failed", response.text
    assert read(v)["sources"] == before


def test_chat_source_message_preserves_explicit_ref_for_the_original_goal():
    for prefix in ("code path", "代码路径"):
        specs = ConversationOrchestrator._extract_system_image_source_specs(
            prefix + " https://example.com/repo.git，tracked_ref=refs/heads/release，US docs URI /requirements.md")
        assert specs[0] == {"source_type": "code", "source_uri": "https://example.com/repo.git", "tracked_ref": "refs/heads/release"}
        assert "tracked_ref" not in specs[1]


def test_reviewed_exweb_commit_tracked_branches_capture_and_historical_replay(evidence_api, tmp_path, monkeypatch):
    root = os.getenv("EXWEB_TRACKED_REF_GIT_ROOT")
    if not root:
        pytest.skip("explicit reviewed exweb Git snapshot required")
    assert os.getenv("NASUS_TEST_OBJECT_STORAGE_MODE") == "minio"
    files, tree_hash, _ = read_git_tree(Path(root), AFTER)
    assert len(files) == 126
    origin = tmp_path / "reviewed-exweb-origin"
    origin.mkdir()
    git_bytes(origin, "init")
    git_bytes(origin, "fetch", "--depth", "1", "--no-tags", Path(root).as_uri(), AFTER)
    git_bytes(origin, "checkout", "--detach", AFTER)
    git_bytes(origin, "branch", "main")
    git_bytes(origin, "branch", "release")
    git_bytes(origin, "checkout", "main")
    v = evidence_api
    install_connector(monkeypatch, tmp_path)
    register_refs(v, origin, ("refs/heads/main", "refs/heads/release"))
    v["invoke"]("system_image.sources.ingest")
    before = read(v)
    selected = next(item for item in before["sources"] if item["tracked_ref"] == "refs/heads/main")
    released = next(item for item in before["sources"] if item["tracked_ref"] == "refs/heads/release")
    assert selected["file_count"] == released["file_count"] == 126
    repo = SourceSnapshotRepository()
    historical = repo.get_manifest(v["project_id"], before["source_manifest"]["manifest_id"])
    assert revision_for(v["project_id"], selected["id"], historical) == AFTER
    readme = origin / "README.md"
    readme.write_bytes(readme.read_bytes() + b"\nControlled Nasus tracked-ref verification, not upstream behavior.\n")
    git_bytes(origin, "add", "README.md")
    git_bytes(origin, "-c", "user.email=nasus-test@example.com", "-c", "user.name=Nasus Test",
        "commit", "-m", "controlled tracked-ref fixture")
    fixture_commit = git_bytes(origin, "rev-parse", "HEAD").decode().strip()
    result = refresh(v, selection(before, selected["id"]))
    after = read(v)
    current = repo.get_manifest(v["project_id"], after["source_manifest"]["manifest_id"])
    assert revision_for(v["project_id"], selected["id"], current) == fixture_commit
    assert revision_for(v["project_id"], released["id"], current) == AFTER
    assert next(item for item in after["sources"] if item["id"] == released["id"]) == released
    assert after["objects"] == before["objects"] and after["candidate_revision"] == before["candidate_revision"]
    old = next(item for item in repo.materialization_sources(historical) if item.id == selected["id"])
    replayed = {item.relative_path: item.text for item in SourceIngestionService().extract_text_units(old)}
    expected_original = {path: body.decode("utf-8") for path, body in files}
    assert replayed == expected_original
    latest = next(item for item in repo.materialization_sources(current) if item.id == selected["id"])
    captured_after = {item.relative_path: item.text for item in SourceIngestionService().extract_text_units(latest)}
    expected_after = {**expected_original, "README.md": expected_original["README.md"]
        + "\nControlled Nasus tracked-ref verification, not upstream behavior.\n"}
    assert captured_after == expected_after
    report_path = os.getenv("EXWEB_TRACKED_REF_REPORT")
    if report_path:
        with Path(report_path).open("x", encoding="utf-8") as output:
            json.dump({"verified_at": datetime.now(timezone.utc).isoformat(),
                "repository": "https://github.com/kunben-duck/exweb.git", "original_commit": AFTER,
                "original_git_tree_hash": tree_hash, "original_file_count": len(files),
                "controlled_fixture_commit": fixture_commit, "canonical_invocation_id": result["id"],
                "before_manifest": before["source_manifest"], "after_manifest": after["source_manifest"],
                "git_connector_actual": True, "private_file_origin": True, "postgresql": True, "minio": True,
                "unchanged_release_commit": AFTER, "historical_code_replayed": True,
                "historical_file_count_replayed": len(replayed), "historical_git_tree_match": True,
                "controlled_modified_file_count": 1, "controlled_unchanged_file_count": 125,
                "controlled_change_not_upstream_commit": True, "upstream_remote_reacquired": False,
                "external_model_called": False, "target_executed": False, "automatic_update_verified": False},
                output, ensure_ascii=False, indent=2)
            output.write("\n")
