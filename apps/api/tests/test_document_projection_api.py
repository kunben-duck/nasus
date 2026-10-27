"""Requirements/cases are immutable source projections, not quality-loop authoring records."""
import pytest
from sqlalchemy import func, select, update, delete
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.infrastructure.persistence.document_projection_models import (
    SourceDocumentIdentityRecord, SourceDocumentRevisionRecord, SourceDocumentEvidenceRecord, SourceDocumentExtractionRecord,
)
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_access_api import grant_member


REQUIREMENT = "# US-17 Search\nDescription: Search the code catalog.\n## Acceptance criteria\nAC-1: Empty input returns HTTP 400.\n"
CASE = "# TC-9 Search validation\nReferences: US-17\nPreconditions: Authenticated user\nSteps: POST /search with empty input\nExpected result: HTTP 400\n"


@pytest.fixture
def documents(evidence_api, request):
    v = evidence_api
    requirement = v["path"].parent / "requirements.md"
    testcase = v["path"].parent / "cases.md"
    ac_count = getattr(request, "param", 1)
    content = REQUIREMENT if ac_count == 1 else "# US-17 Search\nDescription: Search the code catalog.\n## Acceptance criteria\n" + "".join(
        f"AC-{index}: Input variant {index} returns HTTP 400.\n" for index in range(1, ac_count + 1))
    requirement.write_text(content)
    testcase.write_text(CASE)
    v["invoke"]("system_image.sources.register", {"source_specs": [
        {"source_type": "us_doc", "source_uri": str(requirement)}, {"source_type": "test_asset", "source_uri": str(testcase)}]})
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    image_url = f"/v1/projects/{v['project_id']}/system-image"
    image = v["client"].get(image_url, headers=v["headers"]).json()
    objects = [item for item in image["objects"] if item.get("document_reference")]
    assert len(objects) == ac_count + 2
    v.update(requirement_path=requirement, case_path=testcase, document_objects=objects, image_url=image_url,
             document_manifest_id=image["source_manifest"]["manifest_id"])
    return v


def read(v, obj):
    url = f"{v['image_url']}/source-documents/{obj['document_reference']['document_revision_id']}"
    response = v["client"].get(url, headers=v["headers"])
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert "payload_ref" not in response.text and "local-object://" not in response.text
    return response.json(), url


