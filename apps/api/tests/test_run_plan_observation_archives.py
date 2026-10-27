"""Protocol-boundary specimens; native transport and MinIO are tested separately."""
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import asdict
import base64
import hashlib
import json
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.run_plan_observation_archives import (
    RunPlanObservationArchiveApplicationService, RunPlanObservationArchiveParent, SavedRunPlanObservationArchiveAccess,
)
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.run_plan_observations import RunPlanObservationInvalid
from apps.api.app.infrastructure.storage.run_plan_observation_artifacts import RunPlanObservationArtifacts
from apps.api.tests.test_run_plan_observations import http_plan, observation_service, protocol_result


class PrivateStorageSpecimen:
    def __init__(self):
        self.config = SimpleNamespace(bucket="explicit-private-specimen")
        self.objects = {}

    def put_bytes(self, key, body, *, content_type):
        assert content_type == "application/json"
        ref = "s3://" + self.config.bucket + "/" + key
        self.objects[ref] = body
        return SimpleNamespace(storage_ref=ref, content_hash="sha256:" + hashlib.sha256(body).hexdigest())

    def get_bytes(self, ref, *, max_bytes):
        body = self.objects[ref]
        assert len(body) <= max_bytes
        return body


class OriginalPlanAccessSpecimen:
    def __init__(self, plan):
        self.scope = (plan["project_id"], plan["plan_digest"])
        self.calls, self.deny_at = 0, None
        self.parent = RunPlanObservationArchiveParent(project_id=plan["project_id"], run_plan_id="explicit-saved-parent-specimen",
            run_plan_artifact_hash=acceptance_digest("explicit-original-parent-specimen"), plan_digest=plan["plan_digest"])

    def require_plan_access(self, project_id, plan_digest):
        self.calls += 1
        if (project_id, plan_digest) != self.scope or self.calls == self.deny_at:
            raise PermissionError("original plan access denied")
        return self.parent


def inputs():
    plan, observations = http_plan(), observation_service()
    commands = observations.commands(plan, run_id="explicit-archive-attempt", timeout_ms=5000)
    entries = [{"runner_job_id": item.job_id, "result": asdict(protocol_result(item, failed=index == 0))}
        for index, item in enumerate(commands)]
    storage, access = PrivateStorageSpecimen(), OriginalPlanAccessSpecimen(plan)
    artifacts = RunPlanObservationArtifacts(storage)
    service = RunPlanObservationArchiveApplicationService(observations, artifacts, access)
    return plan, entries, service, artifacts, storage, access


def save(plan, entries, service):
    return service.archive(plan, entries, run_id="explicit-archive-attempt", timeout_ms=5000)


def replay(plan, saved, service):
    return service.read(plan["project_id"], saved["artifact_ref"], saved["artifact_hash"], plan_digest=plan["plan_digest"])


def test_complete_archive_replays_every_original_byte_and_oracle_without_authority():
    plan, entries, service, artifacts, storage, access = inputs()
    original = deepcopy((plan, entries))
    saved = save(plan, list(reversed(entries)), service)
    assert access.calls == 4
    # A fresh service has no previous in-memory observations to trust.
    fresh = RunPlanObservationArchiveApplicationService(observation_service(), RunPlanObservationArtifacts(storage), access)
    value = replay(plan, saved, fresh)
    assert value["summary"]["observed_case_count"] == len(entries)
    assert value["summary"]["failed_observation_count"] == 1
    assert value["summary"]["passed_observation_count"] == len(entries) - 1
    assert all(value[key] is False for key in ("execution_authorized", "target_build_verified",
        "business_coverage_verified", "canonical_execution_committed"))
    assert all(value["summary"][key] == 0 for key in ("automated_count", "executed_on_target_count", "passed_count"))
    assert [item["runner_job_id"] for item in value["raw_results"]] == [item["runner_job_id"] for item in entries]
    assert (plan, entries) == original
    assert save(plan, entries, service)["artifact_hash"] == saved["artifact_hash"]


