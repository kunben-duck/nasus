import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.application.system_image.structure_cancel_inputs import STRUCTURE_CANCEL_TOOL
from apps.api.app.application.system_image.structure_cancellations import StructureCancellationApplicationService
from apps.api.app.domain.system_image.source_access import SourceAccessRule, StaleSourceAccessScope
from apps.api.app.domain.system_image.structure_work import StructureWorkLost
from apps.api.app.infrastructure.persistence.code_index_generation_models import CodeIndexGenerationRecord
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, SSEEventOutboxRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.image_revision_models import ImageRevisionRecord
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.structure_build_models import StructureBuildArtifactRecord
from apps.api.app.infrastructure.persistence.structure_cancel_models import StructureCancellationRecord
from apps.api.app.infrastructure.persistence.structure_job_models import StructureWorkLeaseRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.main import app
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_structure_jobs_api import queued, enqueue
from apps.api.tests.test_structure_build_api import request, submit, confirm
from apps.api.tests.test_code_index_lifecycle_api import install_native, _FixtureProcessRunner


@pytest.fixture(autouse=True)
def cancellation_diagnostics(monkeypatch):
    operation = StructureCancellationApplicationService.cancel
    def observed(self, *args, **kwargs):
        try:
            return operation(self, *args, **kwargs)
        except Exception as error:
            print("cancellation diagnostic:", type(error).__name__, str(error))
            raise
    monkeypatch.setattr(StructureCancellationApplicationService, "cancel", observed)


def prepare_cancel(v, ident, payload, *, headers=None, key=None, **changes):
    body = {"tool_id": STRUCTURE_CANCEL_TOOL, "input": {
        **payload, "original_invocation_id": ident, **changes}, "idempotency_key": key or uuid4().hex,
        "conversation_id": v["conversation"].json()["id"]}
    response = v["client"].post("/v1/tool-invocations", headers=headers or v["headers"], json=body)
    assert response.status_code == 200, response.text
    return response.json()


def cancel(v, ident, payload):
    command = prepare_cancel(v, ident, payload)
    assert command["status"] == "waiting_confirmation", command
    result = confirm(v, command["id"])
    assert result["status"] == "completed", result
    return result


def status(v, ident, payload, headers=None):
    return v["client"].get(f"/v1/projects/{v['project_id']}/system-image/build-plans/{payload['plan_id']}"
        f"/structure-commands/{ident}/status", headers=headers or v["headers"], params={
            "plan_digest": payload["plan_digest"], "target_baseline_id": payload["target_baseline_id"]})


def test_stop_status_is_readonly_current_authority_and_private(queued):
    v = queued
    ident, payload = enqueue(v)
    before = list(v["dispatched"])
    assert status(v, ident, payload, v["member_headers"]).status_code == 403
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "viewer"}).status_code == 200
    for headers, allowed in [(v["headers"], True), (v["member_headers"], False)]:
        response = status(v, ident, payload, headers)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert response.json() == {"request": {**payload, "original_invocation_id": ident},
            "original_status": "running", "can_cancel": allowed, "candidate_committed": False,
            "cancellation_requested": False}
    assert v["dispatched"] == before
    with session_scope() as session:
        assert session.get(StructureWorkLeaseRecord, ident) is None
        assert session.get(StructureCancellationRecord, ident) is None
    cancel(v, ident, payload)
    response = status(v, ident, payload)
    assert response.json()["original_status"] == "cancelled"
    assert response.json()["can_cancel"] is False and response.json()["cancellation_requested"] is True
    with session_scope() as session:
        assert session.get(StructureWorkLeaseRecord, ident) is None


@pytest.mark.parametrize("offset", [-901, 60])
def test_expired_or_future_stop_confirmation_cannot_write_intent(queued, monkeypatch, offset):
    import apps.api.app.application.platform.runtime as runtime
    v = queued
    ident, payload = enqueue(v)
    prepared = prepare_cancel(v, ident, payload)
    monkeypatch.setattr(runtime, "_now_iso", lambda: (datetime.now(timezone.utc) + timedelta(seconds=offset)).isoformat())
    assert confirm(v, prepared["id"])["status"] == "failed"
    with session_scope() as session:
        assert session.get(StructureCancellationRecord, ident) is None
        assert session.get(ToolInvocationRecord, ident).status == "running"


