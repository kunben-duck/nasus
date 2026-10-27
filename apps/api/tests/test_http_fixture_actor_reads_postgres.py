"""Actual PG actor locks and read-only transactions; parent is an explicit specimen."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, select, text
from sqlalchemy.exc import OperationalError

from apps.api.app.infrastructure.persistence import http_fixture_journal_repository as journals
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import ProjectRoleBindingRecord, UserIdentityRecord
from apps.api.app.infrastructure.persistence.native_build_repository import NativeBuildRepository
from apps.api.app.infrastructure.persistence.http_fixture_work_repository import PostgresHttpFixtureWorkRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_http_fixture_journal_access import saved_inputs


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
def readonly_transactions():
    def begin(connection):
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        connection.exec_driver_sql("SET LOCAL lock_timeout = '100ms'")
    event.listen(engine, "begin", begin)
    try:
        yield
    finally:
        event.remove(engine, "begin", begin)


def test_readonly_history_checks_current_actor_without_reacquiring_an_owned_write_lock(actor_journal):
    v = actor_journal
    with session_scope() as writer:
        # Actual account and project-role locks on another PG connection.
        actor = NativeBuildRepository._actor(writer, v.scope.project_id, v.actor_id)
        assert actor.user_id == v.actor_id
        with readonly_transactions():
            assert v.journal.inspect(v.scope, "setup", read_only=True) is None
    assert len(v.observed) == 3 and v.observed[0] == v.observed[1] == v.observed[2]


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


@pytest.mark.parametrize("revocation", ["actor_disabled", "project_role_revoked", "project_role_downgraded"])
def test_readonly_history_rechecks_actor_after_its_original_record_read(actor_journal, monkeypatch, revocation):
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
    with pytest.raises(PermissionError):
        v.journal.inspect(v.scope, "setup", read_only=True)


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
