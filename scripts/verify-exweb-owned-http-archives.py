"""Read original probe archives after cleanup, without executing or granting coverage."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.app.application.quality_loop.runner_port import AutomationRunnerCommand
from apps.api.app.domain.quality_loop.native_environment import NativeEnvironmentObservation
from apps.api.app.infrastructure.runner.adapters import HttpAutomationRunner
from apps.api.app.infrastructure.runner.http_observation_verifier import HTTPRunnerObservationVerifier
from apps.api.app.infrastructure.runner.owned_target_environment import _object
from apps.api.app.infrastructure.runner.request_wire import runner_request_body


CASES = {"health", "create", "owner_read", "close", "closed_read", "bound_session_lifecycle", "bound_closed_read"}


def digest(body):
    return "sha256:" + hashlib.sha256(body).hexdigest()


def require(value):
    if not value:
        raise ValueError("original owned HTTP archive could not be verified")


def verify(report_path, repository):
    spec = importlib.util.spec_from_file_location("readonly_exweb_probe", ROOT / "scripts/verify-exweb-runtime.py")
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    report = _object(report_path.read_bytes())
    runner = report["http_runner"]
    files = probe.source_inventory(repository, report["source"]["revision"])
    require(len(files) == len(report["source"]["files"]) == 126)
    require(files == [{key: item[key] for key in ("path", "mode", "git_blob")} for item in report["source"]["files"]])
    for item in report["source"]["files"]:
        body = probe.command(["git", "-C", str(repository), "cat-file", "blob", item["git_blob"]]).stdout
        require(digest(body) == item["content_hash"])
    require(runner["inventory"] == report["native_environment"]["after"]["inventory"])
    NativeEnvironmentObservation(runner["inventory"], runner["inventory_hash"], report["native_environment"]["after"]["observed_at"])
    require(runner["inventory"]["artifact_hash"] == report["build"]["jar_hash"])
    require(report["cleanup"] == {"verified": True, "remaining_owned_resources": []})
    require(len(runner["cases"]) == 7 and {item["case_id"] for item in runner["cases"]} == CASES)
    totals = dict(observed=0, passed=0, failed=0, requests=0, bindings=0)
    statuses = []
    for item in runner["cases"]:
        directory = report_path.with_suffix(".runner")
        request_path, result_path = (directory / (item["case_id"] + suffix) for suffix in (".request.json", ".result.json"))
        require(str(request_path) == item["request_archive"] and str(result_path) == item["result_archive"]
            and not request_path.is_symlink() and not result_path.is_symlink()
            and request_path.stat().st_size <= 512 * 1024 and result_path.stat().st_size <= 24 * 1024 * 1024)
        wire, body = request_path.read_bytes(), result_path.read_bytes()
        raw = _object(wire)
        job = AutomationRunnerCommand(job_id=raw["job_id"], project_id=raw["project_id"], us_id=raw["us_id"],
            base_url=raw["base_url"], steps=tuple(raw["steps"]), timeout_ms=raw["timeout_ms"], metadata=raw["metadata"],
            kind=raw["execution_kind"], http_protocol=raw["receipt_protocol"])
        require(wire == runner_request_body(job) and digest(wire) == item["request_hash"] and digest(body) == item["result_hash"])
        require(job.project_id == runner["inventory"]["project_id"] and job.base_url == "http://127.0.0.1:8080"
            and job.metadata["target_artifact_hash"] == runner["inventory"]["artifact_hash"])
        result = HttpAutomationRunner._result_from_payload(job, _object(body), request_hash=digest(wire))
        receipt = HTTPRunnerObservationVerifier().verify(job, result)
        require(result.status == item["status"] and report["checks"]["runner_" + item["case_id"]] is (result.status == "passed"))
        require(item["owned_inventory_hash"] == runner["inventory_hash"])
        for key, field in (("observed", "observed_assertion_count"), ("passed", "passed_assertion_count"), ("failed", "failed_assertion_count")):
            require(receipt[field] == item[field])
            totals[key] += receipt[field]
        totals["requests"] += len(receipt["requests"])
        totals["bindings"] += len(receipt.get("bindings", []))
        require(receipt["business_coverage_verified"] is False and receipt["target_build_verified"] is False)
        statuses.append(result.status)
    for item in runner["executor_sources"]:
        source = (ROOT / item["path"]).resolve()
        require(source.is_relative_to(ROOT) and digest(source.read_bytes()) == item["content_hash"])
    require(all(runner[key] is False for key in ("execution_authorized", "nasus_runplan_verified", "release_authorized")))
    return dict(source_blobs_verified=len(files), original_jobs_verified=len(statuses), passed_jobs=statuses.count("passed"),
        failed_jobs=statuses.count("failed"), physical_response_bytes_verified=True, totals=totals,
        target_reexecuted=False, formal_coverage_verified=False, cleanup_verified=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.report.resolve(), args.repository.resolve()), sort_keys=True))
