from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.reference_link_models import (
    ReferenceProposalRecord, ReferenceAssertionRecord, ReferenceProposalInvocationRecord,
)
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_document_projection_api import documents, REQUIREMENT, CASE
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_access_api import grant_member


def candidate(v):
    image = v["client"].get(v["image_url"], params={"view": "working"}, headers=v["headers"]).json()
    rows = v["client"].get(f"{v['image_url']}/revisions", headers=v["headers"]).json()["items"]
    return next(row for row in rows if row["manifest_id"] == image["source_manifest"]["manifest_id"])


def invoke(v, image=None, headers=None, extra=None):
    response = v["client"].post("/v1/tool-invocations", headers=headers or v["headers"], json={
        "tool_id": "system_image.links.propose_references", "conversation_id": v["conversation"].json()["id"],
        "input": {"project_id": v["project_id"], "image_revision_id": (image or candidate(v))["image_revision_id"], **(extra or {})},
    })
    return response


def proposal(v, image=None):
    response = invoke(v, image)
    assert response.status_code == 200 and response.json()["status"] == "completed", response.text
    ident = response.json()["result"]["object_refs"][0].split(":", 1)[1]
    url = f"{v['image_url']}/reference-proposals/{ident}"
    result = v["client"].get(url, headers=v["headers"])
    assert result.status_code == 200, result.text
    assert result.headers["cache-control"] == "private, no-store"
    assert "payload_ref" not in result.text and "local-object://" not in result.text
    return result.json(), url, response


def test_canonical_references_are_pinned_audited_idempotent_and_not_coverage(documents):
    v = documents
    image = candidate(v)
    saved, url, result = proposal(v, image)
    assert saved["assertion_count"] == 1 and saved["gap_count"] == 0 and saved["document_count"] == 3
    edge, = saved["items"]
    assert edge["predicate"] == "references" and edge["reference_id"] == "US-17" and edge["status"] == "proposed"
    assert saved["publication"] == "not_in_image_membership"
    assert "Empty input" not in result.text and "US-17" not in result.text
    assert proposal(v, image)[0] == saved
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(ReferenceProposalRecord).where(
            ReferenceProposalRecord.project_id == v["project_id"])) == 1
        assert session.scalar(select(func.count()).select_from(ReferenceAssertionRecord).where(
            ReferenceAssertionRecord.project_id == v["project_id"])) == 1
    for object_key, evidence_key in (("subject_object_id", "subject_evidence_ids"), ("object_id", "object_evidence_ids")):
        for ident in edge[evidence_key]:
            evidence = v["client"].get(f"{v['image_url']}/revisions/{image['image_revision_id']}/objects/{edge[object_key]}/evidence/{ident}", headers=v["headers"])
            assert evidence.status_code == 200 and "US-17" in evidence.json()["content"]
    v["requirement_path"].write_text(REQUIREMENT.replace("400", "422"))
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    changed, _, _ = proposal(v)
    assert changed["digest"] != saved["digest"]
    assert changed["items"][0]["object_revision_id"] != edge["object_revision_id"]
    v["requirement_path"].unlink()
    v["case_path"].unlink()
    assert v["client"].get(url, headers=v["headers"]).json() == saved
    assert proposal(v, image)[0] == saved


def test_missing_and_ambiguous_targets_remain_gaps_not_relationships(documents):
    v = documents
    v["case_path"].write_text(CASE.replace("US-17", "US-170, US-17"))
    duplicate = v["requirement_path"].parent / "duplicate.md"
    duplicate.write_text(REQUIREMENT.replace("Search", "Different requirement"))
    v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "us_doc", "source_uri": str(duplicate)}]})
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    saved, url, _ = proposal(v)
    assert saved["assertion_count"] == 0 and saved["gap_count"] == 2
    gaps = v["client"].get(url, params={"section": "gaps", "limit": 1}, headers=v["headers"]).json()
    assert gaps["next_offset"] == 1
    second = v["client"].get(url, params={"section": "gaps", "offset": 1}, headers=v["headers"]).json()
    rows = gaps["items"] + second["items"]
    assert {row["reason"] for row in rows} == {"ambiguous_reference_target", "target_not_in_selected_image"}
    assert len(next(row for row in rows if row["reference_id"] == "US-17")["candidate_object_ids"]) == 2


def test_reference_scope_and_write_role_are_rechecked(documents, monkeypatch):
    v = documents
    saved, url, _ = proposal(v)
    assert v["client"].get(url).status_code == 401
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 403
    grant_member(v)
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 200
    denied = invoke(v, headers=v["member_headers"])
    assert denied.status_code == 403 or denied.json().get("status") in {"denied", "failed"}, denied.text
    repository = SourceAccessRepository()
    record = app.state.container.reference_links.repository
    original = record.get
    binding = v["client"].get(v["image_url"], headers=v["headers"]).json()["source_manifest"]["members"][-1]["binding_id"]

    def revoke(*args):
        value = original(*args)
        snapshot = repository.load_snapshot(v["project_id"])
        repository.set_policy(v["project_id"], binding, SourceAccessRule("restricted"), expected_epoch=snapshot.acl_epoch,
                              changed_by=v["owner"]["id"], invocation_id="references-read-revoked")
        return value

    monkeypatch.setattr(record, "get", revoke)
    denied = v["client"].get(url, headers=v["member_headers"])
    assert denied.status_code in (403, 409) and "US-17" not in denied.text
    monkeypatch.setattr(record, "get", original)
    other = v["client"].post("/v1/projects", headers=v["headers"], json={"name": f"Other {uuid4().hex}"}).json()["id"]
    assert v["client"].get(f"/v1/projects/{other}/system-image/reference-proposals/{saved['proposal_id']}", headers=v["headers"]).status_code == 404