def test_confirmation_uses_canonical_clock_not_worker_lease_clock(queued, monkeypatch):
    import apps.api.app.infrastructure.persistence.structure_cancel_repository as persistence
    v = queued
    ident, payload = enqueue(v)
    monkeypatch.setattr(persistence, "func", SimpleNamespace(
        clock_timestamp=lambda: func.clock_timestamp() - text("interval '60 seconds'")))
    result = cancel(v, ident, payload)
    assert result["result"]["structure_cancel"]["outcome"] == "cancelled"


def test_late_scope_failure_rolls_back_stop_and_termination_together(queued, monkeypatch):
    v = queued
    ident, payload = enqueue(v)
    service = app.state.container.structure_cancellations
    operation = service.repository.cancel_confirmed
    def late_failure(*args, require_current, **kwargs):
        checks = []
        def guard():
            require_current()
            checks.append(True)
            if len(checks) == 2:
                raise StaleSourceAccessScope("fixture authority changed before commit")
        return operation(*args, require_current=guard, **kwargs)
    monkeypatch.setattr(service.repository, "cancel_confirmed", late_failure)
    command = prepare_cancel(v, ident, payload)
    assert confirm(v, command["id"])["status"] == "failed"
    with session_scope() as session:
        assert session.get(StructureCancellationRecord, ident) is None
        assert session.get(ToolInvocationRecord, ident).status == "running"
        assert session.scalar(select(func.count()).select_from(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.entity_id == ident,
            SSEEventOutboxRecord.event_type == "system_image.build.structure.cancel_requested")) == 0


def test_cancel_queued_before_any_generation_is_durable_and_never_calls_provider(queued, monkeypatch):
    v = queued
    ident, payload = enqueue(v)
    def forbidden(*args, **kwargs):
        raise AssertionError("cancelled queue cannot reach a provider")
    monkeypatch.setattr(v["jobs"].application, "execute", forbidden)
    with session_scope() as session:
        original = session.get(ToolInvocationRecord, ident).input_payload.copy()
    key = uuid4().hex
    prepared = prepare_cancel(v, ident, payload, key=key, confirmed_by_user=True, confirmed_at="forged")
    assert prepared["status"] == "waiting_confirmation"
    with session_scope() as session:
        assert session.get(StructureCancellationRecord, ident) is None
        assert session.get(ToolInvocationRecord, ident).status == "running"
    result = confirm(v, prepared["id"])
    assert result["status"] == "completed", result
    receipt = result["result"]["structure_cancel"]
    assert (receipt["outcome"], receipt["original_status"]) == ("cancelled", "cancelled")
    assert asyncio.run(v["jobs"].run(ident)) == "cancelled"
    assert confirm(v, prepared["id"]) == result
    assert prepare_cancel(v, ident, payload, key=key, confirmed_by_user=True, confirmed_at="forged") == result
    with session_scope() as session:
        assert session.get(ToolInvocationRecord, ident).input_payload == original
        assert session.get(StructureCancellationRecord, ident).cancellation_invocation_id == prepared["id"]
        assert session.get(StructureWorkLeaseRecord, ident) is None
        assert session.get(StructureBuildArtifactRecord, ident) is None
        assert session.scalar(select(func.count()).select_from(CodeIndexGenerationRecord).where(
            CodeIndexGenerationRecord.invocation_id == ident)) == 0
        assert session.scalar(select(func.count()).select_from(AuditEventRecord).where(
            AuditEventRecord.tool_invocation_id == ident, AuditEventRecord.action == "tool.invocation.cancelled")) == 1
        assert session.scalar(select(func.count()).select_from(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.entity_id == ident,
            SSEEventOutboxRecord.event_type == "system_image.build.structure.cancel_requested")) == 1


def test_waiting_confirmation_can_be_cancelled_without_consuming_original_consent(evidence_api):
    v = evidence_api
    payload = request(v)
    ident = submit(v, payload)
    result = cancel(v, ident, payload)
    assert result["result"]["structure_cancel"]["outcome"] == "cancelled", result
    assert confirm(v, ident)["status"] == "cancelled"
    with session_scope() as session:
        assert session.get(ToolInvocationRecord, ident).input_payload.get("confirmed_by_user") is not True
        assert session.get(StructureBuildArtifactRecord, ident) is None


