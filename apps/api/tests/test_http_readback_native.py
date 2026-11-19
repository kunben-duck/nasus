"""Real Node/HTTP protocol specimens, not RealWorld or live-model acceptance."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import subprocess
from threading import Thread

import pytest

from apps.api.app.domain.quality_loop.http_readback import HTTP_READBACK_SCHEMA, validate_readback_steps
from apps.api.app.domain.quality_loop.http_runner_observations import verify_http_runner_observations
from apps.api.app.domain.quality_loop.runner_observations import RunnerObservationInvalid
from apps.api.app.infrastructure.runner.http_observation_artifacts import verify_http_response_artifacts


ROOT = Path(__file__).resolve().parents[3]
NODE = """
import { executeHttpJob } from './apps/runner/src/http-executor.mjs';
const chunks = []; for await (const chunk of process.stdin) chunks.push(chunk);
const wire = Buffer.concat(chunks), job = JSON.parse(wire);
const result = await executeHttpJob(job, { wireBody: wire });
process.stdout.write(JSON.stringify(result));
"""


def request(ident, method="GET", phase="exercise"):
    return dict(action="request", request_id=ident, method=method, path="/article", phase=phase,
        headers_json='{"Content-Type":"application/json"}', body_json='null' if method == 'GET' else '{"title":"changed"}')


def steps(*, skipped_mutation=True):
    result = [request("before"), dict(action="capture_snapshot", request_id="before", pointer="/article", snapshot_id="original"),
        request("edit", "PUT"), dict(action="assert_status", request_id="edit", value="403")]
    if skipped_mutation:
        result += [request("forbidden_after_failure", "PATCH"), dict(action="assert_status", request_id="forbidden_after_failure", value="200")]
    return result + [request("after", phase="readback"),
        dict(action="assert_unchanged", request_id="after", pointer="/article", snapshot_id="original")]


@pytest.fixture
def target():
    state = {"title": "original", "visits": [], "defective": True}
    class Target(BaseHTTPRequestHandler):
        def respond(self):
            state["visits"].append(self.command)
            length = int(self.headers.get("Content-Length", 0))
            if length:
                self.rfile.read(length)
            status = 200
            if self.command != "GET":
                if state["defective"]:
                    state["title"] = "changed"
                else:
                    status = 403
                if state.get("drop_mutation_response"):
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
            is_readback = self.command == "GET" and state["visits"].count("GET") > 1
            if is_readback:
                status = state.get("readback_status", status)
            body = json.dumps(state.get("readback_body") if is_readback and "readback_body" in state else {
                "article": {"title": state["title"], "body": "unchanged"}}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        do_GET = do_PUT = do_PATCH = respond
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Target)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def run(target, *, skipped_mutation=True):
    job = dict(job_id="readback-job", project_id="project", us_id="case", execution_kind="http",
        receipt_protocol=HTTP_READBACK_SCHEMA, base_url=target[0], timeout_ms=5000, steps=steps(skipped_mutation=skipped_mutation))
    wire = json.dumps(job).encode()
    import os
    result = subprocess.run(["node", "--input-type=module", "-e", NODE], input=wire, cwd=ROOT,
        env={**os.environ, "NASUS_RUNNER_ALLOWED_HOSTS": "127.0.0.1"}, capture_output=True, check=True, timeout=15)
    return job, json.loads(result.stdout)


def verify(job, result):
    from hashlib import sha256
    receipt = verify_http_runner_observations(result["execution_receipt"], job_id=job["job_id"], project_id=job["project_id"],
        us_id=job["us_id"], request_hash="sha256:" + sha256(json.dumps(job).encode()).hexdigest(), steps=tuple(job["steps"]),
        status=result["status"], protocol=job["receipt_protocol"])
    verify_http_response_artifacts(receipt, result["artifacts"], tuple(job["steps"]))
    return receipt


def test_failed_denial_still_reads_back_but_never_dispatches_later_mutation(target):
    job, result = run(target)
    receipt = verify(job, result)
    assert result["status"] == "failed"
    assert target[1]["visits"] == ["GET", "PUT", "GET"]
    assert receipt["failed_assertion_count"] == 2
    assert [item["status"] for item in receipt["steps"]] == ["passed", "passed", "passed", "failed",
        "not_executed", "not_executed", "passed", "failed"]
    assert receipt["target_build_verified"] is receipt["business_coverage_verified"] is False


def test_successful_denial_proves_original_data_unchanged(target):
    target[1]["defective"] = False
    job, result = run(target, skipped_mutation=False)
    assert verify(job, result)["failed_assertion_count"] == 0
    assert result["status"] == "passed" and target[1]["title"] == "original"


@pytest.mark.parametrize("override", [
    {"readback_status": 404},
    {"readback_status": 500},
    {"readback_body": {"error": "not found"}},
    {"readback_body": {"article": {"title": "original", "body": False}}},
])
def test_failed_or_changed_readback_cannot_prove_an_unchanged_resource(target, override):
    target[1].update(defective=False, **override)
    job, result = run(target, skipped_mutation=False)
    receipt = verify(job, result)
    assert result["status"] == "failed" and receipt["failed_assertion_count"] == 1
    assert receipt["steps"][-1]["status"] == "failed"
    assert target[1]["visits"] == ["GET", "PUT", "GET"]


def test_lost_write_response_is_not_retried_or_promoted_to_business_failure(target):
    target[1]["drop_mutation_response"] = True
    job, result = run(target, skipped_mutation=False)
    receipt = verify(job, result)
    assert result["status"] == "error" and receipt["failed_assertion_count"] == 0
    assert target[1]["title"] == "changed" and target[1]["visits"] == ["GET", "PUT"]
    assert [item["status"] for item in receipt["steps"]] == [
        "passed", "passed", "interrupted", "not_executed", "not_executed", "not_executed"]


@pytest.mark.parametrize("fault", ["skipped_write_passed", "readback_omitted", "assertion_forged"])
def test_backend_rejects_forged_readback_receipts(target, fault):
    job, result = run(target)
    forged = deepcopy(result)
    receipt = forged["execution_receipt"]
    if fault == "skipped_write_passed":
        receipt["steps"][4]["status"] = "passed"
    elif fault == "readback_omitted":
        receipt["steps"][6]["status"] = "not_executed"
    else:
        receipt["steps"][-1]["status"] = "passed"
        receipt["failed_assertion_count"] -= 1
        receipt["passed_assertion_count"] += 1
        import base64
        manifest = next(item for item in forged["artifacts"] if item["name"] == "http-execution.json")
        manifest["content_base64"] = base64.b64encode(json.dumps(receipt).encode()).decode()
    with pytest.raises(RunnerObservationInvalid):
        verify(job, forged)


@pytest.mark.parametrize("fault", ["write_readback", "undeclared", "duplicate_snapshot", "missing_snapshot", "invalid_pointer", "late_snapshot", "write_snapshot", "self_comparison", "non_readback_comparison"])
def test_complete_protocol_is_validated_before_dispatch(fault):
    values = steps()
    if fault == "write_readback":
        values[2]["phase"] = "readback"
    elif fault == "undeclared":
        values[0].pop("phase")
    elif fault == "duplicate_snapshot":
        values.insert(2, values[1].copy())
    elif fault == "missing_snapshot":
        values[-1]["snapshot_id"] = "unknown"
    elif fault == "late_snapshot":
        values.insert(3, values.pop(1))
    elif fault == "write_snapshot":
        values[0] = request("before", "POST")
    elif fault == "self_comparison":
        values[-1]["request_id"] = "before"
    elif fault == "non_readback_comparison":
        values[-2]["phase"] = "exercise"
    else:
        values[-1]["pointer"] = "/invalid~2"
    with pytest.raises(RunnerObservationInvalid):
        validate_readback_steps(tuple(values))


@pytest.mark.parametrize("index,field", [(0, "phase"), (0, "method"), (0, "request_id"), (0, "action"), (1, "request_id"), (1, "snapshot_id")])
def test_invalid_operand_types_fail_closed_without_internal_type_errors(index, field):
    values = steps()
    values[index][field] = {"untrusted": "not a string"}
    with pytest.raises(RunnerObservationInvalid):
        validate_readback_steps(tuple(values))
