"""Connection specimens prove rejection before any inspection or DDL, not PG persistence."""
from types import SimpleNamespace

import pytest

from apps.api.tests import migration_rehearsal


@pytest.mark.parametrize("database", ["nasus", "postgres", "nasus_test_", "", None, True])
def test_rehearsal_rejects_nonisolated_database_before_any_inspection(database, monkeypatch):
    inspected = []
    def forbidden_inspection(connection):
        inspected.append(connection)
        raise AssertionError("nonisolated rehearsal must fail before inspection")
    monkeypatch.setattr(migration_rehearsal, "inspect", forbidden_inspection)
    connection = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"),
        in_transaction=lambda: True, engine=SimpleNamespace(url=SimpleNamespace(database=database)))
    with pytest.raises(AssertionError, match="isolated nasus_test_ database"):
        migration_rehearsal.detach_downstream_foreign_keys(connection, None, ("original_parent",))
    assert not inspected


@pytest.mark.parametrize("dialect,in_transaction", [("sqlite", True), ("postgresql", False)])
def test_rehearsal_rejects_wrong_transaction_before_database_or_ddl_access(dialect, in_transaction):
    connection = SimpleNamespace(dialect=SimpleNamespace(name=dialect), in_transaction=lambda: in_transaction)
    with pytest.raises(AssertionError, match="explicit PostgreSQL transaction"):
        migration_rehearsal.detach_downstream_foreign_keys(connection, None, ("original_parent",))
