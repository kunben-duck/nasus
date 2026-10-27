"""Real PostgreSQL/private MinIO preview; no model, script or target execution."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.automation_inputs import AutomationInputSelection
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.db_models import LLMCallRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.image_revision_models import ImageObjectMemberRecord
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceBindingRecord, SourceRevisionRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage
from apps.api.app.infrastructure.system_image.source_snapshot_archive import SourceSnapshotArchive
from apps.api.tests.test_source_evidence_api import evidence_api as base_evidence_api
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_image_publications_api import publication
from apps.api.tests.test_test_design_scope_api import design_scope, submit as scope_submit
from apps.api.tests.test_test_design_results_api import generation_result, read_result
from apps.api.tests.test_test_design_mapping_api import mapping, submit, inspect
from apps.api.tests.test_semantic_evaluations_api import completed, count
from apps.api.tests.test_source_access_api import grant_member
from apps.api.tests.test_automation_mapping_parent_postgres import measure_input_read


@pytest.fixture
def evidence_api(base_evidence_api, request, tmp_path):
    v = base_evidence_api
    if getattr(request.node, "originalname", None) not in {"test_fixed_exweb_automation_input_preserves_source_and_oracle_pins",
            "test_fixed_exweb_native_script_draft_preserves_source_case_step_and_oracle_pins",
            "test_fixed_exweb_native_script_review_keeps_original_oracles_and_zero_execution",
            "test_fixed_exweb_script_case_admission_consumes_original_pins",
            "test_fixed_exweb_run_plan_preserves_all_native_source_pins_and_declares_unverified_target",
            "test_fixed_exweb_v3_script_review_plan_preserves_sources_and_original_obligations",
            "test_fixed_exweb_fixture_operation_consent_preserves_all_source_pins",
            "test_fixed_exweb_fixture_dispatch_consent_atomicity_and_unknown_result",
            "test_fixed_exweb_case_admission_preserves_all_source_pins"}:
        return v
    root = os.getenv("EXWEB_SOURCE_REFRESH_GIT_ROOT")
    if not root:
        pytest.skip("explicit reviewed fixed exweb Git export required")
    from apps.api.tests.exweb_git_trees import AFTER, read_git_tree
    files, tree_hash, _ = read_git_tree(Path(root), AFTER)
    assert len(files) == 126
    exported = tmp_path / "fixed-exweb-automation-input"
    exported.mkdir()
    for name, content in files:
        path = exported / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "code", "source_uri": str(exported)}]})
    v["invoke"]("system_image.sources.ingest")
    v.update(exweb_commit=AFTER, exweb_tree_hash=tree_hash, exweb_file_count=len(files),
        exweb_exported=exported, exweb_files=dict(files))
    return v


def accepted(v):
    completed(submit(v))
    return inspect(v).json()["head"]


def preview(v, head, *, headers=None, case_ids=None, artifact_hash=None):
    ids = case_ids if case_ids is not None else head["assessment"]["accepted_case_ids"]
    return v["client"].get(f"/v1/projects/{v['project_id']}/quality/test-design-mapping-reviews/"
        f"{head['revision']['revision_id']}/automation-input-preview", headers=headers or v["headers"],
        params=[("artifact_hash", artifact_hash or head["revision"]["artifact_hash"]), *[("case_ids", ident) for ident in ids]])


def invocation_count(v):
    with session_scope() as session:
        return session.scalar(select(func.count()).select_from(ToolInvocationRecord).where(
            ToolInvocationRecord.conversation_id == v["conversation"].json()["id"]))


def test_http_automation_input_is_fixed_private_and_does_not_write_or_call_models(mapping, monkeypatch):
    v = mapping
    head = accepted(v)
    counts = (count(v, LLMCallRecord), invocation_count(v))
    def no_model(*args, **kwargs):
        raise AssertionError("automation preparation cannot resolve a model or dispatch a runner")
    monkeypatch.setattr(v["result_service"].profiles, "resolve", no_model)
    response = preview(v, head)
    assert response.status_code == 200, response.text
    value = response.json()
    assert response.headers["cache-control"] == "private, no-store"
    assert value["generation_pin"]["artifact_hash"] == v["generation_metadata"]["artifact_hash"]
    assert value["mapping_pin"]["artifact_hash"] == head["revision"]["artifact_hash"]
    assert value["required_constraints"] and value["cases"] and value["obligations"]
    assert value["constraint_denominator"] == head["assessment"]["coverage"]["constraint_denominator"]
    assert value["obligation_denominator"] == head["assessment"]["coverage"]["obligation_denominator"]
    assert value["readiness"]["status"] == "blocked" and not value["generation_authorized"] and not value["execution_authorized"]
    assert value["automated_count"] == value["executed_on_target_count"] == value["passed_count"] == 0
    assert "raw_output" not in response.text and "artifact_ref" not in response.text and "s3://" not in response.text
    assert "synthetic-result-fixture-key" not in response.text
    assert preview(v, head).json() == value
    assert (count(v, LLMCallRecord), invocation_count(v)) == counts
    assert read_result(v, v["generation_metadata"]).json() == v["original_result"]


def test_preview_does_not_drop_mandatory_or_unreviewed_cases(mapping):
    v = mapping
    request = deepcopy(v["mapping_request"])
    request["mappings"][0]["decision"] = "defer"
    completed(submit(v, request))
    head = inspect(v).json()["head"]
    denied = preview(v, head)
    assert denied.status_code == 409, denied.text
    assert denied.json()["detail"]["error"]["code"] == "automation_input_incomplete"
    completed(submit(v, {**v["mapping_request"], "expected_previous_revision_id": head["revision"]["revision_id"]}))
    head = inspect(v).json()["head"]
    assert preview(v, head, case_ids=head["assessment"]["accepted_case_ids"][1:]).status_code == 409
    assert preview(v, head, case_ids=["foreign-case"]).status_code == 409
    first = head["assessment"]["accepted_case_ids"][0]
    assert preview(v, head, case_ids=[first, first]).status_code == 422
    assert preview(v, head, case_ids=[]).status_code == 422
    assert preview(v, head, artifact_hash=acceptance_digest("other")).status_code == 502


def test_preview_requires_current_membership_and_cannot_read_another_project(mapping):
    v = mapping
    head = accepted(v)
    url = f"/v1/projects/{v['project_id']}/quality/test-design-mapping-reviews/{head['revision']['revision_id']}/automation-input-preview"
    params = [("artifact_hash", head["revision"]["artifact_hash"]),
        *[("case_ids", ident) for ident in head["assessment"]["accepted_case_ids"]]]
    assert v["client"].get(url, params=params).status_code == 401
    assert preview(v, head, headers=v["member_headers"]).status_code == 403
    grant_member(v)
    assert preview(v, head, headers=v["member_headers"]).status_code == 200
    other = v["client"].post("/v1/projects", headers=v["headers"], json={"name": "Unrelated automation input"}).json()["id"]
    response = v["client"].get(url.replace(v["project_id"], other), headers=v["headers"], params=params)
    assert response.status_code == 404 and "cases" not in response.text


@pytest.mark.parametrize("dependency", ["mapping", "scope"])
def test_preview_rejects_withdrawn_dependencies_but_preserves_archived_draft(mapping, dependency):
    v = mapping
    head = accepted(v)
    assert preview(v, head).status_code == 200
    if dependency == "mapping":
        completed(submit(v, {**v["mapping_request"], "expected_previous_revision_id": head["revision"]["revision_id"],
            "decision": "withdraw", "mappings": None}))
    else:
        completed(scope_submit(v, {**v["scope_request"], "expected_previous_revision_id": v["execution"]["request"].scope_revision_id,
            "decision": "withdraw", "contract": None}))
    assert preview(v, head).status_code == 409
    assert read_result(v, v["generation_metadata"]).json()["result"] == v["original_result"]["result"]


def test_preview_rechecks_source_access_and_discards_partial_data_after_revocation(mapping, monkeypatch):
    v = mapping
    head = accepted(v)
    grant_member(v)
    assert preview(v, head, headers=v["member_headers"]).status_code == 200
    original = app.state.container.automation_inputs.results.read
    revoked = False
    def revoke(project, generation):
        nonlocal revoked
        value = original(project, generation)
        if not revoked:
            revoked = True
            repository = SourceAccessRepository()
            snapshot = repository.load_snapshot(v["project_id"])
            repository.set_policy(v["project_id"], v["evidence"]["binding_id"], SourceAccessRule("restricted"),
                expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id=uuid4().hex)
        return value
    monkeypatch.setattr(app.state.container.automation_inputs.results, "read", revoke)
    response = preview(v, head, headers=v["member_headers"])
    assert response.status_code in {403, 409}, response.text
    assert "HTTP 400" not in response.text and "cases" not in response.text
    monkeypatch.setattr(app.state.container.automation_inputs.results, "read", original)
    assert preview(v, head, headers=v["member_headers"]).status_code == 403
    assert preview(v, head).status_code == 200


def test_preview_verifies_draft_archive_instead_of_trusting_review_summary(mapping, monkeypatch):
    v = mapping
    head = accepted(v)
    original = v["result_service"].artifacts.read
    def corrupt(project, ref, digest):
        value = original(project, ref, digest)
        if digest == v["generation_metadata"]["artifact_hash"]:
            value["proposal"]["cases"][0]["steps"] = ["secret-corrupted-source"]
        return value
    monkeypatch.setattr(v["result_service"].artifacts, "read", corrupt)
    response = preview(v, head)
    assert response.status_code == 502 and "secret-corrupted-source" not in response.text


def test_fixed_exweb_automation_input_preserves_source_and_oracle_pins(mapping, monkeypatch):
    v = mapping
    head = accepted(v)
    response = preview(v, head)
    assert response.status_code == 200, response.text
    value = response.json()
    assert v["exweb_file_count"] == 126
    assert value["context_pin"] == v["original_result"]["result"]["context_pin"]
    assert value["scope_pin"] == v["original_result"]["result"]["scope_pin"]
    assert value["input_digest"] == acceptance_digest({key: item for key, item in value.items() if key != "input_digest"})
    source_pin, member_count = verify_fixed_exweb_archive(v, value)
    service = app.state.container.automation_inputs
    selection = AutomationInputSelection(project_id=v["project_id"], mapping_revision_id=head["revision"]["revision_id"],
        mapping_artifact_hash=head["revision"]["artifact_hash"], case_ids=tuple(head["assessment"]["accepted_case_ids"]))
    legacy = SimpleNamespace(read=service.mappings.read, resolve=service.mappings.resolve)
    before, control, before_objects = measure_input_read(v, selection, "prepare", legacy, monkeypatch)
    after, production, after_objects = measure_input_read(v, selection, "prepare", service.mappings, monkeypatch)
    assert before == after and before_objects == after_objects and before_objects
    assert value == json.loads(json.dumps(after))
    assert control["results"] == 4 and production["results"] == 2
    assert control["generation"] == production["generation"] == 2
    assert production["sql"] < control["sql"] and production["objects"] < control["objects"]
    report = os.getenv("EXWEB_AUTOMATION_INPUT_REPORT")
    if report:
        with Path(report).open("x") as output:
            json.dump({"schema": "nasus.exweb-automation-input-verification.v1", "verified_at": datetime.now(timezone.utc).isoformat(),
                "repository": "https://github.com/kunben-duck/exweb.git", "commit": v["exweb_commit"],
                "tree_hash": v["exweb_tree_hash"], "exweb_file_count": 126,
                "exweb_source_pin": source_pin, "exweb_frozen_code_member_count": member_count,
                "all_126_archived_blobs_equal_fixed_git_tree": True,
                "oracle_basis": "explicit_protocol_fixture_not_exweb_maintainer_approval",
                "additional_code_source": "isolated Orders protocol fixture", "postgres_private_minio": True,
                "context_pin": value["context_pin"], "scope_pin": value["scope_pin"],
                "generation_pin": value["generation_pin"], "mapping_pin": value["mapping_pin"],
                "input_digest": value["input_digest"], "constraint_denominator": value["constraint_denominator"],
                "verified_parent_read_comparison": {"control": dict(control), "production": dict(production),
                    "full_input_and_original_object_bytes_equal": True, "transactions_read_only": True},
                "obligation_denominator": value["obligation_denominator"], "selected_case_count": len(value["cases"]),
                "readiness": value["readiness"], "script_generation_verified": False, "target_execution_verified": False,
                "native_provider_verified": False, "external_model_verified": False,
                "all_five_context_purposes_verified": False, "full_quality_closure_verified": False}, output, indent=2)


def verify_fixed_exweb_archive(v, value):
    with actor_scope(UserProfile.model_validate(v["owner"])):
        image, payload = app.state.container.image_revisions.frozen_snapshot(v["project_id"], value["context_pin"]["image_revision_id"])
    assert image.artifact_hash == value["context_pin"]["image_artifact_hash"]
    with session_scope() as session:
        binding = session.scalar(select(SourceBindingRecord).where(SourceBindingRecord.project_id == v["project_id"],
            SourceBindingRecord.external_identity == str(v["exweb_exported"])))
        source = next(item for item in payload["source_members"] if item["binding_id"] == binding.binding_id)
        assert source["status"] == "captured" and source["source_type"] == "code"
        revision = session.get(SourceRevisionRecord, source["source_revision_id"])
        assert revision.binding_id == binding.binding_id and revision.file_count == 126
        source_pin = {key: getattr(revision, key) for key in ("source_revision_id", "content_hash", "manifest_hash", "file_count")}
        binding_id, source_id, ref = binding.binding_id, binding.legacy_source_id, revision.manifest_ref
        registered = session.scalars(select(ImageObjectMemberRecord).where(
            ImageObjectMemberRecord.project_id == v["project_id"],
            ImageObjectMemberRecord.image_revision_id == image.image_revision_id,
            ImageObjectMemberRecord.binding_id == binding_id,
            ImageObjectMemberRecord.source_revision_id == source_pin["source_revision_id"],
            ImageObjectMemberRecord.kind == "code_entity")).all()
        registered_pins = {(item.object_id, item.entity_id, item.entity_revision_id) for item in registered}
    exweb_members = [item for item in payload["members"] if item["kind"] == "code_entity"
        and item["source_revision_id"] == source_pin["source_revision_id"]]
    assert exweb_members and all(item["evidence_ids"] for item in exweb_members)
    assert {(item["object_id"], item["entity_id"], item["entity_revision_id"]) for item in exweb_members} == registered_pins
    storage = ObjectStorage()
    assert storage.config.s3_enabled, "This example requires real private MinIO, not local object storage"
    with storage.read_session():
        archived = SourceSnapshotArchive(storage).read_manifest(ref, project_id=v["project_id"], source_id=source_id,
            content_hash=source_pin["content_hash"], manifest_hash=source_pin["manifest_hash"], max_files=5000,
            max_bytes=100 * 1024 * 1024, max_file_bytes=10 * 1024 * 1024)
        assert {item["path"] for item in archived["files"]} == set(v["exweb_files"])
        for item in archived["files"]:
            assert storage.get_bytes(item["content_ref"], max_bytes=10 * 1024 * 1024) == v["exweb_files"][item["path"]]
    return source_pin, len(exweb_members)
