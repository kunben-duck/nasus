"""Private PG/MinIO allocation comparison; documents are protocol specimens."""
from collections import Counter
from dataclasses import asdict
from hashlib import sha256

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.system_image import image_revision_queries as queries
from apps.api.app.application.system_image.generation_sources import ImageGenerationSourceInventory
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.main import app
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_access_api import grant_member, policy


def image_id(value):
    with actor_scope(UserProfile.model_validate(value["owner"])):
        items = app.state.container.image_revisions.list(value["project_id"]).items
    return next(item.image_revision_id for item in items if item.manifest_id == value["document_manifest_id"])


def full_read(value, revision_id, monkeypatch, *, copy_whole_image):
    images = app.state.container.image_revisions
    storage = images.artifacts.storage
    original_payload, original_copy, original_bytes = images._verified_payload, queries.deepcopy, storage.get_bytes
    counts, objects = Counter(), {}

    def copied(item):
        if type(item) is dict and "source_members" in item and "membership_hash" not in item:
            counts["complete_payload_copies"] += 1
        return original_copy(item)

    def complete_copy(*args, **kwargs):
        kwargs.pop("copy_payload", None)
        return original_payload(*args, **kwargs)

    def archive(ref, **kwargs):
        content = original_bytes(ref, **kwargs)
        digest = sha256(content).hexdigest()
        assert ref not in objects or objects[ref] == digest
        objects[ref] = digest
        counts["objects"] += 1
        return content

    def begin(connection):
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")

    def statement(_connection, _cursor, sql, _parameters, _context, _many):
        counts["sql"] += 1
        assert sql.lstrip().split(None, 1)[0].upper() not in {"INSERT", "UPDATE", "DELETE"}
        assert "FOR UPDATE" not in sql.upper()

    event.listen(Engine, "begin", begin)
    event.listen(Engine, "before_cursor_execute", statement)
    try:
        with monkeypatch.context() as scoped, actor_scope(UserProfile.model_validate(value["owner"])):
            scoped.setattr(queries, "deepcopy", copied)
            scoped.setattr(storage, "get_bytes", archive)
            if copy_whole_image:
                scoped.setattr(images, "_verified_payload", complete_copy)
            with images.verified_read_session():
                summary, payload = images.frozen_snapshot(value["project_id"], revision_id)
                views = {"snapshot_hash": snapshot_digest(payload), "summary": asdict(summary), "pages": {},
                    "documents": [], "evidence": []}
                for section in ("objects", "relationships", "members", "source_members", "assertion_members", "semantic_assertion_members"):
                    offset, pages = 0, []
                    while offset is not None:
                        page = images.read(value["project_id"], revision_id, section=section, offset=offset, limit=2)
                        pages.append(asdict(page))
                        offset = page.next_offset
                    views["pages"][section] = pages
                header, members = images.frozen_document_members(value["project_id"], revision_id)
                assert header == summary
                views["document_members"] = members
                source_header, source_members = images.frozen_source_members(value["project_id"], revision_id)
                assert source_header == summary and list(source_members) == payload["source_members"]
                views["source_members"] = source_members
                prepared = {"project_id": value["project_id"], "context_pin": {
                    "image_revision_id": revision_id, "image_artifact_hash": summary.artifact_hash},
                    "context": {"source_manifest_id": summary.manifest_id, "source_manifest_hash": summary.manifest_hash}}
                inventory = ImageGenerationSourceInventory(images)
                views["generation_sources"] = inventory.bindings(prepared)
                views["automation_sources"] = inventory.automation_bindings(prepared)
                views["run_plan_sources"] = inventory.run_plan_sources(prepared)
                selection = []
                for member in payload["members"]:
                    if member["kind"] == "source_document":
                        views["documents"].append(images.read_document(value["project_id"], revision_id, member["object_id"]))
                    for ident in member["evidence_ids"]:
                        selection.append((member["object_id"], ident))
                        views["evidence"].append(asdict(images.read_evidence(value["project_id"], revision_id,
                            member["object_id"], ident)))
                assert selection and len(selection) <= 512
                images.verify_evidence_selection(value["project_id"], revision_id, tuple(selection))
                assert images.frozen_snapshot(value["project_id"], revision_id)[1] == payload
                return views, counts, objects
    finally:
        event.remove(Engine, "before_cursor_execute", statement)
        event.remove(Engine, "begin", begin)


def test_complete_original_pages_documents_and_evidence_match_without_whole_image_copy(documents, monkeypatch):
    if engine.dialect.name != "postgresql":
        pytest.skip("an isolated PostgreSQL database is required")
    ident = image_id(documents)
    before, control, before_objects = full_read(documents, ident, monkeypatch, copy_whole_image=True)
    after, production, after_objects = full_read(documents, ident, monkeypatch, copy_whole_image=False)
    assert before == after and before_objects == after_objects and before_objects
    assert production["complete_payload_copies"] == 2 < control["complete_payload_copies"]
    assert production["objects"] == control["objects"]
    assert production["sql"] == control["sql"]


def test_live_revocation_in_same_pg_snapshot_blocks_selected_reads(documents):
    value = documents
    ident = image_id(value)
    grant_member(value)
    images = app.state.container.image_revisions
    with actor_scope(UserProfile.model_validate(value["member"])), images.verified_read_session():
        images.read(value["project_id"], ident, section="objects", limit=1)
        header, _ = images.frozen_source_members(value["project_id"], ident)
        prepared = {"project_id": value["project_id"], "context_pin": {
            "image_revision_id": ident, "image_artifact_hash": header.artifact_hash},
            "context": {"source_manifest_id": header.manifest_id, "source_manifest_hash": header.manifest_hash}}
        inventory = ImageGenerationSourceInventory(images)
        policy(value)
        for read in (lambda: images.read(value["project_id"], ident, section="objects", limit=1),
                     lambda: images.frozen_document_members(value["project_id"], ident),
                     lambda: images.frozen_source_members(value["project_id"], ident),
                     lambda: inventory.bindings(prepared),
                     lambda: inventory.automation_bindings(prepared),
                     lambda: inventory.run_plan_sources(prepared),
                     lambda: images.verify_evidence_selection(value["project_id"], ident,
                        ((value["obj"]["id"], value["evidence"]["evidence_id"]),))):
            with pytest.raises(SourceAccessDenied):
                read()
