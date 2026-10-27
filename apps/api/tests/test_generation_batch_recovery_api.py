"""Private PG recovery preflight with seeded command/worker and native fixtures.

This does not claim public ToolRuntime/Temporal recovery or external model proof.
"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.generation_batch_recovery import batch_recovery_request, prepare_archived_batch_recovery
from apps.api.app.application.quality_loop.generation_job_ports import GENERATION_RECOVER_TOOL
from apps.api.app.application.quality_loop.generation_work_lease import GenerationLeaseLost, GenerationWorkLease
from apps.api.app.application.quality_loop.test_design_results import TestDesignResultIntegrityError
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.infrastructure.persistence.db_models import ProjectRoleBindingRecord, ToolInvocationRecord, UserIdentityRecord
from apps.api.app.infrastructure.persistence.generation_batch_recovery_repository import GenerationBatchRecoveryRepository
from apps.api.app.infrastructure.persistence.generation_job_models import GenerationWorkLeaseRecord as WorkLease
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_generation_batch_ledger_api import (
    ledger, execution, design_scope, publication, documents, evidence_api, reserve, archive, count, Plan, Claim, BatchReply, Result,
)
from apps.api.tests.test_generation_batches import responses_for


@contextmanager
def changed_record(model, ident, **fields):
    with session_scope() as session:
        row = session.get(model, ident)
        original = {key: deepcopy(getattr(row, key)) for key in fields}
        for key, value in fields.items():
            setattr(row, key, value)
    try:
        yield
    finally:
        with session_scope() as session:
            row = session.get(model, ident)
            for key, value in original.items():
                setattr(row, key, value)


def seed_authority(v, request):
    ident, owner = uuid4().hex, uuid4().hex
    payload = {**request.model_dump(mode="json"), "confirmed_by_user": True,
        "confirmed_actor_id": v["owner"]["id"], "confirmed_at": datetime.now(timezone.utc).isoformat()}
    with session_scope() as session:
        command = ToolInvocationRecord(id=ident, tool_id=GENERATION_RECOVER_TOOL, status="running",
            conversation_id=v["conversation"].json()["id"], input_payload=payload,
            summary="Seeded independent batch recovery fixture, not a public dispatch")
        session.add(command)
        session.flush()
        digest = v["jobs"].repository._request_digest(command)
        now = session.scalar(select(func.clock_timestamp()))
        session.add(WorkLease(invocation_id=ident, project_id=request.project_id, owner_id=owner, epoch=1,
            request_digest=digest, acquired_at=now, renewed_at=now, expires_at=now + timedelta(seconds=90)))
    return GenerationWorkLease(request.project_id, ident, owner, 1, digest), payload


@pytest.mark.parametrize("documents", [3], indirect=True)
def test_pg_private_recovery_requires_complete_pins_fresh_distinct_authority_and_current_worker(ledger):
    v, repository = ledger, GenerationBatchRecoveryRepository()
    with actor_scope(UserProfile.model_validate(v["owner"])):
        plan = reserve(v)
        for sequence, (_, content) in enumerate(responses_for(v["batch_planned"].input, v["batch_planned"].plan)):
            v["batch_receipts"].claim(v["batch_request"], sequence, lease=v["batch_lease"])
            archive(v, sequence, content)
        from apps.api.app.infrastructure.persistence.generation_batch_result_repository import GenerationBatchResultRepository
        calls = GenerationBatchResultRepository().verified_calls(plan, lease=v["batch_lease"], require_current=lambda: None)
        request = batch_recovery_request(plan, v["batch_planned"].input, v["batch_planned"].plan, calls)
        access = v["executor"]._access(v["project_id"])
        for ident in plan.request.execution.source_binding_ids:
            access.require_binding(ident)
    v["stop_batch_heartbeat"]()
    assert v["jobs"].repository.finish(v["project_id"], plan.invocation_id, "failed", "Recovery preflight fixture",
        lease=v["batch_lease"]) == "failed"
    lease, payload = seed_authority(v, request)
    ident = lease.invocation_id
    checks = []
    def current():
        checks.append(True)
        with actor_scope(UserProfile.model_validate(v["owner"])):
            v["executor"].authorization.require_current(access)
    def load(value=request, fence=lease, callback=current):
        return repository.load_for_recovery(value, v["batch_planned"].input, v["batch_planned"].plan,
            lease=fence, require_current=callback)
    loaded = load()
    assert loaded == {"plan": plan, "calls": calls} and len(calls) == 3 and len(checks) == 2
    # The new guard supplies the actual PG fence around every private read;
    # this remains private preparation, not a public recovery result commit.
    def fence(value):
        assert value == lease
        load(fence=value)
    merged = prepare_archived_batch_recovery(request, plan, v["batch_planned"].input,
        v["batch_planned"].plan, calls, v["batch_receipts"].artifacts,
        authority_invocation_id=ident, lease=lease, leases=SimpleNamespace(require_lease=fence), require_current=current)
    coverage = merged["proposal"]["coverage"]
    assert coverage["obligation_denominator"] == len(v["batch_planned"].input["obligations"])
    assert coverage["automated_count"] == coverage["executed_on_target_count"] == coverage["passed_count"] == 0
    assert not coverage["execution_authorized"]
    for mutation in (replace(lease, owner_id="another-owner"), replace(lease, epoch=2),
                     replace(lease, request_digest=acceptance_digest("changed")),
                     replace(lease, invocation_id=plan.invocation_id), replace(lease, project_id="another-project")):
        with pytest.raises(GenerationLeaseLost):
            load(fence=mutation)
    for status in ("running", "completed", "cancelled"):
        with changed_record(ToolInvocationRecord, plan.invocation_id, status=status):
            with pytest.raises(TestDesignResultIntegrityError):
                load()
    for status in ("failed", "completed", "cancelled"):
        with changed_record(ToolInvocationRecord, ident, status=status):
            with pytest.raises(TestDesignResultIntegrityError):
                load()
    altered_payloads = [
        {**payload, "confirmed_by_user": False}, {**payload, "confirmed_actor_id": v["member"]["id"]},
        {**payload, "confirmed_at": (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()},
        {**payload, "confirmed_at": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()},
        {**payload, "confirmed_at": datetime.now().isoformat()},
        {**payload, "request_hash": acceptance_digest("another-request")},
        {**payload, "tool_plan_reason": "canonical payload changed after lease acquisition"},
    ]
    for changed in altered_payloads:
        with changed_record(ToolInvocationRecord, ident, input_payload=changed):
            with pytest.raises((ValueError, GenerationLeaseLost)):
                load()
    fake_calls = deepcopy(calls)
    fake_calls[1]["audit"]["occurred_at"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    fake_request = batch_recovery_request(plan, v["batch_planned"].input, v["batch_planned"].plan, fake_calls)
    fake_payload = {**payload, **fake_request.model_dump(mode="json")}
    fake_digest = acceptance_digest({"tool_id": GENERATION_RECOVER_TOOL, "input_payload": fake_payload})
    with changed_record(ToolInvocationRecord, ident, input_payload=fake_payload), changed_record(WorkLease, ident, request_digest=fake_digest):
        with pytest.raises(TestDesignResultIntegrityError, match="pins changed"):
            load(value=fake_request, fence=replace(lease, request_digest=fake_digest))
    with changed_record(ToolInvocationRecord, ident, conversation_id="foreign-conversation"):
        with pytest.raises(TestDesignResultIntegrityError):
            load()
    with changed_record(WorkLease, ident, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)):
        with pytest.raises(GenerationLeaseLost):
            load()
    with changed_record(UserIdentityRecord, plan.actor_id, status="disabled"):
        with pytest.raises(PermissionError):
            load()
    with session_scope() as session:
        role = session.scalar(select(ProjectRoleBindingRecord).where(ProjectRoleBindingRecord.project_id == plan.project_id,
            ProjectRoleBindingRecord.user_id == plan.actor_id, ProjectRoleBindingRecord.status == "active"))
        role_id = role.binding_id
    with changed_record(ProjectRoleBindingRecord, role_id, role="qa_lead"):
        with pytest.raises(PermissionError):
            load()
    def denied():
        raise PermissionError("current source/model/scope authority unavailable")
    with pytest.raises(PermissionError, match="source/model/scope"):
        load(callback=denied)
    old = {**plan.request.model_dump(mode="json"), "confirmed_by_user": True, "confirmed_actor_id": plan.actor_id,
        "confirmed_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()}
    with changed_record(ToolInvocationRecord, plan.invocation_id, input_payload=old):
        assert load() == loaded
    assert v["jobs"].repository.command(plan.invocation_id)[1] == "failed"
    with session_scope() as session:
        assert session.get(ToolInvocationRecord, ident).status == "running"
    assert count(v, Plan) == 1 and count(v, Claim) == count(v, BatchReply) == 3
    assert count(v, Result) == 0 and not v["native_calls"]


def test_pg_private_recovery_never_accepts_a_fabricated_pin_for_an_unknown_reply(ledger):
    from apps.api.app.application.quality_loop.generation_batch_recovery import BatchRecoveryReplyPin, GenerationBatchRecoveryRequest
    from apps.api.app.application.quality_loop.generation_batch_ledger import batch_call_request_hash
    v = ledger
    with actor_scope(UserProfile.model_validate(v["owner"])):
        plan = reserve(v)
        claim = v["batch_receipts"].claim(v["batch_request"], 0, lease=v["batch_lease"])
    assert len(plan.batches) == 1
    v["stop_batch_heartbeat"]()
    v["jobs"].repository.finish(v["project_id"], plan.invocation_id, "failed", "Unknown native outcome fixture", lease=v["batch_lease"])
    fabricated = acceptance_digest("no archived reply exists")
    request = GenerationBatchRecoveryRequest(project_id=plan.project_id, invocation_id=plan.invocation_id,
        request_hash=acceptance_digest(plan.request.model_dump(mode="json")), reservation_hash=acceptance_digest(plan.model_dump(mode="json")),
        plan_digest=plan.plan_digest, replies_digest=fabricated, replies=(BatchRecoveryReplyPin(sequence=0,
            batch_digest=plan.batches[0].batch_digest, call_id=claim["call_id"], request_hash=batch_call_request_hash(plan, 0),
            reply_artifact_hash=fabricated, response_hash=fabricated, usage_digest=fabricated, audit_digest=fabricated),))
    lease, _ = seed_authority(v, request)
    with pytest.raises(TestDesignResultIntegrityError, match="every successful archived"):
        GenerationBatchRecoveryRepository().load_for_recovery(request, v["batch_planned"].input,
            v["batch_planned"].plan, lease=lease, require_current=lambda: None)
    assert count(v, Claim) == 1 and count(v, BatchReply) == count(v, Result) == 0 and not v["native_calls"]
    assert v["jobs"].repository.command(plan.invocation_id)[1] == "failed"
