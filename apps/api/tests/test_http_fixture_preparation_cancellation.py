"""Original unbound observation/cancellation with explicit session specimens."""
import asyncio
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects.postgresql import dialect

from apps.api.app.application.quality_loop.http_fixture_jobs import HttpFixtureJobApplicationService, HttpFixtureJobTarget
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixture_command import FIXTURE_CANCEL_TOOL, FALSE_AUTHORITIES
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.http_fixture_command_models import HttpFixtureCommandRecord as Intent
from apps.api.app.infrastructure.persistence.http_fixture_job_models import HttpFixtureCancellationRecord as BoundCancellation, HttpFixtureCancellationDeliveryRecord as BoundDelivery
from apps.api.app.infrastructure.persistence.http_fixture_preparation_models import HttpFixturePreparationRecord as Preparation, HttpFixturePreparationBindingRecord as Binding
from apps.api.app.infrastructure.persistence.http_fixture_preparation_cancel_models import HttpFixturePreparationCancellationRecord as Cancellation, HttpFixturePreparationCancellationDeliveryRecord as Delivery
from apps.api.app.infrastructure.persistence import http_fixture_job_repository as adapter
from apps.api.tests.test_http_fixture_commands import command_specimen
from apps.api.tests.test_http_fixture_native_grants import native_grant, spec
from apps.api.tests.test_http_fixture_preparation import preparing
from apps.api.tests.test_http_fixture_jobs import application_specimen, job_specimen


@pytest.fixture
def unbound(preparing):
    v = preparing
    v.preparation = deepcopy(v.claim())
    add = v.session.add
    def record(row):
        add(row)
        if isinstance(row, (Cancellation, Delivery)):
            v.rows[(type(row), row.invocation_id)] = row
    v.session.add = record
    v.target = HttpFixtureJobTarget(project_id=v.inputs.selection.project_id, invocation_id=v.command.id)
    v.control = ToolInvocationRecord(id="cancel-original-preparation", tool_id=FIXTURE_CANCEL_TOOL, status="running",
        conversation_id=None, input_payload={**v.target.model_dump(mode="json"), "confirmed_by_user": True,
            "confirmed_actor_id": "other-administrator", "confirmed_at": v.session.now.isoformat()})
    v.rows[(ToolInvocationRecord, v.control.id)] = v.control
    def cancel():
        return v.repository.cancel(v.target, control_id=v.control.id, actor_id="other-administrator", require_current=lambda: None)
    v.cancel = cancel
    return v


def test_original_preparation_observation_is_metadata_only_and_does_not_bind_or_create_target_history(unbound):
    v = unbound
    before = len(v.session.added)
    observed = v.repository.preparation_state(v.inputs, v.authority)
    assert observed == {"schema": "nasus.http-fixture-job.v2", "project_id": v.target.project_id,
        "invocation_id": v.target.invocation_id, "request_digest": v.authority.request_digest,
        "selection": v.inputs.selection.model_dump(mode="json"), "status": "running",
        "preparation_digest": acceptance_digest(v.preparation), "intent_digest": None, "phase": "preparing",
        "phases": [], "target_observation_verified": False, "cancellation_requested": False,
        "cancellation_delivered": False, **{key: False for key in FALSE_AUTHORITIES}}
    assert len(v.session.added) == before and not v.events and not v.outbox
    assert (Intent, v.command.id) not in v.rows and (Binding, v.command.id) not in v.rows


def test_independent_preparation_cancel_locks_original_and_never_manufactures_intent(unbound):
    v = unbound
    original = deepcopy(v.command.input_payload)
    assert v.cancel() == "cancelled"
    assert v.command.id in v.session.locks and v.control.id in v.session.locks
    assert v.command.input_payload == original and len(v.outbox) == 2
    record = v.rows[(Cancellation, v.command.id)]
    assert record.preparation_digest == acceptance_digest(v.preparation)
    assert record.request_digest == v.authority.request_digest and record.actor_id == "other-administrator"
    assert all(record.payload[key] is False for key in FALSE_AUTHORITIES)
    assert (Intent, v.command.id) not in v.rows and (Binding, v.command.id) not in v.rows
    assert (BoundCancellation, v.command.id) not in v.rows
    observed = v.repository.preparation_state(v.inputs, v.authority)
    assert observed["phase"] == "preparation_cancelled" and observed["cancellation_requested"]
    assert not observed["cancellation_delivered"] and not observed["phases"]
    v.session.now += timedelta(days=2)
    original_cancel = deepcopy(record.payload)
    assert v.cancel() == "cancelled" and record.payload == original_cancel and len(v.outbox) == 2
    v.repository.cancellation_delivered(v.target)
    v.repository.cancellation_delivered(v.target)
    assert len(v.outbox) == 3 and v.rows[(Delivery, v.command.id)].cancellation_digest == acceptance_digest(original_cancel)
    assert v.repository.preparation_state(v.inputs, v.authority)["cancellation_delivered"] is True
    assert v.repository.finish(v.authority, "failed") == "cancelled"
    for event in v.outbox[1:]: v.repository.verify_event(v.session, event)


