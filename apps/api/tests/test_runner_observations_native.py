"""Real Node/Chromium/HTTP/PG/private MinIO, with an explicit local UI fixture.

This does not execute exweb or establish independent business-oracle authority.
"""
from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from threading import RLock, Thread
import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from apps.api.app.infrastructure.persistence.database import get_database_url
from apps.api.app.infrastructure.persistence.quality_loop_repository import QualityLoopRepository
from apps.api.app.infrastructure.quality_loop import LegacyQualityRunWorkspace
from apps.api.app.infrastructure.quality_loop.sqlalchemy_workspaces import SQLAlchemyQualityRunWorkspace
from apps.api.app.infrastructure.runner.adapters import HttpAutomationRunner
from apps.api.app.infrastructure.runner.run_orchestrator import RunOrchestrator
from apps.api.app.infrastructure.runner.request_wire import runner_request_body
from apps.api.app.application.quality_loop.runner_port import AutomationRunnerCommand
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage


@pytest.fixture
def native_runner(tmp_path):
    storage = ObjectStorage()
    if not get_database_url().startswith("postgresql") or not storage.config.s3_enabled:
        pytest.skip("requires disposable PostgreSQL and private MinIO test storage")
    node = shutil.which("node")
    assert node, "native runner validation requires the configured Node runtime"

    class Target(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith('/http-'):
                if self.path == '/http-slow': time.sleep(1.25)
                body = b'{"message":"native HTTP fixture","nested":{"a/b":{"~key":[1,true]}}}'
                status = 200
                if self.path == '/http-failure': status = 500
                if self.path == '/http-precise': body = b'{"value":0.10000000000000000001}'
                if self.path == '/http-duplicate': body = b'{"value":1,"value":1}'
                if self.path == '/http-empty': status, body = 204, b''
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('X-Proof', 'observed')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                try: self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError): pass
                return
            body = '<!doctype html><html lang="zh"><body><h1>订单已退款 🦆</h1></body></html>'.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_POST(self):
            submitted = self.rfile.read(int(self.headers['Content-Length']))
            body = json.dumps({'body': submitted.decode('utf-8')}, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args): pass

    target = ThreadingHTTPServer(("127.0.0.1", 0), Target)
    target_thread = Thread(target=target.serve_forever, daemon=True)
    target_thread.start()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    endpoint = f"http://127.0.0.1:{port}"
    token = "isolated-native-runner-test-token-20261010"
    env = {key: value for key, value in os.environ.items() if not key.startswith("NASUS_")}
    env.update(NASUS_ENV="local", NASUS_RUNNER_HOST="127.0.0.1", NASUS_RUNNER_PORT=str(port),
        NASUS_RUNNER_SERVICE_TOKEN=token, NASUS_RUNNER_ALLOWED_HOSTS="127.0.0.1")
    root = Path(__file__).resolve().parents[3]
    with (tmp_path / "native-runner.log").open("wb") as output:
        process = subprocess.Popen([node, "apps/runner/src/server.mjs"], cwd=root, env=env,
            stdout=output, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 15
            while True:
                assert process.poll() is None, (tmp_path / "native-runner.log").read_text()
                try:
                    ready = httpx.get(endpoint + "/readyz", timeout=1)
                    if ready.status_code == 200: break
                except httpx.HTTPError: pass
                assert time.monotonic() < deadline, "isolated runner did not become ready"
                time.sleep(.05)
            yield HttpAutomationRunner(endpoint, token), f"http://127.0.0.1:{target.server_port}", storage
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            target.shutdown()
            target.server_close()
            target_thread.join(timeout=5)


@pytest.mark.parametrize("workspace_kind", ["production", "compatibility"])
@pytest.mark.parametrize("kind,status,states,observed,passed,failed", [
    ("assertion", "passed", ["passed", "passed"], 1, 1, 0),
    ("failure", "failed", ["passed", "failed", "not_executed"], 1, 0, 1),
    ("deadline", "failed", ["passed", "interrupted", "not_executed"], 0, 0, 0),
    ("navigation", "passed", ["passed"], 0, 0, 0),
])
def test_native_step_observations_survive_pg_and_private_archive(native_runner, workspace_kind, kind, status, states, observed, passed, failed):
    runner, base_url, storage = native_runner
    repository = QualityLoopRepository()
    state = SimpleNamespace(us_items={}, run_details={}, runs={}, execution_evidence={})
    lock = RLock()
    workspace = LegacyQualityRunWorkspace(state, SimpleNamespace(mutation_guard=lambda: lock,
        quality_loop_repository=repository))
    if workspace_kind == "production": workspace = SQLAlchemyQualityRunWorkspace(repository)
    steps = [{"action": "goto", "path": "/"}]
    if kind == "assertion": steps.append({"action": "assert_text", "selector": "h1", "text": "订单已退款 🦆"})
    if kind == "failure": steps.extend([{"action": "assert_text", "selector": "h1", "text": "this oracle must fail"},
        {"action": "assert_visible", "selector": "h1"}])
    if kind == "deadline": steps.extend([{"action": "wait_for", "selector": "#not-present", "timeout_ms": 30000},
        {"action": "assert_visible", "selector": "h1"}])
    project_id, us_id = "native-receipt-" + uuid4().hex, "native-ui-fixture-" + uuid4().hex
    orchestrator = RunOrchestrator(workspace, SimpleNamespace(current_task_context=lambda *args: None), storage, runner=runner)
    outcome = orchestrator.execute_automation(project_id, us_id, invocation_input={"runner_request": {
        "base_url": base_url, "steps": steps, "timeout_ms": 1000 if kind == "deadline" else 10000,
        "automation_asset_ref": "explicit-local-fixture:not-business-approval", "automation_script_id": "local-receipt-script",
    }})
    assert outcome.run.status == status
    fresh = QualityLoopRepository()
    stored = fresh.get_run_detail(project_id, outcome.run.id)
    assert stored.execution_plan == steps
    assert stored.us_id == us_id and stored.target_base_url == base_url
    assert stored.automation_asset_ref == outcome.run.automation_asset_ref
    assert stored.automation_script_id == outcome.run.automation_script_id
    assert stored.execution_timeout_ms == outcome.run.execution_timeout_ms
    assert stored.retry_of_run_id == outcome.run.retry_of_run_id and stored.attempt == outcome.run.attempt
    if kind == "failure":
        repository.replace_failure_analysis(project_id, [stored.model_copy(update={"healing_depth": 1})], [])
        healed = QualityLoopRepository().get_run_detail(project_id, outcome.run.id)
        assert healed.healing_depth == 1 and healed.execution_plan == steps
        assert healed.target_base_url == base_url and healed.automation_script_id == stored.automation_script_id
    evidence = fresh.list_execution_evidence(project_id)
    assert evidence and all(item.case_ref is None for item in evidence)
    report = next(item for item in evidence if item.storage_ref.endswith("runner-result.json"))
    assert report.storage_ref.startswith("s3://")
    wire = storage.get_bytes(report.storage_ref)
    assert "sha256:" + hashlib.sha256(wire).hexdigest() == report.content_hash
    payload = json.loads(wire)
    receipt = payload["execution_receipt"]
    request = payload["execution_request"]
    original = AutomationRunnerCommand(job_id=request["job_id"], project_id=request["project_id"],
        us_id=request["us_id"], base_url=request["base_url"], steps=tuple(request["steps"]),
        timeout_ms=request["timeout_ms"], metadata=request["metadata"])
    assert payload["execution_request_hash"] == receipt["request_hash"]
    assert receipt["request_hash"] == "sha256:" + hashlib.sha256(runner_request_body(original)).hexdigest()
    assert request["steps"] == steps and request["base_url"] == base_url
    assert payload["execution_receipt_verified"] is True
    assert payload["business_coverage_verified"] is payload["target_build_verified"] is False
    assert receipt["project_id"] == project_id and receipt["us_id"] == us_id
    assert receipt["runner_job_id"] == outcome.run.runner_job_id
    assert [item["status"] for item in receipt["steps"]] == states
    assert receipt["observed_assertion_count"] == observed
    assert receipt["passed_assertion_count"] == passed and receipt["failed_assertion_count"] == failed
    assert receipt["business_coverage_verified"] is receipt["target_build_verified"] is False
    if kind == "deadline":
        assert payload["runner_status"] == "timed_out"
    assert "订单" not in json.dumps(receipt, ensure_ascii=False)


@pytest.mark.parametrize("workspace_kind", ["production", "compatibility"])
def test_native_failed_run_commit_does_not_leave_visible_evidence(native_runner, monkeypatch, workspace_kind):
    runner, base_url, storage = native_runner
    repository = QualityLoopRepository()
    state = SimpleNamespace(us_items={}, run_details={}, runs={}, execution_evidence={})
    lock = RLock()
    workspace = LegacyQualityRunWorkspace(state, SimpleNamespace(mutation_guard=lambda: lock,
        quality_loop_repository=repository))
    if workspace_kind == "production": workspace = SQLAlchemyQualityRunWorkspace(repository)
    project_id, us_id = "atomic-native-" + uuid4().hex, "local-oracle-" + uuid4().hex

    def fail_run_mapping(*args):
        raise RuntimeError("injected run persistence failure after native execution")

    monkeypatch.setattr(repository, "_assign_run", fail_run_mapping)
    orchestrator = RunOrchestrator(workspace, SimpleNamespace(current_task_context=lambda *args: None), storage, runner=runner)
    with pytest.raises(RuntimeError, match="injected run persistence failure"):
        orchestrator.execute_automation(project_id, us_id, invocation_input={"runner_request": {
            "base_url": base_url, "steps": [{"action": "goto", "path": "/"},
                {"action": "assert_text", "selector": "h1", "text": "订单已退款 🦆"}], "timeout_ms": 10000,
        }})
    fresh = QualityLoopRepository()
    assert fresh.list_run_details(project_id) == []
    assert fresh.list_execution_evidence(project_id) == []
    assert not state.run_details and not state.runs and not state.execution_evidence


def test_native_execution_keeps_the_dispatched_context_instead_of_the_latest(native_runner):
    runner, base_url, storage = native_runner
    contexts = iter([SimpleNamespace(id="original-dispatched-context"), SimpleNamespace(id="later-context")])
    workspace = SQLAlchemyQualityRunWorkspace(QualityLoopRepository())
    project_id, us_id = "context-native-" + uuid4().hex, "context-fixture-" + uuid4().hex
    orchestrator = RunOrchestrator(workspace, SimpleNamespace(current_task_context=lambda *args: next(contexts)), storage, runner=runner)
    outcome = orchestrator.execute_automation(project_id, us_id, invocation_input={"runner_request": {
        "base_url": base_url, "steps": [{"action": "goto", "path": "/"},
            {"action": "assert_text", "selector": "h1", "text": "订单已退款 🦆"}], "timeout_ms": 10000,
    }})
    assert outcome.run.task_context_id == "original-dispatched-context"
    assert QualityLoopRepository().get_run_detail(project_id, outcome.run.id).task_context_id == "original-dispatched-context"
    evidence = QualityLoopRepository().list_execution_evidence(project_id)
    report = next(item for item in evidence if item.storage_ref.endswith("runner-result.json"))
    payload = json.loads(storage.get_bytes(report.storage_ref))
    assert payload["task_context_id"] == "original-dispatched-context"
    assert payload["execution_request"]["metadata"]["task_context_id"] == "original-dispatched-context"
    assert payload["execution_request_hash"] == payload["execution_receipt"]["request_hash"]