def test_active_cancel_waits_for_thread_exit_before_terminal_ack(queued, monkeypatch):
    v = queued
    ident, payload = enqueue(v)
    entered, cleaning, release, exited = Event(), Event(), Event(), Event()
    def slow(*args, require_work, **kwargs):
        entered.set()
        deadline = time.monotonic() + 15
        try:
            while True:
                require_work()
                if time.monotonic() > deadline:
                    raise TimeoutError("fixture worker received no stop request")
                exited.wait(.01)
        finally:
            cleaning.set()
            assert release.wait(10), "cleanup was not released"
            exited.set()
    monkeypatch.setattr(v["jobs"].application, "execute", slow)
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(asyncio.run, v["jobs"].run(ident))
        try:
            assert entered.wait(10)
            first = cancel(v, ident, payload)
            assert first["result"]["structure_cancel"]["outcome"] == "cancel_requested", first
            assert cleaning.wait(10)
            assert cancel(v, ident, payload)["result"]["structure_cancel"]["outcome"] == "already_requested"
            with session_scope() as session:
                assert session.get(ToolInvocationRecord, ident).status == "running"
                assert session.get(StructureWorkLeaseRecord, ident).expires_at > session.scalar(select(func.clock_timestamp()))
            assert not exited.is_set()
        finally:
            release.set()
        assert running.result(timeout=10) == "cancelled" and exited.is_set()
    with session_scope() as session:
        assert session.get(StructureBuildArtifactRecord, ident) is None
        assert session.get(StructureWorkLeaseRecord, ident).expires_at <= session.scalar(select(func.clock_timestamp()))


def test_cancel_between_artifact_write_and_pg_commit_blocks_candidate(queued, monkeypatch):
    v = queued
    ident, payload = enqueue(v)
    archive = v["jobs"].application.preparation.candidates.artifacts
    put = archive.put
    cancelled = []
    with session_scope() as session:
        before = session.scalar(select(func.count()).select_from(ImageRevisionRecord).where(ImageRevisionRecord.project_id == v["project_id"]))
    def stop_before_commit(*args, **kwargs):
        value = put(*args, **kwargs)
        cancelled.append(cancel(v, ident, payload))
        return value
    monkeypatch.setattr(archive, "put", stop_before_commit)
    assert asyncio.run(v["jobs"].run(ident)) == "cancelled"
    assert cancelled[0]["result"]["structure_cancel"]["outcome"] == "cancel_requested"
    with session_scope() as session:
        assert session.get(StructureBuildArtifactRecord, ident) is None
        assert session.scalar(select(func.count()).select_from(ImageRevisionRecord).where(ImageRevisionRecord.project_id == v["project_id"])) == before


def test_candidate_committed_before_ack_wins_and_is_never_deleted(queued, monkeypatch):
    v = queued
    ident, payload = enqueue(v)
    finish = v["jobs"].repository.finish
    receipts = []
    def after_commit(*args, **kwargs):
        receipts.append(cancel(v, ident, payload))
        return finish(*args, **kwargs)
    monkeypatch.setattr(v["jobs"].repository, "finish", after_commit)
    assert asyncio.run(v["jobs"].run(ident)) == "completed"
    assert receipts[0]["result"]["structure_cancel"]["outcome"] == "already_committed"
    with session_scope() as session:
        assert session.get(StructureBuildArtifactRecord, ident) is not None
        assert session.get(StructureCancellationRecord, ident) is None
        assert session.get(ToolInvocationRecord, ident).status == "completed"


def test_expired_worker_cannot_reclaim_or_commit_after_stop(queued):
    v = queued
    ident, payload = enqueue(v)
    lease = v["jobs"].repository.claim(ident, "expired")
    with session_scope() as session:
        session.get(StructureWorkLeaseRecord, ident).expires_at = session.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)
    assert cancel(v, ident, payload)["result"]["structure_cancel"]["outcome"] == "cancelled"
    with pytest.raises(StructureWorkLost):
        v["jobs"].repository.renew(lease)
    assert asyncio.run(v["jobs"].run(ident)) == "cancelled"


