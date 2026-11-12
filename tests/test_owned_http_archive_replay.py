"""Explicit archive specimens; actual fixed exweb blobs are verified separately."""
import base64
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.api.app.infrastructure.runner.request_wire import runner_request_body
from apps.api.app.infrastructure.runner.owned_target_environment import OwnedTargetEnvironmentInspector
from apps.api.tests.test_owned_target_environment import ARTIFACT, Commands, spec
from apps.api.tests.test_http_runner_observations import command, payload


ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location("archive_reader_under_test", ROOT / "scripts/verify-exweb-owned-http-archives.py")
reader = importlib.util.module_from_spec(loader)
loader.loader.exec_module(reader)


@pytest.fixture
def archive(tmp_path, spec, monkeypatch):
    report_path = tmp_path / "protocol.json"
    directory = report_path.with_suffix(".runner")
    directory.mkdir()
    inventory = OwnedTargetEnvironmentInspector(spec, command=Commands(spec)).inspect(ARTIFACT, require_work=lambda: None)
    source_body = b"explicit source protocol specimen, not exweb"
    files = [dict(path="explicit-source-" + str(index), mode="100644", git_blob=str(index)) for index in range(126)]
    probe = SimpleNamespace(source_inventory=lambda *_: files,
        command=lambda *_args, **_kwargs: SimpleNamespace(stdout=source_body))
    fake_loader = SimpleNamespace(exec_module=lambda _: None)
    monkeypatch.setattr(reader.importlib.util, "spec_from_file_location", lambda *_: SimpleNamespace(loader=fake_loader))
    monkeypatch.setattr(reader.importlib.util, "module_from_spec", lambda _: probe)
    report = dict(source=dict(revision="explicit-protocol-revision", files=[{**item, "content_hash": reader.digest(source_body)} for item in files]),
        build=dict(jar_hash=ARTIFACT), native_environment=dict(after=dict(inventory=inventory.inventory, observed_at=inventory.observed_at)),
        cleanup=dict(verified=True, remaining_owned_resources=[]), checks={},
        http_runner=dict(inventory=inventory.inventory, inventory_hash=inventory.inventory_hash, cases=[],
            executor_sources=[], execution_authorized=False, nasus_runplan_verified=False, release_authorized=False))
    report["http_runner"]["executor_sources"] = [dict(path=code, content_hash=reader.digest((ROOT / code).read_bytes()))
        for code in reader.EXECUTOR_SOURCE_PATHS]
    for label in sorted(reader.CASES):
        job = replace(command(), job_id="explicit-protocol-" + label, us_id=label, project_id=spec.project_id,
            base_url="http://127.0.0.1:8080", metadata=dict(target_artifact_hash=ARTIFACT))
        failed = label in {"closed_read", "bound_closed_read"}
        result = (payload(job, body=b'{"message":"HTTP fixture","nested":{"a/b":{"~name":[2]}}}',
            states=["passed", "passed", "failed", "not_executed", "not_executed"], status="failed") if failed else payload(job))
        wire, body = runner_request_body(job), json.dumps(result).encode()
        request, response = directory / (label + ".request.json"), directory / (label + ".result.json")
        request.write_bytes(wire)
        response.write_bytes(body)
        receipt = result["execution_receipt"]
        report["checks"]["runner_" + label] = not failed
        report["http_runner"]["cases"].append(dict(case_id=label, status=result["status"], request_archive=str(request),
            result_archive=str(response), request_hash=reader.digest(wire), result_hash=reader.digest(body), owned_inventory_hash=inventory.inventory_hash,
            **{field: receipt[field] for field in ("observed_assertion_count", "passed_assertion_count", "failed_assertion_count")}))
    report_path.write_text(json.dumps(report))
    return report_path, report


def test_complete_enriched_sources_and_original_failures_survive_readonly_replay(archive, monkeypatch):
    report_path, _ = archive
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: pytest.fail("archive read attempted execution"))
    result = reader.verify(report_path, Path("explicit-protocol-repository"))
    assert result["source_blobs_verified"] == 126 and result["original_jobs_verified"] == 7
    assert result["passed_jobs"] == 5 and result["failed_jobs"] == 2
    assert result["totals"]["failed"] == 2
    assert result["target_reexecuted"] is False and result["formal_coverage_verified"] is False
    assert result["executor_sources_verified"] == 10 and result["executor_git_blobs_verified"] == 0


