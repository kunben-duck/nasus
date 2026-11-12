"""Read original probe archives after cleanup, without executing or granting coverage."""
import argparse
import base64
import binascii
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.app.application.quality_loop.runner_port import AutomationRunnerCommand
from apps.api.app.domain.quality_loop.native_environment import NativeEnvironmentObservation
from apps.api.app.infrastructure.runner.adapters import HttpAutomationRunner
from apps.api.app.infrastructure.runner.http_observation_verifier import HTTPRunnerObservationVerifier
from apps.api.app.infrastructure.runner.owned_target_environment import _object
from apps.api.app.infrastructure.runner.request_wire import runner_request_body
from scripts.exweb_http_executor_sources import EXECUTOR_SOURCE_PATHS


CASES = {"health", "create", "owner_read", "close", "closed_read", "bound_session_lifecycle", "bound_closed_read"}
MAX_EXECUTOR_SOURCE_BYTES = 512 * 1024
MAX_EXECUTOR_BUNDLE_BYTES = len(EXECUTOR_SOURCE_PATHS) * (4 * ((MAX_EXECUTOR_SOURCE_BYTES + 2) // 3) + 256) + 256
EXECUTOR_BUNDLE_SCHEMA = "nasus.exweb-executor-source-bundle.v1"


def digest(body):
    return "sha256:" + hashlib.sha256(body).hexdigest()


def require(value):
    if not value:
        raise ValueError("original owned HTTP archive could not be verified")


def executor_blob_pins(values):
    pins = {}
    for value in values:
        path, separator, oid = value.partition("=")
        require(bool(separator) and path in EXECUTOR_SOURCE_PATHS and path not in pins
            and re.fullmatch(r"[a-f0-9]{40}", oid) is not None)
        pins[path] = oid
    return pins


def read_executor_bundle(path):
    if not path.exists() and not path.is_symlink():
        return None
    require(path.is_file() and not path.is_symlink())
    with path.open("rb") as handle:
        body = handle.read(MAX_EXECUTOR_BUNDLE_BYTES + 1)
    require(len(body) <= MAX_EXECUTOR_BUNDLE_BYTES)
    bundle = _object(body)
    require(set(bundle) == {"schema", "sources"} and bundle["schema"] == EXECUTOR_BUNDLE_SCHEMA
        and type(bundle["sources"]) is dict and set(bundle["sources"]) == set(EXECUTOR_SOURCE_PATHS))
    values = {}
    for source, encoded in bundle["sources"].items():
        require(type(encoded) is str and len(encoded) <= 4 * ((MAX_EXECUTOR_SOURCE_BYTES + 2) // 3))
        try:
            values[source] = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("original executor source bundle has invalid bytes") from None
    return values


def preserve_executor_bundle(path, sources):
    bundle = {"schema": EXECUTOR_BUNDLE_SCHEMA,
        "sources": {source: base64.b64encode(body).decode("ascii") for source, body in sources.items()}}
    body = (json.dumps(bundle, sort_keys=True, separators=(",", ":")) + "\n").encode()
    require(len(body) <= MAX_EXECUTOR_BUNDLE_BYTES)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".executor-sources-") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())
        os.link(handle.name, path, follow_symlinks=False)


def verify_executor_sources(entries, pins, git, archived):
    require(type(entries) is list and len(entries) == len(EXECUTOR_SOURCE_PATHS))
    verified = {}
    for item in entries:
        require(type(item) is dict and set(item) == {"path", "content_hash"})
        path = item["path"]
        require(type(path) is str and path in EXECUTOR_SOURCE_PATHS and path not in verified)
        if archived is not None:
            body = archived[path]
        elif path in pins:
            prefix = ["git", "-C", str(ROOT), "cat-file"]
            offline = {"GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_NO_REPLACE_OBJECTS": "1"}
            size = git([*prefix, "-s", pins[path]], env=offline).stdout.strip()
            require(size.isdigit() and len(size) <= 6 and 0 < int(size) <= MAX_EXECUTOR_SOURCE_BYTES)
            body = git([*prefix, "blob", pins[path]], env=offline).stdout
            require(len(body) == int(size))
        else:
            source = (ROOT / path).resolve()
            require(source == ROOT / path and source.is_file())
            with source.open("rb") as handle:
                body = handle.read(MAX_EXECUTOR_SOURCE_BYTES + 1)
        require(0 < len(body) <= MAX_EXECUTOR_SOURCE_BYTES and digest(body) == item["content_hash"])
        verified[path] = body
    return verified


def verify(report_path, repository, *, executor_source_blobs=(), preserve_executor_sources=False):
    pins = executor_blob_pins(executor_source_blobs)
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
    directory = report_path.with_suffix(".runner")
    require(directory.is_dir() and not directory.is_symlink())
    totals = dict(observed=0, passed=0, failed=0, requests=0, bindings=0)
    statuses = []
    for item in runner["cases"]:
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
    require(all(runner[key] is False for key in ("execution_authorized", "nasus_runplan_verified", "release_authorized")))
    bundle_path = directory / "executor-sources.json"
    archived = read_executor_bundle(bundle_path)
    require(archived is None or (not pins and not preserve_executor_sources))
    executor_sources = verify_executor_sources(runner["executor_sources"], pins, probe.command, archived)
    if preserve_executor_sources:
        preserve_executor_bundle(bundle_path, executor_sources)
    return dict(source_blobs_verified=len(files), original_jobs_verified=len(statuses), passed_jobs=statuses.count("passed"),
        failed_jobs=statuses.count("failed"), physical_response_bytes_verified=True, totals=totals,
        executor_sources_verified=len(executor_sources), executor_git_blobs_verified=len(pins),
        executor_source_bundle_verified=archived is not None, executor_source_bundle_created=preserve_executor_sources,
        target_reexecuted=False,
        formal_coverage_verified=False, cleanup_verified=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--executor-source-blob", action="append", default=[], metavar="PATH=GIT_BLOB",
        help="Read the given historical executor bytes from the local Nasus Git object database")
    parser.add_argument("--preserve-executor-sources", action="store_true",
        help="Save verified original executor bytes in a new private sidecar beside the request/result archives")
    args = parser.parse_args()
    print(json.dumps(verify(args.report.resolve(), args.repository.resolve(),
        executor_source_blobs=args.executor_source_blob, preserve_executor_sources=args.preserve_executor_sources), sort_keys=True))
