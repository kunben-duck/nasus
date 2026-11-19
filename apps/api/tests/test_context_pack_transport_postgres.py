"""Real single-operation transport reuse with unchanged PG and archive reads."""
from collections import Counter
from contextlib import nullcontext
import os
from statistics import median
from time import perf_counter

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.main import app
from apps.api.tests.test_context_packs_api import acceptance, documents, evidence_api, approve, archive, completed
from apps.api.tests.test_http_fixture_actor_reads_postgres import readonly_transactions


pytestmark = pytest.mark.skipif(os.getenv("NASUS_TEST_OBJECT_STORAGE_MODE") != "minio",
    reason="requires disposable PostgreSQL/MinIO through test-api-postgres.py --minio")


@pytest.fixture(autouse=True)
def isolated_storage_only():
    assert engine.dialect.name == "postgresql" and engine.url.database.startswith("nasus_test_")
    with session_scope() as session:
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
    storage = app.state.container.context_packs.artifacts.storage
    assert storage.config.s3_enabled and storage.config.bucket.startswith("nasus-test-")


def test_context_read_reuses_one_client_without_reducing_sql_or_original_gets(acceptance, monkeypatch):
    v = acceptance
    completed(approve(v))
    done = completed(archive(v)[0])
    context_id = done["result"]["object_refs"][0].split(":", 1)[1]
    service = app.state.container.context_packs
    storage = service.artifacts.storage
    clients, closed, gets, statements, client_times = [], [], [], [], []
    create, get = storage._create_s3_client, storage.get_bytes

    def create_client(config):
        started = perf_counter()
        client = create(config)
        client_times.append(perf_counter() - started)
        clients.append(client)
        close = client.close

        def close_client():
            closed.append(client)
            close()

        client.close = close_client
        return client

    def read_bytes(ref, **kwargs):
        gets.append((ref, kwargs))
        return get(ref, **kwargs)

    def executed(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    monkeypatch.setattr(storage, "_create_s3_client", create_client)
    monkeypatch.setattr(storage, "get_bytes", read_bytes)

    def measure():
        clients.clear()
        closed.clear()
        gets.clear()
        statements.clear()
        client_times.clear()
        started = perf_counter()
        result = service.read(v["project_id"], context_id)
        elapsed = perf_counter() - started
        assert closed == clients and len({id(client) for client in closed}) == len(closed)
        assert storage._read_clients.get() is None
        return result, clients[:], gets[:], Counter(statements), elapsed, sum(client_times)

    event.listen(Engine, "before_cursor_execute", executed)
    try:
        with actor_scope(UserProfile.model_validate(v["owner"])), readonly_transactions():
            with monkeypatch.context() as baseline:
                baseline.setattr(service.artifacts, "read_session", nullcontext)
                expected, old_clients, old_gets, old_sql, old_time, old_init = measure()
            actual, new_clients, new_gets, new_sql, new_time, new_init = measure()
            again, next_clients, next_gets, next_sql, _, _ = measure()
            samples = {"before": [(old_time, old_init)], "after": [(new_time, new_init)]}
            # Alternate order; timings are diagnostic, not a flaky wall-clock gate.
            for mode in ("after", "before", "before", "after"):
                with monkeypatch.context() as comparison:
                    if mode == "before":
                        comparison.setattr(service.artifacts, "read_session", nullcontext)
                    result, transports, originals, queries, elapsed, initialization = measure()
                assert result == expected and originals == old_gets and queries == old_sql
                assert len(transports) == (len(old_clients) if mode == "before" else 1)
                samples[mode].append((elapsed, initialization))
    finally:
        event.remove(Engine, "before_cursor_execute", executed)

    assert actual == again == expected
    assert len(old_clients) >= 3 and len(new_clients) == len(next_clients) == 1
    assert new_clients[0] is not next_clients[0]
    assert old_gets == new_gets == next_gets and len(new_gets) > 1
    assert old_sql == new_sql == next_sql
    assert any("source_access_policy" in sql for sql in old_sql)
    assert any("object_provenance" in sql for sql in old_sql)
    print(f"context transport: clients {len(old_clients)} -> {len(new_clients)}; "
        f"unchanged GETs={len(new_gets)}, SQL={sum(new_sql.values())}; "
        f"median read seconds {median(t[0] for t in samples['before']):.3f} -> "
        f"{median(t[0] for t in samples['after']):.3f}; "
        f"median client-init seconds {median(t[1] for t in samples['before']):.3f} -> "
        f"{median(t[1] for t in samples['after']):.3f}")
