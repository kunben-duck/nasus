from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
from threading import Barrier

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import delete, event, func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from apps.api.app.domain.system_image.source_access import SourceAccessRule, StaleSourceAccessScope
from apps.api.app.infrastructure.persistence import source_access_repository as module
from apps.api.app.infrastructure.persistence.source_access_models import (
    SourceAccessEpochRecord, SourceAccessPolicyHeadRecord, SourceAccessPolicyRevisionRecord,
)
from apps.api.app.infrastructure.persistence.db_models import ProjectRecord, ProjectRoleBindingRecord, SSEEventOutboxRecord
from apps.api.tests.test_source_snapshot_repository import pg_repo, source


@pytest.fixture
def access_repo(pg_repo, monkeypatch):
    snapshots, sessions = pg_repo
    path = Path(__file__).resolve().parents[1] / "migrations/versions/0035_source_access.py"
    spec = importlib.util.spec_from_file_location("source_access_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with sessions.kw["bind"].begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()

    @contextmanager
    def session_scope():
        with sessions.begin() as session:
            yield session

    monkeypatch.setattr(module, "session_scope", session_scope)
    snapshots.register_bindings("project", [source(source_id="public"), source(source_id="private")])
    repo = module.SourceAccessRepository()
    yield repo, snapshots, sessions
    with sessions.kw["bind"].begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.downgrade()


def binding(repo, source_id="private"):
    return next(item.binding_id for item in repo.load_snapshot("project").bindings if item.source_id == source_id)


def restrict(repo, binding_id=None, expected_epoch=0, readers=("reader",)):
    return repo.set_policy("project", binding_id or binding(repo), SourceAccessRule("restricted", readers),
                           expected_epoch=expected_epoch, changed_by="admin", invocation_id="tool-1")


def test_default_idempotent_policies_and_atomic_epoch_history(access_repo):
    repo, snapshots, sessions = access_repo
    target = binding(repo)
    assert repo.load_snapshot("empty").acl_epoch == 0
    original = repo.load_snapshot("project").for_actor("other", "viewer")
    assert original.source_ids == {"public", "private"}
    assert repo.set_policy("project", target, SourceAccessRule(), expected_epoch=0,
                           changed_by="admin", invocation_id="tool-default") == 0
    assert restrict(repo, target) == 1
    assert restrict(repo, target, expected_epoch=1) == 1
    assert repo.load_snapshot("project").for_actor("other", "viewer").source_ids == {"public"}
    assert repo.load_snapshot("project").for_actor("reader", "viewer").source_ids == {"public", "private"}
    with pytest.raises(StaleSourceAccessScope):
        restrict(repo, target, expected_epoch=0)
    assert repo.set_policy("project", target, SourceAccessRule(), expected_epoch=1,
                           changed_by="admin", invocation_id="tool-2") == 2
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(SourceAccessPolicyRevisionRecord)) == 2
        events = session.scalars(select(SSEEventOutboxRecord)).all()
        assert len(events) == 2
        serialized = json.dumps([item.event_payload for item in events])
        assert "reader" not in serialized and target not in serialized and '"private"' not in serialized
    before = repo.load_snapshot("project").for_actor("reader", "viewer")
    snapshots.register_bindings("project", [source(source_id="new")])
    after = repo.load_snapshot("project").for_actor("reader", "viewer")
    assert before.acl_epoch == after.acl_epoch and before.fingerprint != after.fingerprint


def test_foreign_binding_rejected_and_head_composite_fk_cannot_cross_project(access_repo):
    repo, snapshots, sessions = access_repo
    snapshots.register_bindings("other", [source(project="other")])
    foreign = repo.load_snapshot("other").bindings[0].binding_id
    with pytest.raises(KeyError):
        restrict(repo, foreign)
    restrict(repo)
    with sessions() as session:
        revision = session.scalars(select(SourceAccessPolicyRevisionRecord)).one()
        revision_id = revision.policy_revision_id
    with pytest.raises(IntegrityError):
        with sessions.begin() as session:
            session.add(SourceAccessPolicyHeadRecord(binding_id=foreign, project_id="other", policy_revision_id=revision_id))
    assert repo.load_snapshot("other").acl_epoch == 0


