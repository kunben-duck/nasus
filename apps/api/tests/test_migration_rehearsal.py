"""Real PostgreSQL probes, with no application or developer data mutation."""
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import Column, ForeignKeyConstraint, Integer, MetaData, Table, insert, select, text
from sqlalchemy.exc import IntegrityError

from apps.api.app.infrastructure.persistence.database import engine
from apps.api.tests.migration_rehearsal import detach_downstream_foreign_keys, foreign_key_inventory


class RollbackProbe(Exception):
    pass


def test_rehearsal_preserves_populated_downstream_tables_and_restores_all_constraints():
    assert engine.url.get_backend_name() == "postgresql"
    assert engine.url.database.startswith("nasus_test_")
    suffix = uuid4().hex
    metadata = MetaData()
    parent = Table("rehearsal_parent_" + suffix, metadata, Column("id", Integer, primary_key=True))
    unrelated = Table("rehearsal_other_" + suffix, metadata, Column("id", Integer, primary_key=True))
    child = Table("rehearsal_child_" + suffix, metadata,
        Column("id", Integer, primary_key=True), Column("parent_id", Integer, nullable=False),
        Column("other_id", Integer, nullable=False),
        ForeignKeyConstraint(["parent_id"], [parent.c.id], name="rehearsal_parent_fk_" + suffix),
        ForeignKeyConstraint(["other_id"], [unrelated.c.id], name="rehearsal_other_fk_" + suffix))
    grandchild = Table("rehearsal_grandchild_" + suffix, metadata,
        Column("id", Integer, primary_key=True), Column("child_id", Integer, nullable=False),
        ForeignKeyConstraint(["child_id"], [child.c.id], name="rehearsal_child_fk_" + suffix))
    with pytest.raises(RollbackProbe), engine.begin() as connection:
        metadata.create_all(connection)
        for table, values in ((parent, {"id": 1}), (unrelated, {"id": 2}),
                (child, {"id": 3, "parent_id": 1, "other_id": 2}), (grandchild, {"id": 4, "child_id": 3})):
            connection.execute(insert(table).values(**values))
        before = foreign_key_inventory(connection)
        operations = Operations(MigrationContext.configure(connection))
        with pytest.raises(RollbackProbe), connection.begin_nested():
            detached = detach_downstream_foreign_keys(connection, operations, (parent.name,))
            assert detached == ((child.name, "rehearsal_parent_fk_" + suffix),)
            during = foreign_key_inventory(connection)
            assert during.keys() == before.keys()
            assert during[grandchild.name] == before[grandchild.name]
            assert len(during[child.name]) == 1
            assert during[child.name][0][0] == "rehearsal_other_fk_" + suffix
            operations.drop_table(parent.name)
            parent.create(connection)
            connection.execute(insert(parent).values(id=1))
            assert connection.execute(select(child)).one()._asdict() == {"id": 3, "parent_id": 1, "other_id": 2}
            assert connection.execute(select(grandchild)).one()._asdict() == {"id": 4, "child_id": 3}
            raise RollbackProbe()
        assert foreign_key_inventory(connection) == before
        assert connection.execute(select(child)).one()._asdict() == {"id": 3, "parent_id": 1, "other_id": 2}
        assert connection.execute(select(grandchild)).one()._asdict() == {"id": 4, "child_id": 3}
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(insert(child).values(id=5, parent_id=99, other_id=2))
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(insert(child).values(id=5, parent_id=1, other_id=99))
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(insert(grandchild).values(id=6, child_id=99))
        raise RollbackProbe()


@pytest.mark.parametrize("targets", [(), ("missing_rehearsal_table",)])
def test_rehearsal_rejects_invalid_targets_without_schema_changes(targets):
    assert engine.url.get_backend_name() == "postgresql"
    assert engine.url.database.startswith("nasus_test_")
    with engine.begin() as connection:
        before = foreign_key_inventory(connection)
        with pytest.raises(AssertionError):
            detach_downstream_foreign_keys(connection, Operations(MigrationContext.configure(connection)), targets)
        assert foreign_key_inventory(connection) == before


def test_rehearsal_rejects_connection_without_explicit_transaction():
    assert engine.url.get_backend_name() == "postgresql"
    assert engine.url.database.startswith("nasus_test_")
    with engine.connect() as connection:
        with pytest.raises(AssertionError, match="explicit PostgreSQL transaction"):
            detach_downstream_foreign_keys(connection, None, ("quality_automation_provenance",))


def test_named_schema_inventory_retains_exact_foreign_keys_and_leaves_public_unchanged():
    assert engine.url.get_backend_name() == "postgresql"
    assert engine.url.database.startswith("nasus_test_")
    namespace = "nasus_test_fk_inventory_" + uuid4().hex
    metadata = MetaData(schema=namespace)
    parent = Table("inventory_parent", metadata, Column("id", Integer, primary_key=True))
    child = Table("inventory_child", metadata, Column("id", Integer, primary_key=True),
        Column("parent_id", Integer, nullable=False),
        ForeignKeyConstraint(["parent_id"], [parent.c.id], name="inventory_parent_fk",
            deferrable=True, initially="DEFERRED"))
    with pytest.raises(RollbackProbe), engine.begin() as connection:
        public_before = foreign_key_inventory(connection)
        connection.execute(text(f'CREATE SCHEMA "{namespace}"'))
        metadata.create_all(connection)
        selected = foreign_key_inventory(connection, schema=namespace)
        assert selected == {"inventory_parent": (), "inventory_child": (("inventory_parent_fk",
            ("parent_id",), namespace, "inventory_parent", ("id",),
            (("deferrable", True), ("initially", "DEFERRED"))),)}
        assert foreign_key_inventory(connection) == public_before
        raise RollbackProbe()
