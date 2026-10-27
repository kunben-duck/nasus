"""Real PG, canonical confirmation and original archived authority pins."""
import importlib
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import delete, insert, inspect as inspect_database, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.app.main import app
from apps.api.app.domain.system_image.context_authorities import (
    CONTEXT_AUTHORITY_POLICY, REGISTER_CONTEXT_AUTHORITIES_TOOL,
)
from apps.api.app.domain.system_image.context_partition import RULE_AUTHORITY_POLICY
from apps.api.app.domain.system_image.context_pack import ContextPackIntegrityError
from apps.api.app.application.platform.tool_models import EventPayload
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.system_image.context_pack_inputs import ContextAuthorityRegistrationInput
from apps.api.app.infrastructure.persistence.context_authority_models import (
    ContextAuthorityRootRecord as Root, ContextAuthorityDependencyRecord as Dependency,
    ContextAuthorityBackfillTargetRecord as Target,
)
from apps.api.app.infrastructure.persistence.context_authority_projection_v1 import ContextAuthorityProjectorV1
from apps.api.app.infrastructure.persistence.context_pack_models import ContextPackRecord
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord as Event, ToolInvocationRecord as Command
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_authority_provenance_api import authority, acceptance, rule, documents, evidence_api, withdraw
from apps.api.tests.test_context_packs_api import preview, archive, read
from apps.api.tests.test_semantic_evaluations_api import completed, invoke, confirm
from apps.api.tests.test_relation_provenance_api import RollbackProbe


def rows(session, model, project):
    return [dict(row) for row in session.execute(select(*model.__table__.columns).where(model.project_id == project)
        .order_by(model.context_id, *([model.object_id] if hasattr(model, "object_id") else []))).mappings()]


def register(v, context):
    request = {"project_id": v["project_id"], "context_id": context["metadata"]["context_id"],
        "artifact_hash": context["metadata"]["artifact_hash"], "policy_revision": CONTEXT_AUTHORITY_POLICY}
    pending = invoke(v, REGISTER_CONTEXT_AUTHORITIES_TOOL, request, key=uuid4().hex).json()
    assert pending["status"] == "waiting_confirmation", pending
    return confirm(v, pending)


def remove_registration(session, project, *, enroll=False):
    roots, edges = rows(session, Root, project), rows(session, Dependency, project)
    for model in (Dependency, Root):
        session.execute(text(f"ALTER TABLE {model.__tablename__} DISABLE TRIGGER USER"))
        session.execute(delete(model).where(model.project_id == project))
        session.execute(text(f"ALTER TABLE {model.__tablename__} ENABLE TRIGGER USER"))
    if enroll:
        for root in roots:
            session.add(Target(project_id=project, context_id=root["context_id"],
                context_metadata_hash=root["context_metadata_hash"], artifact_hash=root["artifact_hash"],
                policy_revision=CONTEXT_AUTHORITY_POLICY))
    return roots, edges


def restore_registration(session, roots, edges):
    session.execute(insert(Root), roots)
    if edges:
        session.execute(insert(Dependency), edges)


def test_context_captures_exact_approved_and_unapproved_pins_atomically(authority):
    v = authority
    unapproved, _ = read(v, completed(archive(v, preview(v, policy_revision=RULE_AUTHORITY_POLICY))[0]))
    completed(v["authority_submit"](v))
    head = v["authority_inspect"](v)["head"]
    context, url = read(v, completed(archive(v, preview(v, policy_revision=RULE_AUTHORITY_POLICY))[0]))
    with session_scope() as session:
        roots, dependencies = rows(session, Root, v["project_id"]), rows(session, Dependency, v["project_id"])
        negative = next(item for item in dependencies if item["context_id"] == unapproved["metadata"]["context_id"]
            and item["object_id"] == head["object_id"])
        assert negative["status"] == "unapproved" and negative["revision_id"] is None
        fixed = next(item for item in dependencies if item["context_id"] == context["metadata"]["context_id"]
            and item["object_id"] == head["object_id"])
        assert fixed["kind"] == v["authority_kind"] and fixed["revision_id"] == head["revision_id"]
        assert fixed["artifact_hash"] == head["artifact_hash"] and fixed["authority_registration_hash"]
        assert len(roots) == 2 and all(root["registration_invocation_id"] == root["invocation_id"] for root in roots)
        assert not rows(session, Target, v["project_id"])
        assert not any(word in json.dumps(roots + dependencies) for word in ("HTTP 400", "source_fields", "s3://", "local-object://"))
    completed(withdraw(v, head))
    historical = v["client"].get(url, headers=v["headers"])
    assert historical.status_code == 200, historical.text
    assert historical.json()["metadata"] == context["metadata"] and historical.json()["context"] == context["context"]
    assert historical.json()["current_use"]["stale"]
    with session_scope() as session:
        assert rows(session, Root, v["project_id"]) == roots and rows(session, Dependency, v["project_id"]) == dependencies


