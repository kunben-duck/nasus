import importlib.util
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def load():
    path = Path(__file__).resolve().parents[1] / "scripts/verify-exweb-canonical.py"
    spec = importlib.util.spec_from_file_location("verify_exweb_canonical", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cli = load()
REVISION = "fe5827f6b76f77ef34918d8b452ee823142332dc"
HASH = "sha256:" + "a" * 64
REPOSITORY = "https://github.com/kunben-duck/exweb.git"


def evidence():
    return {"schema": cli.LEGACY_REPORT_SCHEMA, "source_commit": REVISION, "source_file_count": 126,
        **dict.fromkeys(("plan_digest", "plan_artifact_hash", "target_artifact_hash", "environment_inventory_hash", "history_digest"), HASH),
        "case_count": 4, "cases": [{"case_id": "case-" + str(i), "status": "failed", "observation_digest": HASH,
            "responses": [{"method": "GET", "response_status": 500, "response_hash": HASH}],
            "oracles": [{"row_id": "oracle", "status": "failed", "oracle_digest": HASH}]} for i in range(1, 5)],
        "fixture_setup_count": 4, "fixture_cleanup_count": 4, "native_runner_calls": 12, "workflow_count": 9,
        "history_verified_after_cleanup": True, "owned_resources_cleanup_verified": True,
        "independent_business_gold": False, "business_coverage_verified": False, "release_authorized": False}


def cleanup_ledger(report):
    return {"schema": cli.CLEANUP_LEDGER_SCHEMA, "plan_digest": report["plan_digest"],
        "plan_artifact_hash": report["plan_artifact_hash"], "observations": [
            {"case_id": case["case_id"], "result_status": "failed" if index == 0 else "passed",
                "result_digest": "sha256:" + sha256(str(index).encode()).hexdigest()}
            for index, case in enumerate(report["cases"])]}


def evidence_v2():
    report = evidence()
    return {**report, "schema": cli.REPORT_SCHEMA, "cleanup_history_verified_after_teardown": True,
        "fixture_cleanup_observations": cleanup_ledger(report)["observations"]}


def archive_witness(report):
    ledger = cleanup_ledger(report)
    return {"schema": cli.CLEANUP_WITNESS_SCHEMA, "scope": cli.CLEANUP_WITNESS_SCOPE,
        "plan_digest": ledger["plan_digest"], "plan_artifact_hash": ledger["plan_artifact_hash"],
        "owned_resources_absent_before_and_after_read": True, "setup_count": 4, "cases": ledger["observations"]}


@pytest.mark.parametrize("defect", ["missing", "wrong_case", "duplicate_digest", "unknown", "before_teardown"])
def test_v2_requires_a_verified_cleanup_observation_for_every_original_case(defect):
    report = evidence_v2()
    assert cli.verify_report(report, REVISION)
    outcomes = report["fixture_cleanup_observations"]
    if defect == "missing":
        outcomes.pop()
    if defect == "wrong_case":
        outcomes[0]["case_id"] = "different-case"
    if defect == "duplicate_digest":
        outcomes[0]["result_digest"] = outcomes[1]["result_digest"]
    if defect == "unknown":
        outcomes[0]["result_status"] = "unknown"
    if defect == "before_teardown":
        report["cleanup_history_verified_after_teardown"] = False
    assert not cli.verify_report(report, REVISION)


def test_summary_distinguishes_cleanup_assertions_and_legacy_workflow_completion():
    probe = SimpleNamespace(REPOSITORY=REPOSITORY, REVISION=REVISION)
    legacy = evidence()
    assert "does not distinguish cleanup assertions" in cli.acceptance_summary(probe, canonical=legacy)
    ledger = cleanup_ledger(legacy)
    witnessed = cli.acceptance_summary(probe, canonical=legacy, cleanup_ledger=ledger)
    post_teardown = cli.acceptance_summary(probe, canonical=evidence_v2())
    assert "Read-only pre-teardown PostgreSQL ledger" in witnessed
    assert "Post-teardown archive readback" in post_teardown
    assert "| `case-1` | failed |" in witnessed and "| `case-2` | passed |" in post_teardown
    with pytest.raises(ValueError, match="does not match"):
        cli.acceptance_summary(probe, canonical=legacy, cleanup_ledger={**ledger, "plan_digest": "sha256:" + "f" * 64})
    with pytest.raises(ValueError, match="does not match"):
        cli.acceptance_summary(probe, canonical=evidence_v2(), cleanup_ledger=ledger)


def test_cli_renders_only_a_matching_legacy_cleanup_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "probe_module", lambda: SimpleNamespace(REVISION=REVISION))
    canonical, ledger_path, summary = (tmp_path / name for name in ("canonical.json", "cleanup.json", "summary.md"))
    report = evidence()
    canonical.write_text(json.dumps(report), encoding="utf-8")
    args = ["--summary", str(summary), "--canonical-report", str(canonical), "--cleanup-ledger", str(ledger_path)]
    ledger = cleanup_ledger(report)
    ledger_path.write_text(json.dumps({**ledger, "plan_artifact_hash": "sha256:" + "f" * 64}), encoding="utf-8")
    assert cli.main(args) == 2 and not summary.exists()
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    assert cli.main(args) == 0
    assert "| `case-1` | failed |" in summary.read_text(encoding="utf-8")


