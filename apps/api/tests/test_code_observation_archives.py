from copy import deepcopy
from dataclasses import replace
import json

import pytest

from apps.api.app.application.system_image.code_observations import received_code_observations
from apps.api.app.domain.system_image.code_observation_archive import (
    OBSERVATION_BASIS, validate_observation_payload, verify_observation_report,
)
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage, ObjectStorageConfig
from apps.api.app.infrastructure.system_image.code_observation_artifacts import ArchivedCodeObservations
from apps.api.tests.test_code_analysis import analyze, unit


def received():
    code = unit("Orders.java", "class Orders { void create() {} }")
    result = analyze(code.text, code.relative_path)
    unknown = replace(result.entities[-1], provider_node_id="native-unmapped", name="unmapped",
        qualified_name="unknown.unmapped", symbol_key=None, identity_status="unresolved",
        location_precision="approximate")
    result = replace(result, entities=(*result.entities, unknown))
    manifest = {"project_id": "project", "source_id": "code", "external_revision": "fixed-commit",
        "files": [{"path": code.relative_path, "content_hash": code.content_hash, "byte_count": code.byte_count}]}
    return manifest, result, received_code_observations(manifest, result)


def archive(tmp_path):
    storage = ObjectStorage(ObjectStorageConfig(None, "isolated", None, None, "us-east-1", tmp_path))
    return ArchivedCodeObservations(storage)


def test_complete_received_projection_preserves_unregistered_entities_and_roundtrips(tmp_path):
    manifest, result, payload = received()
    store = archive(tmp_path)
    original = deepcopy(payload)
    pin = store.put(payload)
    report = {**manifest, "source_manifest_hash": snapshot_digest(manifest),
        "provider": result.provider, "provider_version": result.provider_version, "observation_archive": pin}
    assert store.read(report) == original == payload
    assert store.put(payload) == pin
    assert pin["summary"]["identity_counts"]["unresolved"] == 1
    assert pin["summary"]["entity_count"] == len(result.entities)
    assert pin["summary"]["basis"] == OBSERVATION_BASIS
    assert payload["result"]["entities"][-1]["provider_node_id"] == "native-unmapped"
    assert "source_root" not in json.dumps(payload)
    assert payload["result"]["provider_observations"] == json.loads(json.dumps(
        received_code_observations(manifest, result)["result"]["provider_observations"]))


@pytest.mark.parametrize("field", ["project_id", "source_id", "source_manifest_hash", "external_revision", "provider", "provider_version"])
def test_borrowed_archive_cannot_attach_to_another_report(tmp_path, field):
    manifest, result, payload = received()
    store = archive(tmp_path)
    pin = store.put(payload)
    report = {**manifest, "source_manifest_hash": snapshot_digest(manifest), "provider": result.provider,
        "provider_version": result.provider_version, "observation_archive": pin}
    report[field] = "other" if field != "source_manifest_hash" else "sha256:" + "a" * 64
    with pytest.raises(ValueError):
        store.read(report)


@pytest.mark.parametrize("change", ["body", "count", "missing", "namespace"])
def test_archive_tampering_missing_and_relocated_content_fail_closed(tmp_path, change):
    manifest, result, payload = received()
    store = archive(tmp_path)
    pin = store.put(payload)
    report = {**manifest, "source_manifest_hash": snapshot_digest(manifest), "provider": result.provider,
        "provider_version": result.provider_version, "observation_archive": pin}
    path = tmp_path / "isolated" / store.key("project", "code", pin["artifact_hash"])
    if change == "body":
        path.write_bytes(b"{}")
    elif change == "missing":
        path.unlink()
    elif change == "count":
        pin["summary"]["identity_counts"]["exact"] += 1
        pin["summary"]["entity_count"] += 1
    else:
        pin["artifact_ref"] = pin["artifact_ref"].replace("isolated/", "foreign/")
    with pytest.raises(ValueError):
        store.read(report)


@pytest.mark.parametrize("change", ["duplicate", "foreign_path", "missing_endpoint", "boolean_line", "extra_field", "nan"])
def test_invalid_observations_cannot_create_an_archive(change):
    _, _, payload = received()
    result = payload["result"]
    if change == "duplicate":
        result["entities"].append(result["entities"][0])
    elif change == "foreign_path":
        result["entities"][0]["relative_path"] = "../secret"
    elif change == "missing_endpoint":
        result["relationships"][0]["to_provider_node_id"] = "missing"
    elif change == "boolean_line":
        result["entities"][0]["start_line"] = True
    elif change == "extra_field":
        result["entities"][0]["private_path"] = "/private/source"
    else:
        result["relationships"][0]["confidence"] = float("nan")
    with pytest.raises(ValueError):
        validate_observation_payload(payload)


def test_snapshot_membership_and_archive_size_are_not_silently_truncated(tmp_path, monkeypatch):
    from apps.api.app.domain.system_image import code_observation_archive as domain
    manifest, result, payload = received()
    with pytest.raises(ValueError, match="outside"):
        received_code_observations({**manifest, "files": []}, result)
    monkeypatch.setattr(domain, "MAX_OBSERVATION_BYTES", 1)
    with pytest.raises(ValueError, match="size limit"):
        archive(tmp_path).put(payload)
    assert not list(tmp_path.rglob("*.json"))


def test_archiving_requires_verified_readback_and_does_not_hide_control_exceptions(tmp_path, monkeypatch):
    _, _, payload = received()
    store = archive(tmp_path)
    monkeypatch.setattr(store.storage, "get_bytes", lambda *a, **k: b"{}")
    with pytest.raises(ValueError, match="durably archived"):
        store.put(payload)
    def cancelled(*args, **kwargs):
        raise KeyboardInterrupt("cancelled")
    monkeypatch.setattr(store.storage, "put_bytes", cancelled)
    with pytest.raises(KeyboardInterrupt):
        store.put(payload)