@pytest.mark.parametrize("deny_at", [None, 1, 2, 3, 4])
def test_archive_shares_one_read_scope_but_keeps_each_access_check_and_closes_on_failure(deny_at):
    plan, entries, service, _artifacts, _storage, _access = inputs()

    class ScopedAccess(OriginalPlanAccessSpecimen):
        def __init__(self, original):
            super().__init__(original)
            self.depth, self.sessions = 0, 0

        @contextmanager
        def verified_read_session(self):
            assert self.depth == 0
            self.depth += 1
            self.sessions += 1
            try:
                yield
            finally:
                self.depth -= 1

        def require_plan_access(self, project_id, plan_digest):
            assert self.depth == 1
            return super().require_plan_access(project_id, plan_digest)

    access = service.access = ScopedAccess(plan)
    access.deny_at = deny_at
    if deny_at:
        with pytest.raises(PermissionError):
            save(plan, entries, service)
        assert access.calls == deny_at
    else:
        saved = save(plan, entries, service)
        assert access.calls == 4
    assert access.depth == 0 and access.sessions == 1
    access.deny_at = None
    if deny_at:
        saved = save(plan, entries, service)
    prior = access.calls
    replay(plan, saved, service)
    assert access.calls == prior + 2
    assert access.depth == 0 and access.sessions == (3 if deny_at else 2)


def test_saved_parent_read_scope_is_delegated_without_caching_plan_or_access():
    plan = http_plan()
    artifact = {"project_id": plan["project_id"], "run_plan_id": "original-saved-plan", "plan": plan}
    parent = RunPlanObservationArchiveParent(project_id=plan["project_id"], run_plan_id=artifact["run_plan_id"],
        run_plan_artifact_hash=acceptance_digest(artifact), plan_digest=plan["plan_digest"])
    view = {"artifact": artifact, "metadata": {"project_id": plan["project_id"], "run_plan_id": parent.run_plan_id,
        "artifact_hash": parent.run_plan_artifact_hash, "plan_digest": parent.plan_digest}}
    calls, scope = [], []

    @contextmanager
    def read_session():
        scope.append(True)
        try:
            yield
        finally:
            scope.pop()

    def read(project_id, run_plan_id):
        assert scope == [True]
        calls.append((project_id, run_plan_id))
        return deepcopy(view)

    access = SavedRunPlanObservationArchiveAccess(SimpleNamespace(read=read, verified_read_session=read_session), parent)
    with access.verified_read_session():
        assert access.require_plan_access(parent.project_id, parent.plan_digest) == parent
        view["metadata"]["artifact_hash"] = acceptance_digest("changed-original-parent")
        with pytest.raises(RunPlanObservationInvalid):
            access.require_plan_access(parent.project_id, parent.plan_digest)
    assert scope == [] and calls == [(parent.project_id, parent.run_plan_id)] * 2


def test_native_only_archive_preserves_the_original_v1_content_contract():
    from apps.api.app.domain.quality_loop.run_plan_observations import collect_run_plan_observations
    plan, entries, service, _artifacts, _storage, access = inputs()
    commands = service.observations.commands(plan, run_id="explicit-archive-attempt", timeout_ms=5000)
    results = [service._result(entry["result"]) for entry in entries]
    observed = list(service.observations.observe_http_batch(plan, list(zip(commands, results)),
        run_id="explicit-archive-attempt", timeout_ms=5000))
    expected = {"schema": "nasus.run-plan-observation-archive.v1", "project_id": plan["project_id"],
        "plan_digest": plan["plan_digest"], "run_id": "explicit-archive-attempt", "timeout_ms": 5000,
        "original_run_plan": access.parent.model_dump(mode="json"), "plan": plan,
        "raw_results": [{"runner_job_id": command.job_id, "result": asdict(result)} for command, result in zip(commands, results)],
        "observations": observed, "summary": collect_run_plan_observations(plan, observed),
        "execution_authorized": False, "target_build_verified": False,
        "business_coverage_verified": False, "canonical_execution_committed": False}
    assert save(plan, entries, service)["artifact_hash"] == acceptance_digest(expected)


@pytest.mark.parametrize("count", [0, 1])
def test_partial_or_empty_archive_preserves_all_missing_cases_as_unexecuted(count):
    plan, entries, service, _artifacts, _storage, _access = inputs()
    value = replay(plan, save(plan, entries[:count], service), service)
    assert value["summary"]["observed_case_count"] == count
    assert value["summary"]["not_executed_case_count"] == len(entries) - count
    assert len(value["summary"]["cases"]) == len(entries)