def test_reference_rows_append_only_and_outbox_failure_rolls_back(documents, monkeypatch):
    v = documents
    append = EventOutboxRepository.append

    def fail(self, event, **kwargs):
        if event.event_type == "system_image.references.proposed":
            raise RuntimeError("outbox unavailable")
        return append(self, event, **kwargs)

    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    response = invoke(v)
    assert response.status_code == 200 and response.json()["status"] == "failed", response.text
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(ReferenceProposalRecord).where(
            ReferenceProposalRecord.project_id == v["project_id"])) == 0
    monkeypatch.setattr(EventOutboxRepository, "append", append)
    saved, _, _ = proposal(v)
    for model in (ReferenceProposalRecord, ReferenceAssertionRecord, ReferenceProposalInvocationRecord):
        for statement in (update(model).where(model.project_id == v["project_id"]).values(project_id="other"),
                          delete(model).where(model.project_id == v["project_id"])):
            with pytest.raises(IntegrityError, match="append-only"):
                with session_scope() as session:
                    session.execute(statement)
    with session_scope() as session:
        row = session.scalar(select(ReferenceAssertionRecord).where(ReferenceAssertionRecord.proposal_id == saved["proposal_id"]))
        values = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    values.update(assertion_id=str(uuid4()), ordinal=55, object_revision_id=values["subject_revision_id"])
    with pytest.raises(IntegrityError):
        with session_scope() as session:
            session.add(ReferenceAssertionRecord(**values))


def test_invalid_input_and_forged_source_evidence_fail_closed(documents, monkeypatch):
    v = documents
    assert invoke(v, extra={"accept": True}).json()["status"] == "failed"
    images = app.state.container.image_revisions
    original = images.read_evidence
    monkeypatch.setattr(images, "read_evidence", lambda *args, **kwargs: replace(original(*args, **kwargs), content="US-170 only"))
    result = invoke(v)
    assert result.status_code == 200 and result.json()["status"] == "failed", result.text
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(ReferenceProposalRecord).where(
            ReferenceProposalRecord.project_id == v["project_id"])) == 0


def test_reference_query_receipt_is_body_free_replayable_and_revocable(documents, monkeypatch):
    v = documents
    saved, url, _ = proposal(v)
    query = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "tool_id": "query.system_image.references.read", "conversation_id": v["conversation"].json()["id"],
        "input": {"project_id": v["project_id"], "proposal_id": saved["proposal_id"]},
    })
    assert query.status_code == 200 and query.json()["status"] == "completed", query.text
    receipt = query.json()["result"]["image_query"]
    assert receipt["operation"] == "references" and receipt["assertion_ids"] == [saved["items"][0]["assertion_id"]]
    assert "US-17" not in query.text and "Empty input" not in query.text
    endpoint = f"/v1/tool-invocations/{query.json()['id']}/image-query"
    expanded = v["client"].get(endpoint, headers=v["headers"])
    assert expanded.status_code == 200 and expanded.json() == saved
    original = app.state.container.reference_links.repository.get
    monkeypatch.setattr(app.state.container.reference_links.repository, "get",
        lambda *args: replace(original(*args), digest="sha256:" + "0" * 64))
    assert v["client"].get(endpoint, headers=v["headers"]).status_code == 502
    monkeypatch.setattr(app.state.container.reference_links.repository, "get", original)
    grant_member(v)
    assert v["client"].get(endpoint, headers=v["member_headers"]).status_code == 200
    repository = SourceAccessRepository()
    snapshot = repository.load_snapshot(v["project_id"])
    repository.set_policy(v["project_id"], snapshot.bindings[0].binding_id, SourceAccessRule("restricted"),
        expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="reference-query-revoke")
    denied = v["client"].get(endpoint, headers=v["member_headers"])
    assert denied.status_code == 403 and "US-17" not in denied.text


def test_role_revoked_during_reference_derivation_does_not_commit(documents, monkeypatch):
    v = documents
    member_url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(member_url, headers=v["headers"], json={"role": "tester"}).status_code == 200
    images = app.state.container.image_revisions
    original = images.read_evidence
    revoked = []

    def revoke(*args, **kwargs):
        result = original(*args, **kwargs)
        if not revoked:
            assert v["client"].put(member_url, headers=v["headers"], json={"role": "viewer"}).status_code == 200
            revoked.append(True)
        return result

    monkeypatch.setattr(images, "read_evidence", revoke)
    response = invoke(v, headers=v["member_headers"])
    assert response.status_code == 200 and response.json()["status"] == "failed", response.text
    assert revoked
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(ReferenceProposalRecord).where(
            ReferenceProposalRecord.project_id == v["project_id"])) == 0
