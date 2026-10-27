import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.domain.system_image.image_revision import ImageObjectMember, ImageRevisionIntegrityError
from apps.api.app.infrastructure.persistence.document_projection_models import SourceDocumentRevisionRecord
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_document_projection_api import documents, REQUIREMENT, read
from apps.api.tests.test_source_access_api import grant_member
from apps.api.tests.test_source_evidence_api import evidence_api


def component(v):
    return next(item for item in v["document_objects"] if item["type"] == "SourceAcceptanceCriterion")


def test_source_ac_revision_has_independent_identity_evidence_and_frozen_parent(documents):
    v = documents
    obj = component(v)
    original, _ = read(v, obj)
    parent = next(item for item in v["document_objects"] if item["type"] == "USWorkItem")
    parent_page, _ = read(v, parent)
    assert original["document"]["parent_document_revision_id"] == parent_page["document"]["document_revision_id"]
    assert original["projection"]["parent"]["payload_hash"] == parent_page["payload_hash"]
    assert original["projection"]["authority_status"] == "pending_confirmation"
    assert original["fields"] == [parent_page["fields"][i] for i in original["projection"]["parent"]["field_indices"]]
    assert original["evidence"] and all(row["start_line"] == 4 for row in original["evidence"])
    v["requirement_path"].write_text("\n\n" + REQUIREMENT.replace("400", "422"))
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    image = v["client"].get(v["image_url"], headers=v["headers"]).json()
    changed = next(item for item in image["objects"] if item["id"] == obj["id"])
    latest, _ = read(v, changed)
    assert latest["document"]["entity_id"] == original["document"]["entity_id"]
    for field in ("document_revision_id", "parent_document_revision_id", "source_revision_id"):
        assert latest["document"][field] != original["document"][field]
    assert latest["fields"][0]["start_line"] == 6 and "422" in latest["fields"][0]["value"]
    v["requirement_path"].unlink()
    assert read(v, obj)[0] == original