@pytest.mark.parametrize("fault", ["duplicate", "foreign_job", "foreign_attempt", "extra_field", "missing_field", "unbound_entry",
    "mode", "missing_artifacts", "physical_bytes", "metadata_type"])
def test_archive_rejects_invalid_complete_inputs_before_any_upload(fault):
    plan, entries, service, _artifacts, storage, _access = inputs()
    result = entries[0]["result"]
    if fault == "duplicate": entries[1] = deepcopy(entries[0])
    elif fault == "foreign_job":
        result["runner_job_id"] = entries[0]["runner_job_id"] = "unreviewed-job"
    elif fault == "foreign_attempt":
        command = service.observations.commands(plan, run_id="other-attempt", timeout_ms=5000)[0]
        entries[0] = {"runner_job_id": command.job_id, "result": asdict(protocol_result(command))}
    elif fault == "extra_field": result["authority"] = True
    elif fault == "missing_field": result.pop("execution_receipt")
    elif fault == "unbound_entry": entries[0]["runner_job_id"] = "other"
    elif fault == "mode": result["runner_mode"] = "mock"
    elif fault == "missing_artifacts": result["artifacts"] = []
    elif fault == "physical_bytes": result["artifacts"][0]["content_base64"] = base64.b64encode(b"forged").decode()
    else: result["summary"] = True
    with pytest.raises(ValueError): save(plan, entries, service)
    assert storage.objects == {}


@pytest.mark.parametrize("fault", ["oracle_mapping", "summary", "authority", "physical_bytes", "result_receipt", "missing_case", "extra_field", "parent"])
def test_rehashed_archive_must_still_match_original_bytes_and_complete_case_mapping(fault):
    plan, entries, service, artifacts, _storage, _access = inputs()
    value = replay(plan, save(plan, entries, service), service)
    if fault == "oracle_mapping": value["observations"][0]["oracles"][0]["row_id"] = "another-row"
    elif fault == "summary": value["summary"]["passed_observation_count"] += 1
    elif fault == "authority": value["execution_authorized"] = True
    elif fault == "physical_bytes": value["raw_results"][0]["result"]["artifacts"][0]["content_base64"] = base64.b64encode(b"forged").decode()
    elif fault == "result_receipt": value["raw_results"][0]["result"]["execution_receipt"]["execution_status"] = "passed"
    elif fault == "missing_case": value["raw_results"].pop()
    elif fault == "parent": value["original_run_plan"]["run_plan_id"] = "another-original-plan"
    else: value["unexpected"] = "not part of the original contract"
    ref, digest = artifacts.put(plan["project_id"], value)
    with pytest.raises(ValueError): service.read(plan["project_id"], ref, digest, plan_digest=plan["plan_digest"])


@pytest.mark.parametrize("deny_at", [1, 2, 3, 4])
def test_revoked_plan_access_prevents_private_archive_return(deny_at):
    plan, entries, service, _artifacts, storage, access = inputs()
    access.deny_at = deny_at
    with pytest.raises(PermissionError): save(plan, entries, service)
    if deny_at <= 2: assert storage.objects == {}
    # An already uploaded private orphan grants no public or canonical fact.
    assert access.calls == deny_at


def test_read_rechecks_current_original_plan_access_before_and_after_private_bytes():
    plan, entries, service, _artifacts, _storage, access = inputs()
    saved = save(plan, entries, service)
    with pytest.raises(PermissionError):
        service.read("other-project", saved["artifact_ref"], saved["artifact_hash"], plan_digest=plan["plan_digest"])
    access.deny_at = access.calls + 2
    with pytest.raises(PermissionError): replay(plan, saved, service)


def test_physical_archive_corruption_and_foreign_namespace_are_rejected():
    plan, entries, service, artifacts, storage, _access = inputs()
    saved = save(plan, entries, service)
    with pytest.raises(RunPlanObservationInvalid): artifacts.read("other-project", saved["artifact_ref"], saved["artifact_hash"])
    storage.objects[saved["artifact_ref"]] += b" "
    with pytest.raises(RunPlanObservationInvalid): replay(plan, saved, service)


