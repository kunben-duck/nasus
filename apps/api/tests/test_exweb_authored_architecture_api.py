"""Opt-in pilot with exweb's authored architecture and optional unapproved trial drafts."""
from collections import Counter
import hashlib
import os
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import make_url

from apps.api.app.domain.system_image.evidence import source_lines, text_digest
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceRevisionRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.main import app
from apps.api.tests.exweb_git_trees import AFTER, git_bytes, read_git_tree


@pytest.mark.parametrize("with_drafts", [False, True], ids=["authored_only", "review_drafts"])
def test_authored_architecture_is_archived_evidence_not_an_approved_requirement(tmp_path, monkeypatch, with_drafts):
    approved_root = os.getenv("EXWEB_SOURCE_REFRESH_GIT_ROOT")
    if not approved_root:
        pytest.skip("explicit reviewed exweb Git export required")
    assert os.environ.get("NASUS_TEST_OBJECT_STORAGE_MODE") == "minio"
    db = make_url(os.environ["NASUS_DATABASE_URL"])
    assert db.get_backend_name() == "postgresql" and db.database.startswith("nasus_test_")
    root = Path(approved_root)
    status = ("--no-optional-locks", "status", "--porcelain", "--untracked-files=all")
    assert git_bytes(root, "rev-parse", "HEAD").strip().decode() == AFTER
    assert not git_bytes(root, *status)
    files, _, _ = read_git_tree(root, AFTER)
    assert len(files) == 126
    architecture_path = "docs/architecture/README.md"
    original = dict(files)[architecture_path]
    controller_path, controller_bytes = next((path, body) for path, body in files if path.endswith("/ChatSessionController.java"))
    assert git_bytes(root, "rev-parse", f"{AFTER}:{architecture_path}").strip() == b"fa428f2ae7e7b226a12465e101d61e81813583d0"
    assert hashlib.sha256(original).hexdigest() == "3461cd786d1416b60bb8d5099961d38bcb1f9b008ba47ed4f846ce5e434614a0"
    exported = tmp_path / "exweb"
    for name, body in files:
        path = exported / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    document = exported / architecture_path
    source_specs = [{"source_type": "code", "source_uri": str(exported)},
        {"source_type": "us_doc", "source_uri": str(document)}]
    draft_files = []
    if with_drafts:
        trial = Path(__file__).resolve().parents[3] / "docs/examples/exweb"
        for kind, name in (("us_doc", "session-isolation-draft.md"), ("test_asset", "session-isolation-cases.csv")):
            path = tmp_path / name
            path.write_bytes((trial / name).read_bytes())
            source_specs.append({"source_type": kind, "source_uri": str(path)})
            draft_files.append(path)

    monkeypatch.setattr(app.state, "auth_config", replace(
        app.state.auth_config, mode="required", bearer_token=uuid4().hex))
    with TestClient(app) as client:
        def ok(response):
            assert response.status_code == 200, response.text
            return response.json()

        account = ok(client.post("/v1/auth/register", json={"email": f"pilot-{uuid4().hex}@example.com",
            "name": "Exweb pilot reviewer", "password": "exweb-pilot-password-123"}))
        headers = {"Authorization": f"Bearer {account['access_token']}"}

        def get(url, **params):
            return ok(client.get(url, headers=headers, params=params))

        project = ok(client.post("/v1/projects", headers=headers, json={"name": "Exweb authored architecture"}))["id"]
        conversation = ok(client.post("/v1/conversations", headers=headers, json={
            "space_type": "project", "space_id": project, "title": "Exweb pilot"}))["id"]

        def invoke(tool_id, **inputs):
            body = ok(client.post("/v1/tool-invocations", headers=headers, json={"conversation_id": conversation,
                "tool_id": tool_id, "input": {"project_id": project, **inputs}}))
            assert body["status"] == "completed", body
            return body

        invoke("system_image.sources.register", source_specs=source_specs)
        invoke("system_image.sources.ingest")
        invoke("system_image.context.materialize")
        # Both reads must use the original archived bytes.
        document.unlink()
        (exported / controller_path).unlink()
        for path in draft_files:
            path.unlink()

        url = f"/v1/projects/{project}/system-image"
        image = get(url)
        manifest = image["source_manifest"]
        revisions = {m["source_revision_id"]: m["source_type"] for m in manifest["members"] if m["status"] == "captured"}
        assert Counter(revisions.values()) == ({"code": 1, "us_doc": 2, "test_asset": 1} if with_drafts else {"code": 1, "us_doc": 1})
        code_revision = next(ident for ident, kind in revisions.items() if kind == "code")
        with session_scope() as session:
            rows = {row.source_revision_id: row for row in session.scalars(select(SourceRevisionRecord).where(
                SourceRevisionRecord.project_id == project))}
            assert set(rows) == set(revisions)
            assert all(row.manifest_ref.startswith("s3://nasus-test-") for row in rows.values())
            assert rows[code_revision].file_count == len(files)
            assert all(rows[ident].file_count == 1 for ident, kind in revisions.items() if kind != "code")

        header = next(row for row in get(f"{url}/revisions")["items"] if row["manifest_id"] == manifest["manifest_id"])
        assert header["status"] == "candidate" and header["publication"] == "blocked_pending_revision_governance"
        revision_url = f"{url}/revisions/{header['image_revision_id']}"
        documents = {obj["id"]: get(f"{revision_url}/objects/{obj['id']}/document")
            for obj in image["objects"] if obj.get("document_reference")}
        document_id, archived = next((ident, item) for ident, item in documents.items()
            if item["projection"]["kind"] == "requirement_document")
        document_url = f"{revision_url}/objects/{document_id}"
        assert revisions[archived["document"]["source_revision_id"]] == "us_doc"
        projection = archived["projection"]
        assert projection["kind"] == "requirement_document" and projection["external_id"] is None
        assert projection["semantic_status"] == "source_projection_not_approved_specification"
        assert projection["source_file_hash"] == text_digest(original.decode("utf-8"))
        assert set(projection["gaps"]) == {"missing_acceptance_criterion", "no_explicit_record_identity"}
        assert {field["name"] for field in archived["fields"]} == {"description"}
        evidence_url = f"{document_url}/evidence/{archived['evidence'][0]['evidence_id']}"
        excerpt = get(evidence_url, start_line=315, max_lines=21)
        assert excerpt["integrity"] == "verified"
        assert excerpt["content"] == "".join(source_lines(original.decode("utf-8"))[314:335])
        assert client.get(evidence_url).status_code == 401

        controller = next(obj for obj in image["objects"] if obj["name"] == f"ChatSessionController ({controller_path})")
        ref = controller["code_reference"]
        assert ref["source_revision_id"] == code_revision
        spans = get(f"{url}/evidence", source_revision_id=code_revision, object_id=controller["id"],
            entity_revision_id=ref["entity_revision_id"])
        assert len(spans) == 1
        code = get(f"{revision_url}/objects/{controller['id']}/evidence/{spans[0]['evidence_id']}", max_lines=15)
        controller_lines = source_lines(controller_bytes.decode("utf-8"))
        assert code["integrity"] == "verified" and "class ChatSessionController" in code["content"]
        assert code["content"] == "".join(controller_lines[code["start_line"] - 1:code["end_line"]])

        preview = get(f"{url}/context-packs/preview", image_revision_id=header["image_revision_id"],
            image_artifact_hash=header["artifact_hash"])["context"]
        assert preview["readiness"]["status"] == "blocked"
        constraints = preview["required_constraints"]
        if with_drafts:
            assert len(constraints) == 4
            assert {item["object_id"] for item in constraints} == {ident for ident, item in documents.items()
                if item["projection"]["kind"] in {"acceptance_criterion", "business_rule"}}
            assert all(item["semantic_class"] == "pending_confirmation" and item["oracle"] is None
                and item["authority"]["status"] == "unapproved" and item["authority"]["revision_id"] is None
                for item in constraints)
            assert "unapproved_mandatory_constraint" in preview["readiness"]["reason_codes"]
            assert_trial_references(invoke, get, url, revision_url, header, documents)
        else:
            assert constraints == [] and len(documents) == 1

    assert git_bytes(root, "rev-parse", "HEAD").strip().decode() == AFTER
    assert not git_bytes(root, *status)


