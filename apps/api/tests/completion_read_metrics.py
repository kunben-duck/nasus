"""Compare complete replays without caching bytes or weakening authorization."""
from collections import Counter
from contextlib import nullcontext
from time import perf_counter

from sqlalchemy import event

from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence import source_access_read_session as live
from apps.api.app.main import app


def compare_completion_replays(v, url, expected, monkeypatch):
    authorization = app.state.container.investigations.plans.authorization
    storage = app.state.container.source_deltas.reader.archive.storage
    access_engine = live._session_factory().kw["bind"]
    assert engine.dialect.name == "postgresql" and access_engine is not engine
    original_get = storage.get_bytes

    def measure(reuse):
        counts = {"business": Counter(), "live": Counter()}
        objects, sizes, listeners = Counter(), Counter(), []

        def observe_statement(label):
            def observe(_connection, _cursor, statement, _parameters, _context, _many):
                if "source_access_epochs" in statement and "source_access_policy_heads" in statement:
                    counts[label]["authorization_queries"] += 1
                if statement == "SET TRANSACTION READ ONLY":
                    counts[label]["read_only_setups"] += 1
                if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
                    compiled = getattr(_context, "compiled", None)
                    table = getattr(getattr(compiled, "statement", None), "table", None)
                    bookkeeping = label == "business" and getattr(table, "name", None) in {
                        "access_sessions", "api_rate_limit_windows"}
                    counts[label]["platform_bookkeeping_writes" if bookkeeping else "fact_writes"] += 1
            return observe

        def record(label, name):
            def observe(*_args):
                counts[label][name] += 1
            return observe

        def read(ref, **options):
            body = original_get(ref, **options)
            objects[ref] += 1
            sizes[ref] += len(body)
            return body

        try:
            for label, binding in (("business", engine), ("live", access_engine)):
                for name in ("checkout", "begin", "commit", "rollback", "before_cursor_execute"):
                    callback = observe_statement(label) if name == "before_cursor_execute" else record(label, name)
                    event.listen(binding, name, callback)
                    listeners.append((binding, name, callback))
            with monkeypatch.context() as scoped:
                scoped.setattr(storage, "get_bytes", read)
                if not reuse:
                    scoped.setattr(authorization, "live_read_session", nullcontext)
                started = perf_counter()
                response = v["client"].get(url, headers=v["headers"])
                seconds = perf_counter() - started
            assert response.status_code == 200, response.text
            assert response.headers["cache-control"] == "private, no-store"
            assert response.json() == expected
        finally:
            for binding, name, callback in reversed(listeners):
                event.remove(binding, name, callback)
        assert live.current_source_access_read_session() is None
        assert access_engine.pool.checkedout() == 0
        assert sum(value["fact_writes"] for value in counts.values()) == 0
        metrics = {"connection_reuse": reuse, "elapsed_seconds": round(seconds, 6),
            "connections": {label: dict(value) for label, value in counts.items()},
            "authorization_queries": sum(value["authorization_queries"] for value in counts.values()),
            "object_reads": sum(objects.values()), "returned_bytes": sum(sizes.values()),
            "source_body_reads": sum(count for ref, count in objects.items() if "/files/" in ref),
            "object_read_inventory_hash": snapshot_digest(sorted((ref, count, sizes[ref]) for ref, count in objects.items()))}
        return metrics, (objects, sizes, response.content)

    control, control_reads = measure(False)
    optimized, optimized_reads = measure(True)
    assert control_reads == optimized_reads
    assert control["authorization_queries"] == optimized["authorization_queries"]
    assert optimized["connections"]["live"]["authorization_queries"] >= sum(scan["file_count"] for scan in expected["source_scans"])
    assert optimized["connections"]["live"]["checkout"] == optimized["connections"]["live"]["begin"] == 1
    assert optimized["connections"]["live"]["read_only_setups"] == optimized["connections"]["live"]["rollback"] == 1
    assert optimized["connections"]["live"].get("commit", 0) == 0
    assert not control["connections"]["live"]
    assert control["connections"]["business"]["checkout"] > optimized["connections"]["business"]["checkout"]
    return {"control": control, "optimized": optimized,
        "reports_identical": True, "fresh_authorization_query_count_unchanged": True,
        "raw_read_inventory_unchanged": True, "fact_writes": 0, "capacity_or_p95_acceptance": False}
