"""Real PG batch ledger with explicit native-reply fixtures, not external models."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import importlib
import json
from threading import Event, Thread
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.generation_batch_ledger import batch_execution_request, batch_reservation
from apps.api.app.application.quality_loop.generation_batch_receipts import GenerationBatchReceiptApplicationService
from apps.api.app.application.quality_loop.generation_executor import GenerationOutcomeUnknown, NativeGenerationReply
from apps.api.app.application.quality_loop.generation_work_lease import GenerationLeaseLost
from apps.api.app.application.quality_loop.test_design_results import TestDesignResultIntegrityError
from apps.api.app.infrastructure.persistence.generation_batch_models import (
    GenerationBatchReservationRecord as Plan, GenerationBatchCallRecord as Claim, GenerationBatchReplyRecord as BatchReply,
)
from apps.api.app.infrastructure.persistence.generation_batch_repository import GenerationBatchRepository
from apps.api.app.infrastructure.persistence.generation_job_models import GenerationWorkLeaseRecord as WorkLease
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, LLMCallRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.storage.generation_batch_reply_artifacts import GenerationBatchReplyArtifacts
from apps.api.tests.test_generation_execution_api import (
    execution, design_scope, publication, documents, evidence_api, seed, count, Reservation, Reply, Result, budget,
)
from apps.api.tests.test_generation_batches import responses_for


@pytest.fixture
def ledger(execution, monkeypatch):
    v = execution
    service = v["executor"]
    # This counter is explicitly a test fixture; production uses pinned real
    # tokenizer policies. Three actual source ACs force three complete calls.
    counter = service.policies.resolve(service.profiles.resolve(v["selection"].model_config_id).binding)
    monkeypatch.setattr(service.policies, "resolve", lambda binding: SimpleNamespace(policy=counter.policy,
        count=lambda system, content: 4000 * max(1, len(json.loads(content)["local_constraint_ids"]))))
    selected = v["selection"].model_copy(update={"budget": budget(max_calls=3, max_reserved_tokens=3 * 136192,
        max_reserved_cost_nanos=3 * 136192000, max_input_tokens_per_call=6500)})
    with actor_scope(UserProfile.model_validate(v["owner"])):
        planned = service.batch_planning.prepare(selected)
        request = batch_execution_request(planned)
    v["execution_request"] = request
    ident = seed(v)
    lease = v["jobs"].repository.claim_lease(v["project_id"], ident, uuid4().hex)
    receipts = GenerationBatchReceiptApplicationService(service.batch_planning, service.authorization,
        v["jobs"].repository, GenerationBatchRepository(), GenerationBatchReplyArtifacts(service.artifacts.storage))
    stopped, renewal_errors = Event(), []
    def heartbeat():
        while not stopped.wait(5):
            try:
                v["jobs"].repository.renew_lease(lease)
            except Exception as exc:
                renewal_errors.append(exc)
                return
    worker = Thread(target=heartbeat, daemon=True)
    worker.start()
    def stop():
        stopped.set()
        worker.join(10)
    v.update(batch_receipts=receipts, batch_planned=planned, batch_selection=selected, batch_request=request,
        batch_plan=batch_reservation(planned, invocation_id=ident, actor_id=v["owner"]["id"]),
        batch_lease=lease, batch_invocation_id=ident, stop_batch_heartbeat=stop, batch_renewal_errors=renewal_errors)
    try:
        yield v
    finally:
        stop()
        v["jobs"].repository.release_lease(lease)


def reserve(v):
    return v["batch_receipts"].reserve(v["batch_request"], lease=v["batch_lease"])


def view(v):
    return v["batch_receipts"].read(v["batch_request"], lease=v["batch_lease"])


def archive(v, sequence, content="Explicit native reply fixture; no model request"):
    return v["batch_receipts"].archive_reply(v["batch_request"], sequence,
        NativeGenerationReply(content, 100, 50, "provider"), lease=v["batch_lease"], latency_ms=5)


def transaction_count(v, model):
    if model is AuditEventRecord:
        condition = model.tool_invocation_id == v["batch_invocation_id"]
    elif model is SSEEventOutboxRecord:
        condition = model.entity_id == v["batch_invocation_id"]
    else:
        return count(v, model)
    with session_scope() as session:
        return session.scalar(select(func.count()).select_from(model).where(condition))


@pytest.mark.parametrize("documents", [3], indirect=True)
def test_three_source_acs_have_complete_budget_individual_native_receipts_and_replay(ledger):
    v = ledger
    with actor_scope(UserProfile.model_validate(v["owner"])):
        plan = reserve(v)
        assert len(plan.batches) == 3 and len(plan.request.execution.source_binding_ids) == 3
        assert reserve(v) == plan and count(v, Plan) == 1
        assert view(v)["budget"]["reserved_tokens"] == 3 * 136192
        responses = responses_for(v["batch_planned"].input, v["batch_planned"].plan)
        for sequence, (_, content) in enumerate(responses):
            claim = v["batch_receipts"].claim(v["batch_request"], sequence, lease=v["batch_lease"])
            assert claim["sequence"] == sequence
            with pytest.raises(GenerationOutcomeUnknown):
                v["batch_receipts"].claim(v["batch_request"], sequence, lease=v["batch_lease"])
            archive(v, sequence, content)
        replay = view(v)
        assert replay["responses"] == responses
        assert replay["budget"]["claimed_calls"] == replay["budget"]["archived_calls"] == 3
        assert replay["budget"]["known_input_tokens"] == 300 and replay["budget"]["known_output_tokens"] == 150
        assert replay["budget"]["unknown_calls"] == 0 and replay["budget"]["reservation_released"] is False
        checked = v["executor"].batch_planning.check_outputs(v["batch_selection"],
            expected_planning_digest=v["batch_planned"].digest, responses=replay["responses"])
        assert checked["proposal"]["coverage"]["obligation_denominator"] == len(v["batch_planned"].input["obligations"])
        assert checked["proposal"]["coverage"]["passed_count"] == 0
    assert count(v, Plan) == 1 and count(v, Claim) == count(v, BatchReply) == 3
    assert count(v, Reservation) == count(v, Reply) == count(v, Result) == 0 and not v["native_calls"]
    with session_scope() as session:
        calls = session.scalars(select(LLMCallRecord).where(LLMCallRecord.tool_invocation_id == v["batch_invocation_id"])).all()
        assert len(calls) == 3 and len({call.request_hash for call in calls}) == 3
        assert all(call.model_calls == 1 and call.prompt_version == "batch-v1" for call in calls)
        events = session.scalars(select(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.event_payload["entity_id"].as_string() == v["batch_invocation_id"])).all()
        assert len(events) == 7
        assert "Explicit synthetic test input" not in json.dumps([event.event_payload for event in events])
    assert not v["batch_renewal_errors"]


def test_concurrent_batch_claim_and_unknown_failure_never_release_or_duplicate_calls(ledger):
    v = ledger
    with actor_scope(UserProfile.model_validate(v["owner"])):
        plan = reserve(v)
    def claim():
        with actor_scope(UserProfile.model_validate(v["owner"])):
            try:
                return v["batch_receipts"].claim(v["batch_request"], 0, lease=v["batch_lease"])
            except GenerationOutcomeUnknown:
                return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: claim(), range(2)))
    assert sum(value is not None for value in outcomes) == 1
    claimed = next(value for value in outcomes if value is not None)
    call = v["batch_receipts"]._call(plan, claimed, None, outcome="error", latency_ms=5)
    repository = v["batch_receipts"].repository
    repository.record_failure(plan, 0, call)
    repository.record_failure(plan, 0, call)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        replay = view(v)
        assert replay["budget"]["unknown_calls"] == 1 and not replay["budget"]["reservation_released"]
        with pytest.raises(GenerationOutcomeUnknown):
            archive(v, 0)
        with pytest.raises(GenerationOutcomeUnknown):
            v["batch_receipts"].claim(v["batch_request"], 0, lease=v["batch_lease"])
    assert count(v, Claim) == 1 and count(v, BatchReply) == count(v, Result) == 0 and not v["native_calls"]


@pytest.mark.parametrize("event_type,phase", [
    ("quality.test_design.batch_budget_reserved", "reserve"),
    ("quality.test_design.batch_call_reserved", "claim"),
    ("quality.test_design.batch_reply_archived", "reply"),
])
def test_batch_outbox_failure_rolls_back_each_business_transaction(ledger, monkeypatch, event_type, phase):
    v = ledger
    original = EventOutboxRepository.append
    def fail(self, event, **kwargs):
        if event.event_type == event_type:
            raise RuntimeError("injected batch outbox failure")
        return original(self, event, **kwargs)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        if phase != "reserve":
            reserve(v)
        if phase == "reply":
            v["batch_receipts"].claim(v["batch_request"], 0, lease=v["batch_lease"])
        before = {model: transaction_count(v, model) for model in (Plan, Claim, BatchReply, LLMCallRecord, AuditEventRecord, SSEEventOutboxRecord)}
        monkeypatch.setattr(EventOutboxRepository, "append", fail)
        with pytest.raises(RuntimeError, match="batch outbox failure"):
            if phase == "reserve":
                reserve(v)
            elif phase == "claim":
                v["batch_receipts"].claim(v["batch_request"], 0, lease=v["batch_lease"])
            else:
                archive(v, 0)
        assert all(transaction_count(v, model) == expected for model, expected in before.items())
        if phase == "reply":
            assert view(v)["budget"]["unknown_calls"] == 1
    assert not v["native_calls"]


def test_lost_worker_cannot_archive_reply_after_private_object_write(ledger, monkeypatch):
    v = ledger
    receipts = v["batch_receipts"]
    original = receipts.artifacts.put
    def takeover(*args):
        value = original(*args)
        v["stop_batch_heartbeat"]()
        with session_scope() as session:
            session.execute(update(WorkLease).where(WorkLease.invocation_id == v["batch_invocation_id"]).values(expires_at=func.clock_timestamp()))
        v["jobs"].repository.claim_lease(v["project_id"], v["batch_invocation_id"], uuid4().hex)
        return value
    with actor_scope(UserProfile.model_validate(v["owner"])):
        reserve(v)
        receipts.claim(v["batch_request"], 0, lease=v["batch_lease"])
        monkeypatch.setattr(receipts.artifacts, "put", takeover)
        with pytest.raises(GenerationLeaseLost):
            archive(v, 0)
    assert count(v, Claim) == 1 and count(v, BatchReply) == count(v, Result) == 0


def test_batch_private_archive_corruption_hides_body_and_blocks_reuse(ledger, monkeypatch):
    v = ledger
    with actor_scope(UserProfile.model_validate(v["owner"])):
        reserve(v)
        v["batch_receipts"].claim(v["batch_request"], 0, lease=v["batch_lease"])
        archive(v, 0)
        original = v["batch_receipts"].artifacts.read
        monkeypatch.setattr(v["batch_receipts"].artifacts, "read", lambda *args: {**original(*args), "content": "changed private content"})
        with pytest.raises(TestDesignResultIntegrityError):
            view(v)
    assert count(v, Claim) == count(v, BatchReply) == 1


def test_batch_source_acl_change_blocks_next_claim_without_refunding_budget(ledger):
    from apps.api.app.domain.system_image.source_access import SourceAccessRule
    from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository

    v = ledger
    with actor_scope(UserProfile.model_validate(v["owner"])):
        reserve(v)
        repository = SourceAccessRepository()
        snapshot = repository.load_snapshot(v["project_id"])
        repository.set_policy(v["project_id"], snapshot.bindings[0].binding_id, SourceAccessRule("restricted"),
            expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="batch-source-policy-fixture")
        with pytest.raises(ValueError):
            v["batch_receipts"].claim(v["batch_request"], 0, lease=v["batch_lease"])
    assert count(v, Plan) == 1 and count(v, Claim) == 0 and not v["native_calls"]


def test_batch_plan_claim_reply_are_append_only_and_downgrade_preserves_history(ledger):
    v = ledger
    with actor_scope(UserProfile.model_validate(v["owner"])):
        reserve(v)
        v["batch_receipts"].claim(v["batch_request"], 0, lease=v["batch_lease"])
        archive(v, 0)
    for model in (Plan, Claim, BatchReply):
        for statement in (update(model).where(model.project_id == v["project_id"]).values(project_id="other"),
                          delete(model).where(model.project_id == v["project_id"])):
            with pytest.raises(IntegrityError, match="append-only"):
                with session_scope() as session:
                    session.execute(statement)
    migration = importlib.import_module("apps.api.migrations.versions.0063_generation_batch_ledger")
    with session_scope() as session:
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        with Operations.context(MigrationContext.configure(session.connection())):
            with pytest.raises(RuntimeError, match="generation batch reservations exist"):
                migration.downgrade()


def test_legacy_single_call_cannot_reuse_a_batch_budget_reservation(ledger):
    v = ledger
    with actor_scope(UserProfile.model_validate(v["owner"])):
        plan = reserve(v)
        payload = {"schema": "nasus.test-design-call-reservation.v1", "project_id": plan.project_id,
            "invocation_id": plan.invocation_id, "actor_id": plan.actor_id, "call_id": str(uuid4()),
            "request": plan.request.model_dump(mode="json"), "model_binding": plan.model_binding.model_dump(mode="json"),
            "policy": plan.policy.model_dump(mode="json"), "reservation": plan.reservation.model_dump(mode="json"),
            "reserved_at": datetime.now(timezone.utc).isoformat()}
        def forbidden():
            pytest.fail("mutually exclusive reservation must reject before authorizing legacy egress")
        with pytest.raises(GenerationOutcomeUnknown):
            v["executor"].repository.reserve(plan.request, payload, require_current=forbidden)
    assert count(v, Reservation) == count(v, Reply) == count(v, Result) == 0 and not v["native_calls"]