@pytest.mark.parametrize("change", ["wrong_plan", "wrong_artifact", "before_teardown", "wrong_scope", "wrong_count", "wrong_case", "extra"])
def test_archive_witness_cannot_replace_or_rebind_canonical_history(change):
    report = evidence()
    witness = archive_witness(report)
    updates = {"wrong_plan": ("plan_digest", "other"), "wrong_artifact": ("plan_artifact_hash", "other"),
        "before_teardown": ("owned_resources_absent_before_and_after_read", False), "wrong_scope": ("scope", "canonical"),
        "wrong_count": ("setup_count", 3), "extra": ("raw_response", "private content")}
    if change == "wrong_case":
        witness["cases"][0]["case_id"] = "different"
    else:
        key, value = updates[change]
        witness[key] = value
    probe = SimpleNamespace(REVISION=REVISION)
    with pytest.raises(ValueError, match="does not match"):
        cli.acceptance_summary(probe, canonical=report, cleanup_archive_witness=witness)


def test_cli_renders_independent_archive_witness_as_supplemental_only(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "probe_module", lambda: SimpleNamespace(REVISION=REVISION))
    canonical, witness_path, summary = (tmp_path / name for name in ("canonical.json", "witness.json", "summary.md"))
    report = evidence()
    witness_path.write_text(json.dumps(archive_witness(report)), encoding="utf-8")
    args = ["--summary", str(summary), "--canonical-report", str(canonical), "--cleanup-archive-witness", str(witness_path)]
    canonical.write_text(json.dumps(evidence_v2()), encoding="utf-8")
    assert cli.main(args) == 2 and not summary.exists()
    canonical.write_text(json.dumps(report), encoding="utf-8")
    assert cli.main(args) == 0
    rendered = summary.read_text(encoding="utf-8")
    assert "Independent post-teardown PostgreSQL/MinIO readback, not canonical API history" in rendered
    assert "| `case-1` | failed |" in rendered and "| `case-2` | passed |" in rendered


def native_evidence():
    files = [{"path": f"file-{i}"} for i in range(126)]
    return {"schema": cli.NATIVE_REPORT_SCHEMA, "stage": "observed", "status": "failed",
        "source": {"repository": REPOSITORY, "revision": REVISION, "files": files,
            "inventory_hash": "sha256:" + sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()},
        "checks": {"owner_read": True, "other_tenant_read_status": False},
        "cleanup": {"verified": True, "remaining_owned_resources": []},
        "oracle_authority": "developer_probe_not_approved_specification", "nasus_runplan_verified": False,
        "llm_verified": False, "release_authorized": False, "evidence": ["must-not-expose-native-content"]}


@pytest.mark.parametrize("field,value", [("source_commit", "unreviewed"), ("case_count", 1),
    ("fixture_cleanup_count", 0), ("native_runner_calls", 7), ("history_verified_after_cleanup", False),
    ("owned_resources_cleanup_verified", False), ("release_authorized", True), ("business_coverage_verified", True)])
