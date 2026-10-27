from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from apps.api.app.infrastructure.persistence import source_access_read_session as live
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.main import app
from apps.api.tests.completion_read_metrics import compare_completion_replays
from apps.api.tests.test_build_completion_api import completion, report, submit
from apps.api.tests.test_investigation_api import investigation
from apps.api.tests.test_source_evidence_api import evidence_api


def test_complete_api_replay_reuses_connection_not_permissions_or_bodies(completion, monkeypatch):
    v = completion
    command = submit(v).json()
    assert command["status"] == "completed", command
    expected = report(v, command["id"]).json()
    url = f"/v1/projects/{v['project_id']}/system-image/build-completions/{command['id']}"
    metrics = compare_completion_replays(v, url, expected, monkeypatch)
    assert metrics["reports_identical"] and metrics["raw_read_inventory_unchanged"]
    assert metrics["optimized"]["source_body_reads"] >= sum(scan["file_count"] for scan in expected["source_scans"])


def test_full_live_access_pool_fails_closed_without_starving_business_reads(completion, monkeypatch):
    v = completion
    command = submit(v).json()
    assert command["status"] == "completed", command
    expected = report(v, command["id"]).json()
    dedicated = create_engine(engine.url, future=True, pool_size=1, max_overflow=0, pool_timeout=0.05,
                              isolation_level="READ COMMITTED")
    storage = app.state.container.source_deltas.reader.archive.storage
    original, reads = storage.get_bytes, []

    def read(ref, **options):
        reads.append(ref)
        return original(ref, **options)

    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(live, "_session_factory", lambda: sessionmaker(bind=dedicated, future=True))
            scoped.setattr(storage, "get_bytes", read)
            # Hold the physical connection without propagating a session context
            # into TestClient's worker; the request must acquire its own lease.
            with dedicated.connect():
                unavailable = report(v, command["id"])
                assert unavailable.status_code == 503, unavailable.text
                assert not any(secret in unavailable.text for secret in
                               ("source_scans", "s3://", "postgresql", "credentials"))
                assert reads == []
                with session_scope() as business:
                    assert business.scalar(text("SHOW transaction_read_only")) == "off"
                    assert business.scalar(text("SELECT 1")) == 1
            assert dedicated.pool.checkedout() == 0
            recovered = report(v, command["id"])
            assert recovered.status_code == 200 and recovered.json() == expected, recovered.text
            assert reads and dedicated.pool.checkedout() == 0
        assert live.current_source_access_read_session() is None
    finally:
        dedicated.dispose()