def test_outbox_failure_rolls_back_policy_head_and_epoch(access_repo, monkeypatch):
    repo, _, sessions = access_repo
    def fail(*args, **kwargs):
        raise RuntimeError("outbox unavailable")
    monkeypatch.setattr(module.EventOutboxRepository, "append", fail)
    with pytest.raises(RuntimeError, match="outbox unavailable"):
        restrict(repo)
    assert repo.load_snapshot("project").acl_epoch == 0
    with sessions() as session:
        for model in (SourceAccessEpochRecord, SourceAccessPolicyHeadRecord, SourceAccessPolicyRevisionRecord):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_concurrent_policy_cas_has_one_winner(access_repo):
    repo, _, sessions = access_repo
    target, barrier = binding(repo), Barrier(2)
    def change(reader):
        barrier.wait(timeout=10)
        try:
            return restrict(repo, target, readers=(reader,))
        except StaleSourceAccessScope:
            return "stale"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(change, ("a", "b")), key=str) == [1, "stale"]
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(SourceAccessPolicyRevisionRecord)) == 1
        assert session.scalar(select(func.count()).select_from(SSEEventOutboxRecord)) == 1


@pytest.mark.parametrize("statement", [
    update(SourceAccessPolicyRevisionRecord).values(visibility="project"), delete(SourceAccessPolicyRevisionRecord),
    update(SourceAccessEpochRecord).values(acl_epoch=0), delete(SourceAccessEpochRecord),
])
def test_policy_history_and_monotonic_epoch_are_database_enforced(access_repo, statement):
    repo, _, _ = access_repo
    restrict(repo)
    with pytest.raises(IntegrityError):
        with access_repo[2].begin() as session:
            session.execute(statement)


def test_scope_inventory_and_policy_are_read_in_one_statement(access_repo):
    repo, _, sessions = access_repo
    statements = []
    def record(conn, cursor, statement, params, context, executemany):
        statements.append(statement)
    engine = sessions.kw["bind"]
    event.listen(engine, "before_cursor_execute", record)
    try:
        assert repo.load_snapshot("project").bindings
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert len(statements) == 1
    assert all(table in statements[0] for table in ("source_access_epochs", "source_access_policy_heads", "source_bindings"))


@pytest.fixture
def authorized_repo(access_repo):
    repo, snapshots, sessions = access_repo
    with sessions.kw["bind"].begin() as conn:
        ProjectRecord.__table__.create(conn)
        ProjectRoleBindingRecord.__table__.create(conn)
    with sessions.begin() as session:
        for project_id in ("project", "empty", "other"):
            session.add(ProjectRecord(id=project_id, name=project_id, code="FIX", summary="Fixture"))
        session.add(ProjectRoleBindingRecord(binding_id="membership", project_id="project", user_id="reader",
            role="viewer", scope_key="project:project", scope_ref="project:project", status="active",
            created_at="2026-09-19", updated_at="2026-09-19", created_by="admin"))
    return repo, snapshots, sessions


def test_authorized_scope_is_one_fresh_mvcc_statement(authorized_repo):
    repo, _, sessions = authorized_repo
    restrict(repo)
    expected = repo.load_snapshot("project")
    statements = []
    def record(conn, cursor, statement, params, context, executemany):
        statements.append(statement)
    engine = sessions.kw["bind"]
    event.listen(engine, "before_cursor_execute", record)
    try:
        snapshot, role = repo.load_authorized_snapshot("project", "reader", platform_administrator=False)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert (snapshot, role) == (expected, "viewer")
    assert snapshot.for_actor("reader", role).source_ids == {"public", "private"}
    assert len(statements) == 1
    assert all(table in statements[0] for table in ("projects", "project_role_bindings",
        "source_access_epochs", "source_access_policy_heads", "source_bindings"))
    assert repo.load_authorized_snapshot("project", "outsider", platform_administrator=False)[1] is None
    admin, role = repo.load_authorized_snapshot("project", "admin", platform_administrator=True)
    assert role == "platform_admin" and admin.for_actor("admin", role).binding_ids == snapshot.for_actor("reader", "viewer").binding_ids
    assert repo.load_authorized_snapshot("empty", "admin", platform_administrator=True)[0].bindings == ()
    assert repo.load_authorized_snapshot("other", "reader", platform_administrator=False)[1] is None
    with pytest.raises(KeyError):
        repo.load_authorized_snapshot("missing", "admin", platform_administrator=True)


