"""Private developer evidence. File fences are not a production PG/Tool ledger."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from apps.api.app.application.quality_loop.http_fixtures import (
    HttpFixtureDispatchAlreadyClaimed, HttpFixtureLifecycleApplicationService, HttpFixturePhaseRecord, HttpFixtureScope,
)
from apps.api.app.application.quality_loop.runner_port import AutomationRunnerCommand, OwnedTargetHttpExecution
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixtures import HTTP_FIXTURE_SCHEMA
from apps.api.app.infrastructure.runner.adapters import HttpAutomationRunner
from apps.api.app.infrastructure.runner.http_fixture_verifier import OwnedHttpFixtureObservationVerifier
from apps.api.app.infrastructure.runner.owned_target_environment import _object
from apps.api.app.infrastructure.runner.request_wire import runner_request_body, runner_request_hash


def digest(body):
    return "sha256:" + hashlib.sha256(body).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def write_original(path, body):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as target:
        target.write(body)
        target.flush()
        os.fsync(target.fileno())


def read_original(path, limit=24 * 1024 * 1024):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("fixture probe archive is missing, redirected or oversized")
    return path.read_bytes()


class ProbeFixtureJournal:
    """Original private artifacts only, never a Nasus business persistence adapter."""
    def __init__(self, directory, *, readonly=False):
        self.directory, self.readonly = Path(directory), readonly
        if not readonly:
            self.directory.mkdir(mode=0o700, exist_ok=False)

    def paths(self, scope, phase):
        name = acceptance_digest([scope.project_id, scope.attempt_id, scope.case_id, phase])[7:]
        return {key: self.directory / (name + suffix) for key, suffix in (
            ("claim", ".claim.json"), ("request", ".request.json"), ("result", ".result.json"), ("done", ".done.json"))}

    def inspect(self, scope, phase):
        paths = self.paths(scope, phase)
        if not paths["claim"].exists():
            return None
        claim = _object(read_original(paths["claim"], 512 * 1024))
        if claim["scope"] != asdict(scope) or claim["phase"] != phase:
            raise ValueError("fixture probe claim scope differs")
        command = AutomationRunnerCommand(**{**claim["command"], "steps": tuple(claim["command"]["steps"])})
        if claim["request_hash"] != runner_request_hash(command):
            raise ValueError("fixture probe original command differs")
        if not paths["done"].exists():
            return HttpFixturePhaseRecord(command, None)
        seal = _object(read_original(paths["done"], 1024))
        request, result = read_original(paths["request"], 512 * 1024), read_original(paths["result"])
        if seal != {"request_hash": digest(request), "result_hash": digest(result)} or request != runner_request_body(command):
            raise ValueError("fixture probe original output seal differs")
        decoded = HttpAutomationRunner._result_from_payload(command, _object(result), request_hash=digest(request))
        execution = OwnedTargetHttpExecution(decoded, request, result, scope.environment_id, scope.inventory_hash)
        return HttpFixturePhaseRecord(command, execution)

    def claim(self, scope, phase, command, *, require_current):
        require_current()
        if self.readonly:
            raise ValueError("readonly fixture replay cannot dispatch a missing phase")
        try:
            write_original(self.paths(scope, phase)["claim"], encoded({"scope": asdict(scope), "phase": phase,
                "command": asdict(command), "request_hash": runner_request_hash(command)}))
        except FileExistsError:
            raise HttpFixtureDispatchAlreadyClaimed() from None

    def complete(self, scope, phase, command, execution, *, require_current):
        require_current()
        prior = self.inspect(scope, phase)
        if self.readonly or prior is None or prior.command != command or prior.execution is not None:
            raise ValueError("fixture probe completion cannot replace original dispatch")
        paths = self.paths(scope, phase)
        write_original(paths["request"], execution.request_body)
        write_original(paths["result"], execution.result_body)
        write_original(paths["done"], encoded({"request_hash": digest(execution.request_body), "result_hash": digest(execution.result_body)}))


def recipe(case_id, *, setup_failure=False, cleanup_failure=False):
    path = "/api/v1/finance/chat/sessions"
    def request(ident, method, relative, body="null"):
        return dict(action="request", request_id=ident, method=method, path=relative,
            headers_json='{"Accept":"application/json","Content-Type":"application/json"}', body_json=body)
    def status(ident, value):
        return dict(action="assert_status", request_id=ident, value=str(value))
    def state(ident, value):
        return dict(action="assert_json", request_id=ident, pointer="/status", value_json=json.dumps(value))
    cleanup = [request("close", "POST", path + "/{{session}}/close"), status("close", 200), state("close", "CLOSED")]
    if cleanup_failure:
        # Preserve the independently declared 404; the original target returns 500.
        cleanup.extend([request("closed", "GET", path + "/{{session}}"), status("closed", 404)])
    return dict(schema=HTTP_FIXTURE_SCHEMA, case_id=case_id,
        preconditions_digest=acceptance_digest(["anonymous owned session", "ACTIVE"]),
        setup=["Create an anonymous ACTIVE session in the original owned target"],
        cleanup=["Close the exact resource returned by this setup"],
        setup_steps=[request("create", "POST", path, json.dumps({"title": "Explicit HTTP fixture " + case_id, "channel": "web"})),
            dict(action="capture_json", request_id="create", pointer="/sessionId", binding_id="session"),
            status("create", 200), state("create", "EXPLICIT_NEGATIVE_CONTROL" if setup_failure else "ACTIVE")],
        cleanup_groups={"session": cleanup})


def fixture_report(service, journal, scope, manifest):
    prepared = service.prepare(scope, manifest, require_work=lambda: None)
    cleanup = service.cleanup(scope, manifest, require_work=lambda: None)
    phases = []
    for item in (prepared, *cleanup.phases):
        paths = journal.paths(scope, item.phase)
        phases.append({"phase": item.phase, "runner_job_id": item.command.job_id,
            "request_hash": digest(item.execution.request_body), "result_hash": digest(item.execution.result_body),
            "request_archive": str(paths["request"]), "result_archive": str(paths["result"]),
            "status": item.execution.result.status, "observed_assertion_count": item.receipt["observed_assertion_count"],
            "passed_assertion_count": item.receipt["passed_assertion_count"], "failed_assertion_count": item.receipt["failed_assertion_count"],
            "binding_count": len(item.receipt["bindings"])})
    return {"case_id": scope.case_id, "scope": asdict(scope), "manifest_hash": acceptance_digest(manifest),
        "setup_status": prepared.execution.result.status, "cleanup_verified": cleanup.cleanup_verified,
        "unresolved_bindings": list(cleanup.unresolved_bindings), "unknown_phases": list(cleanup.unknown_phases),
        "phases": phases, "baseline_restored": False, "business_coverage_verified": False,
        "execution_authorized": False, "canonical_runplan_verified": False}


def observe_exweb_http_fixtures(adapter, environment, inventory, deployment, directory, *, revision):
    root = Path(directory) / "fixtures"
    root.mkdir(mode=0o700, exist_ok=False)
    cases, checks = [], {}
    for case_id, setup_failure, cleanup_failure in (("normal", False, False), ("setup_oracle_failure", True, False),
            ("closed_read_cleanup_failure", False, True)):
        manifest = recipe(case_id, setup_failure=setup_failure, cleanup_failure=cleanup_failure)
        scope = HttpFixtureScope(environment.project_id, "exweb-fixture-" + uuid4().hex, case_id,
            acceptance_digest({"kind": "developer_probe", "repository_revision": revision, "artifact_hash": deployment["jar_hash"]}),
            acceptance_digest(manifest), environment.environment_id, deployment["jar_hash"], inventory.inventory_hash, 10000)
        journal = ProbeFixtureJournal(root / case_id)
        write_original(journal.directory / "manifest.json", encoded(manifest))
        service = HttpFixtureLifecycleApplicationService(adapter, journal, OwnedHttpFixtureObservationVerifier())
        report = fixture_report(service, journal, scope, manifest)
        report.update(manifest_archive=str(journal.directory / "manifest.json"),
            probe_kind="explicit_setup_negative_control" if setup_failure else "original_closed_read_oracle" if cleanup_failure else "owned_lifecycle")
        cases.append(report)
        checks["http_fixture_" + case_id] = (report["setup_status"] == ("failed" if setup_failure else "passed")
            and report["cleanup_verified"] is (not cleanup_failure) and not report["unresolved_bindings"] and not report["unknown_phases"])
    source_root = Path(__file__).resolve().parents[1]
    sources = ["apps/api/app/domain/quality_loop/http_fixtures.py", "apps/api/app/application/quality_loop/http_fixtures.py",
        "apps/api/app/infrastructure/runner/http_fixture_verifier.py", "scripts/exweb_http_fixture_probe.py"]
    return {"schema": "nasus.exweb-http-fixture-probe.v1", "cases": cases, "checks": checks,
        "executor_sources": [{"path": relative, "content_hash": digest((source_root / relative).read_bytes())} for relative in sources],
        "oracle_authority": "developer_probe_not_approved_specification", "durable_postgresql_journal_verified": False,
        "canonical_runplan_verified": False, "business_coverage_verified": False, "baseline_restored": False}


class NoExecution:
    def execute_owned_http(self, *args, **kwargs):
        raise AssertionError("readonly fixture replay must never execute the target")


def replay_exweb_http_fixtures(report):
    original = report["http_runner"]["http_fixtures"]
    if original["schema"] != "nasus.exweb-http-fixture-probe.v1" or len(original["cases"]) != 3:
        raise ValueError("unexpected complete fixture probe roster")
    source_root = Path(__file__).resolve().parents[1]
    expected = {"apps/api/app/domain/quality_loop/http_fixtures.py", "apps/api/app/application/quality_loop/http_fixtures.py",
        "apps/api/app/infrastructure/runner/http_fixture_verifier.py", "scripts/exweb_http_fixture_probe.py"}
    if len(original["executor_sources"]) != len(expected) or {item["path"] for item in original["executor_sources"]} != expected:
        raise ValueError("fixture executor source inventory differs")
    for item in original["executor_sources"]:
        if digest(read_original(source_root / item["path"], 256 * 1024)) != item["content_hash"]:
            raise ValueError("fixture executor source changed after original observation")
    cases = []
    for item in original["cases"]:
        scope = HttpFixtureScope(**item["scope"])
        path = Path(item["manifest_archive"])
        manifest = _object(read_original(path, 128 * 1024))
        journal = ProbeFixtureJournal(path.parent, readonly=True)
        service = HttpFixtureLifecycleApplicationService(NoExecution(), journal, OwnedHttpFixtureObservationVerifier())
        actual = fixture_report(service, journal, scope, manifest)
        if actual != {key: value for key, value in item.items() if key not in {"manifest_archive", "probe_kind"}}:
            raise ValueError("fixture replay differs from original complete outcome")
        cases.append(actual)
    return {"schema": "nasus.exweb-http-fixture-replay.v1", "cases": cases, "target_reexecuted": False,
        "formal_coverage_verified": False, "durable_postgresql_journal_verified": False}