def assert_trial_references(invoke, get, url, revision_url, header, documents):
    projections = {item["projection"]["external_id"]: (ident, item["projection"]) for ident, item in documents.items()}
    requirement_id = "US-EXWEB-SESSION"
    requirement_object, requirement = projections[requirement_id]
    case_ids = {"TC-EXWEB-SESSION-OWNER", "TC-EXWEB-SESSION-USER", "TC-EXWEB-SESSION-TENANT"}
    assert {ident for ident, (_, item) in projections.items() if item["kind"] == "test_case"} == case_ids
    assert {ident for ident, (_, item) in projections.items() if item["kind"] == "acceptance_criterion"} == {
        "AC-EXWEB-SESSION-OWNER", "AC-EXWEB-SESSION-USER", "AC-EXWEB-SESSION-TENANT"}
    assert requirement["semantic_status"] == "source_projection_not_approved_specification"
    assert all(projections[case][1]["reference_semantics"] == "references_only_not_asserts_or_implements" for case in case_ids)
    result = invoke("system_image.links.propose_references", image_revision_id=header["image_revision_id"])
    proposal_id = result["result"]["object_refs"][0].split(":", 1)[1]
    proposal = get(f"{url}/reference-proposals/{proposal_id}")
    assert proposal["assertion_count"] == 3 and proposal["gap_count"] == 0
    assert proposal["publication"] == "not_in_image_membership"
    assert {edge["subject_object_id"] for edge in proposal["items"]} == {projections[case][0] for case in case_ids}
    for edge in proposal["items"]:
        assert edge["reference_id"] == requirement_id and edge["object_id"] == requirement_object
        assert edge["predicate"] == "references" and edge["semantic_kind"] == "observed" and edge["status"] == "proposed"
        for endpoint, evidence in (("subject_object_id", "subject_evidence_ids"), ("object_id", "object_evidence_ids")):
            assert edge[evidence]
            for ident in edge[evidence]:
                archived = get(f"{revision_url}/objects/{edge[endpoint]}/evidence/{ident}")
                assert archived["integrity"] == "verified" and requirement_id in archived["content"]
