"""Original fixed exweb source reads; companion documents are not business gold."""
from collections import Counter
from dataclasses import asdict
from hashlib import sha256

from sqlalchemy import event
from sqlalchemy.engine import Engine

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.system_image import image_revision_queries as queries
from apps.api.app.application.system_image.generation_sources import ImageGenerationSourceInventory
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.main import app
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_exweb_context_read_measurement import evidence_api
from apps.api.tests.test_image_selection_copies_postgres import image_id


def read_inventory(value, revision_id, monkeypatch, *, whole_copy):
    images = app.state.container.image_revisions
    storage = images.artifacts.storage
    original_payload, original_copy, original_get = images._verified_payload, queries.deepcopy, storage.get_bytes
    counts, objects = Counter(), {}

    def copied(item):
        if type(item) is dict and "source_members" in item and "membership_hash" not in item:
            counts["full_copies"] += 1
        return original_copy(item)

    def control(*args, **kwargs):
        kwargs.pop("copy_payload", None)
        return original_payload(*args, **kwargs)

    def archive(ref, **kwargs):
        content = original_get(ref, **kwargs)
        digest = sha256(content).hexdigest()
        assert ref not in objects or objects[ref] == digest
        objects[ref] = digest
        counts["object_reads"] += 1
        return content

    def readonly(connection):
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")

    def statement(_connection, _cursor, sql, _parameters, _context, _many):
        counts["sql"] += 1
        assert sql.lstrip().split(None, 1)[0].upper() not in {"INSERT", "UPDATE", "DELETE"}
        assert "FOR UPDATE" not in sql.upper()

    event.listen(Engine, "begin", readonly)
    event.listen(Engine, "before_cursor_execute", statement)
    try:
        with monkeypatch.context() as scoped, actor_scope(UserProfile.model_validate(value["owner"])):
            scoped.setattr(queries, "deepcopy", copied)
            scoped.setattr(storage, "get_bytes", archive)
            if whole_copy:
                scoped.setattr(images, "_verified_payload", control)
            with images.verified_read_session():
                summary, full = images.frozen_snapshot(value["project_id"], revision_id)
                source_header, members = images.frozen_source_members(value["project_id"], revision_id)
                assert source_header == summary and list(members) == full["source_members"]
                source = next(item for item in members if item["binding_id"] == value["exweb_binding"])
                assert source["source_revision_id"] == value["measured_exweb_source"]["source_revision_id"]
                assert source["status"] == "captured" and value["measured_exweb_source"]["file_count"] == 126
                code_members = [item for item in full["members"] if item["kind"] == "code_entity"
                    and item["source_revision_id"] == source["source_revision_id"]]
                assert len(code_members) == 725
                prepared = {"project_id": value["project_id"], "context_pin": {
                    "image_revision_id": revision_id, "image_artifact_hash": summary.artifact_hash},
                    "context": {"source_manifest_id": summary.manifest_id, "source_manifest_hash": summary.manifest_hash}}
                inventory = ImageGenerationSourceInventory(images)
                views = {"header": asdict(summary), "image_hash": snapshot_digest(full),
                    "source_members": members, "generation": inventory.bindings(prepared),
                    "automation": inventory.automation_bindings(prepared), "run_plan": inventory.run_plan_sources(prepared)}
                assert views["generation"] == views["automation"] == tuple(sorted(
                    item["binding_id"] for item in members if item["status"] == "captured"))
                assert views["run_plan"]["source_members"] == full["source_members"]
                assert images.frozen_snapshot(value["project_id"], revision_id)[1] == full
                return views, counts, objects
    finally:
        event.remove(Engine, "before_cursor_execute", statement)
        event.remove(Engine, "begin", readonly)


def test_original_exweb_sources_and_all_graph_proofs_match_without_generation_whole_copies(documents, monkeypatch):
    revision_id = image_id(documents)
    before, control, before_objects = read_inventory(documents, revision_id, monkeypatch, whole_copy=True)
    after, production, after_objects = read_inventory(documents, revision_id, monkeypatch, whole_copy=False)
    assert before == after and before_objects == after_objects and before_objects
    assert production["full_copies"] == 2 and control["full_copies"] == 6
    assert production["sql"] == control["sql"]
    assert production["object_reads"] == control["object_reads"]
    assert app.state.container.image_revisions._current_verified_reads() is None
