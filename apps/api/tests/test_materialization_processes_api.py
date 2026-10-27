"""SIGKILL/new-PID input recovery, not automatic dispatch or atomic completion."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import select

from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.image_revision_models import ImageRevisionRecord
from apps.api.app.infrastructure.persistence.materialization_command_models import MaterializationCommandInputRecord
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
from apps.api.tests.test_materialization_command_inputs_api import events
from apps.api.tests.test_materialization_source_inputs_api import running_materialization
from apps.api.tests.test_source_access_api import policy
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_ingestion_access_api import facts, grant_tester
from apps.api.tests.test_source_refresh_api import read


def worker(v, command, tmp_path, *, mode, window="none", actor=None):
    assert engine.dialect.name == "postgresql" and engine.url.database.startswith("nasus_test_")
    assert os.getenv("NASUS_TEST_OBJECT_STORAGE_MODE") == "minio"
    cache = tmp_path / (mode + "-" + uuid4().hex)
    environment = {**os.environ, "NASUS_SOURCE_CACHE_DIR": str(cache / "source"),
        "NASUS_SOURCE_SNAPSHOT_CACHE_DIR": str(cache / "snapshots")}
    process = subprocess.Popen([sys.executable, "-m", "apps.api.tests.materialization_process_probe"],
        cwd=Path(__file__).resolve().parents[3], env=environment,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    process.stdin.write(json.dumps({"project_id": v["project_id"], "invocation_id": command["id"],
        "actor_id": (actor or v["owner"])["id"], "mode": mode, "window": window}) + "\n")
    process.stdin.flush()
    return process


def killed_worker(v, command, tmp_path, window, *, actor=None):
    process = worker(v, command, tmp_path, mode="interrupt", window=window, actor=actor)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=120), "Worker did not reach the committed boundary"
        line = process.stdout.readline()
        assert line, process.stderr.read() if process.poll() is not None else "Commit marker missing"
        marker = json.loads(line)
        assert marker["pid"] == process.pid and marker["boundary"] == window and not marker["calls"]
        process.kill()
        assert process.wait(timeout=10) == -signal.SIGKILL
        with session_scope() as session:
            assert session.get(ToolInvocationRecord, command["id"]).status == "running"
            assert session.get(MaterializationCommandInputRecord, command["id"]).content_hash == marker["input_hash"]
            if marker["candidate_id"]:
                assert session.get(ImageRevisionRecord, marker["candidate_id"]).manifest_id == marker["input"]["manifest_id"]
        return marker
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


def restored_worker(v, command, tmp_path, *, actor=None, rejected=None):
    process = worker(v, command, tmp_path, mode="restore", actor=actor)
    try:
        output, errors = process.communicate(timeout=120)
        assert process.returncode == (3 if rejected else 0), errors
        result = json.loads(output)
        assert result["pid"] == process.pid and not result["calls"]
        assert result["status"] == ("rejected" if rejected else "restored")
        if rejected:
            assert result["code"] == rejected
        return result
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


@pytest.mark.parametrize("window", ["after_admission", "after_candidate"])
def test_materialization_sigkill_keeps_original_source_input(evidence_api, tmp_path, monkeypatch, window):
    v = evidence_api
    command = running_materialization(v, monkeypatch)
    manifest, before = SourceSnapshotRepository().latest_manifest(v["project_id"]), facts(v)
    marker = killed_worker(v, command, tmp_path, window)
    assert facts(v) == before
    admitted = events(command)
    assert len(admitted) == 1
    v["path"].unlink()
    result = restored_worker(v, command, tmp_path)
    assert result["pid"] != marker["pid"]
    assert result["input"] == marker["input"] and result["input_hash"] == marker["input_hash"]
    assert result["candidate_manifest_id"] == manifest.manifest_id
    assert SourceSnapshotRepository().latest_manifest(v["project_id"]) == manifest
    assert facts(v).raw_assets == before.raw_assets and events(command) == admitted


def test_restarted_materialization_rejects_new_head_without_rebinding(evidence_api, tmp_path, monkeypatch):
    v = evidence_api
    command = running_materialization(v, monkeypatch)
    marker = killed_worker(v, command, tmp_path, "after_admission")
    v["path"].write_text("class DifferentExplicitInput:\n    pass\n")
    v["invoke"]("system_image.sources.ingest")
    head, before, admitted = SourceSnapshotRepository().latest_manifest(v["project_id"]), facts(v), events(command)
    result = restored_worker(v, command, tmp_path, rejected="materialization_sources_changed")
    assert result["pid"] != marker["pid"] and facts(v) == before and events(command) == admitted
    assert SourceSnapshotRepository().latest_manifest(v["project_id"]) == head
    with session_scope() as session:
        assert session.get(MaterializationCommandInputRecord, command["id"]).content_hash == marker["input_hash"]


def test_restarted_materialization_rechecks_current_source_acl(evidence_api, tmp_path, monkeypatch):
    v = evidence_api
    grant_tester(v)
    policy(v, (v["member"]["id"],))
    command = running_materialization(v, monkeypatch, headers=v["member_headers"])
    marker = killed_worker(v, command, tmp_path, "after_admission", actor=v["member"])
    admitted, before = events(command), facts(v)
    policy(v)
    restored_worker(v, command, tmp_path, actor=v["member"], rejected="source_access_denied")
    assert facts(v) == before and events(command) == admitted
    policy(v, (v["member"]["id"],))
    result = restored_worker(v, command, tmp_path, actor=v["member"])
    assert result["input"] == marker["input"] and result["input_hash"] == marker["input_hash"]
    assert events(command) == admitted


def test_exweb_materialization_survives_sigkill_without_source_export(evidence_api, tmp_path, monkeypatch):
    root = os.getenv("EXWEB_SOURCE_REFRESH_GIT_ROOT")
    if not root:
        pytest.skip("explicit reviewed exweb Git export required")
    from apps.api.tests.exweb_git_trees import AFTER, read_git_tree
    files, tree_hash, _ = read_git_tree(Path(root), AFTER)
    assert len(files) == 126
    export = tmp_path / "exweb-materialization-source"
    export.mkdir()
    for name, content in files:
        path = export / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    v = evidence_api
    v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "code", "source_uri": str(export)}]})
    v["invoke"]("system_image.sources.ingest")
    source = next(item for item in read(v)["sources"] if item["source_uri"] == str(export))
    command = running_materialization(v, monkeypatch)
    head, before = SourceSnapshotRepository().latest_manifest(v["project_id"]), facts(v)
    marker = killed_worker(v, command, tmp_path, "after_admission")
    assert facts(v) == before
    shutil.rmtree(export)
    result = restored_worker(v, command, tmp_path)
    assert result["pid"] != marker["pid"] and result["input"] == marker["input"]
    assert result["input_hash"] == marker["input_hash"] and result["candidate_manifest_id"] == head.manifest_id
    assert facts(v).raw_assets == before.raw_assets and SourceSnapshotRepository().latest_manifest(v["project_id"]) == head
    assert len(events(command)) == 1
    archive = SourceIngestionService().snapshots.materialize(source["content_ref"], project_id=v["project_id"],
        source_id=source["id"], content_hash=tree_hash, max_files=5000, max_bytes=100 * 1024 * 1024,
        max_file_bytes=10 * 1024 * 1024)
    assert all((archive / name).read_bytes() == body for name, body in files)
    report = os.getenv("EXWEB_MATERIALIZATION_PROCESS_REPORT")
    if report:
        with Path(report).open("x") as output:
            json.dump({"schema": "nasus.exweb-materialization-process-input.v1",
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "repository": "https://github.com/kunben-duck/exweb.git", "commit": AFTER,
                "tree_hash": tree_hash, "file_count": 126, "postgres_private_minio": True,
                "killed_pid": marker["pid"], "restarted_pid": result["pid"], "sigkill_verified": True,
                "original_canonical_source_input_verified": True, "input_hash": marker["input_hash"],
                "source_export_deleted": True, "reacquisition_count": len(result["calls"]),
                "exact_archive_file_bytes_verified": True, "source_facts_unchanged": True,
                "manifest_unchanged": True, "automatic_dispatch_verified": False,
                "worker_lease_cancellation_verified": False, "atomic_canonical_completion_verified": False,
                "native_provider_or_external_model_verified": False,
                "target_execution_or_full_quality_closure_verified": False}, output, indent=2)
