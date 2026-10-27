"""Actual PG private recovery commits with seeded authority/worker and replies.

Local private storage and protocol fixtures do not prove public dispatch,
Temporal recovery, external Provider egress or execution of the source project.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
from threading import Event, Thread

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.generation_batch_recovery import batch_recovery_request
from apps.api.app.application.quality_loop.generation_batch_recovery_results import GenerationBatchRecoveryApplicationService
from apps.api.app.application.quality_loop.generation_work_lease import GenerationLeaseLost
from apps.api.app.application.quality_loop.test_design_results import RECOVERED_BATCH_RESULT_SCHEMA
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, ModelProviderConfigRecord, SSEEventOutboxRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.generation_batch_recovery_models import GenerationBatchRecoveryResultRecord as Recovery
from apps.api.app.infrastructure.persistence.generation_batch_recovery_repository import GenerationBatchRecoveryRepository
from apps.api.app.infrastructure.persistence.generation_job_models import GenerationWorkLeaseRecord as WorkLease
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.test_design_result_models import TestDesignCaseRecord as Case, TestDesignCoverageRecord as Coverage, TestDesignResultBatchCallRecord as Provenance
from apps.api.app.infrastructure.persistence.test_design_scope_repository import TestDesignScopeRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_generation_batch_recovery_api import (
    ledger, execution, design_scope, publication, documents, evidence_api, reserve, archive, count, Plan, Claim, BatchReply, Result,
    seed_authority, changed_record,
)
from apps.api.tests.test_generation_batches import responses_for
from apps.api.tests.test_source_access_api import grant_member


@pytest.fixture
def recovering(ledger):
    v, repository = ledger, GenerationBatchRecoveryRepository()
    with actor_scope(UserProfile.model_validate(v["owner"])):
        plan = reserve(v)
        for sequence, (_, content) in enumerate(responses_for(v["batch_planned"].input, v["batch_planned"].plan)):
            v["batch_receipts"].claim(v["batch_request"], sequence, lease=v["batch_lease"])
            archive(v, sequence, content)
        calls = repository.verified_calls(plan, lease=v["batch_lease"], require_current=lambda: None)
        request = batch_recovery_request(plan, v["batch_planned"].input, v["batch_planned"].plan, calls)
    v["stop_batch_heartbeat"]()
    assert v["jobs"].repository.finish(v["project_id"], plan.invocation_id, "failed", "Seeded failed batch fixture",
        lease=v["batch_lease"]) == "failed"
    lease, _ = seed_authority(v, request)
    stopped, errors = Event(), []
    # Private seeded-worker heartbeat: not the unregistered public batch parser.
    def heartbeat():
        while not stopped.wait(5):
            try:
                with session_scope() as session:
                    TestDesignScopeRepository._lock(session, plan.project_id)
                    row = session.get(WorkLease, lease.invocation_id)
                    now = session.scalar(select(func.clock_timestamp()))
                    command = session.get(ToolInvocationRecord, lease.invocation_id)
                    if (command.status != "running" or row.owner_id != lease.owner_id or row.epoch != lease.epoch
                            or row.request_digest != lease.request_digest or row.expires_at <= now):
                        return
                    row.renewed_at, row.expires_at = now, now + timedelta(seconds=90)
            except Exception as exc:
                errors.append(exc)
                return
    worker = Thread(target=heartbeat, daemon=True)
    worker.start()
    def stop():
        stopped.set()
        worker.join(15)
    v.update(recovery_plan=plan, recovery_request=request, recovery_lease=lease, recovery_calls=calls,
        recovery_errors=errors, stop_recovery_heartbeat=stop,
        recovery_service=GenerationBatchRecoveryApplicationService(v["executor"].batch_planning,
            v["executor"].authorization, repository, v["batch_receipts"].artifacts, app.state.container.test_design_results.artifacts))
    try:
        yield v
    finally:
        stop()
        v["jobs"].repository.release_lease(lease)


def recover(v):
    with actor_scope(UserProfile.model_validate(v["owner"])):
        return v["recovery_service"].recover(v["recovery_request"], lease=v["recovery_lease"])


def read(v, metadata, headers=None):
    return v["client"].get(f"/v1/projects/{v['project_id']}/quality/test-design-results/{metadata['generation_id']}",
        headers=headers or v["headers"])


def empty(v):
    assert count(v, Result) == count(v, Case) == count(v, Coverage) == count(v, Provenance) == count(v, Recovery) == 0
    with session_scope() as session:
        assert not session.scalars(select(AuditEventRecord).where(
            AuditEventRecord.tool_invocation_id == v["recovery_lease"].invocation_id,
            AuditEventRecord.action == "quality.test_design.generated")).all()
        assert not session.scalars(select(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.event_payload["correlation_id"].as_string() == v["project_id"],
            SSEEventOutboxRecord.event_type == "quality.test_design.generated")).all()


@pytest.mark.parametrize("documents", [3], indirect=True)
def test_private_three_batch_recovery_is_atomic_idempotent_and_has_independent_append_only_provenance(recovering, monkeypatch):
    v, original = recovering, EventOutboxRepository.append
    def fail(self, event, **kwargs):
        if event.event_type == "quality.test_design.generated":
            raise RuntimeError("injected recovery outbox failure")
        return original(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    with pytest.raises(RuntimeError, match="recovery outbox failure"):
        recover(v)
    empty(v)
    assert count(v, Claim) == count(v, BatchReply) == 3 and not v["native_calls"]
    monkeypatch.setattr(EventOutboxRepository, "append", original)
    metadata = recover(v)
    assert metadata["schema"] == RECOVERED_BATCH_RESULT_SCHEMA and metadata["call_id"] is None
    assert metadata["recovery_invocation_id"] == v["recovery_lease"].invocation_id
    assert metadata["invocation_id"] == v["batch_invocation_id"] and len(metadata["call_ids"]) == 3
    response = read(v, metadata)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["view_schema"] == "nasus.test-design-result-view.v4"
    assert value["view_hash"] == acceptance_digest({key: item for key, item in value.items() if key != "view_hash"})
    assert "artifact_ref" not in response.text and "native-test-design-fixture-key" not in response.text
    assert value["result"]["recovery_request"] == v["recovery_request"].model_dump(mode="json")
    assert response.headers["cache-control"] == "private, no-store"
    coverage = value["result"]["proposal"]["coverage"]
    assert coverage["obligation_denominator"] == len(v["batch_planned"].input["obligations"])
    assert coverage["passed_count"] == coverage["executed_on_target_count"] == coverage["automated_count"] == 0
    monkeypatch.setattr(v["recovery_service"].result_artifacts, "put", lambda *args: (_ for _ in ()).throw(
        AssertionError("committed recovery must not rewrite its archive")))
    assert recover(v) == metadata
    assert count(v, Result) == count(v, Recovery) == count(v, Coverage) == 1
    assert count(v, Case) == metadata["case_count"] and count(v, Provenance) == 3
    with session_scope() as session:
        assert session.get(ToolInvocationRecord, v["batch_invocation_id"]).status == "failed"
        assert session.get(ToolInvocationRecord, metadata["recovery_invocation_id"]).status == "running"
        audit = session.scalar(select(AuditEventRecord).where(AuditEventRecord.entity_id == metadata["generation_id"],
            AuditEventRecord.action == "quality.test_design.generated"))
        assert audit.tool_invocation_id == metadata["recovery_invocation_id"]
        assert audit.event_metadata["source_invocation_id"] == v["batch_invocation_id"]
    other, _ = seed_authority(v, v["recovery_request"])
    with actor_scope(UserProfile.model_validate(v["owner"])), pytest.raises(ValueError, match="cannot replace"):
        v["recovery_service"].recover(v["recovery_request"], lease=other)
    for statement in (update(Recovery).values(authority_invocation_id="foreign"), delete(Recovery)):
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as session:
                session.execute(statement.where(Recovery.project_id == v["project_id"]))
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from apps.api.app.infrastructure.persistence.database import engine
    migration = importlib.import_module("apps.api.migrations.versions.0065_generation_batch_recovery")
    with engine.begin() as connection:
        old = migration.op
        try:
            migration.op = Operations(MigrationContext.configure(connection))
            with pytest.raises(RuntimeError, match="cannot downgrade"):
                migration.downgrade()
        finally:
            migration.op = old
    v["stop_recovery_heartbeat"]()
    with changed_record(ToolInvocationRecord, metadata["recovery_invocation_id"], status="completed"), changed_record(
            WorkLease, metadata["recovery_invocation_id"], expires_at=datetime.now(timezone.utc) - timedelta(days=1)):
        monkeypatch.setattr(app.state.container.test_design_results.profiles, "resolve", lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("historical recovery must not resolve current model credentials")))
        assert read(v, metadata).status_code == 200
    grant_member(v)
    assert read(v, metadata, v["member_headers"]).status_code == 200
    repository = SourceAccessRepository()
    snapshot = repository.load_snapshot(v["project_id"])
    repository.set_policy(v["project_id"], snapshot.bindings[0].binding_id, SourceAccessRule("restricted"),
        expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="recovered-draft-reader-revocation")
    assert read(v, metadata, v["member_headers"]).status_code == 403
    assert not v["native_calls"] and not v["recovery_errors"]


@pytest.mark.parametrize("failure", ["lease", "acl", "cancel", "model"])
def test_private_recovery_checks_current_authority_again_after_private_artifact_write(recovering, monkeypatch, failure):
    v = recovering
    original = v["recovery_service"].result_artifacts.put
    def changed(*args):
        result = original(*args)
        if failure == "lease":
            v["stop_recovery_heartbeat"]()
            v["jobs"].repository.release_lease(v["recovery_lease"])
        elif failure == "acl":
            repository = SourceAccessRepository()
            snapshot = repository.load_snapshot(v["project_id"])
            repository.set_policy(v["project_id"], snapshot.bindings[0].binding_id, SourceAccessRule("restricted"),
                expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="recovery-write-scope-change")
        else:
            with session_scope() as session:
                if failure == "cancel":
                    session.get(ToolInvocationRecord, v["recovery_lease"].invocation_id).status = "cancelled"
                else:
                    session.get(ModelProviderConfigRecord, v["selection"].model_config_id).model_name = "changed-before-recovery-commit"
        return result
    monkeypatch.setattr(v["recovery_service"].result_artifacts, "put", changed)
    with pytest.raises((GenerationLeaseLost, PermissionError, ValueError)):
        recover(v)
    empty(v)
    assert count(v, Claim) == count(v, BatchReply) == 1 and not v["native_calls"]
    assert v["jobs"].repository.command(v["batch_invocation_id"])[1] == "failed"