def test_canonical_write_projection_archived_artifacts_and_frozen_field_evidence(documents):
    v = documents
    before = []
    for obj in v["document_objects"]:
        body, url = read(v, obj)
        before.append(body)
        projection = body["projection"]
        assert projection["semantic_status"] == "source_projection_not_approved_specification"
        if projection["kind"] == "test_case":
            assert projection["references"] == ["US-17"]
            assert projection["reference_semantics"] == "references_only_not_asserts_or_implements"
            assert {field["name"] for field in body["fields"]} >= {"step", "expected_result"}
        else:
            assert any(field["name"] == "acceptance_criterion" for field in body["fields"])
        listed = v["client"].get(f"{v['image_url']}/source-documents", headers=v["headers"], params={
            "source_revision_id": obj["document_reference"]["source_revision_id"]})
        assert listed.status_code == 200 and len(listed.json()["items"]) == (1 if projection["kind"] == "test_case" else 2)
        assert obj["document_reference"]["document_revision_id"] in {item["document_revision_id"] for item in listed.json()["items"]}
        assert v["client"].get(url).status_code == 401
        assert v["client"].get(url, headers=v["member_headers"]).status_code == 403
    candidates = v["client"].get(f"{v['image_url']}/revisions", headers=v["headers"]).json()["items"]
    current = next(item for item in candidates if item["manifest_id"] == v["document_manifest_id"])
    revision_url = f"{v['image_url']}/revisions/{current['image_revision_id']}"
    members = v["client"].get(revision_url, headers=v["headers"], params={"section": "members", "limit": 100}).json()["items"]
    for obj in v["document_objects"]:
        member = next(item for item in members if item["object_id"] == obj["id"])
        assert member["kind"] == "source_document" and member["evidence_ids"]
        projected = v["client"].get(f"{revision_url}/objects/{obj['id']}/document", headers=v["headers"])
        assert projected.status_code == 200, projected.text
        assert projected.json()["document"]["document_revision_id"] == member["document_revision_id"]
        for evidence_id in member["evidence_ids"]:
            response = v["client"].get(f"{revision_url}/objects/{obj['id']}/evidence/{evidence_id}", headers=v["headers"])
            assert response.status_code == 200, response.text
            assert response.json()["integrity"] == "verified"
    v["invoke"]("system_image.context.materialize")
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(SourceDocumentRevisionRecord).where(
            SourceDocumentRevisionRecord.project_id == v["project_id"])) == 3
    v["requirement_path"].write_text("\n\n" + REQUIREMENT.replace("400", "422"))
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    v["requirement_path"].unlink()
    updated = v["client"].get(v["image_url"], headers=v["headers"]).json()
    old_obj = next(item for item in v["document_objects"] if item["name"] == "Search")
    new_obj = next(item for item in updated["objects"] if item["id"] == old_obj["id"])
    assert new_obj["document_reference"] != old_obj["document_reference"]
    old_projection, _ = read(v, old_obj)
    new_projection, _ = read(v, new_obj)
    assert old_projection["document"]["entity_id"] == new_projection["document"]["entity_id"]
    assert "422" in str(new_projection["fields"])
    for obj, original in zip(v["document_objects"], before):
        assert read(v, obj)[0] == original
    for model in (SourceDocumentIdentityRecord, SourceDocumentRevisionRecord, SourceDocumentEvidenceRecord, SourceDocumentExtractionRecord):
        for statement in (update(model).where(model.project_id == v["project_id"]).values(project_id="other"),
                          delete(model).where(model.project_id == v["project_id"])):
            with pytest.raises(IntegrityError, match="append-only"):
                with session_scope() as session:
                    session.execute(statement)


def test_document_acl_rechecked_after_artifact_read_and_corruption_fails_closed(documents, monkeypatch):
    v = documents
    grant_member(v)
    body, url = read(v, v["document_objects"][0])
    artifacts = app.state.container.source_documents.artifacts
    original = artifacts.read
    calls = []

    def revoke(*args):
        payload = original(*args)
        repo = SourceAccessRepository()
        snapshot = repo.load_snapshot(v["project_id"])
        repo.set_policy(v["project_id"], body["document"]["binding_id"], SourceAccessRule("restricted"),
            expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="document-read-revoke")
        calls.append(True)
        return payload

    monkeypatch.setattr(artifacts, "read", revoke)
    result = v["client"].get(url, headers=v["member_headers"])
    assert result.status_code in (403, 409) and "Empty input" not in result.text
    assert calls == [True]
    result = v["client"].get(url, headers=v["member_headers"])
    assert result.status_code == 404 and calls == [True]
    monkeypatch.setattr(artifacts, "read", lambda *args: {**original(*args), "schema": "wrong"})
    result = v["client"].get(url, headers=v["headers"])
    assert result.status_code == 502 and "Empty input" not in result.text