def test_complete_archive_budget_rejects_without_truncation_or_upload(monkeypatch):
    from apps.api.app.infrastructure.storage import run_plan_observation_artifacts as adapter
    plan, entries, service, _artifacts, storage, _access = inputs()
    monkeypatch.setattr(adapter, "MAX_OBSERVATION_ARCHIVE_BYTES", 128)
    with pytest.raises(RunPlanObservationInvalid, match="nothing was truncated"): save(plan, entries, service)
    assert storage.objects == {}


@pytest.mark.parametrize("fault", ["duplicate_key", "non_finite"])
def test_artifact_read_rejects_hash_matched_ambiguous_or_non_json_bytes(fault):
    from apps.api.app.application.quality_loop.run_plan_observation_archives import OBSERVATION_ARCHIVE_SCHEMA
    plan, _entries, _service, artifacts, storage, _access = inputs()
    value = {"schema": OBSERVATION_ARCHIVE_SCHEMA, "project_id": plan["project_id"], "extra": float("nan") if fault == "non_finite" else 1}
    body = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    if fault == "duplicate_key": body = body.replace(b'"extra":1', b'"extra":1,"extra":1')
    digest = "sha256:" + hashlib.sha256(body).hexdigest()
    ref = "s3://" + storage.config.bucket + "/" + artifacts._key(plan["project_id"], digest)
    storage.objects[ref] = body
    with pytest.raises(RunPlanObservationInvalid): artifacts.read(plan["project_id"], ref, digest)


@pytest.mark.parametrize("attempt", ["\ud800", "\x7f", "", " ", True])
def test_invalid_attempt_identity_cannot_create_an_archive(attempt):
    plan, entries, service, _artifacts, storage, _access = inputs()
    with pytest.raises(RunPlanObservationInvalid): service.archive(plan, entries, run_id=attempt, timeout_ms=5000)
    assert storage.objects == {}


@pytest.mark.parametrize("fault", [None, "project", "plan", "metadata_hash", "artifact", "digest", "denied"])
def test_saved_parent_access_uses_exact_original_plan_and_preserves_current_source_denial(fault):
    plan = http_plan()
    artifact = {"project_id": plan["project_id"], "run_plan_id": "original-saved-plan", "plan": plan}
    parent = RunPlanObservationArchiveParent(project_id=plan["project_id"], run_plan_id=artifact["run_plan_id"],
        run_plan_artifact_hash=acceptance_digest(artifact), plan_digest=plan["plan_digest"])
    view = {"artifact": artifact, "metadata": {"project_id": plan["project_id"], "run_plan_id": parent.run_plan_id,
        "artifact_hash": parent.run_plan_artifact_hash, "plan_digest": parent.plan_digest}}
    calls = []
    def read(project_id, run_plan_id):
        calls.append((project_id, run_plan_id))
        if fault == "denied": raise PermissionError("original source was revoked")
        return view
    access = SavedRunPlanObservationArchiveAccess(SimpleNamespace(read=read), parent)
    if fault == "project": view["metadata"]["project_id"] = "other-project"
    elif fault == "plan": view["metadata"]["run_plan_id"] = "other-plan"
    elif fault == "metadata_hash": view["metadata"]["artifact_hash"] = acceptance_digest("other")
    elif fault == "artifact": artifact["run_plan_id"] = "other-plan"
    elif fault == "digest": artifact["plan"]["plan_digest"] = acceptance_digest("other")
    if fault is None: assert access.require_plan_access(parent.project_id, parent.plan_digest) == parent
    else:
        with pytest.raises(PermissionError if fault == "denied" else RunPlanObservationInvalid):
            access.require_plan_access(parent.project_id, parent.plan_digest)
    assert calls == [(parent.project_id, parent.run_plan_id)]


def unknown_result(entries, *, index=0, status="error"):
    result = entries[index]["result"]
    result.update(status=status, execution_receipt=None, artifacts=[],
        summary="Explicit lost-receipt specimen; target dispatch is not proven",
        failure_summary="Runner transport or execution receipt validation failed.")


