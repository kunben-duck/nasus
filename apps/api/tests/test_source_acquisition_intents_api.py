"""Real PG admission before connector IO; never run against a developer database."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import importlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from apps.api.app.application.system_image.source_refresh_inputs import source_refresh_selection
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.domain.system_image.source_acquisition import SourceAcquisitionIntentConflict
from apps.api.app.infrastructure.persistence.db_models import (
    RawAssetRecord, SSEEventOutboxRecord, ToolInvocationRecord, UserIdentityRecord,
)
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.source_acquisition_models import SourceAcquisitionIntentRecord as IntentRow
from apps.api.app.infrastructure.persistence.source_acquisition_repository import SourceAcquisitionIntentRepository
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceBindingRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
from apps.api.app.main import app
from apps.api.tests.test_source_access_api import policy
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_ingestion_access_api import facts, grant_tester, revisions
from apps.api.tests.test_source_refresh_api import add_optional, read, refresh, selection


def scope_for(v, actor=None):
    actor_id = (actor or v["owner"])["id"]
    snapshot, role = SourceAccessRepository().load_authorized_snapshot(
        v["project_id"], actor_id, platform_administrator=False)
    return snapshot.for_actor(actor_id, role)


def sources(v, request):
    with session_scope() as session:
        ids = session.scalars(select(SourceBindingRecord.legacy_source_id).where(
            SourceBindingRecord.project_id == v["project_id"])).all()
    return tuple(sorted(request["source_ids"] if request else ids))


def admitted_events(invocation_id):
    with session_scope() as session:
        return deepcopy([row.event_payload for row in session.scalars(select(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.event_id == f"source-acquisition-intent:{invocation_id}")).all()])


def running_command(v, request, monkeypatch, *, headers=None):
    # Only defer the handler. Runtime RBAC, durable claim, audit and the HTTP
    # receipt remain real; no ToolInvocation or authorization facts are forged.
    registry = app.state.container.platform._tool_invocations._runtime.handlers
    original = registry.resolve
    async def deferred(invocation):
        assert invocation.tool_id == "system_image.sources.ingest"
    with monkeypatch.context() as patch:
        patch.setattr(registry, "resolve", lambda tool: SimpleNamespace(handle=deferred)
            if tool == "system_image.sources.ingest" else original(tool))
        return refresh(v, request, key=uuid4().hex, status="running", headers=headers)


@pytest.mark.parametrize("mode", ["selected", "whole_project"])
def test_canonical_command_commits_private_pins_before_real_connector(evidence_api, tmp_path, monkeypatch, mode):
    v = evidence_api
    _, image, source = add_optional(v, tmp_path)
    request = selection(image, source["id"]) if mode == "selected" else {}
    original = SourceIngestionService.ingest
    observed = []
    def checked(service, item):
        with session_scope() as session:
            row = session.scalar(select(IntentRow).join(ToolInvocationRecord,
                IntentRow.invocation_id == ToolInvocationRecord.id).where(
                    IntentRow.project_id == v["project_id"], ToolInvocationRecord.status == "running"))
            assert row is not None
            intent = SourceAcquisitionIntentRepository._from_row(row)
            assert row.created_at.tzinfo is not None
        assert intent.actor_id == v["owner"]["id"] and intent.selection_mode == mode
        assert (intent.origin_manifest_id, intent.origin_manifest_hash) == (
            image["source_manifest"]["manifest_id"], image["source_manifest"]["content_hash"])
        assert tuple(pin.source_id for pin in intent.sources) == sources(v, request)
        events = admitted_events(intent.invocation_id)
        assert len(events) == 1
        assert events[0]["patch"] == {"project_id": v["project_id"]}
        assert all(value not in json.dumps(events) for value in (str(v["path"]), str(tmp_path), "archive_ref", "credential_ref"))
        observed.append(intent.invocation_id)
        return original(service, item)
    monkeypatch.setattr(SourceIngestionService, "ingest", checked)
    result = refresh(v, request, key=uuid4().hex)
    assert len(observed) == (1 if mode == "selected" else 2)
    assert set(observed) == {result["id"]}
    assert SourceAcquisitionIntentRepository().get(result["id"]).content_hash


def test_first_whole_project_command_does_not_invent_a_previous_manifest(evidence_api, tmp_path):
    v = evidence_api
    created = v["client"].post("/v1/projects", headers=v["headers"], json={"name": f"First acquisition {uuid4().hex}"})
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    path = tmp_path / "first.py"
    path.write_text("class First:\n    pass\n")
    registered = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "tool_id": "system_image.sources.register", "input": {"project_id": project_id,
            "source_specs": [{"source_type": "code", "source_uri": str(path)}]}})
    assert registered.status_code == 200 and registered.json()["status"] == "completed", registered.text
    response = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "tool_id": "system_image.sources.ingest", "input": {"project_id": project_id}})
    assert response.status_code == 200 and response.json()["status"] == "completed", response.text
    result = SourceAcquisitionIntentRepository().get(response.json()["id"])
    assert result.origin_manifest_id is result.origin_manifest_hash is None
    assert result.project_id == project_id and len(result.sources) == 1
    assert SourceAcquisitionIntentRepository().get(registered.json()["id"]) is None


def test_concurrent_reentry_and_new_repository_keep_one_original_intent(evidence_api, monkeypatch):
    v = evidence_api
    request = selection(read(v), next(iter(scope_for(v).source_ids)))
    command = running_command(v, request, monkeypatch)
    scope, source_ids, selected = scope_for(v), sources(v, request), source_refresh_selection(request)
    def admit(_):
        return SourceAcquisitionIntentRepository().admit(command["id"], scope, source_ids, selected)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(admit, range(2)))
    assert first == second == SourceAcquisitionIntentRepository().get(command["id"])
    assert len(admitted_events(command["id"])) == 1


def test_whole_reentry_cannot_adopt_newly_registered_sources(evidence_api, tmp_path, monkeypatch):
    v = evidence_api
    command = running_command(v, {}, monkeypatch)
    old_sources = sources(v, {})
    repo = SourceAcquisitionIntentRepository()
    original = repo.admit(command["id"], scope_for(v), old_sources, None)
    path = tmp_path / "later.md"
    path.write_text("# US-LATER\nLate source\n")
    v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "us_doc", "source_uri": str(path)}]})
    with pytest.raises(ValueError, match="complete registered"):
        SourceAcquisitionIntentRepository().admit(command["id"], scope_for(v), old_sources, None)
    with pytest.raises(SourceAcquisitionIntentConflict):
        SourceAcquisitionIntentRepository().admit(command["id"], scope_for(v), sources(v, {}), None)
    assert repo.get(command["id"]) == original and len(admitted_events(command["id"])) == 1


@pytest.mark.parametrize("mode", ["selected", "whole_project"])
def test_reentry_cannot_silently_follow_a_new_source_manifest(evidence_api, monkeypatch, mode):
    v = evidence_api
    request = selection(read(v), next(iter(scope_for(v).source_ids))) if mode == "selected" else {}
    command = running_command(v, request, monkeypatch)
    selected, ids = source_refresh_selection(request), sources(v, request)
    repo = SourceAcquisitionIntentRepository()
    original = repo.admit(command["id"], scope_for(v), ids, selected)
    v["path"].write_text("class Orders:\n    def submit(self):\n        return 'new-revision'\n")
    v["invoke"]("system_image.sources.ingest")
    with pytest.raises((ValueError, SourceAcquisitionIntentConflict)):
        SourceAcquisitionIntentRepository().admit(command["id"], scope_for(v), ids, selected)
    assert repo.get(command["id"]) == original and len(admitted_events(command["id"])) == 1


def test_existing_intent_still_requires_current_source_permission(evidence_api, monkeypatch):
    v = evidence_api
    grant_tester(v)
    policy(v, (v["member"]["id"],))
    command = running_command(v, {}, monkeypatch, headers=v["member_headers"])
    scope, ids = scope_for(v, v["member"]), sources(v, {})
    original = SourceAcquisitionIntentRepository().admit(command["id"], scope, ids, None)
    policy(v)
    with pytest.raises(SourceAccessDenied):
        SourceAcquisitionIntentRepository().admit(command["id"], scope, ids, None)
    with pytest.raises(ValueError):
        SourceAcquisitionIntentRepository().admit(command["id"], scope_for(v, v["member"]), ids, None)
    policy(v, (v["member"]["id"],))
    assert SourceAcquisitionIntentRepository().admit(command["id"], scope_for(v, v["member"]), ids, None) == original


def test_another_authorized_actor_cannot_adopt_the_original_intent(evidence_api, monkeypatch):
    v = evidence_api
    grant_tester(v)
    command = running_command(v, {}, monkeypatch)
    ids = sources(v, {})
    original = SourceAcquisitionIntentRepository().admit(command["id"], scope_for(v), ids, None)
    with pytest.raises(SourceAcquisitionIntentConflict):
        SourceAcquisitionIntentRepository().admit(command["id"], scope_for(v, v["member"]), ids, None)
    assert SourceAcquisitionIntentRepository().get(command["id"]) == original


def test_selected_reentry_does_not_expand_when_an_unselected_source_is_registered(evidence_api, tmp_path, monkeypatch):
    v = evidence_api
    request = selection(read(v), next(iter(scope_for(v).source_ids)))
    command = running_command(v, request, monkeypatch)
    selected, ids = source_refresh_selection(request), sources(v, request)
    repo = SourceAcquisitionIntentRepository()
    original = repo.admit(command["id"], scope_for(v), ids, selected)
    path = tmp_path / "unselected.md"
    path.write_text("# US-UNSELECTED\nNot part of the selected acquisition.\n")
    v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "us_doc", "source_uri": str(path)}]})
    assert len(scope_for(v).source_ids) == 2
    assert repo.admit(command["id"], scope_for(v), ids, selected) == original
    assert len(original.sources) == 1 and len(admitted_events(command["id"])) == 1


@pytest.mark.parametrize("fault", ["stale_manifest", "denied_source"])
def test_pre_admission_rejection_creates_neither_intent_nor_connector_work(evidence_api, monkeypatch, fault):
    v = evidence_api
    grant_tester(v)
    request = selection(read(v), next(iter(scope_for(v).source_ids)))
    if fault == "stale_manifest":
        request["expected_manifest_hash"] = "sha256:" + "0" * 64
    else:
        policy(v)
    before = facts(v)
    calls = []
    monkeypatch.setattr(SourceIngestionService, "ingest", lambda _self, source: calls.append(source.id))
    result = refresh(v, request, status="failed", headers=v["member_headers"])
    assert result["result"]["followup_reason"] in {"source_refresh_scope_changed", "source_access_denied"}
    assert SourceAcquisitionIntentRepository().get(result["id"]) is None
    assert not admitted_events(result["id"]) and not calls and facts(v) == before


@pytest.mark.parametrize("fault", ["input", "terminal", "raw_identity", "inactive_account"])
def test_reentry_rejects_changed_command_identity_or_account(evidence_api, monkeypatch, fault):
    v = evidence_api
    command = running_command(v, {}, monkeypatch)
    scope, ids = scope_for(v), sources(v, {})
    repo = SourceAcquisitionIntentRepository()
    original = repo.admit(command["id"], scope, ids, None)
    # Deliberate fault injection into this test's private DB, not a production
    # API to mutate a completed command or an immutable acquisition intent.
    with session_scope() as session:
        if fault == "input":
            row = session.get(ToolInvocationRecord, command["id"])
            row.input_payload = {**row.input_payload, "changed": True}
        elif fault == "terminal":
            session.get(ToolInvocationRecord, command["id"]).status = "failed"
        elif fault == "raw_identity":
            session.get(RawAssetRecord, ids[0]).source_uri = "/private-substituted-source"
        else:
            session.get(UserIdentityRecord, v["owner"]["id"]).status = "disabled"
    with pytest.raises((ValueError, SourceAccessDenied, SourceAcquisitionIntentConflict)):
        SourceAcquisitionIntentRepository().admit(command["id"], scope, ids, None)
    assert repo.get(command["id"]) == original and len(admitted_events(command["id"])) == 1


def test_admission_and_outbox_rollback_together_before_workspace_changes(evidence_api, monkeypatch):
    v = evidence_api
    before = facts(v)
    original = EventOutboxRepository.append
    def fail(self, event, *args, **kwargs):
        if event.event_type == "system_image.source_acquisition.admitted":
            raise OSError("private-outbox-secret")
        return original(self, event, *args, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    connector_calls = []
    monkeypatch.setattr(SourceIngestionService, "ingest", lambda _self, source: connector_calls.append(source.id))
    result = refresh(v, {}, status="failed")
    assert result["result"]["followup_reason"] == "source_acquisition_unavailable"
    assert "private-outbox-secret" not in json.dumps(result)
    assert SourceAcquisitionIntentRepository().get(result["id"]) is None
    assert not admitted_events(result["id"]) and not connector_calls and facts(v) == before


def test_live_revoke_after_admission_keeps_intent_but_stops_before_mutation(evidence_api, monkeypatch):
    v = evidence_api
    grant_tester(v)
    policy(v, (v["member"]["id"],))
    before, old_revisions = facts(v), revisions(v)
    original = SourceAcquisitionIntentRepository.admit
    def revoke(self, *args):
        result = original(self, *args)
        policy(v)
        return result
    monkeypatch.setattr(SourceAcquisitionIntentRepository, "admit", revoke)
    calls = []
    monkeypatch.setattr(SourceIngestionService, "ingest", lambda _self, source: calls.append(source.id))
    # No conversation: the tester is independently allowed to operate this
    # project, without needing access to the owner's private conversation.
    response = v["client"].post("/v1/tool-invocations", headers=v["member_headers"], json={
        "tool_id": "system_image.sources.ingest", "input": {"project_id": v["project_id"]}})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "failed" and result["result"]["followup_reason"] == "source_access_denied"
    admitted = SourceAcquisitionIntentRepository().get(result["id"])
    assert admitted.actor_id == v["member"]["id"] and len(admitted_events(result["id"])) == 1
    assert not calls and facts(v) == before and revisions(v) == old_revisions


def test_pg_rejects_intent_update_delete_and_destructive_downgrade(evidence_api):
    v = evidence_api
    command = refresh(v, {})
    original = SourceAcquisitionIntentRepository().get(command["id"])
    for sql in ("UPDATE source_acquisition_intents SET actor_id = actor_id WHERE invocation_id = :id",
                "DELETE FROM source_acquisition_intents WHERE invocation_id = :id"):
        with pytest.raises(DBAPIError):
            with session_scope() as session:
                session.execute(text(sql), {"id": command["id"]})
    migration = importlib.import_module("apps.api.migrations.versions.0094_source_acquisition_intents")
    with session_scope() as session:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(migration.op, "get_bind", lambda: session.connection())
            with pytest.raises(RuntimeError, match="populated"):
                migration.downgrade()
    assert SourceAcquisitionIntentRepository().get(command["id"]) == original


def test_corrupted_imported_intent_is_rejected_not_repaired(evidence_api, monkeypatch):
    v = evidence_api
    command = running_command(v, {}, monkeypatch)
    scope, ids = scope_for(v), sources(v, {})
    repo = SourceAcquisitionIntentRepository()
    repo.admit(command["id"], scope, ids, None)
    # Simulate damaged backup bytes only in the isolated test DB. Production
    # writes cannot bypass the trigger and replay must not repair this history.
    with session_scope() as session:
        session.execute(text("ALTER TABLE source_acquisition_intents DISABLE TRIGGER immutable_source_acquisition_intents"))
        session.execute(text("UPDATE source_acquisition_intents SET content_hash = :hash WHERE invocation_id = :id"),
            {"hash": "sha256:" + "0" * 64, "id": command["id"]})
        session.execute(text("ALTER TABLE source_acquisition_intents ENABLE TRIGGER immutable_source_acquisition_intents"))
    with pytest.raises(ValueError, match="integrity"):
        SourceAcquisitionIntentRepository().get(command["id"])
    with pytest.raises(ValueError, match="integrity"):
        SourceAcquisitionIntentRepository().admit(command["id"], scope, ids, None)
    with session_scope() as session:
        assert session.get(IntentRow, command["id"]).content_hash == "sha256:" + "0" * 64
    assert len(admitted_events(command["id"])) == 1


@pytest.mark.parametrize("mode", ["selected", "whole_project"])
@pytest.mark.parametrize("fault", ["binding_hash", "manifest_hash", "manifest_member"])
def test_damaged_source_pins_stop_before_admission_connector_or_projection(evidence_api, monkeypatch, mode, fault):
    v = evidence_api
    image = read(v)
    source_id = next(iter(scope_for(v).source_ids))
    request = selection(image, source_id) if mode == "selected" else {}
    damaged_hash = "sha256:" + "0" * 64
    with session_scope() as session:
        assert session.get_bind().url.database.startswith("nasus_test_")
        binding = session.scalar(select(SourceBindingRecord).where(SourceBindingRecord.legacy_source_id == source_id))
        table = "source_bindings" if fault == "binding_hash" else (
            "source_manifests" if fault == "manifest_hash" else "source_manifest_members")
        # Damaged restore fixture only; normal writes remain append-only.
        session.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
        if fault == "binding_hash":
            session.execute(text("UPDATE source_bindings SET identity_hash = :digest WHERE binding_id = :id"),
                {"digest": damaged_hash, "id": binding.binding_id})
        elif fault == "manifest_hash":
            session.execute(text("UPDATE source_manifests SET content_hash = :digest WHERE manifest_id = :id"),
                {"digest": damaged_hash, "id": image["source_manifest"]["manifest_id"]})
            if mode == "selected":
                request["expected_manifest_hash"] = damaged_hash
        else:
            session.execute(text("UPDATE source_manifest_members SET source_type = 'us_doc' "
                "WHERE manifest_id = :id AND binding_id = :binding"),
                {"id": image["source_manifest"]["manifest_id"], "binding": binding.binding_id})
        session.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER USER"))
        damaged_rows = [tuple(row) for row in session.execute(text(f"SELECT * FROM {table} ORDER BY 1"))]
    before, old_revisions = facts(v), revisions(v)
    original, calls = SourceIngestionService.ingest, []
    def counted(service, source):
        calls.append(source.id)
        return original(service, source)
    monkeypatch.setattr(SourceIngestionService, "ingest", counted)
    result = refresh(v, request, key=uuid4().hex, status="failed")
    assert result["result"]["followup_reason"] == "source_acquisition_scope_invalid"
    assert SourceAcquisitionIntentRepository().get(result["id"]) is None
    assert not admitted_events(result["id"]) and not calls
    assert facts(v) == before and revisions(v) == old_revisions
    with session_scope() as session:
        assert [tuple(row) for row in session.execute(text(f"SELECT * FROM {table} ORDER BY 1"))] == damaged_rows