@pytest.mark.parametrize("damage", ["missing_root", "missing_edge", "basis_digest"])
def test_corrupt_registration_blocks_reads_and_never_self_repairs(authority, damage):
    v = authority
    completed(v["authority_submit"](v))
    context, url = read(v, completed(archive(v, preview(v, policy_revision=RULE_AUTHORITY_POLICY))[0]))
    with session_scope() as session:
        original_roots, original_edges = rows(session, Root, v["project_id"]), rows(session, Dependency, v["project_id"])
        if damage == "missing_root":
            remove_registration(session, v["project_id"])
        else:
            session.execute(text("ALTER TABLE system_image_context_authority_dependencies DISABLE TRIGGER USER"))
            if damage == "missing_edge":
                session.execute(delete(Dependency).where(Dependency.project_id == v["project_id"]))
            else:
                session.execute(update(Dependency).where(Dependency.project_id == v["project_id"])
                    .values(basis_digest="sha256:" + "0" * 64))
            session.execute(text("ALTER TABLE system_image_context_authority_dependencies ENABLE TRIGGER USER"))
        damaged_roots, damaged_edges = rows(session, Root, v["project_id"]), rows(session, Dependency, v["project_id"])
    try:
        response = v["client"].get(url, headers=v["headers"])
        assert response.status_code == 502 and "HTTP 400" not in response.text, response.text
        assert register(v, context).json()["status"] == "failed"
        with session_scope() as session:
            assert rows(session, Root, v["project_id"]) == damaged_roots
            assert rows(session, Dependency, v["project_id"]) == damaged_edges
    finally:
        with session_scope() as session:
            remove_registration(session, v["project_id"])
            restore_registration(session, original_roots, original_edges)
    assert v["client"].get(url, headers=v["headers"]).status_code == 200


