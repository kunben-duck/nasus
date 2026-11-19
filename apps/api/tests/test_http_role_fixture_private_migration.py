"""Rollback-only migration rehearsals inside disposable PostgreSQL schemas."""
from contextlib import contextmanager
import importlib
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from apps.api.tests.test_http_role_fixture_private_postgres import (
    Claim, Envelope, Result, canonical, digest, pg, state,
)


MIGRATION = importlib.import_module("apps.api.migrations.versions.0132_http_role_fixture_private_state")
MODELS = (Envelope, Claim, Result)


@contextmanager
def rehearsal(pg):
    namespace = "role_private_migration_" + uuid4().hex
    with pg[0].connect() as conn:
        transaction = conn.begin()
        try:
            assert conn.scalar(text("SELECT current_database()")).startswith("nasus_test_")
            conn.execute(text(f'CREATE SCHEMA "{namespace}"'))
            conn.execute(text(f'SET LOCAL search_path TO "{namespace}", public'))
            with Operations.context(MigrationContext.configure(conn)):
                yield conn, namespace
        finally:
            transaction.rollback()
    with pg[0].connect() as conn:
        assert not inspect(conn).has_schema(namespace)


def seed(conn, state, retained):
    if retained == "envelope":
        conn.execute(Envelope.__table__.insert().values(storage_key=state.key,
            envelope=state.envelope, content_hash=digest(state.envelope)))
        return
    claim_body = canonical({"schema": "nasus.private-http-role-fixture-claim.v1", "scope": state.scope.payload(),
        "manifest_hash": state.record.manifest_hash, "phase": "setup"})
    identity = dict(project_id=state.scope.project_id, batch_id=state.scope.batch_id,
        case_id=state.scope.case_id, phase="setup")
    conn.execute(Claim.__table__.insert().values(**identity, payload=claim_body, claim_hash=digest(claim_body)))
    if retained == "result":
        result_body = canonical({"schema": "nasus.private-http-role-fixture-result.v1", "claim_hash": digest(claim_body),
            "result": {"status": "unknown", "evidence_digest": state.result.evidence_digest, "resources": []}})
        conn.execute(Result.__table__.insert().values(**identity, claim_hash=digest(claim_body),
            payload=result_body, content_hash=digest(result_body)))


def test_revision_ids_fit_default_alembic_column_and_use_updated_parent():
    assert MIGRATION.revision == "0132_http_role_private_state" and len(MIGRATION.revision) <= 32
    assert MIGRATION.down_revision == "0131_execution_environment" and len(MIGRATION.down_revision) <= 32


def test_empty_upgrade_downgrade_upgrade_matches_models_and_rolls_back(pg):
    with rehearsal(pg) as (conn, namespace):
        before = {model.__tablename__: conn.scalar(text(f"SELECT count(*) FROM public.{model.__tablename__}"))
                  for model in MODELS}
        MIGRATION.upgrade()
        MIGRATION.downgrade()
        assert all(not inspect(conn).has_table(model.__tablename__, schema=namespace) for model in MODELS)
        MIGRATION.upgrade()
        inspector = inspect(conn)
        for model in MODELS:
            table = model.__table__
            columns = inspector.get_columns(table.name, schema=namespace)
            assert {column["name"] for column in columns} == set(table.columns.keys())
            assert all(not column["nullable"] for column in columns)
            assert set(inspector.get_pk_constraint(table.name, schema=namespace)["constrained_columns"]) == {
                column.name for column in table.primary_key.columns}
            assert {item["name"] for item in inspector.get_check_constraints(table.name, schema=namespace)} == {
                constraint.name for constraint in table.constraints if constraint.__class__.__name__ == "CheckConstraint"}
            actual_fk = inspector.get_foreign_keys(table.name, schema=namespace)
            assert len(actual_fk) == len(table.foreign_key_constraints)
            if model is Result:
                assert actual_fk[0]["constrained_columns"] == ["project_id", "batch_id", "case_id", "phase", "claim_hash"]
                assert actual_fk[0]["referred_table"] == Claim.__tablename__
                assert actual_fk[0]["referred_schema"] in (None, namespace)
            triggers = conn.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal "
                "AND tgrelid = CAST(:table AS regclass)"), {"table": namespace + "." + table.name}).scalars().all()
            assert set(triggers) == {"immutable_" + table.name, "retain_" + table.name}
        assert {model.__tablename__: conn.scalar(text(f"SELECT count(*) FROM public.{model.__tablename__}"))
                for model in MODELS} == before
        assert inspector.get_columns("alembic_version", schema="public")[0]["type"].length == 32


@pytest.mark.parametrize("retained", ["envelope", "claim", "result"])
def test_downgrade_refuses_retained_ciphertext_unknown_claims_and_results_without_partial_drop(pg, state, retained):
    with rehearsal(pg) as (conn, namespace):
        MIGRATION.upgrade()
        seed(conn, state, retained)
        before = {model.__tablename__: conn.scalar(text(f'SELECT count(*) FROM "{namespace}".{model.__tablename__}'))
                  for model in MODELS}
        with pytest.raises(RuntimeError, match="retained private HTTP role state"):
            MIGRATION.downgrade()
        assert all(inspect(conn).has_table(model.__tablename__, schema=namespace) for model in MODELS)
        assert {model.__tablename__: conn.scalar(text(f'SELECT count(*) FROM "{namespace}".{model.__tablename__}'))
                for model in MODELS} == before


@pytest.mark.parametrize("model,limit", [(Claim, 4096), (Result, 16384)])
def test_journal_payload_byte_limits_are_database_constraints(pg, state, model, limit):
    with rehearsal(pg) as (conn, _):
        MIGRATION.upgrade()
        if model is Result: seed(conn, state, "claim")
        claim_hash = conn.scalar(text("SELECT claim_hash FROM quality_http_role_fixture_claims LIMIT 1"))
        body = b"x" * (limit + 1)
        value = dict(project_id=state.scope.project_id, batch_id=state.scope.batch_id,
            case_id=state.scope.case_id, phase="setup", payload=body)
        if model is Claim: value["claim_hash"] = digest(body)
        else: value.update(claim_hash=claim_hash, content_hash=digest(body))
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(model.__table__.insert().values(**value))


def test_migration_failure_is_transactional_and_leaves_no_partial_tables_or_functions(pg):
    with rehearsal(pg) as (conn, namespace):
        with pytest.raises(RuntimeError, match="synthetic rollback"), conn.begin_nested():
            MIGRATION.upgrade()
            raise RuntimeError("synthetic rollback")
        assert all(not inspect(conn).has_table(model.__tablename__, schema=namespace) for model in MODELS)
        assert conn.scalar(text("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = :name"), {"name": namespace}) == 0
        MIGRATION.upgrade()
        MIGRATION.downgrade()