def test_verification_report_must_preserve_all_original_phases_without_approving_release(field, value):
    assert cli.verify_report(evidence(), REVISION)
    assert not cli.verify_report({**evidence(), field: value}, REVISION)


def test_missing_physical_response_for_assertion_failure_cannot_pass():
    report = evidence()
    report["cases"][0]["responses"] = []
    assert not cli.verify_report(report, REVISION)


@pytest.mark.parametrize("status,oracle_states,valid", [
    ("passed", ["passed", "passed"], True),
    ("passed", ["failed"], False),
    ("passed", ["passed", "not_executed"], False),
    ("failed", ["passed", "failed", "not_executed"], True),
    ("failed", ["passed"], False),
    ("failed", ["failed", "failed"], False),
    ("failed", ["failed", "interrupted"], False),
    ("timed_out", ["passed", "interrupted", "not_executed"], True),
    ("timed_out", ["failed"], False),
    ("error", ["not_executed"], True),
    ("error", ["interrupted", "interrupted"], False),
    ("error", ["skipped"], False),
])
def test_report_status_must_match_native_assertion_states(status, oracle_states, valid):
    report = evidence()
    case = report["cases"][0]
    case.update(status=status, oracles=[{"row_id": f"oracle-{i}", "oracle_digest": HASH, "status": value}
        for i, value in enumerate(oracle_states)])
    assert cli.verify_report(report, REVISION) is valid


def test_report_rejects_duplicate_oracles_and_unsupported_http_methods():
    report = evidence()
    case = report["cases"][0]
    case["oracles"].append({**case["oracles"][0], "status": "not_executed"})
    assert not cli.verify_report(report, REVISION)
    case["oracles"].pop()
    case["responses"][0]["method"] = "TRACE"
    assert not cli.verify_report(report, REVISION)


def incomplete_evidence():
    report = evidence()
    return {**report, "case_count": 3, "cases": report["cases"][:3], "fixture_setup_count": 3,
            "fixture_cleanup_count": 3, "native_runner_calls": 9, "workflow_count": 7}


def test_self_consistent_partial_cohort_is_not_a_complete_verification():
    assert not cli.verify_report(incomplete_evidence(), REVISION)


@pytest.mark.parametrize("key,value", [("NASUS_DATABASE_URL", "postgresql://u:p@127.0.0.1/db?host=remote.example"),
    ("NASUS_DATABASE_URL", "postgresql://u:p@remote.example/db"), ("NASUS_S3_ENDPOINT", "http://remote.example:9000"),
    ("NASUS_TEMPORAL_ADDRESS", "remote.example:7233"), ("NASUS_TEMPORAL_ADDRESS", "127.0.0.1:7233/path")])
def test_launch_rejects_remote_or_rebound_endpoints(key, value):
    env = dict(NASUS_DATABASE_URL="postgresql://u:p@127.0.0.1/db", NASUS_S3_ENDPOINT="http://127.0.0.1:9000",
        NASUS_S3_ACCESS_KEY="test", NASUS_S3_SECRET_KEY="test", NASUS_TEMPORAL_ADDRESS="127.0.0.1:7233")
    assert cli.isolated_environment(env)[0]["TEST_TEMPORAL_ADDRESS"] == "127.0.0.1:7233"
    with pytest.raises(ValueError, match="loopback"):
        cli.isolated_environment({**env, key: value})