def test_cancelled_preparation_never_rebinds_or_starts_workflow(unbound):
    v = unbound
    v.cancel()
    with pytest.raises(HttpFixtureInvalid):
        v.repository.bind(v.inputs, v.authority, require_current=lambda: None)
    assert (Intent, v.command.id) not in v.rows
    async def start(_): pytest.fail("cancelled preparation must not start a workflow")
    jobs = HttpFixtureJobApplicationService(SimpleNamespace(grants=None), v.repository, SimpleNamespace(start=start))
    assert asyncio.run(jobs.deliver(v.command.id)) == "cancelled"
    assert asyncio.run(jobs.fail(v.command.id)) == "cancelled"


@pytest.mark.parametrize("change", ["target", "tool", "actor", "confirmation", "expired", "future", "naive", "extra", "missing_actor"])
def test_unbound_cancel_requires_exact_independent_control_without_terminal_write(unbound, change):
    v = unbound
    if change == "target": v.control.input_payload["invocation_id"] = "other-command"
    elif change == "tool": v.control.tool_id = "quality.http_fixture.execute"
    elif change == "actor": v.control.input_payload["confirmed_actor_id"] = "another"
    elif change == "confirmation": v.control.input_payload["confirmed_by_user"] = 1
    elif change == "expired": v.session.now += timedelta(seconds=901)
    elif change == "future": v.session.now -= timedelta(seconds=1)
    elif change == "naive": v.control.input_payload["confirmed_at"] = v.session.now.replace(tzinfo=None).isoformat()
    elif change == "missing_actor": v.control.input_payload.pop("confirmed_actor_id")
    else: v.control.input_payload["execution_authorized"] = True
    with pytest.raises(HttpFixtureInvalid): v.cancel()
    assert v.command.status == "running" and not v.outbox and (Cancellation, v.command.id) not in v.rows


@pytest.mark.parametrize("change", ["original_input", "control_input", "preparation", "missing_preparation", "actor",
    "project", "recorded_before", "recorded_expired", "authority", "orphan_delivery", "wrong_branch", "invented_intent"])
def test_preparation_cancel_replay_rejects_rehashed_or_missing_ancestry_without_repair(unbound, change):
    v = unbound
    v.cancel()
    row = v.rows[(Cancellation, v.command.id)]
    if change == "original_input": v.command.input_payload["idempotency_key"] = "changed"
    elif change == "control_input": v.control.input_payload["idempotency_key"] = "changed"
    elif change == "missing_preparation": v.rows.pop((Preparation, v.command.id))
    elif change == "orphan_delivery":
        v.repository.cancellation_delivered(v.target)
        v.rows.pop((Cancellation, v.command.id))
    elif change == "wrong_branch": v.rows[(BoundDelivery, v.command.id)] = SimpleNamespace()
    elif change == "invented_intent": v.rows[(Intent, v.command.id)] = SimpleNamespace()
    else:
        key, value = {"preparation": ("preparation_digest", acceptance_digest("other")), "actor": ("actor_id", ""),
            "project": ("project_id", "other"), "recorded_before": ("recorded_at", (v.session.now - timedelta(seconds=1)).isoformat()),
            "recorded_expired": ("recorded_at", (v.session.now + timedelta(seconds=901)).isoformat()),
            "authority": ("business_coverage_verified", True)}[change]
        row.payload[key] = value
        if key in row.__table__.columns: setattr(row, key, value)
        row.content_hash = acceptance_digest(row.payload)
    before = len(v.session.added)
    with pytest.raises(HttpFixtureInvalid): v.repository._cancellation(v.session, v.command.id)
    assert len(v.session.added) == before and v.command.status == "cancelled"


def test_missing_preparation_cancel_cannot_be_read_as_an_uncancelled_terminal_job(unbound):
    v = unbound
    v.cancel()
    v.rows.pop((Cancellation, v.command.id))
    with pytest.raises(HttpFixtureInvalid, match="lost its original cancellation"):
        v.repository.preparation_state(v.inputs, v.authority)
    assert (Cancellation, v.command.id) not in v.rows


@pytest.mark.parametrize("branch", ["request", "delivery"])
@pytest.mark.parametrize("recorded_at", [None, True, "invalid-private-time", "2026-10-13T00:00:00"])
def test_corrupt_preparation_cancellation_time_is_a_typed_integrity_rejection(unbound, branch, recorded_at):
    v = unbound
    v.cancel()
    if branch == "delivery": v.repository.cancellation_delivered(v.target)
    row = v.rows[(Cancellation if branch == "request" else Delivery, v.command.id)]
    row.payload["recorded_at"] = row.recorded_at = recorded_at
    row.content_hash = acceptance_digest(row.payload)
    before = len(v.session.added)
    with pytest.raises(HttpFixtureInvalid): v.repository._cancellation(v.session, v.command.id)
    assert len(v.session.added) == before and v.command.status == "cancelled"
    assert row.recorded_at == recorded_at


