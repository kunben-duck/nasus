"""Preflight or run the isolated, fixed exweb RunPlan verification."""
import argparse
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
from tempfile import mkdtemp
from urllib.parse import urlsplit

import httpx
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


ROOT = Path(__file__).resolve().parents[1]
LOCAL = {"localhost", "127.0.0.1", "::1"}
PIN = re.compile(r"sha256:[0-9a-f]{64}")
LEGACY_REPORT_SCHEMA = "nasus.exweb-canonical-handoff-verification.v1"
REPORT_SCHEMA = "nasus.exweb-canonical-handoff-verification.v2"
CLEANUP_LEDGER_SCHEMA = "nasus.exweb-original-cleanup-ledger.v1"
CLEANUP_WITNESS_SCHEMA = "nasus.exweb-post-teardown-archive-witness.v1"
CLEANUP_WITNESS_SCOPE = "independent_read_only_archive_verifier_not_public_api_or_release"
NATIVE_REPORT_SCHEMA = "nasus.exweb-native-runtime-probe.v1"
HISTORY_CANARY = "apps/api/tests/test_http_fixture_history_postgres.py"
TEST = "apps/api/tests/test_run_plan_fixture_handoff_exweb.py"
REVIEWED_CASE_COUNT = 4
ROLES = ("maven", "postgres", "redis")
CHECK_NAME = re.compile(r"[a-z][a-z0-9_]{0,95}")
CASE_LABEL = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
MAX_SUMMARY_INPUT = 16 * 1024 * 1024
HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
ORACLE_LABELS = {"passed": "passed", "failed": "failed", "interrupted": "interrupted", "not_executed": "not executed"}
NATIVE_OBSERVATION_LABELS = {
    "owner_read": "Read own session",
    "other_user_read": "Read another user's session",
    "other_tenant_read": "Read another tenant's session",
    "closed_read": "Read a closed session",
    "session_in_postgres": "Matching session rows in PostgreSQL",
    "session_survives_restart": "List sessions after target restart",
}