@pytest.mark.parametrize("status", ["error", "timed_out"])
def test_unknown_result_preserves_other_verified_cases_and_original_v1_replay(status):
    from apps.api.app.application.quality_loop.run_plan_observation_archives import OBSERVATION_ATTEMPT_ARCHIVE_SCHEMA
    plan, entries, service, artifacts, storage, access = inputs()
    original = save(plan, entries, service)
    original_bytes = storage.objects[original["artifact_ref"]]
    unknown_result(entries, status=status)
    saved = save(plan, entries, service)
    value = replay(plan, saved, RunPlanObservationArchiveApplicationService(observation_service(), artifacts, access))
    assert value["schema"] == OBSERVATION_ATTEMPT_ARCHIVE_SCHEMA
    assert value["raw_results"][0]["result"] == json.loads(json.dumps(entries[0]["result"]))
    assert value["summary"]["outcome_unknown_case_count"] == 1
    assert value["summary"]["observed_case_count"] == len(entries) - 1
    assert value["summary"]["no_result_case_count"] == 0
    assert "not_executed_case_count" not in value["summary"]
    uncertain = value["unverified_attempts"][0]
    assert uncertain["runner_status"] == status and uncertain["native_dispatch_verified"] is False
    assert uncertain["retry_requires_new_explicit_attempt"] is True
    assert all(item["status"] == "unknown" for item in uncertain["oracles"])
    assert value["summary"]["cases"][0]["status"] == "outcome_unknown"
    assert value["summary"]["passed_observation_count"] == len(entries) - 1
    assert value["summary"]["passed_count"] == value["summary"]["executed_on_target_count"] == 0
    assert replay(plan, original, service)["schema"] == "nasus.run-plan-observation-archive.v1"
    assert storage.objects[original["artifact_ref"]] == original_bytes
    assert save(plan, entries, service)["artifact_hash"] == saved["artifact_hash"]


def test_unknown_result_is_not_the_same_as_a_case_with_no_submitted_result():
    plan, entries, service, _artifacts, _storage, _access = inputs()
    unknown_result(entries)
    value = replay(plan, save(plan, entries[:1], service), service)
    assert value["summary"]["outcome_unknown_case_count"] == 1
    assert value["summary"]["no_result_case_count"] == len(entries) - 1
    assert value["summary"]["observed_case_count"] == 0
    assert value["summary"]["cases"][0]["status"] == "outcome_unknown"
    assert all(case["status"] == "not_observed" for case in value["summary"]["cases"][1:])


@pytest.mark.parametrize("fault", ["passed", "failed", "wrong_mode", "partial_artifacts", "invalid_receipt", "foreign_job"])
def test_unknown_branch_cannot_hide_claimed_pass_corruption_or_another_job(fault):
    plan, entries, service, _artifacts, storage, _access = inputs()
    artifacts = deepcopy(entries[0]["result"]["artifacts"])
    unknown_result(entries)
    result = entries[0]["result"]
    if fault in {"passed", "failed"}: result["status"] = fault
    elif fault == "wrong_mode": result["runner_mode"] = "protocol_stub"
    elif fault == "partial_artifacts": result["artifacts"] = artifacts
    elif fault == "invalid_receipt": result["execution_receipt"] = {"execution_status": "passed"}
    else: result["runner_job_id"] = entries[0]["runner_job_id"] = "other-attempt-job"
    with pytest.raises(ValueError): save(plan, entries, service)
    assert storage.objects == {}


@pytest.mark.parametrize("fault", ["request_hash", "result_hash", "oracle", "claimed_pass", "summary", "retry", "schema"])
def test_rehashed_unknown_archive_still_requires_original_result_and_case_pins(fault):
    plan, entries, service, artifacts, _storage, _access = inputs()
    unknown_result(entries)
    value = replay(plan, save(plan, entries, service), service)
    unknown = value["unverified_attempts"][0]
    if fault == "request_hash": unknown["request_hash"] = acceptance_digest("other-request")
    elif fault == "result_hash": unknown["runner_result_hash"] = acceptance_digest("other-result")
    elif fault == "oracle": unknown["oracles"][0]["oracle_digest"] = acceptance_digest("other-oracle")
    elif fault == "claimed_pass": unknown["status"] = "passed"
    elif fault == "summary": value["summary"]["outcome_unknown_case_count"] = 0
    elif fault == "retry": unknown["retry_requires_new_explicit_attempt"] = False
    else: value["schema"] = "nasus.run-plan-observation-archive.v1"
    ref, digest = artifacts.put(plan["project_id"], value)
    with pytest.raises(ValueError): service.read(plan["project_id"], ref, digest, plan_digest=plan["plan_digest"])
