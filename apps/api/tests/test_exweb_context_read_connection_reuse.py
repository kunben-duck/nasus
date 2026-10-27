"""Real production connection scope compared with its unscoped read algorithm."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import pytest

from apps.api.app.infrastructure.persistence import source_access_read_session as live
from apps.api.app.main import app
from apps.api.tests.context_read_metrics import measure_context_http_read, summarize_read_samples
from apps.api.tests.exweb_git_trees import AFTER
from apps.api.tests.test_exweb_context_read_measurement import evidence_api, acceptance, documents
from apps.api.tests.test_context_packs_api import preview, archive, read
from apps.api.tests.test_semantic_evaluations_api import completed
from apps.api.tests.test_source_access_api import grant_member, policy


def test_exweb_same_context_connection_only_reuse_keeps_all_reads_and_fresh_authorization(acceptance, monkeypatch):
    report_path = os.getenv("EXWEB_CONTEXT_READ_CONNECTION_REPORT")
    if not report_path:
        pytest.skip("explicit experimental report required")
    v = acceptance
    expected, url = read(v, completed(archive(v, preview(v))[0]))
    service = app.state.container.context_packs
    original_read = service.read
    unscoped_read = service._read_current
    completed_scopes = []

    def observed_read(project_id, context_id):
        assert live.current_source_access_read_session() is None
        try:
            return original_read(project_id, context_id)
        finally:
            assert live.current_source_access_read_session() is None
            completed_scopes.append((project_id, context_id))

    control, experiment = [], []
    count = int(os.getenv("EXWEB_CONTEXT_READ_SAMPLES", "5"))
    assert 5 <= count <= 30
    for _ in range(count):
        with monkeypatch.context() as scoped:
            scoped.setattr(service, "read", unscoped_read)
            before = measure_context_http_read(v, url, expected, monkeypatch)
        with monkeypatch.context() as scoped:
            scoped.setattr(service, "read", observed_read)
            after = measure_context_http_read(v, url, expected, monkeypatch)
        for field in ("response_hash", "response_contract_hash", "response_bytes", "authorization_queries",
                      "object_reads", "distinct_objects", "returned_object_bytes", "read_inventory_hash", "fact_writes"):
            assert before[field] == after[field], field
        assert not before["connections"]["live"]
        held = after["connections"]["live"]
        assert held["checkout"] == held["begin"] == held["read_only_setups"] == held["rollback"] == 1
        assert held.get("commit", 0) == 0
        assert held["authorization_queries"] == before["authorization_queries"]
        assert before["connections"]["business"]["checkout"] > after["connections"]["business"]["checkout"]
        control.append(before)
        experiment.append(after)
    assert len(completed_scopes) == count

    grant_member(v)
    storage = service.artifacts.storage
    original_get = storage.get_bytes
    _, archive_ref = service.repository.get(v["project_id"], expected["metadata"]["context_id"])
    revoked = []

    def revoke_during_read(ref, **options):
        body = original_get(ref, **options)
        if ref == archive_ref and not revoked:
            policy(v)
            revoked.append(True)
        return body

    with monkeypatch.context() as scoped:
        scoped.setattr(service, "read", observed_read)
        assert v["client"].get(url, headers=v["member_headers"]).json() == expected
        scoped.setattr(storage, "get_bytes", revoke_during_read)
        denied = v["client"].get(url, headers=v["member_headers"])
        assert revoked == [True] and denied.status_code == 409
        assert denied.json()["detail"]["error"]["code"] == "source_access_changed"
        assert not any(value in denied.text for value in ("HTTP 400", "orders.py", "s3://", "Search validation"))
        scoped.setattr(storage, "get_bytes", original_get)
        assert v["client"].get(url, headers=v["member_headers"]).status_code == 403
        assert v["client"].get(url, headers=v["headers"]).json() == expected
        def corrupt(ref, **options):
            return b"private-connection-probe" if ref == archive_ref else original_get(ref, **options)
        scoped.setattr(storage, "get_bytes", corrupt)
        invalid = v["client"].get(url, headers=v["headers"])
        assert invalid.status_code == 502 and "private-connection-probe" not in invalid.text and archive_ref not in invalid.text
    assert service.read == original_read and live.current_source_access_read_session() is None
    assert len(completed_scopes) == count + 5
    assert v["client"].get(url, headers=v["headers"]).json() == expected
    report = {"schema": "nasus.exweb-context-read-connection-comparison.v2", "verified_at": datetime.now(timezone.utc).isoformat(),
        "repository": "https://github.com/kunben-duck/exweb.git", "revision": AFTER, "source": v["measured_exweb_source"],
        "context_metadata": expected["metadata"], "control": summarize_read_samples(control),
        "experiment": summarize_read_samples(experiment), "sample_order": "control_then_experiment_per_pair",
        "same_raw_reads_bytes_responses_and_authorization_query_count": True,
        "read_only_read_committed_connection_returned_after_every_request": True,
        "mid_request_revocation_still_denied": True, "corrupt_context_still_denied": True,
        "source_authorization_cache_added": False, "source_content_cache_added": False,
        "production_read_scope_applied": True, "production_method_restored_after_control": True,
        "control_strategy": "same_read_algorithm_without_enclosing_connection_scope",
        "target_executed": False, "external_model_called": False,
        "companion_sources": "synthetic_search_requirement_and_case_plus_orders_sentinel", "business_gold": False,
        "controlled_load_or_linux_baseline": False, "capacity_or_p95_acceptance": False}
    Path(report_path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
