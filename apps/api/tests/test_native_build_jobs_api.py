"""Real PG/private MinIO/HTTP command tests. Builder specimens are not Java execution."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import importlib
import json
import os
from pathlib import Path
from threading import Event
import time
from unittest.mock import AsyncMock
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import delete, inspect, select, text, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.native_build_inputs import (
    NATIVE_BUILD_TOOL, NATIVE_BUILD_PREVIEW_TOOL, NATIVE_BUILD_QUERY_TOOL, NATIVE_BUILD_CANCEL_TOOL, NativeBuildCommand,
)
from apps.api.app.application.quality_loop.native_builds import NativeBuildApplicationService
from apps.api.app.application.quality_loop.generation_work_lease import GenerationLeaseBusy, GenerationLeaseLost
from apps.api.app.domain.quality_loop.native_build import NativeBuildOutput
from apps.api.app.domain.shared.native_build_source import byte_digest
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, SSEEventOutboxRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.native_build_models import (
    NativeBuildReservationRecord as Reservation, NativeBuildResultRecord as Result, NativeBuildWorkLeaseRecord as Lease,
)
from apps.api.app.infrastructure.persistence.native_build_repository import NativeBuildRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.runner.native_maven_build import runtime_jar_inventory
from apps.api.tests.test_native_build import protocol_jar
from apps.api.tests.test_native_build_sources_api import fixed_exweb_native_input
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_access_api import grant_member, policy
from apps.api.tests.test_semantic_evaluations_api import completed, invoke, confirm, count


class ProtocolBuilder:
    def __init__(self):
        self.calls = []
        self.image_id = "sha256:" + "a" * 64

    def policy(self):
        return {"image_id": self.image_id, "protocol_specimen": True}

    def build(self, request, *, require_work):
        require_work()
        self.calls.append(request.digest)
        artifact = protocol_jar()
        return NativeBuildOutput(request.digest, artifact, b"Protocol only, not native Java compilation.",
            {"image_id": self.image_id, "maven": "3.9.11", "java": "21", "network": "none",
                "dependency_cache": "operator_read_only", "version_output_hash": byte_digest(b"protocol")},
            runtime_jar_inventory(artifact))


@pytest.fixture
def native_job(evidence_api, tmp_path, monkeypatch):
    v = evidence_api
    root = tmp_path / "protocol-maven"
    root.mkdir()
    (root / "pom.xml").write_text("<project>Protocol only.</project>")
    (root / "Example.java").write_text("class Example {}")
    v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "code", "source_uri": str(root)}]})
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    service, jobs = app.state.container.native_builds, app.state.container.native_build_jobs
    builder, workflow = ProtocolBuilder(), AsyncMock()
    monkeypatch.setattr(service, "builder", builder)
    monkeypatch.setattr(jobs, "workflow", workflow)
    snapshot = service.authorization.repository.load_snapshot(v["project_id"])
    response = v["client"].get(f"/v1/projects/{v['project_id']}/system-image/revisions", headers=v["headers"])
    assert response.status_code == 200, response.text
    summary = response.json()["items"][0]
    from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
    source_repository = SourceSnapshotRepository()
    manifest = source_repository.latest_manifest(v["project_id"])
    source = next(item for item in source_repository.materialization_sources(manifest) if item.source_uri == str(root))
    binding = next(item for item in snapshot.bindings if item.source_id == source.id)
    summary = next(item for item in response.json()["items"] if item["manifest_id"] == manifest.manifest_id)
    member = next(item for item in manifest.members if item.binding_id == binding.binding_id)
    selection = {"project_id": v["project_id"], "image_revision_id": summary["image_revision_id"],
        "image_artifact_hash": summary["artifact_hash"], "binding_id": binding.binding_id,
        "source_revision_id": member.source_revision_id, "artifact_path": "target/app.jar"}
    preview = completed(invoke(v, NATIVE_BUILD_PREVIEW_TOOL, selection))["result"]["native_build_preview"]
    v.update(service=service, jobs=jobs, builder=builder, workflow=workflow, selection=selection,
        preview=preview, request=preview["request"], root=root)
    return v


def queued(v, payload=None):
    pending = invoke(v, NATIVE_BUILD_TOOL, payload or v["request"], key=uuid4().hex)
    assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
    assert not v["builder"].calls
    response = confirm(v, pending.json())
    assert response.status_code == 200 and response.json()["status"] == "running", response.text
    v["workflow"].start.assert_awaited_with(pending.json()["id"])
    return pending.json()["id"]


def command(v, invocation_id):
    response = v["client"].get(f"/v1/tool-invocations/{invocation_id}", headers=v["headers"])
    assert response.status_code == 200, response.text
    return response.json()


def read(v, invocation_id, *, headers=None):
    result = completed(invoke(v, NATIVE_BUILD_QUERY_TOOL, {"project_id": v["project_id"], "invocation_id": invocation_id}, headers=headers))
    return result["result"]["native_build_job"]


def test_native_canonical_confirmation_result_and_original_replay(native_job):
    v = native_job
    assert v["preview"]["source_execution_started"] is False and not v["preview"]["execution_authorized"]
    assert "Example.java" not in json.dumps(v["preview"]) and "s3://" not in json.dumps(v["preview"])
    forged = invoke(v, NATIVE_BUILD_TOOL, {**v["request"], "confirmed_by_user": True})
    assert forged.json()["status"] == "waiting_confirmation" and count(v, Reservation) == 0
    ident = queued(v)
    assert read(v, ident)["call_reserved"] is False
    assert asyncio.run(v["jobs"].run(ident)) == "completed"
    first = read(v, ident)
    assert first["status"] == "completed" and first["metadata"]["runtime_library_count"] == 1
    assert not first["execution_authorized"] and not first["outcome_unknown"]
    assert count(v, Reservation) == count(v, Result) == len(v["builder"].calls) == 1
    assert "artifact_ref" not in json.dumps(first) and "receipt" not in first
    assert asyncio.run(v["jobs"].run(ident)) == "completed" and len(v["builder"].calls) == 1
    original = command(v, ident)
    replay = confirm(v, {"id": ident})
    assert replay.json()["status"] == "completed" and len(v["builder"].calls) == 1
    fresh = NativeBuildApplicationService(v["service"].sources, v["service"].authorization, ProtocolBuilder(),
        NativeBuildRepository(), v["service"].artifacts)
    fresh.builder.image_id = "sha256:" + "b" * 64
    with actor_scope(UserProfile.model_validate(v["owner"])):
        archived = fresh.read(v["project_id"], ident)
    assert archived["metadata"] == first["metadata"] and not fresh.builder.calls
    assert archived["receipt"]["passed_count"] == archived["receipt"]["executed_on_target_count"] == 0
    with session_scope() as session:
        result = session.get(Result, ident)
        assert result.artifact_ref.startswith("s3://")
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == ident)).all()
        audits = session.scalars(select(AuditEventRecord).where(AuditEventRecord.entity_id == ident)).all()
        assert {event.event_type for event in events} >= {"quality.native_build.reserved", "quality.native_build.archived"}
        assert {item.action for item in audits} >= {"quality.native_build.reserved", "quality.native_build.archived"}
        value = json.dumps([event.event_payload for event in events]) + json.dumps([item.event_metadata for item in audits]) + json.dumps(original)
        assert "Example.java" not in value and "Protocol only" not in value and "s3://" not in value


@pytest.mark.parametrize("mode", ["operator", "payload", "old_confirm", "future_confirm", "actor"])
def test_native_changed_authority_or_pins_reject_before_reservation(native_job, mode):
    v = native_job
    ident = queued(v)
    if mode == "operator":
        v["builder"].image_id = "sha256:" + "b" * 64
    elif mode in {"old_confirm", "future_confirm", "payload"}:
        with session_scope() as session:
            row = session.get(ToolInvocationRecord, ident)
            value = dict(row.input_payload)
            if mode == "payload":
                value["request_digest"] = byte_digest(b"changed confirmed source")
            else:
                value["confirmed_at"] = (datetime.now(timezone.utc) + timedelta(seconds=-901 if mode == "old_confirm" else 60)).isoformat()
            row.input_payload = value
    else:
        assert v["client"].put(f"/v1/projects/{v['project_id']}/members/{v['member']['id']}",
            headers=v["headers"], json={"role": "project_admin"}).status_code == 200
        membership = f"/v1/projects/{v['project_id']}/members/{v['owner']['id']}"
        assert v["client"].put(membership, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    assert asyncio.run(v["jobs"].run(ident)) == "failed"
    assert count(v, Reservation) == count(v, Result) == 0 and not v["builder"].calls


def test_native_unknown_reservation_never_executes_again(native_job, monkeypatch):
    v = native_job
    def unavailable(request, *, require_work):
        v["builder"].calls.append(request.digest)
        raise RuntimeError("private native transport failure")
    monkeypatch.setattr(v["builder"], "build", unavailable)
    ident = queued(v)
    with pytest.raises(RuntimeError):
        asyncio.run(v["jobs"].run(ident))
    assert read(v, ident)["outcome_unknown"] and count(v, Reservation) == 1 and count(v, Result) == 0
    assert asyncio.run(v["jobs"].run(ident)) == "failed" and len(v["builder"].calls) == 1
    assert "private native" not in json.dumps(command(v, ident))


def test_native_result_committed_before_worker_failure_replays_original_without_build(native_job, monkeypatch):
    v = native_job
    finish = v["jobs"].repository.finish
    attempts = []
    def interrupted(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("worker lost after result commit")
        return finish(*args, **kwargs)
    monkeypatch.setattr(v["jobs"].repository, "finish", interrupted)
    ident = queued(v)
    with pytest.raises(RuntimeError):
        asyncio.run(v["jobs"].run(ident))
    assert count(v, Result) == 1 and command(v, ident)["status"] == "running"
    original = read(v, ident)["metadata"]
    v["builder"].image_id = "sha256:" + "b" * 64
    assert asyncio.run(v["jobs"].run(ident)) == "completed"
    assert read(v, ident)["metadata"] == original and len(v["builder"].calls) == 1


def test_native_archive_outbox_failure_rolls_back_result_and_audit(native_job, monkeypatch):
    v = native_job
    append = EventOutboxRepository.append
    def reject_archive(self, event, **kwargs):
        if event.event_type == "quality.native_build.archived":
            raise RuntimeError("injected native outbox failure")
        return append(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", reject_archive)
    ident = queued(v)
    with pytest.raises(RuntimeError):
        asyncio.run(v["jobs"].run(ident))
    assert count(v, Result) == 0 and count(v, Reservation) == 1
    with session_scope() as session:
        assert not session.scalars(select(AuditEventRecord).where(AuditEventRecord.entity_id == ident,
            AuditEventRecord.action == "quality.native_build.archived")).all()
        assert not session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == ident,
            SSEEventOutboxRecord.event_type == "quality.native_build.archived")).all()
    assert asyncio.run(v["jobs"].run(ident)) == "failed" and len(v["builder"].calls) == 1


def test_native_reservation_outbox_failure_rolls_back_before_source_execution(native_job, monkeypatch):
    v = native_job
    append = EventOutboxRepository.append
    def reject_reservation(self, event, **kwargs):
        if event.event_type == "quality.native_build.reserved":
            raise RuntimeError("reservation transaction rejected")
        return append(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", reject_reservation)
    ident = queued(v)
    with pytest.raises(RuntimeError):
        asyncio.run(v["jobs"].run(ident))
    assert not v["builder"].calls and count(v, Reservation) == count(v, Result) == 0
    with session_scope() as session:
        assert not session.scalars(select(AuditEventRecord).where(AuditEventRecord.entity_id == ident,
            AuditEventRecord.action == "quality.native_build.reserved")).all()
    monkeypatch.setattr(EventOutboxRepository, "append", append)
    assert asyncio.run(v["jobs"].run(ident)) == "completed" and len(v["builder"].calls) == 1


def test_native_lease_fences_original_worker_and_cannot_commit_under_replacement(native_job):
    v = native_job
    ident = queued(v)
    repository = v["jobs"].repository
    first = repository.claim_lease(v["project_id"], ident, "first-owner")
    with pytest.raises(GenerationLeaseBusy):
        repository.claim_lease(v["project_id"], ident, "competitor")
    request = NativeBuildCommand.model_validate(v["request"])
    with actor_scope(UserProfile.model_validate(v["owner"])):
        source = v["service"]._request(request.selection()).source.metadata()
        repository.reserve(request, source, v["builder"].policy(), actor_id=v["owner"]["id"], invocation_id=ident,
            lease=first, require_current=lambda: repository.require_lease(first))
    repository.release_lease(first)
    second = repository.claim_lease(v["project_id"], ident, "replacement-owner")
    assert second.epoch == first.epoch + 1
    with pytest.raises(GenerationLeaseLost):
        repository.require_lease(first)
    with pytest.raises(GenerationLeaseLost):
        repository.commit(request, {}, {}, invocation_id=ident, lease=second, require_current=lambda: None)
    repository.release_lease(first)
    repository.require_lease(second)
    repository.release_lease(second)
    assert asyncio.run(v["jobs"].run(ident)) == "failed" and not v["builder"].calls


def test_native_independently_confirmed_cancel_and_source_acl_before_artifact_read(native_job, monkeypatch):
    v = native_job
    ident = queued(v)
    pending = invoke(v, NATIVE_BUILD_CANCEL_TOOL, {"project_id": v["project_id"], "invocation_id": ident})
    assert pending.json()["status"] == "waiting_confirmation" and command(v, ident)["status"] == "running"
    completed(confirm(v, pending.json()))
    v["workflow"].cancel.assert_awaited_with(ident)
    assert asyncio.run(v["jobs"].run(ident)) == "cancelled" and not v["builder"].calls
    second = queued(v)
    assert asyncio.run(v["jobs"].run(second)) == "completed"
    grant_member(v)
    assert read(v, second, headers=v["member_headers"])["status"] == "completed"
    original, calls = v["service"].artifacts.read, []
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(v["service"].artifacts, "read", counted)
    policy(v)
    denied = invoke(v, NATIVE_BUILD_QUERY_TOOL, {"project_id": v["project_id"], "invocation_id": second}, headers=v["member_headers"])
    assert denied.status_code == 200 and denied.json()["status"] == "failed", denied.text
    assert not calls


def test_native_preview_requires_admin_and_late_revocation_rejects_result(native_job, monkeypatch):
    v = native_job
    grant_member(v)
    denied = invoke(v, NATIVE_BUILD_PREVIEW_TOOL, v["selection"], headers=v["member_headers"])
    assert denied.status_code == 200 and denied.json()["status"] == "failed", denied.text
    refusal = denied.json()
    assert refusal["input_payload"]["authorization_denied"]
    assert refusal["input_payload"]["authorization_required_roles"] == ["project_admin", "platform_admin"]
    assert refusal["result"]["native_build_preview"] is None
    assert not v["builder"].calls and count(v, Reservation) == count(v, Result) == 0
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "project_admin"}).status_code == 200
    v["request"] = completed(invoke(v, NATIVE_BUILD_PREVIEW_TOOL, v["selection"]))["result"]["native_build_preview"]["request"]
    put = v["service"].artifacts.put
    def revoke_after_put(*args, **kwargs):
        value = put(*args, **kwargs)
        response = v["client"].put(f"/v1/projects/{v['project_id']}/members/{v['owner']['id']}",
            headers=v["headers"], json={"role": "qa_lead"})
        assert response.status_code == 200, response.text
        return value
    monkeypatch.setattr(v["service"].artifacts, "put", revoke_after_put)
    ident = queued(v)
    assert asyncio.run(v["jobs"].run(ident)) == "failed"
    assert count(v, Reservation) == len(v["builder"].calls) == 1 and count(v, Result) == 0
    assert asyncio.run(v["jobs"].run(ident)) == "failed" and len(v["builder"].calls) == 1


def test_native_original_command_and_query_receipts_recheck_source_acl_and_never_broadcast_body(native_job, monkeypatch):
    v = native_job
    ident = queued(v)
    assert asyncio.run(v["jobs"].run(ident)) == "completed"
    preview = completed(invoke(v, NATIVE_BUILD_PREVIEW_TOOL, v["selection"]))
    query = completed(invoke(v, NATIVE_BUILD_QUERY_TOOL, {"project_id": v["project_id"], "invocation_id": ident}))
    cancel = invoke(v, NATIVE_BUILD_CANCEL_TOOL, {"project_id": v["project_id"], "invocation_id": ident}).json()
    assert cancel["status"] == "waiting_confirmation"
    grant_member(v)
    commands = (ident, preview["id"], query["id"], cancel["id"])
    for original in commands:
        url = f"/v1/tool-invocations/{original}"
        response = v["client"].get(url, headers=v["member_headers"])
        assert response.status_code == 200, response.text
        with actor_scope(UserProfile.model_validate(v["owner"])):
            value = app.state.container.platform.get_tool_invocation(original)
            projected = app.state.container.agent._events.tool_broadcast_view(value)
        assert projected.input_payload == {} and projected.result is None and projected.idempotency_key is None
    calls, read_archive = [], v["service"].artifacts.read
    def counted(*args, **kwargs):
        calls.append(1)
        return read_archive(*args, **kwargs)
    monkeypatch.setattr(v["service"].artifacts, "read", counted)
    policy(v)
    for original in commands:
        denied = v["client"].get(f"/v1/tool-invocations/{original}", headers=v["member_headers"])
        assert denied.status_code == 403, denied.text
        assert '"input_payload":' not in denied.text and '"receipt":' not in denied.text
        assert denied.json()["error"]["details"] == {} and "s3://" not in denied.text
    conversation_id = v["conversation"].json()["id"]
    public = v["client"].get(f"/v1/conversations/{conversation_id}", headers=v["member_headers"])
    assert public.status_code == 200, public.text
    for original in commands:
        projected = next(item for item in public.json()["tool_invocations"] if item["id"] == original)
        assert projected["input_payload"] == {} and projected["result"] is None
        assert projected["summary"] == f"Native build command status: {projected['status']}."
    assert not calls and len(v["builder"].calls) == 1


def test_native_cancel_unknown_delivery_is_durable_and_never_reports_cleanup(native_job):
    from apps.api.app.infrastructure.workflow.native_build_runtime import reconcile_native_builds_once
    v = native_job
    v["workflow"].cancel.side_effect = RuntimeError("private cancel RPC unavailable")
    ident = queued(v)
    pending = invoke(v, NATIVE_BUILD_CANCEL_TOOL, {"project_id": v["project_id"], "invocation_id": ident})
    control = completed(confirm(v, pending.json()))
    assert control["result"]["native_build_job"]["cancellation_requested"]
    assert not control["result"]["native_build_job"]["cleanup_confirmed"]
    assert v["jobs"].repository.pending_cancellations() == [(ident, v["project_id"])]
    assert not v["builder"].calls and command(v, ident)["status"] == "cancelled"
    assert "private cancel RPC" not in json.dumps(control)
    v["workflow"].cancel.side_effect = None
    asyncio.run(reconcile_native_builds_once(v["workflow"], v["jobs"].repository))
    assert not v["jobs"].repository.pending_cancellations()
    assert v["workflow"].cancel.await_count == 2 and not v["builder"].calls


def test_native_pg_schema_append_only_fk_and_downgrade_guards(native_job):
    v = native_job
    ident = queued(v)
    assert asyncio.run(v["jobs"].run(ident)) == "completed"
    with session_scope() as session:
        actual = inspect(session.connection())
        for model in (Reservation, Result, Lease):
            columns = {item["name"]: item for item in actual.get_columns(model.__tablename__)}
            assert set(columns) == {column.name for column in model.__table__.columns}
            assert all(columns[column.name]["nullable"] == column.nullable for column in model.__table__.columns)
            expected = {(tuple(item.parent.name for item in fk.elements), fk.referred_table.name,
                tuple(item.column.name for item in fk.elements)) for fk in model.__table__.foreign_key_constraints}
            found = {(tuple(fk["constrained_columns"]), fk["referred_table"], tuple(fk["referred_columns"]))
                for fk in actual.get_foreign_keys(model.__tablename__)}
            assert found == expected
        migration = importlib.import_module("apps.api.migrations.versions.0102_native_builds")
        with Operations.context(MigrationContext.configure(session.connection())), pytest.raises(RuntimeError, match="populated"):
            migration.downgrade()
    for model in (Reservation, Result):
        for statement in (update(model).where(model.invocation_id == ident).values(content_hash=byte_digest(b"changed")),
                delete(model).where(model.invocation_id == ident)):
            with pytest.raises(IntegrityError), session_scope() as session:
                session.execute(statement)
    # Rollback restores the triggers while testing the actual FK independently.
    for model, fields in ((Reservation, {"source_revision_id": "unrelated-source"}),
            (Reservation, {"image_revision_id": "unrelated-image"}), (Result, {"build_id": "unrelated-build"})):
        with pytest.raises(IntegrityError) as violation, session_scope() as session:
            session.execute(text(f"ALTER TABLE {model.__tablename__} DISABLE TRIGGER USER"))
            session.execute(update(model).where(model.invocation_id == ident).values(**fields))
        assert violation.value.orig.sqlstate == "23503"


@pytest.mark.skipif(not os.getenv("TEST_TEMPORAL_ADDRESS"), reason="requires explicitly configured isolated Temporal queue")
def test_native_real_temporal_result_commit_retry_never_rebuilds(native_job, monkeypatch):
    from temporalio.client import Client
    from temporalio.worker import Worker, Replayer
    from apps.api.app.infrastructure.config.agent_runtime_config import temporal_gateway_config_from_env
    from apps.api.app.infrastructure.workflow.native_build_runtime import TemporalNativeBuildRuntime, build_native_build_activities
    from apps.api.app.infrastructure.workflow.nasus_native_build_workflow import NasusNativeBuildWorkflow
    v = native_job
    ident = queued(v)
    finish, attempts = v["jobs"].repository.finish, []
    def once(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("private failure after original native result")
        return finish(*args, **kwargs)
    monkeypatch.setattr(v["jobs"].repository, "finish", once)
    monkeypatch.setenv("NASUS_AGENT_WORKFLOW_RUNTIME", "temporal")
    async def verify():
        config = replace(temporal_gateway_config_from_env(), address=os.environ["TEST_TEMPORAL_ADDRESS"],
            task_queue="nasus-native-build-test-" + uuid4().hex)
        client = await Client.connect(config.address, namespace=config.namespace)
        runtime = TemporalNativeBuildRuntime(config, client)
        async with Worker(client, task_queue=runtime.task_queue, workflows=[NasusNativeBuildWorkflow],
                activities=build_native_build_activities()):
            assert await runtime.start(ident)
            handle = client.get_workflow_handle("nasus-native-build:" + ident)
            assert await asyncio.wait_for(handle.result(), 180) == "completed"
            assert not await runtime.start(ident)
            history = await handle.fetch_history()
            assert "private failure" not in str(history) and "Protocol only" not in str(history)
            assert (await Replayer(workflows=[NasusNativeBuildWorkflow]).replay_workflow(history)).replay_failure is None
    asyncio.run(verify())
    assert len(attempts) == 2 and len(v["builder"].calls) == 1 and read(v, ident)["status"] == "completed"


@pytest.mark.skipif(not os.getenv("TEST_TEMPORAL_ADDRESS"), reason="requires explicitly configured isolated Temporal queue")
def test_fixed_exweb_native_build_through_canonical_command_and_original_archive(evidence_api, tmp_path, monkeypatch):
    from apps.api.app.infrastructure.runner.configured_native_build import ConfiguredNativeBuild
    from temporalio.client import Client
    from temporalio.worker import Worker, Replayer
    from apps.api.app.infrastructure.config.agent_runtime_config import temporal_gateway_config_from_env
    from apps.api.app.infrastructure.workflow.native_build_runtime import TemporalNativeBuildRuntime, build_native_build_activities
    from apps.api.app.infrastructure.workflow.nasus_native_build_workflow import NasusNativeBuildWorkflow
    request, files, tree_hash, cache, image_id = fixed_exweb_native_input(evidence_api, tmp_path)
    v = evidence_api
    service, jobs = app.state.container.native_builds, app.state.container.native_build_jobs
    monkeypatch.setenv("NASUS_NATIVE_BUILD_IMAGE_ID", image_id)
    monkeypatch.setenv("NASUS_NATIVE_BUILD_MAVEN_CACHE", cache)
    monkeypatch.setattr(service, "builder", ConfiguredNativeBuild())
    selection = {key: getattr(request.source.pin, key) for key in
        ("project_id", "image_revision_id", "image_artifact_hash", "binding_id", "source_revision_id")}
    selection["artifact_path"] = request.artifact_path
    preview = completed(invoke(v, NATIVE_BUILD_PREVIEW_TOOL, selection))["result"]["native_build_preview"]
    assert preview["request"]["request_digest"] == request.digest
    monkeypatch.setenv("NASUS_AGENT_WORKFLOW_RUNTIME", "temporal")
    async def verify():
        config = replace(temporal_gateway_config_from_env(), address=os.environ["TEST_TEMPORAL_ADDRESS"],
            task_queue="nasus-exweb-native-test-" + uuid4().hex)
        client = await Client.connect(config.address, namespace=config.namespace)
        runtime = TemporalNativeBuildRuntime(config)
        monkeypatch.setattr(jobs, "workflow", runtime)
        async with Worker(client, task_queue=runtime.task_queue, workflows=[NasusNativeBuildWorkflow],
                activities=build_native_build_activities()):
            pending = await asyncio.to_thread(invoke, v, NATIVE_BUILD_TOOL, preview["request"], key=uuid4().hex)
            assert pending.json()["status"] == "waiting_confirmation", pending.text
            ident = pending.json()["id"]
            accepted = await asyncio.to_thread(confirm, v, pending.json())
            assert accepted.json()["status"] == "running", accepted.text
            handle = client.get_workflow_handle("nasus-native-build:" + ident)
            assert await asyncio.wait_for(handle.result(), 300) == "completed"
            assert not await runtime.start(ident)
            history = await handle.fetch_history()
            assert "FinanceEXChatService" not in str(history)
            assert (await Replayer(workflows=[NasusNativeBuildWorkflow]).replay_workflow(history)).replay_failure is None
            return ident
    ident = asyncio.run(verify())
    with actor_scope(UserProfile.model_validate(v["owner"])):
        archived = service.read(v["project_id"], ident)
    result = read(v, ident)
    assert result["metadata"]["compiled_class_count"] == 121
    assert result["metadata"]["runtime_library_count"] == 109
    assert not result["execution_authorized"] and archived["receipt"]["passed_count"] == 0
    assert count(v, Reservation) == count(v, Result) == 1
    assert asyncio.run(jobs.run(ident)) == "completed"
    report_path = os.getenv("EXWEB_CANONICAL_NATIVE_BUILD_REPORT")
    if report_path:
        from apps.api.tests.exweb_git_trees import AFTER
        report = {"recorded_at": datetime.now(timezone.utc).isoformat(), "repository": "https://github.com/kunben-duck/exweb.git",
            "reviewed_git_commit": AFTER, "git_tree_hash": tree_hash, "source_file_count": len(files),
            "canonical_http_confirmation_verified": True, "actual_docker_offline_build": True,
            "original_private_minio_result_replay": True, "pg_reservation_result_verified": True,
            "invocation_id": ident, "metadata": result["metadata"], "receipt": archived["receipt"],
            "temporal_build_execution_verified": True, "workflow_history_replay_verified": True,
            "workflow_dispatch": "actual_canonical_http_to_temporal_worker",
            "native_target_execution": False, "full_quality_closure_verified": False,
            "artifact_storage": "isolated_test_private_minio_removed_after_suite"}
        with Path(report_path).open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)


@pytest.mark.skipif(not os.getenv("TEST_TEMPORAL_ADDRESS"), reason="requires explicitly configured isolated Temporal queue")
@pytest.mark.parametrize("mode", ["cancel", "revoke"])
def test_fixed_exweb_canonical_temporal_interrupts_running_container(evidence_api, tmp_path, monkeypatch, mode):
    from temporalio.client import Client, WorkflowFailureError
    from temporalio.worker import Worker
    from apps.api.app.infrastructure.config.agent_runtime_config import temporal_gateway_config_from_env
    from apps.api.app.infrastructure.workflow.native_build_runtime import TemporalNativeBuildRuntime, build_native_build_activities
    from apps.api.app.infrastructure.workflow.nasus_native_build_workflow import NasusNativeBuildWorkflow
    from apps.api.app.infrastructure.runner.configured_native_build import ConfiguredNativeBuild
    from apps.api.app.infrastructure.runner.native_maven_build import OfflineMavenNativeBuild, bounded_command
    request, files, tree_hash, cache, image_id = fixed_exweb_native_input(evidence_api, tmp_path)
    v = evidence_api
    service, jobs = app.state.container.native_builds, app.state.container.native_build_jobs
    actor_headers = v["headers"]
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    if mode == "revoke":
        assert v["client"].put(membership, headers=v["headers"], json={"role": "project_admin"}).status_code == 200
        actor_headers = v["member_headers"]
    monkeypatch.setenv("NASUS_AGENT_WORKFLOW_RUNTIME", "temporal")
    names, entered = [], Event()
    def monitor(args, **kwargs):
        if args[1] == "run":
            names.append(args[args.index("--name") + 1])
            if args[-1] == "verify":
                entered.set()
        return bounded_command(args, **kwargs)
    builder = ConfiguredNativeBuild()
    monkeypatch.setattr(builder, "_builder", lambda: OfflineMavenNativeBuild(image_id=image_id, maven_cache=Path(cache), command=monitor))
    monkeypatch.setattr(service, "builder", builder)
    selection = {key: getattr(request.source.pin, key) for key in
        ("project_id", "image_revision_id", "image_artifact_hash", "binding_id", "source_revision_id")}
    selection["artifact_path"] = request.artifact_path
    preview = completed(invoke(v, NATIVE_BUILD_PREVIEW_TOOL, selection, headers=actor_headers))["result"]["native_build_preview"]

    async def verify():
        config = replace(temporal_gateway_config_from_env(), address=os.environ["TEST_TEMPORAL_ADDRESS"],
            task_queue="nasus-exweb-native-interrupt-test-" + uuid4().hex)
        client = await Client.connect(config.address, namespace=config.namespace)
        runtime = TemporalNativeBuildRuntime(config)
        monkeypatch.setattr(jobs, "workflow", runtime)
        async with Worker(client, task_queue=runtime.task_queue, workflows=[NasusNativeBuildWorkflow],
                activities=build_native_build_activities()):
            pending = await asyncio.to_thread(invoke, v, NATIVE_BUILD_TOOL, preview["request"], headers=actor_headers)
            assert pending.json()["status"] == "waiting_confirmation", pending.text
            ident = pending.json()["id"]
            accepted = await asyncio.to_thread(v["client"].post, f"/v1/tool-invocations/{ident}/confirm", headers=actor_headers)
            assert accepted.json()["status"] == "running", accepted.text
            handle = client.get_workflow_handle("nasus-native-build:" + ident)
            try:
                assert await asyncio.to_thread(entered.wait, 20)
                running = False
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    code, state = await asyncio.to_thread(bounded_command,
                        ["docker", "container", "inspect", "--format", "{{json .State}}", names[-1]], timeout=5, max_bytes=65536)
                    if not code and json.loads(state).get("Running") is True:
                        running = True
                        break
                    await asyncio.sleep(0.05)
                assert running, "must interrupt an actual running Docker compile container"
                started = time.monotonic()
                if mode == "cancel":
                    control = await asyncio.to_thread(invoke, v, NATIVE_BUILD_CANCEL_TOOL,
                        {"project_id": v["project_id"], "invocation_id": ident})
                    assert control.json()["status"] == "waiting_confirmation", control.text
                    completed(await asyncio.to_thread(confirm, v, control.json()))
                    try:
                        assert await asyncio.wait_for(handle.result(), 30) == "cancelled"
                    except WorkflowFailureError as failure:
                        from temporalio.exceptions import is_cancelled_exception
                        assert is_cancelled_exception(failure)
                else:
                    revoked = await asyncio.to_thread(v["client"].delete, membership, headers=v["headers"])
                    assert revoked.status_code == 200, revoked.text
                    assert await asyncio.wait_for(handle.result(), 30) == "failed"
                return ident, time.monotonic() - started
            finally:
                state = await handle.describe()
                from temporalio.client import WorkflowExecutionStatus
                if state.status == WorkflowExecutionStatus.RUNNING:
                    await handle.cancel()
                    try:
                        await asyncio.wait_for(handle.result(), 30)
                    except WorkflowFailureError:
                        pass
    ident, elapsed = asyncio.run(verify())
    assert command(v, ident)["status"] == ("cancelled" if mode == "cancel" else "failed")
    assert count(v, Reservation) == 1 and count(v, Result) == 0 and len(names) == 2
    for name in names:
        code, output = bounded_command(["docker", "container", "inspect", name], timeout=5, max_bytes=65536)
        assert code and b"No such" in output
    report_path = os.getenv("EXWEB_CANONICAL_NATIVE_CANCEL_REPORT" if mode == "cancel" else "EXWEB_CANONICAL_NATIVE_REVOCATION_REPORT")
    if report_path:
        from apps.api.tests.exweb_git_trees import AFTER
        report = {"recorded_at": datetime.now(timezone.utc).isoformat(), "reviewed_git_commit": AFTER,
            "git_tree_hash": tree_hash, "source_file_count": len(files), "invocation_id": ident, "interruption": mode,
            "canonical_http_confirmation_verified": True, "temporal_build_execution_verified": True,
            "actual_running_docker_compile_verified": True, "resources_removed_before_workflow_terminal": True,
            "pg_reservation_without_success_result": True, "real_membership_revocation": mode == "revoke",
            "durable_cancellation_verified": mode == "cancel", "latency_seconds": elapsed,
            "native_target_execution": False, "full_quality_closure_verified": False}
        with Path(report_path).open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