@pytest.mark.parametrize("mode", ["check", "skipped", "runner-failed", "partial", "legacy", "verified"])
def test_launcher_requires_explicit_execution_and_zero_exit_with_complete_new_evidence(tmp_path, monkeypatch, mode):
    class ProbeFailure(RuntimeError):
        pass

    calls = []
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-forward")
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "probe_module", lambda: SimpleNamespace(REVISION=REVISION, ProbeFailure=ProbeFailure))
    monkeypatch.setattr(cli, "preflight", lambda *_: ({"TEST_TEMPORAL_ADDRESS": "127.0.0.1:7233"}, dict.fromkeys(cli.ROLES, HASH)))

    def run(command, *, cwd, env, **_):
        assert cwd == tmp_path and "--minio" in command and "-x" in command
        assert command.index(cli.HISTORY_CANARY) < command.index(cli.TEST)
        assert env["EXWEB_EXECUTE_REVIEWED_NATIVE_BUILD"] == "1" and env["EXWEB_NATIVE_MAVEN_IMAGE_ID"] == HASH
        assert "OPENAI_API_KEY" not in env
        path = Path(env["EXWEB_CANONICAL_HANDOFF_REPORT"])
        assert not path.exists()
        if mode in {"verified", "runner-failed"}:
            path.write_text(json.dumps(evidence_v2()), encoding="utf-8")
        if mode == "legacy":
            path.write_text(json.dumps(evidence()), encoding="utf-8")
        if mode == "partial":
            path.write_text(json.dumps(incomplete_evidence()), encoding="utf-8")
        calls.append(path)
        return SimpleNamespace(returncode=1 if mode == "runner-failed" else 0)

    monkeypatch.setattr(cli.subprocess, "run", run)
    args = ["--repository", str(tmp_path), *(part for role in cli.ROLES for part in ("--" + role + "-image-id", HASH))]
    if mode != "check":
        args.append("--execute-reviewed-target")
    assert cli.main(args) == (0 if mode in {"check", "verified"} else 1)
    assert len(calls) == int(mode != "check")


@pytest.mark.parametrize("include_canonical", [False, True])
def test_summary_keeps_target_failures_and_does_not_run_or_export_wire_content(tmp_path, monkeypatch, include_canonical):
    def forbidden(*_args, **_kwargs):
        pytest.fail("summary must not run preflight or target subprocesses")

    monkeypatch.setattr(cli, "preflight", forbidden)
    monkeypatch.setattr(cli.subprocess, "run", forbidden)
    monkeypatch.setattr(cli, "probe_module", lambda: SimpleNamespace(REPOSITORY=REPOSITORY, REVISION=REVISION))
    native, canonical, summary = (tmp_path / name for name in ("native.json", "canonical.json", "summary.md"))
    native.write_text(json.dumps(native_evidence()), encoding="utf-8")
    observed = evidence()
    observed["cases"][0]["responses"][0]["body"] = "must-not-expose-response"
    observed["cases"][0]["case_id"] = "<script>must-not-render-markup</script>"
    canonical.write_text(json.dumps(observed), encoding="utf-8")
    args = ["--summary", str(summary), "--native-report", str(native)]
    if include_canonical:
        args += ["--canonical-report", str(canonical)]
    assert cli.main(args) == 0
    rendered = summary.read_text(encoding="utf-8")
    assert "1/2 checks passed" in rendered and "`other_tenant_read_status` | Failed" in rendered
    assert "must-not" not in rendered and "grants no release approval" in rendered
    if include_canonical:
        assert "4 observed cases" in rendered and "Case 1 | failed | 500 | 1 failed" in rendered
        assert "12 native Runner calls across 9 workflows" in rendered
        assert "controlled test inputs and assertions, not independently approved" in rendered
    else:
        assert "No complete canonical report supplied" in rendered and "500" not in rendered
    assert cli.main(args) == 2 and summary.read_text(encoding="utf-8") == rendered


def test_summary_displays_fixed_target_observations_without_exporting_raw_evidence():
    report = native_evidence()
    report["evidence"] = [
        {"check_id": "session_survives_restart", "status": 200, "response_hash": HASH, "response": []},
        {"check_id": "owner_read", "status": 200, "response_hash": HASH, "response": {"owner": "must-not-expose"}},
        {"check_id": "other_tenant_read", "status": 500, "response_hash": HASH, "path": "/must-not-expose"},
        {"check_id": "session_in_postgres", "row_count": "0", "request": "must-not-expose"},
        {"check_id": "must-not-expose-new-label", "status": 299, "response_hash": HASH},
    ]
    rendered = cli.acceptance_summary(SimpleNamespace(REPOSITORY=REPOSITORY, REVISION=REVISION), native=report)
    assert "| Read own session | HTTP 200 |" in rendered
    assert "| Read another tenant's session | HTTP 500 |" in rendered
    assert "| Matching session rows in PostgreSQL | 0 |" in rendered
    assert "| List sessions after target restart | HTTP 200; 0 entries returned |" in rendered
    assert "must-not-expose" not in rendered and HASH not in rendered and "HTTP 299" not in rendered
    assert "No complete canonical report supplied" in rendered


