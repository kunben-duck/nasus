"""Observe complete HTTP reads without caching facts or authorization."""
from collections import Counter
import hashlib
from math import ceil, isfinite
import re
from time import perf_counter

from sqlalchemy import event

from apps.api.app.domain.system_image.source_snapshots import snapshot_digest


def summarize_read_samples(samples):
    if type(samples) is not list or not 5 <= len(samples) <= 30:
        raise ValueError("read measurement requires 5..30 independent samples")
    for sample in samples:
        seconds = sample.get("elapsed_seconds") if type(sample) is dict else None
        if type(seconds) not in {int, float} or not isfinite(seconds) or seconds <= 0:
            raise ValueError("read measurement requires finite positive elapsed times")
        if sample.get("fact_writes") != 0 or type(sample.get("fact_writes")) is not int:
            raise ValueError("read measurement must not mutate business facts")
        if type(sample.get("response_hash")) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", sample["response_hash"]):
            raise ValueError("read measurement requires verified response identities")
    if len({sample["response_hash"] for sample in samples}) != 1:
        raise ValueError("read measurement cannot mix different responses")
    ordered = sorted(float(sample["elapsed_seconds"]) for sample in samples)
    return {"sample_count": len(samples), "percentile_method": "nearest_rank",
        "min_seconds": ordered[0], "p50_seconds": ordered[ceil(0.50 * len(ordered)) - 1],
        "p95_seconds": ordered[ceil(0.95 * len(ordered)) - 1], "max_seconds": ordered[-1],
        "samples": samples, "identical_response_verified": True, "fact_writes": 0,
        "capacity_or_p95_acceptance": False}


def measure_context_http_read(v, url, expected, monkeypatch):
    from apps.api.app.infrastructure.persistence.database import engine
    from apps.api.app.infrastructure.persistence import source_access_read_session as live
    from apps.api.app.main import app

    storage = app.state.container.context_packs.artifacts.storage
    access_engine = live._session_factory().kw["bind"]
    assert engine.dialect.name == "postgresql" and access_engine is not engine
    counts = {"business": Counter(), "live": Counter()}
    objects, sizes, identities, listeners = Counter(), Counter(), {}, []
    original_get = storage.get_bytes

    def statement_observer(label):
        def observe(_connection, _cursor, statement, _parameters, context, _many):
            counts[label]["statements"] += 1
            if statement == "SET TRANSACTION READ ONLY":
                counts[label]["read_only_setups"] += 1
            if "source_access_epochs" in statement and "source_access_policy_heads" in statement:
                counts[label]["authorization_queries"] += 1
            compiled = getattr(context, "compiled", None)
            compiled_statement = getattr(compiled, "statement", None)
            if (getattr(compiled_statement, "is_dml", False)
                    or statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}):
                table = getattr(compiled_statement, "table", None)
                bookkeeping = label == "business" and getattr(table, "name", None) in {
                    "access_sessions", "api_rate_limit_windows"}
                counts[label]["platform_bookkeeping_writes" if bookkeeping else "fact_writes"] += 1
        return observe

    def lifecycle_observer(label, name):
        def observe(*_args):
            counts[label][name] += 1
        return observe

    def read(ref, **options):
        body = original_get(ref, **options)
        digest = hashlib.sha256(body).hexdigest()
        assert ref not in identities or identities[ref] == digest
        identities[ref] = digest
        objects[ref] += 1
        sizes[ref] += len(body)
        return body

    try:
        for label, binding in (("business", engine), ("live", access_engine)):
            for name in ("checkout", "begin", "commit", "rollback", "before_cursor_execute"):
                callback = statement_observer(label) if name == "before_cursor_execute" else lifecycle_observer(label, name)
                event.listen(binding, name, callback)
                listeners.append((binding, name, callback))
        with monkeypatch.context() as scoped:
            scoped.setattr(storage, "get_bytes", read)
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
    assert sum(value["authorization_queries"] for value in counts.values()) > 0
    assert sum(objects.values()) > 0
    return {"elapsed_seconds": seconds, "response_hash": "sha256:" + hashlib.sha256(response.content).hexdigest(),
        "response_bytes": len(response.content), "response_contract_hash": snapshot_digest(expected),
        "connections": {label: dict(value) for label, value in counts.items()},
        "authorization_queries": sum(value["authorization_queries"] for value in counts.values()),
        "object_reads": sum(objects.values()), "distinct_objects": len(objects), "returned_object_bytes": sum(sizes.values()),
        "read_inventory_hash": snapshot_digest(sorted((ref, count, sizes[ref]) for ref, count in objects.items())),
        "distinct_read_inventory_hash": snapshot_digest(sorted(identities.items())),
        "fact_writes": 0}