def test_components_cannot_be_frozen_without_the_exact_parent_and_migration_cannot_drop_them(documents):
    v = documents
    obj = component(v)
    page, _ = read(v, obj)
    parent_id = page["document"]["parent_document_revision_id"]
    root = f"{v['image_url']}/revisions"
    header = next(item for item in v["client"].get(root, headers=v["headers"]).json()["items"]
                  if item["manifest_id"] == v["document_manifest_id"])
    payload = v["client"].get(f"{root}/{header['image_revision_id']}", headers=v["headers"],
                            params={"section": "members", "limit": 100}).json()
    members = tuple(ImageObjectMember(**{**item, "evidence_ids": tuple(item["evidence_ids"])})
                    for item in payload["items"] if item.get("document_revision_id") != parent_id)
    repository = app.state.container.image_revisions.repository
    _, ref, _ = repository.get(v["project_id"], header["image_revision_id"])
    manifest = SourceSnapshotRepository().get_manifest(v["project_id"], header["manifest_id"])
    with pytest.raises(ImageRevisionIntegrityError, match="document member"):
        repository.record(manifest, header["baseline_id"], artifact_ref=ref, artifact_hash=header["artifact_hash"],
            members=members, relationship_count=0, invocation_id=None, recorded_at="now")
    with session_scope() as session:
        row = session.get(SourceDocumentRevisionRecord, page["document"]["document_revision_id"])
        values = {col.name: getattr(row, col.name) for col in SourceDocumentRevisionRecord.__table__.columns}
    foreign_parent = next(item["document_reference"]["document_revision_id"] for item in v["document_objects"]
                          if item["type"] == "TestCase")
    for parent in (None, "missing-parent", foreign_parent, "self"):
        with pytest.raises(IntegrityError):
            with session_scope() as session:
                new_id = str(uuid4())
                session.execute(SourceDocumentRevisionRecord.__table__.insert().values(
                    {**values, "document_revision_id": new_id, "payload_hash": "sha256:" + uuid4().hex * 2,
                     "parent_document_revision_id": new_id if parent == "self" else parent}))
    path = Path(__file__).resolve().parents[1] / "migrations/versions/0046_requirement_components.py"
    spec = importlib.util.spec_from_file_location("requirement_component_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with session_scope() as session:
        migration.op = Operations(MigrationContext.configure(session.connection()))
        with pytest.raises(RuntimeError, match="component revisions exist"):
            migration.downgrade()
    assert read(v, obj)[0] == page


def test_business_rules_and_same_ac_ids_in_other_requirements_are_separate(documents):
    v = documents
    v["requirement_path"].write_text(REQUIREMENT + "## Business rules\nBR-1: Authenticated users only.\n"
        + REQUIREMENT.replace("US-17", "US-18").replace("Search", "Other"))
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    image = v["client"].get(v["image_url"], headers=v["headers"]).json()
    acs = [item for item in image["objects"] if item["type"] == "SourceAcceptanceCriterion"]
    assert len(acs) == 2 and acs[0]["id"] != acs[1]["id"]
    pages = [read(v, item)[0] for item in acs]
    assert {page["projection"]["parent"]["external_id"] for page in pages} == {"US-17", "US-18"}
    assert {page["projection"]["external_id"] for page in pages} == {"AC-1"}
    rule = next(item for item in image["objects"] if item["type"] == "SourceBusinessRule")
    rule_page, _ = read(v, rule)
    assert rule_page["projection"]["parent"]["external_id"] == "US-17"
    assert rule_page["projection"]["external_id"] == "BR-1"
    assert rule_page["projection"]["authority_status"] == "pending_confirmation"


def test_parent_artifact_is_reverified_and_acl_revocation_during_parent_read_fails_closed(documents, monkeypatch):
    from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
    from apps.api.app.domain.system_image.source_access import SourceAccessRule
    v = documents
    grant_member(v)
    obj = component(v)
    page, url = read(v, obj)
    artifacts = app.state.container.source_documents.artifacts
    original = artifacts.read
    calls = []

    def corrupt_parent(*args):
        payload = original(*args)
        calls.append(payload["kind"])
        if payload["kind"] == "requirement":
            return {**payload, "title": "forged-parent-title"}
        return payload

    monkeypatch.setattr(artifacts, "read", corrupt_parent)
    response = v["client"].get(url, headers=v["member_headers"])
    assert response.status_code == 502 and "Empty input" not in response.text
    assert calls == ["acceptance_criterion", "requirement"]

    def revoke_parent(*args):
        payload = original(*args)
        if payload["kind"] == "requirement":
            access = SourceAccessRepository()
            scope = access.load_snapshot(v["project_id"])
            access.set_policy(v["project_id"], page["document"]["binding_id"], SourceAccessRule("restricted"),
                expected_epoch=scope.acl_epoch, changed_by=v["owner"]["id"], invocation_id="component-parent-read-revoke")
        return payload

    monkeypatch.setattr(artifacts, "read", revoke_parent)
    response = v["client"].get(url, headers=v["member_headers"])
    assert response.status_code in (403, 409) and "Empty input" not in response.text


def test_pre_component_v1_image_and_receipt_remain_unchanged_after_reextraction(evidence_api, monkeypatch):
    from apps.api.app.domain.system_image import document_projection
    from apps.api.app.infrastructure.system_image import archived_document_projection
    from apps.api.tests.test_image_query_tools_api import invoke, completed, expansion
    v = evidence_api
    path = v["path"].parent / "legacy-requirement.md"
    path.write_text(REQUIREMENT)
    v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "us_doc", "source_uri": str(path)}]})
    v["invoke"]("system_image.sources.ingest")
    with monkeypatch.context() as legacy:
        legacy.setattr(document_projection, "DOCUMENT_EXTRACTOR", "nasus.explicit-document.v1")
        legacy.setattr(archived_document_projection, "DOCUMENT_EXTRACTOR", "nasus.explicit-document.v1")
        legacy.setattr(archived_document_projection, "component_payloads", lambda *args: iter(()))
        v["invoke"]("system_image.context.materialize")
    v["image_url"] = f"/v1/projects/{v['project_id']}/system-image"
    image = v["client"].get(v["image_url"], headers=v["headers"]).json()
    obj, = [item for item in image["objects"] if item.get("document_reference")]
    original, _ = read(v, obj)
    assert original["projection"]["extractor_version"] == "nasus.explicit-document.v1"
    assert "parent_document_revision_id" not in original["document"]
    root = f"{v['image_url']}/revisions"
    header = next(item for item in v["client"].get(root, headers=v["headers"]).json()["items"]
                  if item["manifest_id"] == image["source_manifest"]["manifest_id"])
    receipt = completed(invoke(v, "document", {"image_revision_id": header["image_revision_id"], "object_id": obj["id"]}))
    expanded = expansion(v, receipt).json()
    v["invoke"]("system_image.context.materialize")
    updated = v["client"].get(v["image_url"], headers=v["headers"]).json()
    assert any(item["type"] == "SourceAcceptanceCriterion" for item in updated["objects"])
    new_parent = next(item for item in updated["objects"] if item["id"] == obj["id"])
    assert new_parent["document_reference"]["document_revision_id"] != obj["document_reference"]["document_revision_id"]
    assert read(v, obj)[0] == original
    assert expansion(v, receipt).json() == expanded
    old_page = v["client"].get(f"{root}/{header['image_revision_id']}", headers=v["headers"])
    assert old_page.status_code == 200 and old_page.json()["revision"]["artifact_hash"] == header["artifact_hash"]