@pytest.mark.parametrize("branch", ["request", "delivery"])
@pytest.mark.parametrize("recorded_at", [None, True, "invalid-private-time", "2026-10-13T00:00:00"])
def test_legacy_bound_cancellation_corrupt_time_has_the_same_typed_rejection(job_specimen, branch, recorded_at):
    v = job_specimen
    v.job_repository.cancel(v.target, control_id=v.control.id, actor_id="other-administrator", require_current=lambda: None)
    if branch == "delivery": v.job_repository.cancellation_delivered(v.target)
    row = v.rows[(BoundCancellation if branch == "request" else BoundDelivery, v.command.id)]
    row.payload["recorded_at"] = row.recorded_at = recorded_at
    row.content_hash = acceptance_digest(row.payload)
    before = len(v.session.added)
    with pytest.raises(HttpFixtureInvalid): v.job_repository._cancellation(v.session, v.command.id)
    assert len(v.session.added) == before and v.command.status == "cancelled"
    assert row.recorded_at == recorded_at


def test_bound_cancel_keeps_legacy_branch_when_binding_wins_project_lock(unbound):
    v = unbound
    v.repository.bind(v.inputs, v.authority, require_current=lambda: None)
    assert v.repository.preparation_state(v.inputs, v.authority) is None
    add = v.session.add
    def record(row):
        add(row)
        if isinstance(row, BoundCancellation): v.rows[(BoundCancellation, row.invocation_id)] = row
    v.session.add = record
    assert v.cancel() == "cancelled"
    assert (BoundCancellation, v.command.id) in v.rows and (Cancellation, v.command.id) not in v.rows
    assert (Intent, v.command.id) in v.rows and (Binding, v.command.id) in v.rows


@pytest.mark.parametrize("status", ["failed", "completed"])
def test_preparation_cancel_does_not_overwrite_existing_terminal_command(unbound, status):
    v = unbound
    v.command.status = status
    assert v.cancel() == status and not v.outbox and (Cancellation, v.command.id) not in v.rows


def test_cancelled_preparation_event_does_not_accept_private_body_or_invented_run_authority(unbound):
    v = unbound
    v.cancel()
    event = v.outbox[-1]
    for change in ({"payload": {"target_response": "private"}}, {"run_id": "invented-run"}):
        with pytest.raises(HttpFixtureInvalid): v.repository.verify_event(v.session, event.model_copy(update=change))


def test_pending_cancellations_union_has_global_id_cursor_and_bounded_limit(unbound):
    v = unbound
    queries = []
    v.session.execute = lambda query: queries.append(query) or [SimpleNamespace(invocation_id=v.command.id, project_id=v.target.project_id)]
    assert v.repository.pending_cancellations(after_id="earlier", limit=105) == [(v.command.id, v.target.project_id)]
    query = queries[0]
    compiled = query.compile(dialect=dialect())
    sql = str(compiled)
    assert "UNION ALL" in sql and "quality_http_fixture_preparation_cancellations" in sql
    assert "quality_http_fixture_cancellations" in sql and "ORDER BY anon_1.invocation_id" in sql
    assert "anon_1.invocation_id >" in sql and query._limit_clause.value == 100


def test_application_unbound_read_reauthorizes_without_opening_target_archive(application_specimen):
    v = application_specimen
    receipt = {"schema": "nasus.http-fixture-job.v2", "phase": "preparing", "target_observation_verified": False}
    v.jobs.repository.preparation_state = lambda *_: receipt
    def forbidden(*args, **kwargs): pytest.fail("unbound state must not read target archive")
    v.jobs.execution.read = forbidden
    target = HttpFixtureJobTarget(project_id=v.selected.project_id, invocation_id=v.authority.invocation_id)
    assert v.jobs.read(target) == receipt
    v.source.state["revoked"] = True
    with pytest.raises(SourceAccessDenied): v.jobs.read(target)


@pytest.mark.parametrize("outage", [False, True])
def test_application_unbound_cancel_is_durable_before_rpc_and_transport_loss(application_specimen, outage):
    v = application_specimen
    v.jobs.repository.preparation_state = lambda *_: {"phase": "preparing"}
    v.state["delivery_fault"] = outage
    v.jobs.execution.read = lambda *args, **kwargs: pytest.fail("preparation cancel must not read target archive")
    target = HttpFixtureJobTarget(project_id=v.selected.project_id, invocation_id=v.authority.invocation_id)
    assert asyncio.run(v.jobs.cancel(target, control_id="original-control")) == "cancelled"
    assert v.calls.index("cancel-recorded") < v.calls.index("workflow-cancel")
    assert ("delivery-recorded" in v.calls) is not outage
