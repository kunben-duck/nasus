"""Actual fixed exweb Git export; the changed README is a controlled fixture."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url

from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.source_acquisition_repository import SourceAcquisitionIntentRepository
from apps.api.tests.exweb_git_trees import AFTER, read_git_tree
from apps.api.tests.test_source_refresh_api import evidence_api, read, selection, refresh
from apps.api.tests.test_source_ingestion_access_api import grant_tester, facts, revisions


def test_actual_fixed_exweb_selected_refresh_keeps_optional_sources_and_replays_old_code(evidence_api, tmp_path, monkeypatch):
    root = os.getenv("EXWEB_SOURCE_REFRESH_GIT_ROOT")
    if not root:
        pytest.skip("explicit reviewed exweb Git export required")
    assert os.environ.get("NASUS_TEST_OBJECT_STORAGE_MODE") == "minio"
    database = make_url(os.environ["NASUS_DATABASE_URL"])
    assert database.get_backend_name() == "postgresql" and database.database.startswith("nasus_test_")
    v = evidence_api
    files, tree_hash, _ = read_git_tree(Path(root), AFTER)
    exported = tmp_path / "exweb-export"
    exported.mkdir()
    for name, body in files:
        destination = exported / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)
    assert len(files) == 126
    requirement = tmp_path / "requirements.md"
    requirement.write_text("# US-REFRESH\nSynthetic protocol fixture, not exweb business approval.\n")
    cases = tmp_path / "cases.md"
    cases.write_text("# TC-REFRESH\nReferences: US-REFRESH\nExpected result: synthetic protocol only.\n")
    v["invoke"]("system_image.sources.register", {"source_specs": [
        {"source_type": "code", "source_uri": str(exported)},
        {"source_type": "us_doc", "source_uri": str(requirement)},
        {"source_type": "test_asset", "source_uri": str(cases)}]})
    v["invoke"]("system_image.sources.ingest")
    before = read(v)
    source = next(item for item in before["sources"] if item["source_uri"] == str(exported))
    assert before["read_state"]["mode"] == "legacy_draft"
    # Resolve durable source facts through the manifest port, not the public view.
    from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
    repository = SourceSnapshotRepository()
    old_manifest = repository.get_manifest(v["project_id"], before["source_manifest"]["manifest_id"])
    archived_sources = repository.materialization_sources(old_manifest)
    old_source = next(item for item in archived_sources if item.id == source["id"])
    old_units = SourceIngestionService().extract_text_units(old_source)
    old_text = {item.relative_path: item.text for item in old_units}
    readme = exported / "README.md"
    readme.write_bytes(readme.read_bytes() + b"\nControlled Nasus source refresh verification.\n")
    requirement.unlink()
    cases.unlink()
    grant_tester(v)
    access = SourceAccessRepository()
    binding_id = next(item.binding_id for item in access.load_snapshot(v["project_id"]).bindings if item.source_id == source["id"])
    assert binding_id in {item.binding_id for item in old_manifest.members}

    def set_readers(rule):
        access.set_policy(v["project_id"], binding_id, rule,
            expected_epoch=access.load_snapshot(v["project_id"]).acl_epoch,
            changed_by=v["owner"]["id"], invocation_id="exweb-acl-fixture-" + uuid4().hex)

    calls = []
    intent_ids = []
    acquire = SourceIngestionService.ingest

    def counted(service, item):
        from sqlalchemy import select
        from apps.api.app.infrastructure.persistence.source_acquisition_models import SourceAcquisitionIntentRecord
        from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
        from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
        with session_scope() as session:
            row = session.scalar(select(SourceAcquisitionIntentRecord).join(ToolInvocationRecord,
                SourceAcquisitionIntentRecord.invocation_id == ToolInvocationRecord.id).where(
                    SourceAcquisitionIntentRecord.project_id == v["project_id"], ToolInvocationRecord.status == "running"))
            assert row is not None
            intent = SourceAcquisitionIntentRepository._from_row(row)
        assert intent.actor_id == v["member"]["id"] and intent.selection_mode == "selected"
        assert tuple(pin.source_id for pin in intent.sources) == (source["id"],)
        assert intent.sources[0].binding_id == binding_id
        assert (intent.origin_manifest_id, intent.origin_manifest_hash) == (old_manifest.manifest_id, old_manifest.content_hash)
        intent_ids.append(intent.invocation_id)
        calls.append(item.id)
        return acquire(service, item)

    monkeypatch.setattr(SourceIngestionService, "ingest", counted)
    set_readers(SourceAccessRule("restricted"))
    original_facts, original_revisions = facts(v), revisions(v)
    denied = refresh(v, selection(before, source["id"]), headers=v["member_headers"], status="failed")
    assert denied["result"]["followup_reason"] == "source_access_denied" and not calls
    assert SourceAcquisitionIntentRepository().get(denied["id"]) is None
    assert facts(v) == original_facts and revisions(v) == original_revisions
    assert repository.latest_manifest(v["project_id"]) == old_manifest
    set_readers(SourceAccessRule("restricted", (v["member"]["id"],)))
    result = refresh(v, selection(before, source["id"]), headers=v["member_headers"])
    assert calls == [source["id"]] and intent_ids == [result["id"]]
    original_intent = SourceAcquisitionIntentRepository().get(result["id"])
    # Restore the fixture's public projection policy before comparing full
    # manifests; source-filtered HTTP views intentionally omit the global pins.
    set_readers(SourceAccessRule("project"))
    assert not any(value in json.dumps(result["result"]) for value in ("s3://", "local-object://", str(exported)))
    after = read(v)
    unselected_before = [item for item in before["sources"] if item["id"] != source["id"]]
    assert [item for item in after["sources"] if item["id"] != source["id"]] == unselected_before
    assert [item for item in after["chunks"] if item["raw_asset_id"] != source["id"]] == [
        item for item in before["chunks"] if item["raw_asset_id"] != source["id"]]
    assert after["candidate_revision"] == before["candidate_revision"]
    old_members = {item.binding_id: item.source_revision_id for item in old_manifest.members}
    new_manifest = repository.get_manifest(v["project_id"], after["source_manifest"]["manifest_id"])
    changed = [item for item in new_manifest.members if item.source_revision_id != old_members[item.binding_id]]
    assert len(changed) == 1 and changed[0].source_type == "code"
    original_revision = old_members[changed[0].binding_id]
    delta = v["client"].get(f"/v1/projects/{v['project_id']}/system-image/source-delta", headers=v["headers"],
        params={"before_revision_id": original_revision, "after_revision_id": changed[0].source_revision_id})
    assert delta.status_code == 200, delta.text
    comparison = delta.json()
    assert comparison["complete"] and comparison["counts"]["modified"] == 1
    assert comparison["counts"]["added"] == comparison["counts"]["deleted"] == comparison["counts"]["unresolved"] == 0
    assert next(item for item in comparison["items"] if item["kind"] == "modified")["path"] == "README.md"
    assert {item.relative_path: item.text for item in SourceIngestionService().extract_text_units(old_source)} == old_text
    assert SourceAcquisitionIntentRepository().get(result["id"]) == original_intent
    # Revoke after two completed receipts pass their individual checks.
    # State enumeration need not match the response's chronological ordering.
    from apps.api.app.main import app
    set_readers(SourceAccessRule("restricted", (v["member"]["id"],)))
    receipt_url = "/v1/tool-invocations"
    receipt_params = {"conversation_id": v["conversation"].json()["id"], "tool_id": "system_image.sources.ingest"}
    visible = v["client"].get(receipt_url, headers=v["member_headers"], params=receipt_params)
    assert visible.status_code == 200 and result["id"] in visible.text
    earlier = [item["id"] for item in visible.json() if item["status"] == "completed" and item["id"] != result["id"]]
    assert earlier
    completed_ids = set(earlier + [result["id"]])
    receipt_access = app.state.container.platform._tool_invocations._read_resources
    require_access = receipt_access.require_access
    checked, revoked = [], []
    replay_facts, replay_revisions = facts(v), revisions(v)

    def revoke_after_later_receipt(item):
        require_access(item)
        if item.id in completed_ids and completed_ids.intersection(checked) and not revoked:
            set_readers(SourceAccessRule("restricted"))
            revoked.append(item.id)
        checked.append(item.id)

    with monkeypatch.context() as scoped:
        scoped.setattr(receipt_access, "require_access", revoke_after_later_receipt)
        hidden = v["client"].get(receipt_url, headers=v["member_headers"], params=receipt_params)
    assert len(revoked) == 1 and hidden.status_code == 403, hidden.text
    assert len(completed_ids.intersection(checked)) >= 2
    assert source["id"] not in hidden.text and result["id"] not in hidden.text
    assert calls == [source["id"]] and facts(v) == replay_facts and revisions(v) == replay_revisions
    set_readers(SourceAccessRule("restricted", (v["member"]["id"],)))
    restored = v["client"].get(receipt_url, headers=v["member_headers"], params=receipt_params)
    assert restored.status_code == 200 and restored.json() == visible.json(), restored.text
    set_readers(SourceAccessRule("project"))
    report = {"verified_at": datetime.now(timezone.utc).isoformat(),
        "repository": "https://github.com/kunben-duck/exweb.git", "original_commit": AFTER,
        "original_git_tree_hash": tree_hash, "original_git_file_count": len(files),
        "code_capture_file_count": source["file_count"], "canonical_invocation_id": result["id"],
        "denied_canonical_invocation_id": denied["id"],
        "fresh_source_acl_before_acquisition_verified": True,
        "immutable_canonical_admission_before_connector_verified": True,
        "acquisition_intent_hash": original_intent.content_hash,
        "acquisition_origin_manifest_id": original_intent.origin_manifest_id,
        "acquisition_execution_actor_id": original_intent.actor_id,
        "acquisition_lease_or_crash_recovery_verified": False,
        "denied_connector_call_count": 0, "named_reader_acquisition_verified": True,
        "late_batch_source_revocation_verified": True,
        "late_batch_denied_http_status": hidden.status_code,
        "late_batch_history_restoration_verified": restored.json() == visible.json(),
        "before_manifest": before["source_manifest"], "after_manifest": after["source_manifest"],
        "source_delta_hash": comparison["content_hash"], "source_delta_counts": comparison["counts"],
        "unchanged_unselected_sources": len(unselected_before),
        "unchanged_optional_sources": sum(item["source_type"] != "code" for item in unselected_before),
        "postgresql": True, "minio": True,
        "canonical_local_git_export_ingestion": True, "native_remote_git_acquisition": False,
        "controlled_change_not_upstream_commit": True, "historical_code_replayed": True,
        "external_model_called": False, "target_executed": False, "automatic_update_verified": False}
    path = os.getenv("EXWEB_SOURCE_REFRESH_REPORT")
    if path:
        with Path(path).open("x", encoding="utf-8") as output:
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.write("\n")