def test_explicit_historical_backfill_uses_original_archive_not_current_approval(authority):
    v = authority
    completed(v["authority_submit"](v))
    head = v["authority_inspect"](v)["head"]
    context, url = read(v, completed(archive(v, preview(v, policy_revision=RULE_AUTHORITY_POLICY))[0]))
    with session_scope() as session:
        before_roots, before_edges = remove_registration(session, v["project_id"], enroll=True)
    pending_url = f"/v1/projects/{v['project_id']}/system-image/context-authority-backfill"
    pending = v["client"].get(pending_url, headers=v["headers"])
    assert pending.status_code == 200 and pending.headers["cache-control"] == "private, no-store", pending.text
    assert pending.json()["items"][0]["registration_request"]["context_id"] == context["metadata"]["context_id"]
    assert "HTTP 400" not in pending.text and "s3://" not in pending.text
    unavailable = v["client"].get(url, headers=v["headers"])
    assert unavailable.status_code == 409 and unavailable.json()["detail"]["error"]["code"] == "context_authority_registration_required"
    history_url = f"/v1/projects/{v['project_id']}/system-image/context-packs"
    history_params = {key: context["metadata"][key] for key in ("image_revision_id", "image_artifact_hash")}
    unavailable_list = v["client"].get(history_url, headers=v["headers"], params=history_params)
    assert unavailable_list.status_code == 409
    assert unavailable_list.json()["detail"]["error"]["code"] == "context_authority_registration_required"
    completed(withdraw(v, head))
    done = completed(register(v, context))
    historical = v["client"].get(url, headers=v["headers"])
    assert historical.status_code == 200 and historical.json()["context"] == context["context"], historical.text
    assert historical.json()["metadata"] == context["metadata"] and historical.json()["current_use"]["stale"]
    with session_scope() as session:
        roots, edges = rows(session, Root, v["project_id"]), rows(session, Dependency, v["project_id"])
        assert edges == before_edges and roots[0]["registration_invocation_id"] == done["id"]
        assert roots[0]["invocation_id"] == before_roots[0]["invocation_id"]
        events = session.scalars(select(Event).where(Event.entity_id == context["metadata"]["context_id"],
            Event.event_type == "system_image.context.authorities_registered")).all()
        assert len(events) == 1
        registered_event = deepcopy(events[0].event_payload)
    with pytest.raises(ContextPackIntegrityError):
        with session_scope() as session:
            forged = {**registered_event, "event_id": str(uuid4()), "patch": {
                **registered_event["patch"], "authority_count": registered_event["patch"]["authority_count"] + 1}}
            EventOutboxRepository().append(EventPayload(**forged), session=session)
    completed(register(v, context))
    assert v["client"].get(pending_url, headers=v["headers"]).json()["items"] == []
    with session_scope() as session:
        assert rows(session, Root, v["project_id"]) == roots
        assert len(session.scalars(select(Event).where(Event.entity_id == context["metadata"]["context_id"],
            Event.event_type == "system_image.context.authorities_registered")).all()) == 1
        command = session.get(Command, done["id"])
        original_input = deepcopy(command.input_payload)
        command.input_payload = {**original_input, "confirmed_at": "1900-01-01T00:00:00+00:00"}
    try:
        assert v["client"].get(url, headers=v["headers"]).status_code == 200
    finally:
        with session_scope() as session:
            session.get(Command, done["id"]).input_payload = original_input


def test_current_reads_verify_registration_command_and_event_replay_is_never_a_repair(authority):
    v = authority
    context, url = read(v, completed(archive(v, preview(v, policy_revision=RULE_AUTHORITY_POLICY))[0]))
    context_id = context["metadata"]["context_id"]
    with session_scope() as session:
        root = session.get(Root, (v["project_id"], context_id))
        command = session.get(Command, root.registration_invocation_id)
        command_id, original_input, original_tool = command.id, deepcopy(command.input_payload), command.tool_id
        compiled_event = deepcopy(session.scalar(select(Event).where(Event.entity_id == context_id,
            Event.event_type == "system_image.context.compiled")).event_payload)
        roots, edges = rows(session, Root, v["project_id"]), rows(session, Dependency, v["project_id"])
    for changes in ({"confirmed_by_user": False}, {"confirmed_actor_id": "another-reviewer"},
                    {"image_revision_id": "another-image"}, {"unrecognized_field": "not-a-command"}):
        with session_scope() as session:
            session.get(Command, command_id).input_payload = {**original_input, **changes}
        try:
            response = v["client"].get(url, headers=v["headers"])
            assert response.status_code == 502 and "HTTP 400" not in response.text, response.text
            with pytest.raises(ContextPackIntegrityError):
                with session_scope() as session:
                    EventOutboxRepository().append(EventPayload(**{**compiled_event, "event_id": str(uuid4())}), session=session)
        finally:
            with session_scope() as session:
                session.get(Command, command_id).input_payload = original_input
    with session_scope() as session:
        session.get(Command, command_id).tool_id = REGISTER_CONTEXT_AUTHORITIES_TOOL
    try:
        assert v["client"].get(url, headers=v["headers"]).status_code == 502
    finally:
        with session_scope() as session:
            session.get(Command, command_id).tool_id = original_tool
    with pytest.raises(ContextPackIntegrityError):
        with session_scope() as session:
            forged = {**compiled_event, "event_id": str(uuid4()), "patch": {**compiled_event["patch"], "readiness": "ready"}}
            EventOutboxRepository().append(EventPayload(**forged), session=session)
    with session_scope() as session:
        before_roots, before_edges = remove_registration(session, v["project_id"])
    try:
        with pytest.raises(ContextPackIntegrityError):
            with session_scope() as session:
                EventOutboxRepository().append(EventPayload(**{**compiled_event, "event_id": str(uuid4())}), session=session)
        with session_scope() as session:
            assert not rows(session, Root, v["project_id"]) and not rows(session, Dependency, v["project_id"])
    finally:
        with session_scope() as session:
            restore_registration(session, before_roots, before_edges)
    assert v["client"].get(url, headers=v["headers"]).status_code == 200
    with session_scope() as session:
        assert rows(session, Root, v["project_id"]) == roots and rows(session, Dependency, v["project_id"]) == edges


