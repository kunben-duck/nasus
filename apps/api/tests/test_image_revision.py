from copy import deepcopy
from dataclasses import asdict, replace

import pytest

from apps.api.app.domain.system_image.image_revision import (
    IMAGE_POLICY, ImageRevisionConflict, ImageRevisionIntegrityError, ImageRevisionSummary,
    build_image_artifact, verify_image_artifact,
)
from apps.api.app.domain.system_image.source_snapshots import CapturedSourceManifest, SourceManifestMember, snapshot_digest
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage, ObjectStorageConfig
from apps.api.app.infrastructure.system_image.image_artifacts import ArchivedImageArtifacts


def candidate():
    inputs = (SourceManifestMember("binding", "code", "source-revision", "captured"),)
    manifest = CapturedSourceManifest("manifest", "project", snapshot_digest([asdict(item) for item in inputs]), "now", inputs)
    objects = [{"id": "code", "name": "Orders", "freshness": "today", "code_reference": {
        "entity_id": "entity", "entity_revision_id": "entity-revision", "source_revision_id": "source-revision"}},
        {"id": "core", "name": "Project", "freshness": "today"}]
    relationships = [{"id": "edge", "project_id": "project", "baseline_id": "baseline",
                      "from_object_id": "code", "to_object_id": "core"}]
    return manifest, objects, relationships


def header(payload):
    return ImageRevisionSummary("image", "project", "baseline", "manifest", payload["manifest_hash"],
        snapshot_digest(payload), snapshot_digest(payload["members"]), IMAGE_POLICY, "now", 2, 1, 1)


def test_frozen_artifact_is_order_independent_and_not_an_approved_assertion():
    manifest, objects, relationships = candidate()
    payload, members = build_image_artifact(manifest, "baseline", objects, relationships)
    assert payload["semantic_status"] == "legacy_observations_not_approved_assertions"
    assert payload["publication"] == "blocked_pending_revision_governance"
    assert [item.kind for item in members] == ["code_entity", "legacy_observation"]
    assert "freshness" not in payload["objects"][0]
    other, _ = build_image_artifact(manifest, "baseline", list(reversed(objects)), relationships)
    assert other == payload
    verify_image_artifact(payload, header(payload))
    payload["members"][0]["evidence_ids"] = ["fixed-evidence"]
    verify_image_artifact(payload, header(payload))


@pytest.mark.parametrize("status", ["failed", "pending", "legacy_unverified"])
def test_optional_missing_source_is_frozen_as_a_gap_not_invented_content(status):
    manifest, objects, relationships = candidate()
    members = (*manifest.members, SourceManifestMember("optional", "us_doc", None, status))
    manifest = replace(manifest, members=members, content_hash=snapshot_digest([asdict(item) for item in members]))
    payload, _ = build_image_artifact(manifest, "baseline", objects, relationships)
    assert payload["source_members"][1]["status"] == status
    verify_image_artifact(payload, header(payload))


@pytest.mark.parametrize("change", ["unverified", "no_code", "duplicate", "wrong_hash", "foreign_object", "foreign_edge", "open_edge"])
def test_incomplete_or_mixed_inputs_cannot_be_frozen(change):
    manifest, objects, relationships = candidate()
    if change in {"unverified", "no_code", "duplicate"}:
        member = manifest.members[0]
        members = ((replace(member, status="legacy_unverified", source_revision_id=None),) if change == "unverified" else
                   (replace(member, source_type="us_doc"),) if change == "no_code" else (member, member))
        manifest = replace(manifest, members=members, content_hash=snapshot_digest([asdict(item) for item in members]))
    elif change == "wrong_hash":
        manifest = replace(manifest, content_hash="sha256:" + "0" * 64)
    elif change == "foreign_object":
        objects[0]["code_reference"]["source_revision_id"] = "foreign"
    elif change == "foreign_edge":
        relationships[0]["project_id"] = "foreign"
    else:
        relationships[0]["to_object_id"] = "not-in-candidate"
    with pytest.raises((ImageRevisionConflict, ImageRevisionIntegrityError)):
        build_image_artifact(manifest, "baseline", objects, relationships)


@pytest.mark.parametrize("change", ["object", "membership", "count", "schema", "malformed"])
def test_full_artifact_is_verified_even_when_its_transport_digest_matches(change):
    payload, _ = build_image_artifact(candidate()[0], "baseline", *candidate()[1:])
    summary = header(payload)
    bad = deepcopy(payload)
    if change == "object":
        bad["objects"][0]["name"] = "tampered"
    elif change == "membership":
        bad["members"][0]["object_hash"] = "sha256:" + "z" * 64
    elif change == "schema":
        bad["schema"] = "unknown"
    elif change == "malformed":
        del bad["source_members"]
    else:
        summary = replace(summary, code_member_count=0)
    summary = replace(summary, artifact_hash=snapshot_digest(bad), membership_hash=snapshot_digest(bad["members"]))
    with pytest.raises(ImageRevisionIntegrityError):
        verify_image_artifact(bad, summary)


def test_archive_rejects_tampering_foreign_namespace_and_oversize(tmp_path, monkeypatch):
    storage = ObjectStorage(ObjectStorageConfig(None, "images", None, None, "local", tmp_path))
    archive = ArchivedImageArtifacts(storage)
    payload, _ = build_image_artifact(candidate()[0], "baseline", *candidate()[1:])
    ref, digest = archive.put("project", payload)
    assert archive.read("project", ref, digest)["manifest_id"] == "manifest"
    for project, candidate_ref, candidate_hash in (("foreign", ref, digest), ("project", ref + "x", digest),
                                                 ("project", ref, "sha256:" + "z" * 64)):
        with pytest.raises(ImageRevisionIntegrityError):
            archive.read(project, candidate_ref, candidate_hash)
    monkeypatch.setattr(storage, "get_bytes", lambda *args, **kwargs: b"private-storage-data")
    with pytest.raises(ImageRevisionIntegrityError):
        archive.read("project", ref, digest)
    monkeypatch.setattr(archive, "MAX_BYTES", 10)
    with pytest.raises(ValueError, match="size limit"):
        archive.put("project", payload)