def test_source_filtered_knowledge_preserves_visible_document_without_cross_source_names(documents):
    v = documents
    grant_member(v)
    case = next(item for item in v["document_objects"] if item["name"] == "Search validation")
    hidden, _ = read(v, case)
    repository = SourceAccessRepository()
    snapshot = repository.load_snapshot(v["project_id"])
    repository.set_policy(v["project_id"], hidden["document"]["binding_id"], SourceAccessRule("restricted"),
        expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="document-knowledge-filter")
    response = v["client"].get(v["image_url"], headers=v["member_headers"])
    assert response.status_code == 200, response.text
    assert response.json()["visibility"]["mode"] == "source_filtered"
    assert case["id"] not in response.text and "Search validation" not in response.text
    visible = [item for item in response.json()["objects"] if item.get("document_reference")]
    assert len(visible) == 2 and any(item["name"] == "Search" for item in visible)
    assert all(item["relations"] == [] and item["evidence"] == [] for item in visible)
    detail = v["client"].get(f"/v1/projects/{v['project_id']}/knowledge/{visible[0]['id']}", headers=v["member_headers"])
    assert detail.status_code == 200 and detail.json() == visible[0]
    unavailable = v["client"].get(f"/v1/projects/{v['project_id']}/knowledge/{case['id']}", headers=v["member_headers"])
    assert unavailable.status_code == 404


def test_duplicate_document_ids_are_not_merged_and_failed_formats_are_recorded(evidence_api):
    v = evidence_api
    root = v["path"].parent / "documents"
    root.mkdir()
    (root / "a.md").write_text(REQUIREMENT)
    (root / "b.md").write_text(REQUIREMENT.replace("Search", "Different requirement"))
    (root / "bad.csv").write_text('id,title\nUS-2,"unclosed')
    (root / "unsupported.xml").write_text("<spec>not a verified document adapter</spec>")
    v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "us_doc", "source_uri": str(root)}]})
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    v["image_url"] = f"/v1/projects/{v['project_id']}/system-image"
    image = v["client"].get(v["image_url"], headers=v["headers"]).json()
    objects = [item for item in image["objects"] if item.get("document_reference")]
    assert len(objects) == 4 and len({item["id"] for item in objects}) == 4
    for obj in objects:
        payload, _ = read(v, obj)
        if payload["projection"]["kind"] == "requirement":
            assert payload["projection"]["identity_status"] == "ambiguous"
            assert "duplicate_external_id" in payload["projection"]["gaps"]
        else:
            assert payload["projection"]["identity_status"] == "source_occurrence"
            assert "parent_identity_not_unique" in payload["projection"]["gaps"]
    with session_scope() as session:
        report = session.scalar(select(SourceDocumentExtractionRecord).where(SourceDocumentExtractionRecord.project_id == v["project_id"]))
        assert report.summary == {"file_count": 4, "entity_count": 4, "parsed": 2, "failed": 1, "unsupported": 1, "not_analyzed": 0}
        extraction_id, source_revision_id = report.extraction_id, report.source_revision_id
    reports_url = f"{v['image_url']}/source-document-extractions"
    listed = v["client"].get(reports_url, headers=v["headers"], params={"source_revision_id": source_revision_id})
    assert listed.status_code == 200 and listed.json()["items"][0]["extraction_id"] == extraction_id
    result = v["client"].get(f"{reports_url}/{extraction_id}", headers=v["headers"], params={"limit": 2})
    assert result.status_code == 200, result.text
    assert result.json()["next_offset"] == 2 and result.json()["total_files"] == 4
    assert "report_ref" not in result.text and "local-object://" not in result.text
    second = v["client"].get(f"{reports_url}/{extraction_id}", headers=v["headers"], params={"offset": 2})
    assert {row["status"] for row in second.json()["files"]} == {"failed", "unsupported"}
    assert v["client"].get(f"{reports_url}/{extraction_id}", headers=v["member_headers"]).status_code == 403


