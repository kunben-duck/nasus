"""Original canonical inputs and failure windows on isolated PG/private MinIO."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import importlib
import json

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.system_image.materialization_inputs import MaterializationInputApplicationService
from apps.api.app.domain.system_image.materialization_command import MaterializationOriginalInputUnavailable
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.materialization_command_models import (
    MaterializationCommandInputRecord as Input, MaterializationLegacyCommandRecord as Legacy,
)
from apps.api.app.infrastructure.persistence.materialization_command_repository import MaterializationCommandInputRepository
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.main import app
from apps.api.tests.test_materialization_source_inputs_api import (
    running_materialization, count_acquisitions, materialize,
)
from apps.api.tests.test_source_acquisition_intents_api import scope_for
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_ingestion_access_api import facts, grant_tester
from apps.api.tests.test_source_access_api import policy
from apps.api.tests.test_document_projection_api import documents


class Interrupted(BaseException):
    pass


def events(command):
    with session_scope() as session:
        return deepcopy([row.event_payload for row in session.scalars(select(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.event_id == f"materialization-source-input:{command['id']}")).all()])


def begin(v, command, monkeypatch, *, actor=None):
    service = app.state.container.system_image.lifecycle._operations
    with monkeypatch.context() as fault:
        fault.setattr(service.candidate_preparation, "prepare", lambda *args, **kwargs: (_ for _ in ()).throw(Interrupted()))
        with actor_scope(UserProfile.model_validate(actor or v["owner"])), pytest.raises(Interrupted):
            asyncio.run(service.materialize_context(v["project_id"], invocation_id=command["id"]))
    return service


def resume(v, command, service, *, actor=None):
    with actor_scope(UserProfile.model_validate(actor or v["owner"])):
        return asyncio.run(service.materialize_context(v["project_id"], invocation_id=command["id"]))


def test_original_input_is_durable_before_preparation_and_fresh_application_reuses_archive(evidence_api, monkeypatch):
    v = evidence_api
    command = running_materialization(v, monkeypatch)
    manifest = SourceSnapshotRepository().latest_manifest(v["project_id"])
    before = facts(v)
    service = begin(v, command, monkeypatch)
    repo = MaterializationCommandInputRepository()
    original = repo.get(command["id"], scope_for(v))
    assert (original.manifest_id, original.manifest_hash, original.actor_id) == (
        manifest.manifest_id, manifest.content_hash, v["owner"]["id"])
    assert facts(v) == before
    admitted = events(command)
    assert len(admitted) == 1 and admitted[0]["patch"] == {"project_id": v["project_id"]}
    assert str(v["path"]) not in json.dumps(admitted)
    with session_scope() as session:
        assert session.get(ToolInvocationRecord, command["id"]).materialization_input_hash == original.content_hash
        assert session.get(Input, command["id"]).created_at.tzinfo is not None
    v["path"].unlink()
    calls = count_acquisitions(monkeypatch)
    # Fresh application/repository state, not an in-memory admission object.
    fresh = MaterializationInputApplicationService(SourceSnapshotRepository(), service.materialization_inputs.authorization,
        MaterializationCommandInputRepository())
    monkeypatch.setattr(service, "materialization_inputs", fresh)
    result = resume(v, command, service)
    assert result.candidate_revision.manifest_id == manifest.manifest_id
    assert not calls and events(command) == admitted
    assert repo.get(command["id"], scope_for(v)) == original


def test_concurrent_admission_keeps_one_command_input_and_one_outbox_event(evidence_api, monkeypatch):
    v = evidence_api
    command = running_materialization(v, monkeypatch)
    manifest, scope = SourceSnapshotRepository().latest_manifest(v["project_id"]), scope_for(v)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: MaterializationCommandInputRepository().admit(command["id"], scope, manifest), range(2)))
    assert results[0] == results[1] == MaterializationCommandInputRepository().get(command["id"], scope)
    assert len(events(command)) == 1


def test_admission_and_command_consumption_pin_roll_back_with_outbox(evidence_api, monkeypatch):
    v = evidence_api
    before = facts(v)
    append = EventOutboxRepository.append
    def fail(repo, event, *args, **kwargs):
        if event.event_type == "system_image.materialization.admitted":
            raise OSError("private-storage-secret")
        return append(repo, event, *args, **kwargs)
    calls = count_acquisitions(monkeypatch)
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    result = materialize(v)
    assert result["status"] == "failed" and result["result"]["followup_reason"] == "materialization_inputs_unavailable"
    assert not calls and facts(v) == before and events(result) == []
    assert "private-storage-secret" not in json.dumps(result)
    with session_scope() as session:
        assert session.get(Input, result["id"]) is None
        assert session.get(ToolInvocationRecord, result["id"]).materialization_input_hash is None


@pytest.mark.parametrize("fault", ["command_payload", "terminal", "actor", "input_hash", "missing_input"])
def test_invalid_original_input_fails_before_preparation_and_is_not_repaired(evidence_api, monkeypatch, fault):
    v = evidence_api
    grant_tester(v)
    command = running_materialization(v, monkeypatch)
    service = begin(v, command, monkeypatch)
    before = facts(v)
    original_events = events(command)
    with session_scope() as session:
        assert session.get_bind().url.database.startswith("nasus_test_")
        if fault == "command_payload":
            row = session.get(ToolInvocationRecord, command["id"])
            row.input_payload = {**row.input_payload, "different": True}
        elif fault == "terminal":
            session.get(ToolInvocationRecord, command["id"]).status = "failed"
        elif fault in {"input_hash", "missing_input"}:
            session.execute(text("ALTER TABLE materialization_source_inputs DISABLE TRIGGER immutable_materialization_source_inputs"))
            if fault == "input_hash":
                session.execute(text("UPDATE materialization_source_inputs SET content_hash = :digest WHERE invocation_id = :id"),
                    {"id": command["id"], "digest": "sha256:" + "0" * 64})
            else:
                session.execute(text("DELETE FROM materialization_source_inputs WHERE invocation_id = :id"), {"id": command["id"]})
            session.execute(text("ALTER TABLE materialization_source_inputs ENABLE TRIGGER immutable_materialization_source_inputs"))
    calls = count_acquisitions(monkeypatch)
    with pytest.raises(PlatformApplicationError) as error:
        resume(v, command, service, actor=v["member"] if fault == "actor" else None)
    assert error.value.code == "materialization_input_integrity_failed"
    assert not calls and facts(v) == before and events(command) == original_events
    with session_scope() as session:
        row = session.get(Input, command["id"])
        if fault == "missing_input":
            assert row is None
        elif fault == "input_hash":
            assert row.content_hash == "sha256:" + "0" * 64


@pytest.mark.parametrize("change", ["source_acl", "membership_role"])
def test_original_command_rechecks_current_permission_after_interruption(evidence_api, monkeypatch, change):
    v = evidence_api
    grant_tester(v)
    policy(v, (v["member"]["id"],))
    command = running_materialization(v, monkeypatch, headers=v["member_headers"])
    service = begin(v, command, monkeypatch, actor=v["member"])
    before = facts(v)
    if change == "source_acl":
        policy(v)
    else:
        response = v["client"].put(f"/v1/projects/{v['project_id']}/members/{v['member']['id']}",
            headers=v["headers"], json={"role": "viewer"})
        assert response.status_code == 200, response.text
    calls = count_acquisitions(monkeypatch)
    with pytest.raises(PlatformApplicationError) as error:
        resume(v, command, service, actor=v["member"])
    assert error.value.code == "source_access_denied" and error.value.status_code == 403
    assert not calls and facts(v) == before and len(events(command)) == 1


def test_production_materializer_rejects_unowned_direct_write(evidence_api, monkeypatch):
    v = evidence_api
    service = app.state.container.system_image.lifecycle._operations
    before = facts(v)
    calls = count_acquisitions(monkeypatch)
    with actor_scope(UserProfile.model_validate(v["owner"])), pytest.raises(PlatformApplicationError) as error:
        asyncio.run(service.materialize_context(v["project_id"]))
    assert error.value.code == "materialization_canonical_command_required"
    assert not calls and facts(v) == before


def test_pg_protects_input_and_consumption_pin_and_refuses_destructive_downgrade(evidence_api, monkeypatch):
    v = evidence_api
    command = running_materialization(v, monkeypatch)
    begin(v, command, monkeypatch)
    for sql in (
        "UPDATE materialization_source_inputs SET manifest_id = manifest_id WHERE invocation_id = :id",
        "DELETE FROM materialization_source_inputs WHERE invocation_id = :id",
        "UPDATE tool_invocations SET materialization_input_hash = NULL WHERE id = :id",
    ):
        with pytest.raises(DBAPIError):
            with session_scope() as session:
                session.execute(text(sql), {"id": command["id"]})
    migration = importlib.import_module("apps.api.migrations.versions.0096_materialization_inputs")
    with session_scope() as session:
        with monkeypatch.context() as patch:
            patch.setattr(migration.op, "get_bind", lambda: session.connection())
            with pytest.raises(RuntimeError, match="populated"):
                migration.downgrade()


def test_legacy_command_marker_never_invents_an_original_manifest(evidence_api, monkeypatch):
    v = evidence_api
    command = running_materialization(v, monkeypatch)
    with session_scope() as session:
        session.add(Legacy(invocation_id=command["id"]))
    before = facts(v)
    with pytest.raises(MaterializationOriginalInputUnavailable):
        MaterializationCommandInputRepository().get(command["id"], scope_for(v))
    service = app.state.container.system_image.lifecycle._operations
    with pytest.raises(PlatformApplicationError) as error:
        resume(v, command, service)
    assert error.value.code == "materialization_original_input_required"
    assert facts(v) == before and events(command) == []
    with session_scope() as session:
        assert session.get(Input, command["id"]) is None


def test_baseline_confirmation_uses_its_own_materialization_source_input(evidence_api):
    v = evidence_api
    manifest = SourceSnapshotRepository().latest_manifest(v["project_id"])
    pending = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "tool_id": "system_image.baseline.initialize", "input": {"project_id": v["project_id"]},
    })
    assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
    invocation_id = pending.json()["id"]
    with session_scope() as session:
        assert session.get(Input, invocation_id) is None
    confirmed = v["client"].post(f"/v1/tool-invocations/{invocation_id}/confirm", headers=v["headers"])
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "completed", confirmed.text
    with session_scope() as session:
        row = session.get(Input, invocation_id)
        original = MaterializationCommandInputRepository._from_row(row)
        assert (original.manifest_id, original.manifest_hash) == (manifest.manifest_id, manifest.content_hash)
        assert session.get(ToolInvocationRecord, invocation_id).materialization_input_hash == original.content_hash
        from apps.api.app.infrastructure.persistence.image_publication_models import ImagePublicationHeadRecord
        assert session.scalar(select(ImagePublicationHeadRecord).where(ImagePublicationHeadRecord.project_id == v["project_id"])) is None


def test_canonical_us_start_does_not_hide_a_second_materialization(documents, monkeypatch):
    v = documents
    service = app.state.container.system_image.lifecycle._operations
    items = service.workspace.list_us_items(v["project_id"])
    assert items
    with session_scope() as session:
        original_inputs = session.scalars(select(Input.invocation_id).where(Input.project_id == v["project_id"])).all()
    async def forbidden(*args, **kwargs):
        pytest.fail("US start must not rebuild the image outside a separate canonical invocation")
    monkeypatch.setattr(service, "materialize_context", forbidden)
    calls = count_acquisitions(monkeypatch)
    result = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "tool_id": "us.task.start", "input": {"project_id": v["project_id"], "us_id": items[0].id},
    })
    assert result.status_code == 200 and result.json()["status"] == "completed", result.text
    assert not calls
    with session_scope() as session:
        assert session.scalars(select(Input.invocation_id).where(Input.project_id == v["project_id"])).all() == original_inputs