@pytest.mark.parametrize("role", ["viewer", "tester"])
def test_forbidden_confirmation_does_not_consume_reviewer_pending_stop(queued, role):
    v = queued
    ident, payload = enqueue(v)
    pending = prepare_cancel(v, ident, payload)
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": role}).status_code == 200
    denied = v["client"].post(f"/v1/tool-invocations/{pending['id']}/confirm", headers=v["member_headers"])
    assert denied.status_code == 403, denied.text
    with session_scope() as session:
        assert session.get(ToolInvocationRecord, pending["id"]).status == "waiting_confirmation"
        assert session.get(StructureCancellationRecord, ident) is None
        assert session.get(ToolInvocationRecord, ident).status == "running"
    assert confirm(v, pending["id"])["result"]["structure_cancel"]["outcome"] == "cancelled"


@pytest.mark.parametrize("field,value", [("plan_digest", "sha256:" + "f" * 64), ("target_baseline_id", "foreign"),
    ("original_invocation_id", "foreign")])
def test_wrong_pins_are_rejected_before_original_mutation(queued, field, value):
    v = queued
    ident, payload = enqueue(v)
    response = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={"tool_id": STRUCTURE_CANCEL_TOOL,
        "input": {**payload, "original_invocation_id": ident, field: value}})
    assert response.status_code == 403, response.text
    with session_scope() as session:
        assert session.get(StructureCancellationRecord, ident) is None
        assert session.get(ToolInvocationRecord, ident).status == "running"


def test_cancel_is_append_only_and_private_after_source_revocation(queued):
    v = queued
    ident, payload = enqueue(v)
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    prepared = prepare_cancel(v, ident, payload, headers=v["member_headers"])
    result = v["client"].post(f"/v1/tool-invocations/{prepared['id']}/confirm", headers=v["member_headers"])
    assert result.status_code == 200 and result.json()["status"] == "completed", result.text
    for statement in (update(StructureCancellationRecord).values(command_hash="changed"), delete(StructureCancellationRecord)):
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as session:
                session.execute(statement.where(StructureCancellationRecord.original_invocation_id == ident))
    with session_scope() as session:
        rows = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == prepared["id"],
            SSEEventOutboxRecord.event_type == "tool.invocation.updated")).all()
        assert rows
        for row in rows:
            broadcast = row.event_payload["payload"]["tool_invocation"]
            assert broadcast["input_payload"] == {} and broadcast["result"] is None
    source = next(item for item in v["image"]["source_manifest"]["members"] if item["status"] == "captured")
    repo = SourceAccessRepository()
    snapshot = repo.load_snapshot(v["project_id"])
    repo.set_policy(v["project_id"], source["binding_id"], SourceAccessRule("restricted", ()),
        expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="structure-stop-revoke")
    denied = v["client"].get(f"/v1/tool-invocations/{prepared['id']}", headers=v["member_headers"])
    assert denied.status_code == 403 and payload["plan_digest"] not in denied.text, denied.text


def test_native_index_running_is_stopped_by_structure_intent(evidence_api, monkeypatch, tmp_path):
    v = evidence_api
    paused, release = Event(), Event()
    class PauseNative(_FixtureProcessRunner):
        def run(self, args, **kwargs):
            result = super().run(args, **kwargs)
            if len(args) > 2 and args[2] == "index_repository":
                paused.set()
                deadline = time.monotonic() + 15
                while not release.wait(.01):
                    kwargs["check_current"]()
                    if time.monotonic() > deadline:
                        raise TimeoutError("fixture index received no stop request")
            return result
    install_native(v, monkeypatch, tmp_path, PauseNative())
    payload = request(v)
    ident = submit(v, payload)
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(confirm, v, ident)
        try:
            assert paused.wait(10)
            receipt = cancel(v, ident, payload)
            assert receipt["result"]["structure_cancel"]["outcome"] == "cancel_requested", receipt
            assert running.result(timeout=10)["status"] == "cancelled"
        finally:
            release.set()
    with session_scope() as session:
        assert session.get(StructureBuildArtifactRecord, ident) is None