def test_authorized_scope_observes_role_revocation_policies_and_new_bindings(authorized_repo):
    repo, snapshots, sessions = authorized_repo
    first, role = repo.load_authorized_snapshot("project", "reader", platform_administrator=False)
    with sessions.begin() as session:
        session.get(ProjectRoleBindingRecord, "membership").role = "qa_lead"
    second, changed_role = repo.load_authorized_snapshot("project", "reader", platform_administrator=False)
    assert changed_role == "qa_lead"
    assert second.for_actor("reader", changed_role).fingerprint != first.for_actor("reader", role).fingerprint
    restrict(repo, readers=())
    restricted, role = repo.load_authorized_snapshot("project", "reader", platform_administrator=False)
    assert restricted.for_actor("reader", role).source_ids == {"public"}
    snapshots.register_bindings("project", [source(source_id="new")])
    expanded, role = repo.load_authorized_snapshot("project", "reader", platform_administrator=False)
    assert expanded.acl_epoch == restricted.acl_epoch
    assert expanded.for_actor("reader", role).source_ids == {"public", "new"}
    assert expanded.for_actor("reader", role).fingerprint != restricted.for_actor("reader", role).fingerprint
    with sessions.begin() as session:
        session.get(ProjectRoleBindingRecord, "membership").status = "revoked"
    assert repo.load_authorized_snapshot("project", "reader", platform_administrator=False)[1] is None