def test_document_outbox_failure_does_not_commit_entities_or_image(evidence_api, monkeypatch):
    from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
    from apps.api.app.infrastructure.persistence.image_revision_models import ImageRevisionRecord
    v = evidence_api
    path = v["path"].parent / "requirement.md"
    path.write_text(REQUIREMENT)
    v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "us_doc", "source_uri": str(path)}]})
    v["invoke"]("system_image.sources.ingest")
    append = EventOutboxRepository.append

    def fail(self, event, *args, **kwargs):
        if event.event_type == "system_image.documents.projected":
            raise RuntimeError("document outbox unavailable")
        return append(self, event, *args, **kwargs)

    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    response = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "conversation_id": v["conversation"].json()["id"], "tool_id": "system_image.context.materialize",
        "input": {"project_id": v["project_id"]}})
    assert response.status_code == 200 and response.json()["status"] == "failed", response.text
    with session_scope() as session:
        for model in (SourceDocumentIdentityRecord, SourceDocumentRevisionRecord, SourceDocumentEvidenceRecord, SourceDocumentExtractionRecord):
            assert session.scalar(select(func.count()).select_from(model).where(model.project_id == v["project_id"])) == 0
        assert session.scalar(select(func.count()).select_from(ImageRevisionRecord).where(ImageRevisionRecord.project_id == v["project_id"])) == 1


def test_document_tool_is_audited_body_free_and_reauthorizes_frozen_inputs(documents, monkeypatch):
    import json
    from apps.api.tests.test_image_query_tools_api import invoke, completed, expansion
    from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord, ToolInvocationRecord
    from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository

    v = documents
    grant_member(v)
    candidates = v["client"].get(f"{v['image_url']}/revisions", headers=v["headers"]).json()["items"]
    current = next(item for item in candidates if item["manifest_id"] == v["document_manifest_id"])
    obj = next(item for item in v["document_objects"] if item["name"] == "Search")
    pins = {"image_revision_id": current["image_revision_id"], "object_id": obj["id"], "limit": 1}
    result = completed(invoke(v, "document", pins, key="document-query"))
    assert completed(invoke(v, "document", pins, key="document-query"))["id"] == result["id"]
    receipt = result["result"]["image_query"]
    assert receipt["operation"] == "document" and receipt["next_offset"] == 1
    assert receipt["document_revision_id"] == obj["document_reference"]["document_revision_id"]
    assert "query.system_image.revisions.document" in result["result"]["next_recommended_tools"]
    page = expansion(v, result, v["member_headers"])
    assert page.status_code == 200 and page.json()["fields"][0]["value"] == "Search the code catalog.", page.text
    assert page.headers["cache-control"] == "private, no-store"
    next_page = completed(invoke(v, "document", {**pins, "offset": 1}))
    assert "Empty input" in expansion(v, next_page).text
    with session_scope() as session:
        record = session.get(ToolInvocationRecord, result["id"])
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == result["id"])).all()
        assert events and record.result_payload["image_query"] == receipt
        persisted = json.dumps(record.result_payload) + json.dumps([event.event_payload for event in events])
        assert not any(secret in persisted for secret in ("Search the code catalog", "Empty input", "requirements.md", "s3://", "local-object://"))
    restored = ConversationRepository().get_tool_invocation(result["id"])
    assert restored.result.image_query.model_dump(mode="json") == receipt
    # A document from another revision, or the code member, cannot bypass the frozen membership.
    for bad in ({"object_id": v["obj"]["id"]}, {"image_revision_id": "missing"}, {"limit": True}):
        denied = invoke(v, "document", {**pins, **bad})
        assert denied.status_code == 200 and denied.json()["status"] == "failed", denied.text
    v["requirement_path"].write_text(REQUIREMENT.replace("400", "422"))
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    v["requirement_path"].unlink()
    assert expansion(v, result).json() == page.json()
    # Hiding any contributing source invalidates expansion of the whole image.
    access = SourceAccessRepository()
    snapshot = access.load_snapshot(v["project_id"])
    binding = page.json()["document"]["binding_id"]
    access.set_policy(v["project_id"], binding, SourceAccessRule("restricted"), expected_epoch=snapshot.acl_epoch,
                      changed_by=v["owner"]["id"], invocation_id="document-tool-revocation")
    reads = []
    monkeypatch.setattr(app.state.container.source_documents.artifacts, "read", lambda *args: reads.append(args))
    denied = expansion(v, result, v["member_headers"])
    assert denied.status_code == 403 and "Search the code catalog" not in denied.text
    assert not reads
