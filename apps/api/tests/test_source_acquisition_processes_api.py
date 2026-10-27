"""Actual SIGKILL/new-process recovery, not automatic Temporal dispatch or lease."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import select

from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
from apps.api.tests.test_source_acquisition_intents_api import running_command
from apps.api.tests.test_source_acquisition_results_api import command_results, acquire_events
from apps.api.tests.test_source_access_api import policy
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_ingestion_access_api import facts, grant_tester
from apps.api.tests.test_source_refresh_api import add_optional, read, selection


def process_request(v, command, tmp_path, *, mode, window, actor=None):
    assert engine.dialect.name == "postgresql" and engine.url.database.startswith("nasus_test_")
    assert os.getenv("NASUS_TEST_OBJECT_STORAGE_MODE") == "minio"
    environment = os.environ.copy()
    cache = tmp_path / (mode + "-" + uuid4().hex)
    environment.update({"NASUS_SOURCE_CACHE_DIR": str(cache / "source"),
        "NASUS_SOURCE_SNAPSHOT_CACHE_DIR": str(cache / "snapshots")})
    process = subprocess.Popen([sys.executable, "-m", "apps.api.tests.source_acquisition_process_probe"],
        cwd=Path(__file__).resolve().parents[3], env=environment,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    request = {"project_id": v["project_id"], "invocation_id": command["id"],
        "actor_id": (actor or v["owner"])["id"], "mode": mode, "window": window}
    process.stdin.write(json.dumps(request) + "\n")
    process.stdin.flush()
    return process


def kill_committed_worker(v, command, tmp_path, window, *, actor=None):
    process = process_request(v, command, tmp_path, mode="capture", window=window, actor=actor)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=40), "Acquisition worker did not commit before timeout"
        line = process.stdout.readline()
        assert line, process.stderr.read() if process.poll() is not None else "Worker did not emit a commit marker"
        marker = json.loads(line)
        assert marker["pid"] == process.pid and marker["boundary"] == window
        process.kill()
        assert process.wait(timeout=10) == -signal.SIGKILL
        assert command_results(command)
        with session_scope() as session:
            assert session.get(ToolInvocationRecord, command["id"]).status == "running"
        return marker
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


def restored_worker(v, command, tmp_path, *, actor=None, rejected=None):
    process = process_request(v, command, tmp_path, mode="restore", window="none", actor=actor)
    try:
        output, errors = process.communicate(timeout=40)
        assert process.returncode == (3 if rejected else 0), errors
        result = json.loads(output)
        assert result["pid"] == process.pid
        assert result["status"] == ("rejected" if rejected else "restored")
        if rejected:
            assert result["code"] == rejected and not result["calls"]
        return result
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


@pytest.mark.parametrize("mode", ["selected", "whole_project"])
@pytest.mark.parametrize("window", ["after_capture", "after_manifest"])
def test_sigkill_then_fresh_process_consumes_original_results(evidence_api, tmp_path, monkeypatch, mode, window):
    v = evidence_api
    optional, image, source = add_optional(v, tmp_path)
    v["path"].write_text("class FixedBeforeKill:\n    pass\n")
    optional.write_text("# US-1\nOriginal content before worker kill.\n")
    command = running_command(v, selection(image, source["id"]) if mode == "selected" else {}, monkeypatch)
    marker = kill_committed_worker(v, command, tmp_path, window)
    saved = {item["source_id"]: item for item in command_results(command)}
    assert len(saved) == (2 if mode == "whole_project" and window == "after_manifest" else 1)
    v["path"].write_text("class MutableAfterKill:\n    pass\n")
    optional.write_text("# US-1\nLater content after worker kill.\n")
    result = restored_worker(v, command, tmp_path)
    assert marker["pid"] != result["pid"] and not set(result["calls"]).intersection(saved)
    assert len(marker["calls"]) + len(result["calls"]) == (1 if mode == "selected" else 2)
    after = facts(v)
    for ident, original in saved.items():
        source_fact = next(item for item in after.raw_assets if item.id == ident)
        assert (source_fact.content_hash, source_fact.content_ref, source_fact.last_ingested_at) == (
            original["content_hash"], original["content_ref"], original["acquired_at"])
        assert original in command_results(command)
        assert not any("MutableAfterKill" in unit.text or "Later content" in unit.text
            for unit in SourceIngestionService().extract_text_units(source_fact))
    head = SourceSnapshotRepository().latest_manifest(v["project_id"])
    before = command_results(command)
    replay = restored_worker(v, command, tmp_path)
    assert not replay["calls"] and command_results(command) == before
    assert SourceSnapshotRepository().latest_manifest(v["project_id"]) == head
    assert len(acquire_events(command, "system_image.source_acquisition.manifest_committed")) == 1
    assert len(acquire_events(command, "system_image.source_acquisition.result_recorded")) == len(before)


def test_restarted_process_cannot_roll_back_another_commands_head(evidence_api, tmp_path, monkeypatch):
    v = evidence_api
    command = running_command(v, {}, monkeypatch)
    kill_committed_worker(v, command, tmp_path, "after_manifest")
    saved = command_results(command)
    v["path"].write_text("class NewExplicitCommand:\n    pass\n")
    v["invoke"]("system_image.sources.ingest")
    head, before = SourceSnapshotRepository().latest_manifest(v["project_id"]), facts(v)
    restored_worker(v, command, tmp_path, rejected="source_acquisition_scope_changed")
    assert command_results(command) == saved and facts(v) == before
    assert SourceSnapshotRepository().latest_manifest(v["project_id"]) == head


def test_restarted_process_rechecks_real_source_acl(evidence_api, tmp_path, monkeypatch):
    v = evidence_api
    grant_tester(v)
    policy(v, (v["member"]["id"],))
    command = running_command(v, {}, monkeypatch, headers=v["member_headers"])
    kill_committed_worker(v, command, tmp_path, "after_manifest", actor=v["member"])
    saved, head = command_results(command), SourceSnapshotRepository().latest_manifest(v["project_id"])
    policy(v)
    before = facts(v)
    restored_worker(v, command, tmp_path, actor=v["member"], rejected="source_access_denied")
    assert command_results(command) == saved and facts(v) == before
    policy(v, (v["member"]["id"],))
    result = restored_worker(v, command, tmp_path, actor=v["member"])
    assert not result["calls"] and command_results(command) == saved
    assert SourceSnapshotRepository().latest_manifest(v["project_id"]) == head


def test_exweb_archive_survives_sigkill_and_independent_process_recovery(evidence_api, tmp_path, monkeypatch):
    root = os.getenv("EXWEB_SOURCE_REFRESH_GIT_ROOT")
    if not root:
        pytest.skip("explicit reviewed exweb Git export required")
    from apps.api.tests.exweb_git_trees import AFTER, read_git_tree
    files, tree_hash, _ = read_git_tree(Path(root), AFTER)
    assert len(files) == 126
    exported = tmp_path / "exweb-process-source"
    exported.mkdir()
    for name, body in files:
        path = exported / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    v = evidence_api
    v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "code", "source_uri": str(exported)}]})
    image = read(v)
    source = next(item for item in image["sources"] if item["source_uri"] == str(exported))
    command = running_command(v, selection(image, source["id"]), monkeypatch)
    marker = kill_committed_worker(v, command, tmp_path, "after_manifest")
    saved = deepcopy(command_results(command))
    assert len(saved) == 1 and saved[0]["file_count"] == 126 and saved[0]["content_hash"] == tree_hash
    head = SourceSnapshotRepository().latest_manifest(v["project_id"])
    (exported / "README.md").write_bytes(b"Controlled content after worker kill.\n")
    (exported / "pom.xml").unlink()
    result = restored_worker(v, command, tmp_path)
    assert marker["pid"] != result["pid"] and not result["calls"]
    assert command_results(command) == saved and SourceSnapshotRepository().latest_manifest(v["project_id"]) == head
    reader = SourceIngestionService()
    archive = reader.snapshots.materialize(saved[0]["content_ref"], project_id=v["project_id"], source_id=source["id"],
        content_hash=tree_hash, max_files=5000, max_bytes=100 * 1024 * 1024, max_file_bytes=10 * 1024 * 1024)
    assert all((archive / name).read_bytes() == body for name, body in files)
    report = os.getenv("EXWEB_SOURCE_ACQUISITION_PROCESS_REPORT")
    if report:
        with Path(report).open("x") as output:
            json.dump({"schema": "nasus.exweb-source-acquisition-process-recovery.v1",
                "verified_at": datetime.now(timezone.utc).isoformat(), "commit": AFTER, "tree_hash": tree_hash,
                "file_count": 126, "original_running_canonical_command": True, "postgres_private_minio": True,
                "killed_pid": marker["pid"], "restarted_pid": result["pid"], "sigkill_verified": True,
                "reacquisition_count": len(result["calls"]), "exact_archive_file_bytes_verified": True,
                "independent_native_process_restart_verified": True, "automatic_dispatch_verified": False,
                "temporal_lease_cancellation_verified": False, "external_model_or_target_execution_verified": False}, output, indent=2)