def test_authorized_cohort_is_one_mvcc_statement_with_project_membership_and_policy(authorized_repo):
    repo, snapshots, sessions = authorized_repo
    snapshots.register_bindings("other", [source(source_id="other-private", project="other")])
    restrict(repo)
    with sessions.begin() as session:
        session.add(ProjectRoleBindingRecord(binding_id="other-membership", project_id="other", user_id="reader",
            role="tester", scope_key="project:other", scope_ref="project:other", status="active",
            created_at="2026-10-09", updated_at="2026-10-09", created_by="admin"))
    expected = {ident: repo.load_authorized_snapshot(ident, "reader", platform_administrator=False)
        for ident in ("project", "other", "empty")}
    statements = []
    engine = sessions.kw["bind"]

    def record(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        actual = repo.load_authorized_snapshots(("project", "other", "empty"), "reader", platform_administrator=False)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert actual == expected and len(statements) == 1
    assert "UNION ALL" in statements[0] and "project_role_bindings" in statements[0]
    assert actual["empty"][0].bindings == () and actual["empty"][1] is None
    with sessions.begin() as session:
        session.get(ProjectRoleBindingRecord, "other-membership").status = "revoked"
    restrict(repo, expected_epoch=1, readers=())
    changed = repo.load_authorized_snapshots(("project", "other", "empty"), "reader", platform_administrator=False)
    assert changed["project"][0].for_actor("reader", "viewer").source_ids == {"public"}
    assert changed["other"][1] is None
    assert changed["project"][0].acl_epoch != actual["project"][0].acl_epoch
    assert "missing" not in repo.load_authorized_snapshots(("project", "missing"), "reader", platform_administrator=False)
    administrator = repo.load_authorized_snapshots(("project", "other", "empty"), "admin", platform_administrator=True)
    assert all(role == "platform_admin" for _, role in administrator.values())


@pytest.mark.parametrize("project_ids", [(), [], ("project", "project"), (None,), ("",),
    tuple(f"project-{index}" for index in range(129))])
def test_authorized_cohort_rejects_invalid_inventory_before_sql(authorized_repo, monkeypatch, project_ids):
    repo, _, _ = authorized_repo
    monkeypatch.setattr(module, "session_scope", lambda: pytest.fail("invalid cohort must not acquire a connection"))
    with pytest.raises(ValueError):
        repo.load_authorized_snapshots(project_ids, "reader", platform_administrator=False)


@pytest.mark.parametrize("scoped_field", ["version_id", "session_id"])
def test_narrow_membership_cannot_grant_project_source_scope(authorized_repo, scoped_field):
    repo, _, sessions = authorized_repo
    with sessions.begin() as session:
        setattr(session.get(ProjectRoleBindingRecord, "membership"), scoped_field, "narrow-scope")
    assert repo.load_authorized_snapshot("project", "reader", platform_administrator=False)[1] is None


def test_ambiguous_membership_is_not_resolved_to_an_arbitrary_role(authorized_repo):
    repo, _, sessions = authorized_repo
    with sessions.begin() as session:
        session.add(ProjectRoleBindingRecord(binding_id="duplicate", project_id="project", user_id="reader",
            role="project_admin", scope_key="malformed-duplicate", scope_ref="project:project", status="active",
            created_at="2026-09-19", updated_at="2026-09-19", created_by="admin"))
    with pytest.raises(DBAPIError):
        repo.load_authorized_snapshot("project", "reader", platform_administrator=False)


def test_one_live_read_connection_observes_every_intervening_permission_commit(authorized_repo, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from apps.api.app.infrastructure.persistence import source_access_read_session as live
    repo, snapshots, sessions = authorized_repo
    dedicated = create_engine(sessions.kw["bind"].url, isolation_level="READ COMMITTED",
                              pool_size=1, max_overflow=0, future=True)
    monkeypatch.setattr(live, "_session_factory", lambda: sessionmaker(bind=dedicated, autoflush=False, future=True))
    checkouts, statements = [], []
    event.listen(dedicated, "checkout", lambda *args: checkouts.append(1))
    event.listen(dedicated, "before_cursor_execute", lambda conn, cursor, statement, *args: statements.append(statement))
    try:
        with repo.live_read_session() as connection:
            assert connection.scalar(text("SHOW transaction_isolation")) == "read committed"
            assert connection.scalar(text("SHOW transaction_read_only")) == "on"
            original, role = repo.load_authorized_snapshot("project", "reader", platform_administrator=False)
            assert role == "viewer"
            with sessions.begin() as writer:
                writer.get(ProjectRoleBindingRecord, "membership").role = "qa_lead"
            changed, role = repo.load_authorized_snapshot("project", "reader", platform_administrator=False)
            assert role == "qa_lead"
            assert changed.for_actor("reader", role).fingerprint != original.for_actor("reader", "viewer").fingerprint
            restrict(repo, readers=())
            restricted, role = repo.load_authorized_snapshot("project", "reader", platform_administrator=False)
            assert restricted.for_actor("reader", role).source_ids == {"public"}
            snapshots.register_bindings("project", [source(source_id="new")])
            with repo.live_read_session() as nested:
                assert nested is connection
                expanded, role = repo.load_authorized_snapshot("project", "reader", platform_administrator=False)
            assert expanded.acl_epoch == restricted.acl_epoch
            assert expanded.for_actor("reader", role).source_ids == {"public", "new"}
            assert expanded.for_actor("reader", role).fingerprint != restricted.for_actor("reader", role).fingerprint
            with sessions.begin() as writer:
                writer.get(ProjectRoleBindingRecord, "membership").status = "revoked"
            assert repo.load_authorized_snapshot("project", "reader", platform_administrator=False)[1] is None
            # A different actor/project on the same transport still has an
            # independent SQL scope; neither identity inherits the last result.
            assert repo.load_authorized_snapshot("other", "reader", platform_administrator=False)[1] is None
            assert repo.load_authorized_snapshot("project", "admin", platform_administrator=True)[1] == "platform_admin"
        assert len(checkouts) == 1
        assert len([statement for statement in statements if "source_access_epochs" in statement]) == 7
        assert live.current_source_access_read_session() is None
        assert dedicated.pool.checkedout() == 0
        repo.load_authorized_snapshot("project", "reader", platform_administrator=False)
        assert len(checkouts) == 1
    finally:
        dedicated.dispose()


def test_live_permission_transaction_cannot_write_business_facts(authorized_repo, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from apps.api.app.infrastructure.persistence import source_access_read_session as live
    repo, _, sessions = authorized_repo
    dedicated = create_engine(sessions.kw["bind"].url, isolation_level="READ COMMITTED", future=True)
    monkeypatch.setattr(live, "_session_factory", lambda: sessionmaker(bind=dedicated, autoflush=False, future=True))
    try:
        with pytest.raises(DBAPIError, match="read-only"):
            with repo.live_read_session() as session:
                session.execute(update(ProjectRoleBindingRecord).values(role="platform_admin"))
        assert live.current_source_access_read_session() is None and dedicated.pool.checkedout() == 0
        assert repo.load_authorized_snapshot("project", "reader", platform_administrator=False)[1] == "viewer"
    finally:
        dedicated.dispose()
