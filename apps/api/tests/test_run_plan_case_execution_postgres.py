"""Real PG parents/journal and private MinIO; model/Runner wire are specimens.

The case claim is an explicit canonical-journal specimen, not a public native
build/environment/fixture grant or proof of exweb business coverage.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from apps.api.app.application.quality_loop.run_plan_case_execution import RunPlanCaseExecutionApplicationService
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.run_plan_case_execution import (
    CASE_EXECUTE_TOOL, RunPlanCaseWorkBusy, RunPlanCaseExecutionInvalid, execution_roster,
)
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.infrastructure.persistence.db_models import (
    AuditEventRecord, SSEEventOutboxRecord, ToolInvocationRecord, UserIdentityRecord,
)
from apps.api.app.infrastructure.persistence.run_plan_case_execution_models import (
    RunPlanCaseWorkRecord as Work, RunPlanCaseLeaseRecord as Lease,
    RunPlanCaseClaimRecord as Claim, RunPlanCaseOutcomeRecord as Outcome,
)
from apps.api.app.infrastructure.persistence.run_plan_case_execution_repository import PostgresRunPlanCaseExecutionRepository
from apps.api.app.infrastructure.persistence.run_plan_case_preparation_models import RunPlanCasePreparationBindingRecord as Binding
from apps.api.app.infrastructure.persistence.tool_claim_journal import ToolClaimJournal
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.runner.http_fixture_verifier import OwnedHttpFixtureObservationVerifier
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage
from apps.api.app.infrastructure.storage.run_plan_case_artifacts import RunPlanCaseArtifacts
from apps.api.tests.test_run_plan_case_execution import Runner, inputs
from apps.api.tests.test_run_plans_api import (
    native_scripts, base_evidence_api, evidence_api, documents, publication, design_scope, generation_result, mapping,
    reviewed_plan_inputs, preview, submit, read,
)
from apps.api.tests.test_semantic_evaluations_api import completed


@pytest.fixture
def pg_case_execution(native_scripts):
    v = native_scripts
    storage = ObjectStorage()
    assert storage.config.s3_enabled and storage.config.bucket.startswith("nasus-test-")
    with session_scope() as session:
        assert session.get_bind().dialect.name == "postgresql"
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
    _, _, _, selection = reviewed_plan_inputs(v)
    prepared = preview(v, selection)
    assert prepared.status_code == 200, prepared.text
    saved = completed(submit(v, prepared.json()["request"]))
    plan_id = saved["result"]["object_refs"][0].split(":", 1)[1]
    response = read(v, plan_id)
    assert response.status_code == 200, response.text
    archive = response.json()
    return dict(v=v, archive=archive)


def new_attempt(parent):
    v, archive = parent["v"], parent["archive"]
    storage = ObjectStorage()
    assert storage.config.s3_enabled and storage.config.bucket.startswith("nasus-test-")
    plan, base, _, _ = inputs(archive["artifact"]["plan"])
    selected = {**deepcopy(base.selection), "run_id": "pg-case-" + uuid4().hex,
        "run_plan_id": archive["metadata"]["run_plan_id"], "run_plan_artifact_hash": archive["metadata"]["artifact_hash"]}
    ident, actor_id = "pg-case-command-" + uuid4().hex, v["owner"]["id"]
    with session_scope() as session:
        now = session.scalar(select(func.clock_timestamp())).isoformat()
        session.add(ToolInvocationRecord(id=ident, tool_id=CASE_EXECUTE_TOOL, status="waiting_confirmation",
            summary="Explicit original case journal specimen", input_payload=selected, revision=0))
    command = ConversationRepository(tool_claim_journal=ToolClaimJournal()).claim_tool_invocation_for_execution(
        ident, expected_statuses=("waiting_confirmation",), input_updates={"confirmed_by_user": True,
            "confirmed_actor_id": actor_id, "confirmed_at": now})
    assert command is not None and command.status == "running"
    scope = replace(base, invocation_id=ident, actor_id=actor_id, run_id=selected["run_id"],
        run_plan_id=selected["run_plan_id"], run_plan_artifact_hash=selected["run_plan_artifact_hash"], selection=selected,
        request_digest=acceptance_digest(selected), command_digest=acceptance_digest({
            "tool_id": CASE_EXECUTE_TOOL, "input_payload": command.input_payload}))
    journal, runner, artifacts = PostgresRunPlanCaseExecutionRepository(), Runner(), RunPlanCaseArtifacts(storage)
    service = RunPlanCaseExecutionApplicationService(runner, OwnedHttpFixtureObservationVerifier(), journal, artifacts)
    return dict(v=v, plan=plan, scope=scope, roster=execution_roster(plan, scope), journal=journal,
        runner=runner, artifacts=artifacts, service=service)


def journal_counts(value):
    scope = value["scope"]
    with session_scope() as session:
        return tuple(session.scalar(statement) for statement in (
            select(func.count()).select_from(Work).where(Work.work_id == scope.work_id),
            select(func.count()).select_from(Lease).where(Lease.work_id == scope.work_id),
            select(func.count()).select_from(Binding).where(Binding.invocation_id == scope.invocation_id),
            select(func.count()).select_from(Claim).where(Claim.work_id == scope.work_id),
            select(func.count()).select_from(Outcome).join(Claim).where(Claim.work_id == scope.work_id),
            select(func.count()).select_from(AuditEventRecord).where(AuditEventRecord.tool_invocation_id == scope.invocation_id),
            select(func.count()).select_from(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == scope.work_id),
        ))


def original_outcome(value, lease, claim):
    scope, service = value["scope"], value["service"]
    job, command = service._commands(value["plan"], scope)[claim["case_id"]]
    execution = value["runner"].execute_owned_http(command, environment_id=scope.environment_id,
        artifact_hash=scope.target_artifact_hash, inventory_hash=scope.inventory_hash, require_work=lambda: None)
    archive = service._archive(value["plan"], scope, job, command, execution)
    ref, digest = value["artifacts"].put(scope.project_id, archive)
    return dict(artifact_ref=ref, artifact_hash=digest, observation=archive["observation"])


def assert_complete_original_cases_commit_to_actual_pg_and_minio_without_nested_worker_lock(pg_case_execution):
    value = pg_case_execution
    plan, scope = value["plan"], value["scope"]
    original = deepcopy(plan)
    result = asyncio.run(value["service"].execute(plan, scope, require_current=lambda: None))
    size = len(value["roster"])
    assert result["state"]["state"] == "observed" and len(result["observations"]) == size
    assert len(value["runner"].commands) == size
    assert journal_counts(value) == (1, 1, 1, size, size, 1 + size * 2, 1 + size * 2)
    assert result["state"]["passed_count"] == result["state"]["executed_on_target_count"] == 0
    assert result["state"]["business_coverage_verified"] is False and plan == original
    fresh = RunPlanCaseExecutionApplicationService(None, OwnedHttpFixtureObservationVerifier(),
        PostgresRunPlanCaseExecutionRepository(), RunPlanCaseArtifacts(ObjectStorage()))
    assert fresh.read(plan, scope, require_access=lambda: None) == result
    with session_scope() as session:
        outcomes = session.scalars(select(Outcome).join(Claim).where(Claim.work_id == scope.work_id)).all()
        for outcome in outcomes:
            private = value["artifacts"].read(scope.project_id, outcome.artifact_ref, outcome.artifact_hash)
            assert private["observation"]["observation_digest"] == outcome.observation_digest
            assert private["request_body"] and private["result_body"]
        for model, selector in ((Work, Work.work_id == scope.work_id),
                (Claim, Claim.work_id == scope.work_id),
                (Outcome, Outcome.claim_id == outcomes[0].claim_id)):
            with pytest.raises(DBAPIError):
                with session.begin_nested():
                    session.execute(update(model).where(selector).values(content_hash=acceptance_digest("tampered")))
        with pytest.raises(DBAPIError):
            with session.begin_nested():
                session.execute(update(Lease).where(Lease.work_id == scope.work_id).values(epoch=2, owner_id="late-owner"))
    assert journal_counts(value) == (1, 1, 1, size, size, 1 + size * 2, 1 + size * 2)


def assert_actual_pg_unknown_claim_keeps_complete_denominator_and_cannot_replay(pg_case_execution):
    value = pg_case_execution
    value["runner"].failure = TimeoutError("explicit possibly dispatched wire specimen")
    result = asyncio.run(value["service"].execute(value["plan"], value["scope"], require_current=lambda: None))
    assert result["state"]["state"] == "outcome_unknown"
    assert result["state"]["not_dispatched_case_count"] == len(value["roster"]) - 1
    assert journal_counts(value) == (1, 1, 1, 1, 0, 2, 2)
    value["runner"].failure = None
    with pytest.raises(RunPlanCaseWorkBusy):
        asyncio.run(value["service"].execute(value["plan"], value["scope"], require_current=lambda: None))
    assert len(value["runner"].commands) == 1
    assert value["service"].read(value["plan"], value["scope"], require_access=lambda: None) == result


def assert_actual_pg_concurrent_acquisition_has_one_original_work_binding_and_owner(pg_case_execution):
    value, gate = pg_case_execution, Barrier(2)
    def acquire():
        gate.wait(timeout=10)
        try:
            return value["journal"].acquire(value["scope"], value["roster"], uuid4().hex, require_current=lambda: None)
        except RunPlanCaseWorkBusy:
            return None
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(acquire) for _ in range(2)]
        results = [future.result(timeout=20) for future in futures]
    assert sum(result is not None for result in results) == 1
    assert journal_counts(value) == (1, 1, 1, 0, 0, 1, 1)


def assert_actual_pg_late_revoke_or_flush_failure_rolls_back_only_uncommitted_original_facts(pg_case_execution, monkeypatch, stage, fault):
    value, revoked, retained = pg_case_execution, False, []
    journal, scope, roster = value["journal"], value["scope"], value["roster"]
    lease = journal.acquire(scope, roster, uuid4().hex, require_current=lambda: None) if stage != "acquire" else None
    claim = journal.claim(lease, roster[0], require_current=lambda: None) if stage == "complete" else None
    outcome = original_outcome(value, lease, claim) if claim else None
    before = journal_counts(value)
    original_event = journal._event
    def fail_after_flush(session, *args):
        nonlocal revoked
        original_event(session, *args)
        session.flush()
        if fault == "outbox_failure":
            raise RuntimeError("explicit original outbox failure")
        if fault == "actor_disable":
            # Keep an identity-map hit alive so the final guard must fetch current PG state.
            retained.append(session.get(UserIdentityRecord, scope.actor_id))
            assert retained[-1].status == "active"
            with session_scope() as separate:
                separate.execute(update(UserIdentityRecord).where(UserIdentityRecord.user_id == scope.actor_id).values(status="disabled"))
        revoked = True
    monkeypatch.setattr(journal, "_event", fail_after_flush)
    def current():
        if revoked and fault == "source_revoke":
            raise SourceAccessDenied("explicit source revoke at the original transaction boundary")
    expected = {"source_revoke": SourceAccessDenied, "actor_disable": PermissionError, "outbox_failure": RuntimeError}[fault]
    try:
        with pytest.raises(expected):
            if stage == "acquire": journal.acquire(scope, roster, uuid4().hex, require_current=current)
            elif stage == "claim": journal.claim(lease, roster[0], require_current=current)
            else: journal.complete(lease, claim, **outcome, require_current=current)
        assert journal_counts(value) == before
    finally:
        if fault == "actor_disable":
            with session_scope() as session:
                session.execute(update(UserIdentityRecord).where(UserIdentityRecord.user_id == scope.actor_id).values(status="active"))


def assert_corrupt_owned_minio_case_bytes_fail_read_without_rewriting_actual_pg(pg_case_execution):
    value = pg_case_execution
    result = asyncio.run(value["service"].execute(value["plan"], value["scope"], require_current=lambda: None))
    assert result["state"]["state"] == "observed"
    before = journal_counts(value)
    with session_scope() as session:
        outcome = session.scalar(select(Outcome).join(Claim).where(Claim.work_id == value["scope"].work_id))
        assert outcome is not None
        original = value["artifacts"].read(value["scope"].project_id, outcome.artifact_ref, outcome.artifact_hash)
        assert original["observation"]["case_id"] == outcome.payload["case_id"]
        key = value["artifacts"]._key(value["scope"].project_id, outcome.artifact_hash)
    value["artifacts"].storage.put_bytes(key, b"{}", content_type="application/json")
    with pytest.raises(RunPlanCaseExecutionInvalid):
        value["service"].read(value["plan"], value["scope"], require_access=lambda: None)
    assert journal_counts(value) == before


def test_original_case_journal_pg_minio_lifecycle_and_transaction_faults(pg_case_execution, monkeypatch):
    # Reuse only the immutable verified parent; every scenario has a fresh command/run/lease/archive namespace.
    for check in (assert_complete_original_cases_commit_to_actual_pg_and_minio_without_nested_worker_lock,
            assert_actual_pg_unknown_claim_keeps_complete_denominator_and_cannot_replay,
            assert_actual_pg_concurrent_acquisition_has_one_original_work_binding_and_owner,
            assert_corrupt_owned_minio_case_bytes_fail_read_without_rewriting_actual_pg):
        check(new_attempt(pg_case_execution))
    for stage in ("acquire", "claim", "complete"):
        for fault in ("source_revoke", "actor_disable", "outbox_failure"):
            with monkeypatch.context() as changes:
                assert_actual_pg_late_revoke_or_flush_failure_rolls_back_only_uncommitted_original_facts(
                    new_attempt(pg_case_execution), changes, stage, fault)