def probe_module():
    spec = importlib.util.spec_from_file_location("exweb_probe_preflight", ROOT / "scripts/verify-exweb-runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def isolated_environment(env):
    keys = {"NASUS_TEST_DATABASE_URL": "NASUS_DATABASE_URL", "NASUS_TEST_S3_ENDPOINT": "NASUS_S3_ENDPOINT",
        "NASUS_TEST_S3_ACCESS_KEY": "NASUS_S3_ACCESS_KEY", "NASUS_TEST_S3_SECRET_KEY": "NASUS_S3_SECRET_KEY",
        "TEST_TEMPORAL_ADDRESS": "NASUS_TEMPORAL_ADDRESS"}
    result = {key: env.get(key) or env.get(fallback) for key, fallback in keys.items()}
    if not all(result.values()):
        raise ValueError("Configure local PostgreSQL, MinIO and Temporal with the development runtime first.")
    db = make_url(result["NASUS_TEST_DATABASE_URL"])
    storage = urlsplit(result["NASUS_TEST_S3_ENDPOINT"])
    temporal = urlsplit("//" + result["TEST_TEMPORAL_ADDRESS"])
    if (db.get_backend_name() != "postgresql" or db.host not in LOCAL or db.query
            or storage.scheme not in {"http", "https"} or storage.hostname not in LOCAL
            or storage.username or storage.password or storage.path not in {"", "/"} or storage.query or storage.fragment
            or temporal.hostname not in LOCAL or not temporal.port or temporal.path or temporal.username
            or temporal.password or temporal.query or temporal.fragment):
        raise ValueError("Canonical verification requires loopback PostgreSQL, MinIO and Temporal endpoints.")
    return result, db, storage, temporal


def preflight(args, probe):
    settings, db, storage, temporal = isolated_environment(os.environ)
    if not all(shutil.which(tool) for tool in ("git", "docker", "node")):
        raise ValueError("Git, Docker and Node are required.")
    endpoint = probe.command(["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"]).stdout.decode().strip()
    if not endpoint.startswith("unix:///"):
        raise ValueError("Canonical verification requires a local Docker socket.")
    files = probe.source_inventory(args.repository.resolve(strict=True), probe.REVISION)
    if len(files) != 126 or not args.maven_cache.is_dir():
        raise ValueError("Expected all 126 reviewed files and an existing offline Maven cache directory.")
    images = {role: getattr(args, role + "_image_id") for role in ROLES}
    for role, image in images.items():
        if not PIN.fullmatch(image) or probe.pinned_image(image)["image_id"] != image:
            raise ValueError("The reviewed local " + role + " image ID is required; no image is pulled.")
    for host, port in ((db.host, db.port or 5432), (temporal.hostname, temporal.port)):
        with socket.create_connection((host, port), timeout=5):
            pass
    with httpx.Client(timeout=5, trust_env=False) as client:
        response = client.get(f"{storage.scheme}://{storage.netloc}/minio/health/live")
        if response.status_code != 200:
            raise ValueError("Local MinIO health check failed.")
    return settings, images


def verify_report(report, revision):
    if type(report) is not dict:
        return False
    n = report.get("case_count")
    cases = report.get("cases")
    pins = ("plan_digest", "plan_artifact_hash", "target_artifact_hash", "environment_inventory_hash", "history_digest")
    if (report.get("schema") not in (REPORT_SCHEMA, LEGACY_REPORT_SCHEMA) or report.get("source_commit") != revision
            or type(report.get("source_file_count")) is not int or report["source_file_count"] != 126
            or type(n) is not int or n != REVIEWED_CASE_COUNT
            or type(cases) is not list or len(cases) != n or any(not PIN.fullmatch(str(report.get(key))) for key in pins)
            or any(type(report.get(key)) is not int or report[key] != count for key, count in (
                ("fixture_setup_count", n), ("fixture_cleanup_count", n), ("native_runner_calls", 3 * n), ("workflow_count", 2 * n + 1)))
            or any(report.get(key) is not True for key in ("history_verified_after_cleanup", "owned_resources_cleanup_verified"))
            or any(report.get(key) is not False for key in ("independent_business_gold", "business_coverage_verified", "release_authorized"))):
        return False
    if any(type(case) is not dict or not isinstance(case.get("case_id"), str) or not case["case_id"].strip()
            or case.get("status") not in ("passed", "failed", "error", "timed_out")
            or not PIN.fullmatch(str(case.get("observation_digest"))) for case in cases):
        return False
    for case in cases:
        responses, oracles = case.get("responses"), case.get("oracles")
        if (type(responses) is not list or len(responses) > 100 or type(oracles) is not list or not 1 <= len(oracles) <= 100
                or not responses and case["status"] in ("passed", "failed")):
            return False
        if any(type(item) is not dict or item.get("method") not in HTTP_METHODS or type(item.get("response_status")) is not int
                or not 100 <= item["response_status"] <= 599 or not PIN.fullmatch(str(item.get("response_hash")))
                for item in responses):
            return False
        if any(type(item) is not dict or not PIN.fullmatch(str(item.get("oracle_digest")))
                or not isinstance(item.get("row_id"), str) or not item["row_id"]
                or type(item.get("status")) is not str or item["status"] not in ORACLE_LABELS for item in oracles):
            return False
        states = tuple(item["status"] for item in oracles)
        if len({item["row_id"] for item in oracles}) != len(oracles) or not consistent_oracles(case["status"], states):
            return False
    if len({case["case_id"] for case in cases}) != n:
        return False
    if report["schema"] == REPORT_SCHEMA:
        return (report.get("cleanup_history_verified_after_teardown") is True
                and valid_cleanup_observations(report, report.get("fixture_cleanup_observations")))
    return "fixture_cleanup_observations" not in report and "cleanup_history_verified_after_teardown" not in report


def valid_cleanup_observations(report, observations):
    if type(observations) is not list or len(observations) != report["fixture_cleanup_count"]:
        return False
    if any(type(item) is not dict or set(item) != {"case_id", "result_status", "result_digest"}
            or type(item["case_id"]) is not str or item["result_status"] not in ("passed", "failed", "error", "timed_out")
            or type(item["result_digest"]) is not str or not PIN.fullmatch(item["result_digest"]) for item in observations):
        return False
    return (sorted(item["case_id"] for item in observations) == sorted(case["case_id"] for case in report["cases"])
            and len({item["result_digest"] for item in observations}) == len(observations))


def legacy_cleanup_observations(report, ledger):
    if (report["schema"] != LEGACY_REPORT_SCHEMA or type(ledger) is not dict
            or set(ledger) != {"schema", "plan_digest", "plan_artifact_hash", "observations"}
            or ledger["schema"] != CLEANUP_LEDGER_SCHEMA
            or any(ledger[key] != report[key] for key in ("plan_digest", "plan_artifact_hash"))
            or not valid_cleanup_observations(report, ledger["observations"])):
        raise ValueError("Cleanup ledger does not match the original canonical report.")
    return ledger["observations"]


def legacy_archive_witness_observations(report, witness):
    if (report["schema"] != LEGACY_REPORT_SCHEMA or type(witness) is not dict
            or set(witness) != {"schema", "plan_digest", "plan_artifact_hash", "scope",
                "owned_resources_absent_before_and_after_read", "setup_count", "cases"}
            or witness["schema"] != CLEANUP_WITNESS_SCHEMA or witness["scope"] != CLEANUP_WITNESS_SCOPE
            or witness["owned_resources_absent_before_and_after_read"] is not True
            or type(witness["setup_count"]) is not int or witness["setup_count"] != report["fixture_setup_count"]
            or any(witness[key] != report[key] for key in ("plan_digest", "plan_artifact_hash"))
            or not valid_cleanup_observations(report, witness["cases"])):
        raise ValueError("Cleanup archive witness does not match the original canonical report.")
    return witness["cases"]


def consistent_oracles(status, states):
    if status == "passed":
        return all(state == "passed" for state in states)
    if status == "failed":
        return states.count("failed") == 1 and "interrupted" not in states
    return "failed" not in states and states.count("interrupted") <= 1


def native_checks(report, probe):
    if type(report) is not dict:
        raise ValueError("Missing native probe report.")
    source, checks, cleanup = (report.get(key) for key in ("source", "checks", "cleanup"))
    if (report.get("schema") != NATIVE_REPORT_SCHEMA or report.get("stage") != "observed"
            or report.get("oracle_authority") != "developer_probe_not_approved_specification"
            or "error" in report
            or any(report.get(key) is not False for key in ("nasus_runplan_verified", "llm_verified", "release_authorized"))
            or type(source) is not dict or source.get("repository") != probe.REPOSITORY or source.get("revision") != probe.REVISION
            or type(source.get("files")) is not list or len(source["files"]) != 126
            or type(cleanup) is not dict or cleanup.get("verified") is not True or cleanup.get("remaining_owned_resources") != []
            or type(checks) is not dict or not 1 <= len(checks) <= 128
            or any(type(key) is not str or not CHECK_NAME.fullmatch(key) or type(value) is not bool for key, value in checks.items())
            or report.get("status") != ("passed" if all(checks.values()) else "failed")):
        raise ValueError("Native probe report is incomplete or is not for the reviewed exweb revision.")
    inventory = "sha256:" + sha256(json.dumps(source["files"], sort_keys=True).encode()).hexdigest()
    if source.get("inventory_hash") != inventory:
        raise ValueError("Native probe source inventory does not match its recorded digest.")
    return checks


def native_observation_rows(report):
    """Display only fixed probe labels and scalar observations, never wire content."""
    evidence = report.get("evidence")
    if evidence is None:
        return []
    if type(evidence) is not list or len(evidence) > 256:
        raise ValueError("Invalid native observation collection.")
    selected = {}
    for item in evidence:
        if type(item) is not dict or type(item.get("check_id")) is not str:
            continue
        name = item["check_id"]
        if name not in NATIVE_OBSERVATION_LABELS:
            continue
        if name in selected:
            raise ValueError("Duplicate native observation.")
        if name == "session_in_postgres":
            count = item.get("row_count")
            if type(count) is not str or not re.fullmatch(r"0|[1-9][0-9]{0,8}", count):
                raise ValueError("Invalid native row count.")
            selected[name] = count
            continue
        status = item.get("status")
        if type(status) is not int or not 100 <= status <= 599 or not PIN.fullmatch(str(item.get("response_hash"))):
            raise ValueError("Invalid native HTTP observation.")
        response = item.get("response")
        suffix = (f"; {len(response)} entries returned"
            if name == "session_survives_restart" and type(response) is list else "")
        selected[name] = f"HTTP {status}{suffix}"
    return [(label, selected[name]) for name, label in NATIVE_OBSERVATION_LABELS.items() if name in selected]


def acceptance_summary(probe, *, native=None, canonical=None, cleanup_ledger=None, cleanup_archive_witness=None):
    if cleanup_ledger is not None and cleanup_archive_witness is not None:
        raise ValueError("Use at most one supplemental legacy cleanup input.")
    lines = ["# exweb Verification", "", f"Fixed source: `{probe.REVISION}` (126 files).", "",
        "This summary separates observed target behavior from RunPlan execution evidence. It grants no release approval.", "",
        "## Independent Docker Probe", ""]
    if native is None:
        lines.append("No independent probe report supplied.")
    else:
        checks = native_checks(native, probe)
        lines.extend([f"**{sum(checks.values())}/{len(checks)} checks passed.** Owned resources were cleaned up.", "",
            "These expectations are developer probes, not approved business requirements.", ""])
        observations = native_observation_rows(native)
        if observations:
            lines.extend(["| Scenario | Actual Observation |", "| --- | --- |"])
            lines.extend(f"| {label} | {observation} |" for label, observation in observations)
            lines.append("")
        lines.extend(["| Check | Observed Result |", "| --- | --- |"])
        lines.extend(f"| `{key}` | {'Passed' if value else 'Failed'} |" for key, value in checks.items())
    lines.extend(["", "## Canonical RunPlan", ""])
    if canonical is None:
        if cleanup_ledger is not None or cleanup_archive_witness is not None:
            raise ValueError("Supplemental cleanup evidence needs its original canonical report.")
        lines.append("No complete canonical report supplied. Dispatch, cleanup, and historical readback are not established by this summary.")
    else:
        if not verify_report(canonical, probe.REVISION):
            raise ValueError("Canonical RunPlan report is incomplete or is not for the reviewed exweb revision.")
        observations = canonical.get("fixture_cleanup_observations")
        cleanup_scope = "Post-teardown archive readback"
        if cleanup_ledger is not None:
            observations = legacy_cleanup_observations(canonical, cleanup_ledger)
            cleanup_scope = "Read-only pre-teardown PostgreSQL ledger"
        elif cleanup_archive_witness is not None:
            observations = legacy_archive_witness_observations(canonical, cleanup_archive_witness)
            cleanup_scope = "Independent post-teardown PostgreSQL/MinIO readback, not canonical API history"
        lines.extend([f"The report records {canonical['case_count']} observed cases, "
            f"{canonical['fixture_setup_count']} setups, and {canonical['fixture_cleanup_count']} observed cleanup operations. "
            f"It includes {canonical['native_runner_calls']} native Runner calls across "
            f"{canonical['workflow_count']} workflows. Historical readback was verified after resource cleanup.", "",
            "The real target was exercised with controlled test inputs and assertions, not independently approved "
            "acceptance criteria. Case failures are preserved. This is not a business coverage or release verdict.", "",
            "| Case | Result | HTTP Statuses | Oracle Results |", "| --- | --- | --- | --- |"])
        for index, case in enumerate(canonical["cases"], 1):
            label = f"`{case['case_id']}`" if CASE_LABEL.fullmatch(case["case_id"]) else f"Case {index}"
            responses = ", ".join(str(item["response_status"]) for item in case["responses"]) or "No response"
            states = [item["status"] for item in case["oracles"]]
            oracles = ", ".join(f"{states.count(status)} {ORACLE_LABELS[status]}" for status in sorted(set(states)))
            lines.append(f"| {label} | {case['status']} | {responses} | {oracles} |")
        if observations is None:
            lines.extend(["", "This legacy report does not distinguish cleanup assertions from archived workflow completion."])
        else:
            lines.extend(["", f"Fixture cleanup assertion outcomes ({cleanup_scope}):", "",
                "| Case | Cleanup Result |", "| --- | --- |"])
            by_case = {item["case_id"]: item["result_status"] for item in observations}
            for index, case in enumerate(canonical["cases"], 1):
                label = f"`{case['case_id']}`" if CASE_LABEL.fullmatch(case["case_id"]) else f"Case {index}"
                lines.append(f"| {label} | {by_case[case['case_id']]} |")
        lines.extend(["", f"RunPlan digest: `{canonical['plan_digest']}`."])
    return "\n".join(lines) + "\n"


def _report_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Verification report contains a duplicate JSON field.")
        result[key] = value
    return result


def _reject_nonfinite(_):
    raise ValueError("Verification report contains a non-finite JSON value.")


def read_report(path):
    with path.open("rb") as handle:
        body = handle.read(MAX_SUMMARY_INPUT + 1)
    if len(body) > MAX_SUMMARY_INPUT:
        raise ValueError("Verification report exceeds the summary byte limit.")
    value = json.loads(body.decode("utf-8"), object_pairs_hook=_report_fields, parse_constant=_reject_nonfinite)
    if value is None:
        raise ValueError("A supplied verification report cannot be null.")
    return value


def write_summary(args, probe):
    try:
        native = read_report(args.native_report) if args.native_report else None
        canonical = read_report(args.canonical_report) if args.canonical_report else None
        ledger = read_report(args.cleanup_ledger) if args.cleanup_ledger else None
        witness = read_report(args.cleanup_archive_witness) if args.cleanup_archive_witness else None
        rendered = acceptance_summary(probe, native=native, canonical=canonical, cleanup_ledger=ledger, cleanup_archive_witness=witness)
        with args.summary.open("x", encoding="utf-8") as handle:
            handle.write(rendered)
    except (OSError, ValueError):
        print("Could not write the summary. Provide complete reports for the fixed revision and a new output path.", file=sys.stderr)
        return 2
    print(f"Verification summary: {args.summary}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path)
    parser.add_argument("--maven-cache", type=Path)
    for role in ROLES:
        parser.add_argument("--" + role + "-image-id")
    parser.add_argument("--execute-reviewed-target", action="store_true")
    parser.add_argument("--summary", type=Path, help="Write a new read-only Markdown summary; never starts the target")
    parser.add_argument("--native-report", type=Path)
    parser.add_argument("--canonical-report", type=Path)
    supplemental = parser.add_mutually_exclusive_group()
    supplemental.add_argument("--cleanup-ledger", type=Path, help="Optional matching read-only ledger for a legacy canonical report")
    supplemental.add_argument("--cleanup-archive-witness", type=Path, help="Optional matching independent post-teardown readback for a legacy report")
    args = parser.parse_args(argv)
    cleanup_input = args.cleanup_ledger or args.cleanup_archive_witness
    image_args = [getattr(args, role + "_image_id") for role in ROLES]
    if args.summary:
        if (not (args.native_report or args.canonical_report) or args.execute_reviewed_target
                or args.repository or args.maven_cache or any(image_args) or (cleanup_input and not args.canonical_report)):
            parser.error("summary mode requires at least one report and cannot launch validation")
        return write_summary(args, probe_module())
    if args.native_report or args.canonical_report or cleanup_input:
        parser.error("report inputs require --summary")
    if args.repository is None or not all(image_args):
        parser.error("preflight and execution require --repository and all three reviewed image IDs")
    args.maven_cache = args.maven_cache or Path.home() / ".m2/repository"
    probe = probe_module()
    try:
        settings, images = preflight(args, probe)
    except (ValueError, OSError, ArgumentError, httpx.HTTPError, subprocess.TimeoutExpired, probe.ProbeFailure):
        print("exweb preflight failed. Check the reviewed origin/commit, offline cache, local image IDs and local runtime services.", file=sys.stderr)
        return 2
    print(f"Preflight passed for exweb {probe.REVISION} (126 fixed files).", flush=True)
    if not args.execute_reviewed_target:
        print("No target started. Supply --execute-reviewed-target to run the isolated verification.")
        return 0
    base = ROOT / "output/exweb-canonical-runs"
    base.mkdir(parents=True, exist_ok=True)
    run = Path(mkdtemp(prefix="run-", dir=base))
    log, report = run / "pytest.log", run / "verification.json"
    inherited = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "USER", "LANG", "LC_ALL") if key in os.environ}
    env = {**inherited, **settings, "EXWEB_EXECUTE_REVIEWED_NATIVE_BUILD": "1",
        "EXWEB_SOURCE_REFRESH_GIT_ROOT": str(args.repository.resolve()), "EXWEB_NATIVE_MAVEN_CACHE": str(args.maven_cache.resolve()),
        "EXWEB_CANONICAL_HANDOFF_REPORT": str(report),
        **{"EXWEB_NATIVE_" + role.upper() + "_IMAGE_ID": image for role, image in images.items()}}
    command = [sys.executable, "scripts/test-api-postgres.py", "--minio", HISTORY_CANARY, TEST,
        "-x", "-q", "--tb=short", "-o", "log_cli=true", "--log-cli-level=INFO"]
    if sys.platform == "darwin" and (awake := shutil.which("caffeinate")):
        command = [awake, "-i", *command]
    print(f"Running isolated verification. Log: {log}", flush=True)
    with log.open("x", encoding="utf-8") as handle:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=handle, stderr=subprocess.STDOUT, check=False)
    try:
        document = read_report(report) if result.returncode == 0 else None
        verified = verify_report(document, probe.REVISION) and document["schema"] == REPORT_SCHEMA
    except (ValueError, OSError):
        verified = False
    if not verified:
        print(f"Canonical verification did not pass. Inspect {log}", file=sys.stderr)
        return 1
    print(f"Verified execution, cleanup and historical readback: {report}")
    print("Observed failures are retained. This does not authorize release or prove business coverage.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