def test_historical_executor_blob_must_match_the_original_archive_digest(archive, monkeypatch):
    report_path, report = archive
    sources = report["http_runner"]["executor_sources"]
    source = sources[0]
    body, oid, calls = b"older executor source, not a target command", "a" * 40, []
    source["content_hash"] = reader.digest(body)
    report_path.write_text(json.dumps(report))
    repository = Path("explicit-protocol-repository")
    with pytest.raises(ValueError):
        reader.verify(report_path, repository)

    probe = reader.importlib.util.module_from_spec(None)
    original_git = probe.command

    def local_git(args, *, env=None):
        if env is None:
            return original_git(args)
        calls.append(args[4:])
        assert args[:4] == ["git", "-C", str(ROOT), "cat-file"]
        assert args[5] == oid and env["GIT_NO_LAZY_FETCH"] == "1"
        return SimpleNamespace(stdout=(str(len(body)).encode() if args[4] == "-s" else body))

    monkeypatch.setattr(probe, "command", local_git)
    pins = [source["path"] + "=" + oid]
    verified = reader.verify(report_path, repository, executor_source_blobs=pins)
    assert verified["executor_sources_verified"] == 10 and verified["executor_git_blobs_verified"] == 1
    assert calls == [["-s", oid], ["blob", oid]]
    source["content_hash"] = reader.digest(b"different original")
    report_path.write_text(json.dumps(report))
    with pytest.raises(ValueError):
        reader.verify(report_path, repository, executor_source_blobs=pins)


def test_private_executor_bundle_replays_without_worktree_sources_and_cannot_be_overwritten(archive, monkeypatch):
    report_path, report = archive
    original = report_path.read_bytes()
    repository = Path("explicit-protocol-repository")
    result = reader.verify(report_path, repository, preserve_executor_sources=True)
    assert result["executor_source_bundle_created"] and not result["executor_source_bundle_verified"]
    path = report_path.with_suffix(".runner") / "executor-sources.json"
    body = path.read_bytes()
    assert path.stat().st_mode & 0o777 == 0o600 and report_path.read_bytes() == original
    monkeypatch.setattr(reader, "ROOT", report_path.parent / "no-worktree-sources")
    replay = reader.verify(report_path, repository)
    assert replay["executor_source_bundle_verified"] and not replay["executor_source_bundle_created"]
    assert replay["executor_sources_verified"] == 10 and replay["executor_git_blobs_verified"] == 0
    with pytest.raises(ValueError):
        reader.verify(report_path, repository, preserve_executor_sources=True)
    assert path.read_bytes() == body

    bundle = json.loads(body)
    source = report["http_runner"]["executor_sources"][0]["path"]
    bundle["sources"][source] = base64.b64encode(b"not the original bytes").decode("ascii")
    path.write_text(json.dumps(bundle))
    with pytest.raises(ValueError):
        reader.verify(report_path, repository)


@pytest.mark.parametrize("pin", ["../../etc/passwd=" + "a" * 40, "apps/runner/src/owned-http-cli.mjs=HEAD:path",
    "apps/runner/src/owned-http-cli.mjs=--filters", "apps/runner/src/owned-http-cli.mjs"])
def test_executor_blob_pins_reject_paths_and_git_expressions(pin):
    with pytest.raises(ValueError):
        reader.executor_blob_pins([pin])


@pytest.mark.parametrize("fault", ["missing-source", "source-bytes", "source-identity", "missing-case", "duplicate-case", "inventory", "cleanup",
    "wire", "response", "passed-flag", "executor-code", "executor-missing", "executor-duplicate", "formal-authority"])
def test_bad_or_incomplete_archives_cannot_be_reported_as_verified(archive, fault):
    report_path, report = archive
    runner = report["http_runner"]
    if fault == "missing-source": report["source"]["files"].pop()
    if fault == "source-bytes": report["source"]["files"][0]["content_hash"] = "sha256:" + "0" * 64
    if fault == "source-identity": report["source"]["files"][0]["path"] = "other"
    if fault == "missing-case": runner["cases"].pop()
    if fault == "duplicate-case": runner["cases"][-1] = runner["cases"][0]
    if fault == "inventory": runner["inventory_hash"] = "sha256:" + "0" * 64
    if fault == "cleanup": report["cleanup"]["remaining_owned_resources"] = ["not-cleaned"]
    if fault in {"wire", "response"}:
        entry = runner["cases"][0]
        path = Path(entry["request_archive"] if fault == "wire" else entry["result_archive"])
        path.write_bytes(path.read_bytes() + b" ")
    if fault == "passed-flag": report["checks"]["runner_" + runner["cases"][0]["case_id"]] = True
    if fault == "executor-code": runner["executor_sources"][0]["content_hash"] = "sha256:" + "0" * 64
    if fault == "executor-missing": runner["executor_sources"].pop()
    if fault == "executor-duplicate": runner["executor_sources"][-1] = runner["executor_sources"][0]
    if fault == "formal-authority": runner["execution_authorized"] = True
    report_path.write_text(json.dumps(report))
    with pytest.raises(ValueError): reader.verify(report_path, Path("explicit-protocol-repository"))
