"""Rollback-only migration probes must preserve downstream tables and facts."""
from sqlalchemy import inspect


def foreign_key_inventory(connection, *, schema=None):
    inspector = inspect(connection)
    return {
        table: tuple(sorted((
            fk["name"], tuple(fk["constrained_columns"]), fk["referred_schema"],
            fk["referred_table"], tuple(fk["referred_columns"]),
            tuple(sorted(fk.get("options", {}).items())),
        ) for fk in inspector.get_foreign_keys(table, schema=schema)))
        for table in inspector.get_table_names(schema=schema)
    }


def detach_downstream_foreign_keys(connection, operations, rebuilt_tables):
    if connection.dialect.name != "postgresql" or not connection.in_transaction():
        raise AssertionError("migration rehearsal requires an explicit PostgreSQL transaction")
    database = connection.engine.url.database
    if (type(database) is not str or not database.startswith("nasus_test_")
            or len(database) <= len("nasus_test_")):
        raise AssertionError("migration rehearsal requires an isolated nasus_test_ database")
    targets = frozenset(rebuilt_tables)
    if not targets:
        raise AssertionError("migration rehearsal requires explicit rebuilt tables")
    inspector = inspect(connection)
    inventory = foreign_key_inventory(connection)
    if not targets <= inventory.keys():
        raise AssertionError("migration rehearsal target table is missing")
    detached = []
    for table, foreign_keys in sorted(inventory.items()):
        if table in targets:
            continue
        for name, _, schema, referred_table, _, _ in foreign_keys:
            if referred_table in targets and schema in (None, inspector.default_schema_name):
                if not name:
                    raise AssertionError("migration rehearsal requires named downstream constraints")
                detached.append((table, name))
    # Validate the full plan before issuing DDL; never drop downstream tables.
    for table, name in detached:
        operations.drop_constraint(name, table, type_="foreignkey")
    return tuple(detached)
