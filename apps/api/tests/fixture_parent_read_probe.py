"""One-pair diagnostic on complete private parents, not a performance acceptance."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from apps.api.tests.context_read_metrics import measure_context_http_read


def _grant_service():
    from apps.api.app.main import app
    return app.state.container.http_fixture_grants


def measure_fixture_parent_reuse(v, url, expected, monkeypatch):
    report_path = os.getenv("FIXTURE_PARENT_READ_REPORT")
    if not report_path:
        return
    service = _grant_service()
    original = service.recipes.read_with_plan
    with monkeypatch.context() as scoped:
        # Same full read algorithm, deliberately discarding its verified parent.
        scoped.setattr(service.recipes, "read_with_plan", None)
        control = measure_context_http_read(v, url, expected, monkeypatch)
    production = measure_context_http_read(v, url, expected, monkeypatch)
    assert service.recipes.read_with_plan == original
    for key in ("response_hash", "response_contract_hash", "response_bytes", "distinct_objects", "distinct_read_inventory_hash", "fact_writes"):
        assert control[key] == production[key], key
    assert production["object_reads"] < control["object_reads"]
    assert production["returned_object_bytes"] < control["returned_object_bytes"]
    assert production["connections"]["business"]["statements"] < control["connections"]["business"]["statements"]
    held = production["connections"]["live"]
    assert held["checkout"] == held["begin"] == held["read_only_setups"] == held["rollback"] == 1
    assert held.get("commit", 0) == 0 and held["authorization_queries"] > 0
    report = {"schema": "nasus.fixture-parent-read-reuse.v1", "verified_at": datetime.now(timezone.utc).isoformat(),
        "control": control, "production": production, "sample_order": "control_then_production_one_pair",
        "source_revision": v.get("exweb_commit"), "source_file_count": v.get("exweb_file_count"),
        "source_kind": "fixed_exweb_git" if v.get("exweb_commit") else "protocol_source_specimen",
        "same_complete_object_set_and_bytes": True, "same_response": True,
        "source_authorization_cache_added": False, "cross_request_content_cache_added": False,
        "target_executed": False, "business_gold": False, "controlled_linux_load": False,
        "capacity_or_p95_acceptance": False}
    Path(report_path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