def test_historical_backfill_failure_rolls_back_dependencies_and_its_event(authority, monkeypatch):
    v = authority
    context, _ = read(v, completed(archive(v, preview(v, policy_revision=RULE_AUTHORITY_POLICY))[0]))
    with session_scope() as session:
        remove_registration(session, v["project_id"], enroll=True)
    append = EventOutboxRepository.append
    def fail(self, event, **kwargs):
        if event.event_type == "system_image.context.authorities_registered":
            raise RuntimeError("fixture historical outbox failure")
        return append(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    assert register(v, context).json()["status"] == "failed"
    with session_scope() as session:
        assert not rows(session, Root, v["project_id"]) and not rows(session, Dependency, v["project_id"])
        assert rows(session, Target, v["project_id"])
        assert not session.scalars(select(Event).where(Event.entity_id == context["metadata"]["context_id"],
            Event.event_type == "system_image.context.authorities_registered")).all()


def test_historical_registration_requires_fresh_exact_confirmation_at_final_commit(authority):
    v = authority
    context, _ = read(v, completed(archive(v, preview(v, policy_revision=RULE_AUTHORITY_POLICY))[0]))
    with session_scope() as session:
        remove_registration(session, v["project_id"], enroll=True)
    request = ContextAuthorityRegistrationInput(project_id=v["project_id"],
        context_id=context["metadata"]["context_id"], artifact_hash=context["metadata"]["artifact_hash"])
    pending = invoke(v, REGISTER_CONTEXT_AUTHORITIES_TOOL, request.model_dump(mode="json"), key=uuid4().hex).json()
    assert pending["status"] == "waiting_confirmation"
    base = {**pending["input_payload"], "confirmed_by_user": True,
        "confirmed_actor_id": v["owner"]["id"], "confirmed_at": datetime.now(timezone.utc).isoformat()}
    changes = ({"confirmed_by_user": False}, {"confirmed_actor_id": "another-reviewer"},
        {"confirmed_at": (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()},
        {"confirmed_at": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()},
        {"confirmed_at": datetime.now().isoformat()}, {"context_id": "another-context"},
        {"artifact_hash": "sha256:" + "0" * 64}, {"agent_goal_id": "another-goal"})
    for change in changes:
        with session_scope() as session:
            command = session.get(Command, pending["id"])
            command.status, command.input_payload = "running", {**base, **change}
        with actor_scope(UserProfile.model_validate(v["owner"])), pytest.raises((ContextPackIntegrityError, ValueError)):
            app.state.container.context_packs.register_authorities(request, invocation_id=pending["id"],
                recorded_at=datetime.now(timezone.utc).isoformat())
        with session_scope() as session:
            assert not rows(session, Root, v["project_id"]) and not rows(session, Dependency, v["project_id"])
            assert not session.scalars(select(Event).where(Event.entity_id == request.context_id,
                Event.event_type == "system_image.context.authorities_registered")).all()


def test_corrupt_archives_and_nonreviewers_cannot_backfill_or_discover_private_dependencies(authority, monkeypatch):
    v = authority
    context, _ = read(v, completed(archive(v, preview(v, policy_revision=RULE_AUTHORITY_POLICY))[0]))
    with session_scope() as session:
        remove_registration(session, v["project_id"], enroll=True)
    url = f"/v1/projects/{v['project_id']}/system-image/context-authority-backfill"
    assert v["client"].get(url).status_code == 401
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 403
    artifacts = app.state.container.context_packs.artifacts
    original = artifacts.read
    def corrupt(*args):
        result = original(*args)
        result["provenance"]["authority_pins"] = []
        return result
    monkeypatch.setattr(artifacts, "read", corrupt)
    response = v["client"].get(url, headers=v["headers"])
    assert response.status_code == 502 and "HTTP 400" not in response.text
    assert register(v, context).json()["status"] == "failed"
    with session_scope() as session:
        assert not rows(session, Root, v["project_id"]) and not rows(session, Dependency, v["project_id"])


def test_event_failure_rolls_back_native_context_and_all_dependency_records(authority, monkeypatch):
    v = authority
    append = EventOutboxRepository.append
    def fail(self, event, **kwargs):
        if event.event_type == "system_image.context.compiled":
            raise RuntimeError("fixture outbox failure")
        return append(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    response, _ = archive(v, preview(v, policy_revision=RULE_AUTHORITY_POLICY))
    assert response.json()["status"] == "failed"
    with session_scope() as session:
        assert not rows(session, Root, v["project_id"]) and not rows(session, Dependency, v["project_id"])
        assert not session.scalars(select(ContextPackRecord).where(ContextPackRecord.project_id == v["project_id"])).all()


def test_dependencies_are_append_only_and_typed_foreign_keys_prevent_cross_project_pins(authority):
    v = authority
    completed(v["authority_submit"](v))
    completed(archive(v, preview(v, policy_revision=RULE_AUTHORITY_POLICY))[0])
    for model in (Root, Dependency):
        for statement in (update(model).where(model.project_id == v["project_id"]).values(project_id="other"),
                          delete(model).where(model.project_id == v["project_id"])):
            with pytest.raises(IntegrityError, match="append-only"):
                with session_scope() as session:
                    session.execute(statement)
    with session_scope() as session:
        saved = rows(session, Dependency, v["project_id"])[0]
    with pytest.raises(IntegrityError):
        with session_scope() as session:
            session.execute(insert(Dependency).values(**{**saved, "project_id": "other"}))


def drop_context_authorities(connection):
    for model in (Dependency, Target, Root):
        model.__table__.drop(connection)
    connection.execute(text("DROP FUNCTION nasus_reject_context_authority_mutation()"))


def test_populated_migration_enrolls_exact_archives_without_guessing_any_authority(authority, monkeypatch):
    v = authority
    completed(v["authority_submit"](v))
    context, url = read(v, completed(archive(v, preview(v, policy_revision=RULE_AUTHORITY_POLICY))[0]))
    migration = importlib.import_module("apps.api.migrations.versions.0075_context_authorities")
    with pytest.raises(RollbackProbe), engine.begin() as connection:
        drop_context_authorities(connection)
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        with Session(bind=connection) as session:
            target = session.get(Target, (v["project_id"], context["metadata"]["context_id"]))
            assert target is not None and target.artifact_hash == context["metadata"]["artifact_hash"]
            assert not rows(session, Root, v["project_id"]) and not rows(session, Dependency, v["project_id"])
        with pytest.raises(RuntimeError, match="Cannot discard"):
            migration.downgrade()
        raise RollbackProbe()
    assert v["client"].get(url, headers=v["headers"]).json()["metadata"] == context["metadata"]


def test_context_authority_ddl_matches_native_column_order_types_and_nullability():
    for model in (Root, Dependency, Target):
        columns = inspect_database(engine).get_columns(model.__tablename__)
        assert [column["name"] for column in columns] == list(model.__table__.columns.keys())
        for actual, expected in zip(columns, model.__table__.columns):
            assert actual["nullable"] == expected.nullable and actual["type"]._type_affinity is expected.type._type_affinity
