"""Opt-in real fixed exweb/PG/MinIO reads; companion documents are synthetic."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.engine import make_url

from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceBindingRecord, SourceRevisionRecord
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.storage.object_storage import ObjectStorageConfig
from apps.api.app.main import app
from apps.api.tests.context_read_metrics import measure_context_http_read, summarize_read_samples
from apps.api.tests.test_exweb_context_change_impact import export_tree
from apps.api.tests.exweb_git_trees import AFTER, git_bytes
from apps.api.tests.test_source_evidence_api import evidence_api as base_evidence_api
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_acceptance_specifications_api import acceptance
from apps.api.tests.test_context_packs_api import preview, archive, read
from apps.api.tests.test_semantic_evaluations_api import completed
from apps.api.tests.test_source_access_api import grant_member


@pytest.fixture
def evidence_api(tmp_path, monkeypatch):
    if not os.getenv("EXWEB_CONTEXT_READ_REPORT") or not os.getenv("EXWEB_DELTA_GIT_ROOT"):
        pytest.skip("explicit fixed Git root and read measurement report are required")
    database = make_url(os.environ["NASUS_DATABASE_URL"])
    config = ObjectStorageConfig.from_env()
    assert database.get_backend_name() == "postgresql" and database.database.startswith("nasus_test_")
    assert os.getenv("NASUS_TEST_OBJECT_STORAGE_MODE") == "minio" and config.bucket.startswith("nasus-test-")
    assert git_bytes(Path(os.environ["EXWEB_DELTA_GIT_ROOT"]), "rev-parse", "HEAD").decode().strip() == AFTER
    assert not git_bytes(Path(os.environ["EXWEB_DELTA_GIT_ROOT"]), "status", "--porcelain")
    v = base_evidence_api.__wrapped__(tmp_path, monkeypatch)
    try:
        exported = tmp_path / "exweb-export"
        count, tree_hash = export_tree(Path(os.environ["EXWEB_DELTA_GIT_ROOT"]), AFTER, exported)
        assert count == 126
        v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "code", "source_uri": str(exported)}]})
        v["invoke"]("system_image.sources.ingest")
        v["invoke"]("system_image.context.materialize")
        with session_scope() as session:
            binding = session.scalar(select(SourceBindingRecord).where(
                SourceBindingRecord.project_id == v["project_id"], SourceBindingRecord.external_identity == str(exported)))
            assert binding is not None
            v["exweb_binding"] = binding.binding_id
        member = next(item for item in SourceSnapshotRepository().latest_manifest(v["project_id"]).members
            if item.binding_id == v["exweb_binding"])
        with session_scope() as session:
            source = session.scalar(select(SourceRevisionRecord).where(
                SourceRevisionRecord.project_id == v["project_id"], SourceRevisionRecord.binding_id == v["exweb_binding"],
                SourceRevisionRecord.source_revision_id == member.source_revision_id))
            assert source is not None and source.file_count == count and source.content_hash == tree_hash
            v["measured_exweb_source"] = {"binding_id": source.binding_id, "source_revision_id": source.source_revision_id,
                "tree_hash": tree_hash, "manifest_hash": source.manifest_hash, "file_count": count}
        yield v
    finally:
        v["client"].close()


def test_fixed_exweb_context_replays_have_measured_latency_and_still_fail_closed(acceptance, monkeypatch):
    v = acceptance
    view = preview(v)
    assert view["context"]["readiness"]["status"] == "blocked"
    assert all(item["oracle"] is None for item in view["context"]["required_constraints"])
    expected, url = read(v, completed(archive(v, view)[0]))
    count = int(os.getenv("EXWEB_CONTEXT_READ_SAMPLES", "5"))
    assert 5 <= count <= 30
    observed = [measure_context_http_read(v, url, expected, monkeypatch) for _ in range(count)]
    measurement = summarize_read_samples(observed)
    assert len({item["read_inventory_hash"] for item in observed}) == 1
    assert len({item["response_contract_hash"] for item in observed}) == 1

    grant_member(v)
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 200
    storage = app.state.container.context_packs.artifacts.storage
    original_get = storage.get_bytes
    _, archive_ref = app.state.container.context_packs.repository.get(v["project_id"], expected["metadata"]["context_id"])
    revoked = []

    def revoke_during_read(ref, **options):
        body = original_get(ref, **options)
        if ref == archive_ref and not revoked:
            repository = SourceAccessRepository()
            scope = repository.load_snapshot(v["project_id"])
            repository.set_policy(v["project_id"], v["exweb_binding"], SourceAccessRule("restricted"),
                expected_epoch=scope.acl_epoch, changed_by=v["owner"]["id"], invocation_id="read-probe-" + uuid4().hex)
            revoked.append(True)
        return body

    with monkeypatch.context() as scoped:
        scoped.setattr(storage, "get_bytes", revoke_during_read)
        denied = v["client"].get(url, headers=v["member_headers"])
    assert revoked == [True] and denied.status_code == 409
    assert denied.json()["detail"]["error"]["code"] == "source_access_changed"
    assert "context" not in denied.json().get("detail", {})
    assert not any(item in denied.text for item in ("HTTP 400", "orders.py", "s3://", "Search validation"))
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 403
    assert v["client"].get(url, headers=v["headers"]).json() == expected

    def corrupt(ref, **options):
        return b"private-corrupted-probe" if ref == archive_ref else original_get(ref, **options)

    with monkeypatch.context() as scoped:
        scoped.setattr(storage, "get_bytes", corrupt)
        invalid = v["client"].get(url, headers=v["headers"])
    assert invalid.status_code == 502
    assert "private-corrupted-probe" not in invalid.text and archive_ref not in invalid.text
    assert v["client"].get(url, headers=v["headers"]).json() == expected
    report = {"schema": "nasus.exweb-context-read-measurement.v1", "verified_at": datetime.now(timezone.utc).isoformat(),
        "repository": "https://github.com/kunben-duck/exweb.git", "revision": AFTER,
        "source": v["measured_exweb_source"], "context_metadata": expected["metadata"], "measurement": measurement,
        "scope": {"transport": "asgi_testclient_end_to_end_no_network_link", "host_os": platform.system(),
            "host_machine": platform.machine(), "host_cpu_count": os.cpu_count(), "setup_and_capture_excluded": True,
            "setup_already_read_original_context": True, "independent_request_scopes": True,
            "application_cross_request_content_cache_added": False, "source_authorization_cache_added": False,
            "parallel_load_measured": False, "linux_8cpu_16gb_baseline_measured": False,
            "context_policy": expected["metadata"]["policy_revision"], "readiness": view["context"]["readiness"]["status"],
            "companion_sources": "synthetic_search_requirement_and_case_plus_orders_sentinel",
            "external_model_called": False, "target_executed": False, "business_gold": False},
        "safety_checks": {"source_revocation_during_read_denied": True, "revoked_member_read_denied": True,
            "corrupt_context_archive_denied": True, "original_archive_response_unchanged": True}}
    Path(os.environ["EXWEB_CONTEXT_READ_REPORT"]).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
