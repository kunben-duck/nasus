"""Frozen image roots are real manifests, not invented business objects."""
from sqlalchemy import select

from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.persistence.image_revision_models import ImageObjectMemberRecord
from apps.api.app.infrastructure.persistence.image_revision_repository import ImageRevisionRepository
from apps.api.app.infrastructure.persistence.object_provenance_projection_v1 import ObjectProvenanceProjectorV1
from apps.api.app.infrastructure.persistence.image_revision_models import ImageRevisionRecord
from apps.api.app.infrastructure.persistence.image_publication_models import ImagePublicationHeadRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.main import app
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_image_revision_api import selected


def test_new_frozen_candidate_contains_only_source_pinned_members(evidence_api):
    v = evidence_api
    _, summary, url = selected(v)
    with session_scope() as session:
        members = session.scalars(select(ImageObjectMemberRecord).where(
            ImageObjectMemberRecord.image_revision_id == summary["image_revision_id"])).all()
        assert members and all(item.kind == "code_entity" for item in members)
        image = session.get(ImageRevisionRecord, summary["image_revision_id"])
        projector = ObjectProvenanceProjectorV1()
        nodes = projector.expected(session, image)
        assert projector.image(session, image, write=False) == 0
        root = nodes["image_objects:" + image.image_revision_id]
        assert "manifest:" + summary["manifest_id"] in root.parents
        assert root.source_pins and len(root.parents) == len(members) + 1
    view = v["client"].get(url, headers=v["headers"], params={"section": "objects"}).json()
    assert view["total"] == summary["code_member_count"] == summary["object_count"]
    assert all(item["code_reference"] for item in view["items"])
    assert not any(item["type"] == "System" for item in view["items"])


def test_single_file_with_no_dependency_edges_is_not_padded_to_pass_a_count_gate(evidence_api):
    v = evidence_api
    _, old, old_url = selected(v)
    old_view = v["client"].get(old_url, headers=v["headers"]).json()
    old_header, old_ref, _ = ImageRevisionRepository().get(v["project_id"], old["image_revision_id"])
    v["path"].write_text("VALUE = 1\n", encoding="utf-8")
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    list_url = f"/v1/projects/{v['project_id']}/system-image/revisions"
    images = v["client"].get(list_url, headers=v["headers"]).json()["items"]
    new = next(item for item in images if item["image_revision_id"] != old["image_revision_id"])
    members = v["client"].get(f"{list_url}/{new['image_revision_id']}", headers=v["headers"],
        params={"section": "members"}).json()
    assert new["object_count"] == new["code_member_count"] == 1
    assert members["total"] == 1 and members["items"][0]["kind"] == "code_entity"
    assert new["relationship_count"] == 0
    assert new["status"] == "candidate" and new["publication"] == "blocked_pending_revision_governance"
    assert v["client"].get(old_url, headers=v["headers"]).json() == old_view
    assert ImageRevisionRepository().get(v["project_id"], old["image_revision_id"])[:2] == (old_header, old_ref)
    assert snapshot_digest(old_view) == snapshot_digest(v["client"].get(old_url, headers=v["headers"]).json())


def test_legacy_root_artifact_remains_readable_and_unchanged_after_new_build(evidence_api):
    v = evidence_api
    operations = app.state.container.system_image.lifecycle._operations
    frozen = operations.source_snapshots.latest_manifest(v["project_id"])
    baseline = f"base_{v['project_id']}_official"
    legacy = operations.context_extraction.extract(project_id=v["project_id"], project_name="Legacy display",
        baseline_id=baseline, sources=operations.source_snapshots.materialization_sources(frozen),
        version_id=None, captured_at="2026-10-08T00:00:00+00:00")
    # A historical-contract fixture, not a second production write authority.
    assert any(item.type == "System" and item.code_reference is None for item in legacy.objects)
    header = operations.image_candidates.freeze(frozen, baseline, objects=legacy.objects,
        relationships=legacy.relationships, invocation_id=None, recorded_at="2026-10-08T00:00:00+00:00")
    url = f"/v1/projects/{v['project_id']}/system-image/revisions/{header.image_revision_id}"
    before = v["client"].get(url, headers=v["headers"]).json()
    original = ImageRevisionRepository().get(v["project_id"], header.image_revision_id)
    v["path"].write_text("VALUE = 2\n", encoding="utf-8")
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    current = v["client"].get(f"/v1/projects/{v['project_id']}/system-image", headers=v["headers"]).json()
    assert current["source_manifest"]["manifest_id"] != frozen.manifest_id
    assert len(current["objects"]) == 1 and current["objects"][0]["code_reference"]
    assert v["client"].get(url, headers=v["headers"]).json() == before
    assert ImageRevisionRepository().get(v["project_id"], header.image_revision_id) == original


def test_single_file_initialization_reuses_manifest_validation_without_publishing(evidence_api):
    v = evidence_api
    v["path"].write_text("VALUE = 3\n", encoding="utf-8")
    v["invoke"]("system_image.sources.ingest")
    pending = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "conversation_id": v["conversation"].json()["id"], "tool_id": "system_image.baseline.initialize",
        "input": {"project_id": v["project_id"]}})
    assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
    with session_scope() as session:
        assert session.scalars(select(ImagePublicationHeadRecord).where(
            ImagePublicationHeadRecord.project_id == v["project_id"])).first() is None
    confirmed = v["client"].post(f"/v1/tool-invocations/{pending.json()['id']}/confirm", headers=v["headers"])
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "completed", confirmed.text
    current = v["client"].get(f"/v1/projects/{v['project_id']}/system-image", headers=v["headers"]).json()
    assert current["project"]["system_image_status"] == "ready"
    assert len(current["objects"]) == 1 and current["objects"][0]["code_reference"]
    operations = app.state.container.system_image.lifecycle._operations
    with session_scope() as session:
        assert session.scalars(select(ImagePublicationHeadRecord).where(
            ImagePublicationHeadRecord.project_id == v["project_id"])).first() is None
    assert operations.source_snapshots.latest_manifest(v["project_id"]).manifest_id == current["source_manifest"]["manifest_id"]