@pytest.mark.parametrize("evidence", [
    [{"check_id": "owner_read", "status": "500", "response_hash": HASH}],
    [{"check_id": "owner_read", "status": 200, "response_hash": "not-a-pin"}],
    [{"check_id": "owner_read", "status": 200, "response_hash": HASH}] * 2,
    [{"check_id": "session_in_postgres", "row_count": "0 | <script>"}],
    [{"check_id": "session_in_postgres", "row_count": 0}],
    {"check_id": "owner_read", "status": 200, "response_hash": HASH},
])
def test_summary_rejects_invalid_or_ambiguous_named_observations(evidence):
    with pytest.raises(ValueError):
        cli.native_observation_rows({"evidence": evidence})


@pytest.mark.parametrize("fault", ["native_source", "native_inventory", "native_status", "native_cleanup", "native_counts",
    "canonical_cleanup", "canonical_partial", "null"])
def test_summary_refuses_incomplete_or_mixed_reports_without_writing(tmp_path, monkeypatch, fault):
    monkeypatch.setattr(cli, "probe_module", lambda: SimpleNamespace(REPOSITORY=REPOSITORY, REVISION=REVISION))
    native, canonical, summary = (tmp_path / name for name in ("native.json", "canonical.json", "summary.md"))
    report, observed = native_evidence(), evidence()
    if fault == "native_source": report["source"]["revision"] = "another commit"
    if fault == "native_inventory": report["source"]["files"][0] = {"path": "changed-after-observation"}
    if fault == "native_status": report["status"] = "passed"
    if fault == "native_cleanup": report["cleanup"]["remaining_owned_resources"] = ["owned-resource"]
    if fault == "native_counts": report["checks"]["other_tenant_read_status"] = 0
    if fault == "canonical_cleanup": observed["history_verified_after_cleanup"] = False
    if fault == "canonical_partial": observed = incomplete_evidence()
    if fault == "null": observed = None
    native.write_text(json.dumps(report), encoding="utf-8")
    canonical.write_text(json.dumps(observed), encoding="utf-8")
    assert cli.main(["--summary", str(summary), "--native-report", str(native), "--canonical-report", str(canonical)]) == 2
    assert not summary.exists()


@pytest.mark.parametrize("extra", ['"case_count":3,', '"unused":NaN,'])
def test_summary_rejects_ambiguous_json_before_writing(tmp_path, monkeypatch, extra):
    monkeypatch.setattr(cli, "probe_module", lambda: SimpleNamespace(REPOSITORY=REPOSITORY, REVISION=REVISION))
    canonical, summary = tmp_path / "canonical.json", tmp_path / "summary.md"
    canonical.write_text("{" + extra + json.dumps(evidence())[1:], encoding="utf-8")
    assert cli.main(["--summary", str(summary), "--canonical-report", str(canonical)]) == 2
    assert not summary.exists()


def test_summary_keeps_failed_and_unexecuted_oracles_distinct():
    report = evidence()
    report["cases"][0]["oracles"].append({"row_id": "later-oracle", "oracle_digest": HASH, "status": "not_executed"})
    rendered = cli.acceptance_summary(SimpleNamespace(REPOSITORY=REPOSITORY, REVISION=REVISION), canonical=report)
    assert "| `case-1` | failed | 500 | 1 failed, 1 not executed |" in rendered


def test_summary_and_execution_cannot_be_combined(tmp_path):
    with pytest.raises(SystemExit) as error:
        cli.main(["--summary", str(tmp_path / "summary.md"), "--native-report", "native.json", "--execute-reviewed-target"])
    assert error.value.code == 2
