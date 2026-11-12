"""Actual PG actor locks and read-only transactions; parent is an explicit specimen."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, select, text
from sqlalchemy.exc import OperationalError

from apps.api.app.application.quality_loop.http_fixture_commands import HttpFixtureCommandAuthority
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixture_command import FIXTURE_CANONICAL_DISPATCH_SCHEMA
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.infrastructure.persistence import http_fixture_journal_repository as journals
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import ProjectRoleBindingRecord, UserIdentityRecord
from apps.api.app.infrastructure.persistence.native_build_repository import NativeBuildRepository
from apps.api.app.infrastructure.persistence.http_fixture_work_repository import PostgresHttpFixtureWorkRepository
from apps.api.app.infrastructure.persistence.test_design_scope_repository import TestDesignScopeRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.storage.http_fixture_artifacts import HttpFixtureExecutionArtifacts
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage
from apps.api.tests.test_http_fixture_journal_access import saved_inputs
from apps.api.tests.test_http_fixtures import Runner


@pytest.fixture
def actor_journal(monkeypatch):
    assert engine.dialect.name == "postgresql"
    access, scope, _manifest, view = saved_inputs()
    actor_id = "fixture-read-actor-" + uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    with session_scope() as session:
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
        session.add(UserIdentityRecord(user_id=actor_id, email=actor_id + "@example.invalid",
            display_name="Read-lock protocol specimen", role="qa_lead", password_hash="not-a-login-hash",
            status="active", created_at=now, updated_at=now))
        session.add(ProjectRoleBindingRecord(binding_id=uuid4().hex, project_id=scope.project_id,
            user_id=actor_id, role="project_admin", scope_key="project:" + scope.project_id,
            scope_ref=scope.project_id, status="active", created_at=now, updated_at=now, created_by=actor_id))
    journal = journals.PostgresHttpFixtureDispatchJournal(access, None, actor_id=actor_id)
    # This test verifies only real identity SQL, not a native parent or execution.
    monkeypatch.setattr(journal, "_parent", lambda *_args: None)
    monkeypatch.setattr(journal, "_records", lambda *_args: (None, None))
    observed = []
    access.plans.read = lambda *_args: (observed.append(deepcopy(view)) or deepcopy(view))
    try:
        yield SimpleNamespace(journal=journal, scope=scope, actor_id=actor_id, observed=observed)
    finally:
        with session_scope() as session:
            session.execute(delete(ProjectRoleBindingRecord).where(ProjectRoleBindingRecord.user_id == actor_id))
            session.execute(delete(UserIdentityRecord).where(UserIdentityRecord.user_id == actor_id))


@contextmanager
def readonly_transactions(*, when=None):
    def begin(connection):
        if when is not None and not when():
            return
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        connection.exec_driver_sql("SET LOCAL lock_timeout = '100ms'")
    event.listen(engine, "begin", begin)
    try:
        yield
    finally:
        event.remove(engine, "begin", begin)


def test_readonly_guard_applies_only_inside_the_business_query_scope(actor_journal):
    active = ContextVar("fixture_history_read_scope", default=False)
    with readonly_transactions(when=active.get):
        with session_scope() as session:
            assert session.scalar(text("SHOW transaction_read_only")) == "off"
        token = active.set(True)
        try:
            with session_scope() as session:
                assert session.scalar(text("SHOW transaction_read_only")) == "on"
        finally:
            active.reset(token)
        with session_scope() as session:
            assert session.scalar(text("SHOW transaction_read_only")) == "off"


@pytest.mark.parametrize("worker", [False, True])
def test_history_checks_current_actor_without_reacquiring_an_owned_write_lock(actor_journal, worker):
    v = actor_journal
    if worker:
        v.journal.work_fence = object()  # Inspection cannot use this write-only fence.
    with session_scope() as writer:
        # Actual account and project-role locks on another PG connection.
        TestDesignScopeRepository._lock(writer, v.scope.project_id)
        actor = NativeBuildRepository._actor(writer, v.scope.project_id, v.actor_id)
        assert actor.user_id == v.actor_id
        with readonly_transactions():
            assert v.journal.inspect(v.scope, "setup", read_only=not worker) is None
    assert len(v.observed) == 2 and v.observed[0] == v.observed[1]


@pytest.mark.parametrize("revocation", ["actor_disabled", "project_role_revoked", "project_role_downgraded"])
def test_readonly_history_rechecks_actor_and_role_after_each_transaction(actor_journal, revocation):
    v = actor_journal
    with readonly_transactions():
        assert v.journal.inspect(v.scope, "setup", read_only=True) is None
    with session_scope() as writer:
        if revocation == "actor_disabled":
            writer.get(UserIdentityRecord, v.actor_id).status = "disabled"
        else:
            role = writer.scalar(select(ProjectRoleBindingRecord).where(ProjectRoleBindingRecord.user_id == v.actor_id))
            if revocation == "project_role_revoked":
                role.status = "revoked"
            else:
                role.role = "qa_lead"
    with readonly_transactions(), pytest.raises(PermissionError):
        v.journal.inspect(v.scope, "setup", read_only=True)


@pytest.mark.parametrize("worker", [False, True])
@pytest.mark.parametrize("revocation", ["actor_disabled", "project_role_revoked", "project_role_downgraded"])
def test_history_rechecks_actor_after_its_original_record_read(actor_journal, monkeypatch, revocation, worker):
    v = actor_journal

    @contextmanager
    def readonly_reader():
        with session_scope() as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            session.execute(text("SET LOCAL lock_timeout = '100ms'"))
            yield session

    def records(*_args):
        with session_scope() as writer:
            if revocation == "actor_disabled":
                writer.get(UserIdentityRecord, v.actor_id).status = "disabled"
            else:
                role = writer.scalar(select(ProjectRoleBindingRecord).where(ProjectRoleBindingRecord.user_id == v.actor_id))
                if revocation == "project_role_revoked":
                    role.status = "revoked"
                else:
                    role.role = "qa_lead"
        return None, None

    monkeypatch.setattr(journals, "session_scope", readonly_reader)
    monkeypatch.setattr(v.journal, "_records", records)
    if worker:
        v.journal.work_fence = object()
    with pytest.raises(PermissionError):
        v.journal.inspect(v.scope, "setup", read_only=not worker)


@pytest.mark.parametrize("mode,revocation", [
    (mode, change) for mode in ("setup", "stable_setup", "cleanup")
    for change in (None, "setup-records", "cleanup-records")
] + [("cleanup", "late-cleanup-change")])
def test_fixture_cohort_reads_without_write_locks_and_detects_committed_changes(actor_journal, monkeypatch, mode, revocation):
    v = actor_journal
    stable = mode == "stable_setup"
    authority = HttpFixtureCommandAuthority(invocation_id="setup-cohort-command", request_digest=acceptance_digest("request"))
    command = v.journal.access.command(v.scope, "setup")
    wire = Runner().execute_owned_http(command, environment_id=v.scope.environment_id, artifact_hash=v.scope.artifact_hash,
        inventory_hash=v.scope.inventory_hash, require_work=lambda: None)
    receipt = v.journal.verifier.verify(command, wire, environment_id=v.scope.environment_id, inventory_hash=v.scope.inventory_hash)
    phases, archives, original_checks = [], [], []

    def revoke():
        with session_scope() as writer:
            role = writer.scalar(select(ProjectRoleBindingRecord).where(ProjectRoleBindingRecord.user_id == v.actor_id))
            role.status = "revoked"

    def records(_session, _parent, scope, phase, _command):
        assert scope == v.scope
        phases.append(phase)
        if phase == "setup":
            if revocation == "setup-records":
                revoke()
            return {"schema": FIXTURE_CANONICAL_DISPATCH_SCHEMA, "canonical_command": authority.model_dump(mode="json")}, {
                "receipt_digest": acceptance_digest(receipt), "status": wire.result.status,
                "artifact_ref": "setup-archive", "artifact_hash": acceptance_digest("wire")}
        if revocation == "cleanup-records":
            revoke()
        if revocation == "late-cleanup-change" and phases.count(phase) == 2:
            return {"late": "original cleanup changed"}, None
        return None, None

    @contextmanager
    def readonly_reader():
        with session_scope() as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            session.execute(text("SET LOCAL lock_timeout = '100ms'"))
            yield session

    def current():
        if revocation == "setup-records":
            with readonly_reader() as session:
                NativeBuildRepository._actor(session, v.scope.project_id, v.actor_id, lock=False)

    def read_archive(_parent, _scope, phase, *_args):
        archives.append(phase)
        return wire

    monkeypatch.setattr(journals, "session_scope", readonly_reader)
    monkeypatch.setattr(v.journal, "_records", records)
    v.journal.artifacts = SimpleNamespace(read=read_archive)
    v.observed.clear()
    options = {"verify_original": lambda: original_checks.append(True)} if stable else {}
    if mode == "cleanup":
        read = lambda: v.journal.inspect_cleanup_history(v.scope, require_current=current)
    else:
        read = lambda: v.journal.inspect_original_setup_cohort(v.scope, original_setup=authority, require_current=current, **options)
    if revocation == "late-cleanup-change":
        with pytest.raises(HttpFixtureInvalid, match="original fixture journal changed"):
            read()
    elif revocation is not None:
        with pytest.raises(PermissionError):
            read()
    else:
        with session_scope() as writer:
            TestDesignScopeRepository._lock(writer, v.scope.project_id)
            NativeBuildRepository._actor(writer, v.scope.project_id, v.actor_id)
            result = read()
        assert result[0][1].execution == wire and result[1] == ("cleanup:session", None)
    if revocation == "setup-records":
        assert phases == ["setup"] and not archives and len(v.observed) == 1
    else:
        repeated = 2 if mode != "setup" and revocation in (None, "late-cleanup-change") else 1
        assert phases == ["setup", "cleanup:session"] * repeated and archives == ["setup"] * repeated and len(v.observed) == 2
    assert original_checks == ([True] if stable and revocation != "setup-records" else [])
    if mode == "cleanup" and revocation is None:
        v.observed.clear()
        archives.clear()
        original = tuple((phase, v.journal.inspect(v.scope, phase, read_only=True, require_current=current))
            for phase in ("setup", "cleanup:session"))
        assert original == result and len(v.observed) == 6 and archives == ["setup", "setup"]


@pytest.mark.skipif(os.environ.get("NASUS_TEST_OBJECT_STORAGE_MODE") != "minio", reason="private MinIO is required")
def test_cleanup_history_replays_exact_minio_archives_and_rejects_corruption(actor_journal, monkeypatch):
    v = actor_journal
    storage = ObjectStorage()
    assert storage.config.bucket.startswith("nasus-test-")
    artifacts = HttpFixtureExecutionArtifacts(storage)
    v.journal.artifacts = artifacts
    parent, setup = v.journal.access.command_with_parent(v.scope, "setup")
    runner = Runner()
    def archived(phase, command):
        execution = runner.execute_owned_http(command, environment_id=v.scope.environment_id,
            artifact_hash=v.scope.artifact_hash, inventory_hash=v.scope.inventory_hash, require_work=lambda: None)
        receipt = v.journal.verifier.verify(command, execution, environment_id=v.scope.environment_id,
            inventory_hash=v.scope.inventory_hash)
        ref, digest = artifacts.put(parent, v.scope, phase, command, execution)
        return execution, receipt, {"receipt_digest": acceptance_digest(receipt), "status": execution.result.status,
            "artifact_ref": ref, "artifact_hash": digest}

    setup_output, receipt, setup_pin = archived("setup", setup)
    [(phase, cleanup)] = v.journal.access.cleanup_commands_from_receipt(v.scope, receipt)
    cleanup_output, _, cleanup_pin = archived(phase, cleanup)
    pins = {"setup": (setup, setup_pin), phase: (cleanup, cleanup_pin)}
    def records(_session, bound_parent, scope, name, command):
        assert bound_parent == parent and scope == v.scope and command == pins[name][0]
        return {"phase": name}, deepcopy(pins[name][1])

    monkeypatch.setattr(v.journal, "_records", records)
    with readonly_transactions():
        original = tuple((name, v.journal.inspect(v.scope, name, read_only=True, require_current=lambda: None))
            for name in ("setup", phase))
        grouped = v.journal.inspect_cleanup_history(v.scope, require_current=lambda: None)
    assert original == grouped
    assert [record.execution for _, record in grouped] == [setup_output, cleanup_output]
    assert len(runner.commands) == 2

    storage.put_bytes(artifacts._key(v.scope.project_id, cleanup_pin["artifact_hash"]), b"damaged test archive",
        content_type="application/json")
    with readonly_transactions(), pytest.raises(HttpFixtureInvalid, match="cannot be verified"):
        v.journal.inspect_cleanup_history(v.scope, require_current=lambda: None)
    assert len(runner.commands) == 2


@pytest.mark.parametrize("revocation", ["actor_disabled", "project_role_revoked",
    "project_role_downgraded", "platform_role_downgraded"])
def test_worker_actor_fence_rechecks_committed_revocation_in_the_same_readonly_session(actor_journal, revocation):
    v = actor_journal
    if revocation == "platform_role_downgraded":
        with session_scope() as writer:
            writer.get(UserIdentityRecord, v.actor_id).role = "platform_admin"
            writer.scalar(select(ProjectRoleBindingRecord).where(
                ProjectRoleBindingRecord.user_id == v.actor_id)).role = "qa_lead"
    with session_scope() as reader:
        reader.execute(text("SET TRANSACTION READ ONLY"))
        reader.execute(text("SET LOCAL lock_timeout = '100ms'"))
        assert reader.scalar(text("SHOW transaction_isolation")) == "read committed"
        # Hold ORM identities so a fresh SELECT cannot rely on weak-map eviction.
        actor = reader.get(UserIdentityRecord, v.actor_id)
        role = reader.scalar(select(ProjectRoleBindingRecord).where(
            ProjectRoleBindingRecord.user_id == v.actor_id))
        PostgresHttpFixtureWorkRepository._actor_current(reader, v.scope.project_id, v.actor_id)
        with session_scope() as writer:
            if revocation == "actor_disabled":
                writer.get(UserIdentityRecord, v.actor_id).status = "disabled"
            elif revocation == "platform_role_downgraded":
                writer.get(UserIdentityRecord, v.actor_id).role = "qa_lead"
            else:
                binding = writer.get(ProjectRoleBindingRecord, role.binding_id)
                if revocation == "project_role_revoked":
                    binding.status = "revoked"
                else:
                    binding.role = "qa_lead"
        assert actor.status == "active" and role.status == "active"
        with pytest.raises(PermissionError):
            PostgresHttpFixtureWorkRepository._actor_current(reader, v.scope.project_id, v.actor_id)


@pytest.mark.parametrize("lock", [False, True])
@pytest.mark.parametrize("revocation", ["actor_disabled", "project_role_revoked",
    "project_role_downgraded", "platform_role_downgraded"])
def test_native_actor_fence_refreshes_retained_identities_before_its_original_lock(actor_journal, lock, revocation):
    v = actor_journal
    if revocation == "platform_role_downgraded":
        with session_scope() as writer:
            writer.get(UserIdentityRecord, v.actor_id).role = "platform_admin"
            writer.scalar(select(ProjectRoleBindingRecord).where(
                ProjectRoleBindingRecord.user_id == v.actor_id)).role = "qa_lead"
    with session_scope() as reader:
        if not lock:
            reader.execute(text("SET TRANSACTION READ ONLY"))
        reader.execute(text("SET LOCAL lock_timeout = '100ms'"))
        assert reader.scalar(text("SHOW transaction_isolation")) == "read committed"
        actor = reader.get(UserIdentityRecord, v.actor_id)
        role = reader.scalar(select(ProjectRoleBindingRecord).where(
            ProjectRoleBindingRecord.user_id == v.actor_id))
        assert NativeBuildRepository._actor(reader, v.scope.project_id, v.actor_id, lock=False) is actor
        with session_scope() as writer:
            if revocation == "actor_disabled":
                writer.get(UserIdentityRecord, v.actor_id).status = "disabled"
            elif revocation == "platform_role_downgraded":
                writer.get(UserIdentityRecord, v.actor_id).role = "qa_lead"
            else:
                binding = writer.get(ProjectRoleBindingRecord, role.binding_id)
                if revocation == "project_role_revoked":
                    binding.status = "revoked"
                else:
                    binding.role = "qa_lead"
        assert actor.status == "active" and role.status == "active"
        with pytest.raises(PermissionError):
            NativeBuildRepository._actor(reader, v.scope.project_id, v.actor_id, lock=lock)


@pytest.mark.parametrize("lock", [False, True])
@pytest.mark.parametrize("entity", ["account", "project_role"])
def test_native_actor_fence_preserves_the_exact_original_row_lock_contract(actor_journal, lock, entity):
    v = actor_journal
    query = (select(UserIdentityRecord).where(UserIdentityRecord.user_id == v.actor_id) if entity == "account" else
        select(ProjectRoleBindingRecord).where(ProjectRoleBindingRecord.user_id == v.actor_id))
    with session_scope() as owner:
        if not lock:
            owner.execute(text("SET TRANSACTION READ ONLY"))
        actor = NativeBuildRepository._actor(owner, v.scope.project_id, v.actor_id, lock=lock)
        assert actor.status == "active"
        if lock:
            with pytest.raises(OperationalError) as raised:
                with session_scope() as competitor:
                    competitor.scalar(query.with_for_update(nowait=True))
            assert raised.value.orig.sqlstate == "55P03"
        else:
            with session_scope() as competitor:
                assert competitor.scalar(query.with_for_update(nowait=True)) is not None
    with session_scope() as competitor:
        assert competitor.scalar(query.with_for_update(nowait=True)) is not None
