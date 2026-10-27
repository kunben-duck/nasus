"""A draft fixes the target, but does not grant execution or publication."""
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from apps.api.app.main import app
from apps.api.app.infrastructure.persistence.build_plan_models import BuildPlanRecord
from apps.api.app.infrastructure.persistence.db_models import BaselineRecord, VersionRecord
from apps.api.app.infrastructure.persistence.build_authorization_models import BuildAuthorizationRecord
from apps.api.app.infrastructure.persistence.image_publication_models import ImagePublicationHeadRecord
from apps.api.app.domain.system_image.publication import PublicationChanged
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceBindingRecord
from apps.api.app.infrastructure.persistence.structure_build_models import StructureBuildArtifactRecord
from apps.api.app.infrastructure.persistence.image_revision_models import ImageRevisionRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_image_publications_api import publication, review, publish_request
from apps.api.tests.test_semantic_evaluations_api import invoke, completed
from apps.api.tests.test_build_plan_api import submit, urls
from apps.api.tests.test_structure_build_api import submit as prepare_structure, confirm
from apps.api.tests.test_agent_build_plan_api import goal_request, READ_BUILD_PLAN_TOOL
from apps.api.tests.test_agent_investigation_continuation import replace_graph, resume
from apps.api.tests.test_build_authorization_api import BUDGET
from apps.api.tests.test_source_access_api import grant_member


def target_url(v, baseline_id):
    return f"/v1/projects/{v['project_id']}/system-image/build-targets/{baseline_id}"


def fixed_request(v, *, baseline_id=None):
    if baseline_id is None:
        with session_scope() as session:
            baseline_id = session.scalar(select(BaselineRecord.id).where(BaselineRecord.project_id == v["project_id"]))
    response = v["client"].get(target_url(v, baseline_id), headers=v["headers"])
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    target = response.json()
    saved = submit(v, target=target)
    assert saved.status_code == 200 and saved.json()["status"] == "completed", saved.text
    ident = saved.json()["result"]["object_refs"][0].split(":", 1)[1]
    plan = v["client"].get(urls(v, ident)[1], headers=v["headers"]).json()
    assert plan["proposal"]["policy_version"] == "nasus.image-investigation-plan.v3"
    assert plan["proposal"]["intent"]["target"] == target
    return {"project_id": v["project_id"], "plan_id": ident, "plan_digest": plan["plan_digest"],
        "target_baseline_id": baseline_id}, plan


def changed_version(v, baseline_id):
    with session_scope() as session:
        version = VersionRecord(id=uuid4().hex, project_id=v["project_id"], name="Changed fixture version", branch_name="fixture")
        session.add(version)
        session.get(BaselineRecord, baseline_id).source_version_id = version.id


def test_target_selection_and_plan_are_private_pinned_and_not_grants(evidence_api):
    v = evidence_api
    fixed, plan = fixed_request(v)
    intent = plan["proposal"]["intent"]
    assert intent["scope_binding_ids"] == [item["binding_id"] for item in intent["sources"]]
    assert intent["expected_head_status"] == "resolved" and intent["expected_head"] is None
    assert plan["execution_authorizations"] == [] and plan["structural_artifacts"] == []
    url = target_url(v, fixed["target_baseline_id"])
    assert v["client"].get(url).status_code == 401
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 403
    grant_member(v)
    assert v["client"].get(url, headers=v["member_headers"]).json() == intent["target"]
    changed_version(v, fixed["target_baseline_id"])
    assert v["client"].get(urls(v, fixed["plan_id"])[1], headers=v["headers"]).json() == plan
    assert submit(v, target=intent["target"]).json()["status"] == "failed"
    assert v["client"].get(url, headers=v["headers"]).json()["target_version_id"] != intent["target"]["target_version_id"]


@pytest.mark.parametrize("change", ["project", "baseline", "version", "head", "hash", "missing-null"])
def test_mismatched_or_incomplete_target_cannot_save_a_draft(evidence_api, change):
    v = evidence_api
    with session_scope() as session:
        baseline_id = session.scalar(select(BaselineRecord.id).where(BaselineRecord.project_id == v["project_id"]))
    target = v["client"].get(target_url(v, baseline_id), headers=v["headers"]).json()
    if change == "project": target["project_id"] = "other"
    if change == "baseline": target["target_baseline_id"] = "missing"
    if change == "version": target["target_version_id"] = "different"
    if change == "head": target.update(expected_head_id="head", expected_head_hash="sha256:" + "a" * 64)
    if change == "hash": target["expected_head_hash"] = "sha256:" + "a" * 64
    if change == "missing-null": target.pop("expected_head_id")
    response = submit(v, target=target)
    assert response.status_code == 200 and response.json()["status"] == "failed", response.text
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(BuildPlanRecord).where(BuildPlanRecord.project_id == v["project_id"])) == 0


@pytest.mark.parametrize("kind", ["local", "langgraph_postgres"])
def test_agent_uses_the_original_target_and_archived_inputs_through_independent_consent(evidence_api, monkeypatch, kind):
    v = evidence_api
    replace_graph(monkeypatch, kind)
    fixed, original = fixed_request(v)
    response = goal_request(v, fixed, [(READ_BUILD_PLAN_TOOL, {key: fixed[key] for key in ("project_id", "plan_id")}),
        ("system_image.build.authorize", {**fixed, "budget": BUDGET}), ("system_image.build.structure", fixed)])
    assert response.status_code == 200, response.text
    goal = response.json()
    assert goal["pause_reason"] == "waiting_confirmation"
    assert v["client"].get(urls(v, fixed["plan_id"])[1], headers=v["headers"]).json() == original
    v["path"].unlink()
    replace_graph(monkeypatch, kind)
    built = resume(v, goal["id"], expected=goal)
    assert built["pause_reason"] == "structural_candidate_review", built
    saved = v["client"].get(urls(v, fixed["plan_id"])[1], headers=v["headers"]).json()
    assert saved["proposal"] == original["proposal"] and len(saved["structural_artifacts"]) == 1
    assert saved["execution_authorizations"][0]["target_baseline_id"] == original["proposal"]["intent"]["target"]["target_baseline_id"]
    assert saved["execution_authorizations"][0]["publication_allowed"] is False
    pending = resume(v, goal["id"], expected=built)
    assert pending["pause_reason"] == "waiting_confirmation"
    final = resume(v, goal["id"], expected=pending)
    assert final["id"] == goal["id"] and final["pause_reason"] == "build_completion_review" and final["model_calls_used"] == 0


@pytest.mark.parametrize("when", ["before-execution", "before-commit"])
def test_target_version_change_prevents_candidate_commit(evidence_api, monkeypatch, when):
    v = evidence_api
    fixed, plan = fixed_request(v)
    command = prepare_structure(v, fixed)
    with session_scope() as session:
        before = session.scalar(select(func.count()).select_from(ImageRevisionRecord).where(ImageRevisionRecord.project_id == v["project_id"]))
    if when == "before-execution":
        changed_version(v, fixed["target_baseline_id"])
    else:
        repository = app.state.container.structure_builds.preparation.candidates.repository
        original = repository.record
        def change_then_record(*args, **kwargs):
            changed_version(v, fixed["target_baseline_id"])
            return original(*args, **kwargs)
        monkeypatch.setattr(repository, "record", change_then_record)
    assert confirm(v, command)["status"] == "failed"
    with session_scope() as session:
        assert session.get(StructureBuildArtifactRecord, command) is None
        assert session.scalar(select(func.count()).select_from(ImageRevisionRecord).where(ImageRevisionRecord.project_id == v["project_id"])) == before
    assert v["client"].get(urls(v, fixed["plan_id"])[1], headers=v["headers"]).json() == plan


def test_a_new_publication_requires_a_new_intent_but_preserves_old_plan_history(publication):
    v = publication
    fixed, old_plan = fixed_request(v, baseline_id=v["target"]["target_baseline_id"])
    command = prepare_structure(v, fixed)
    approval, _ = review(v)
    published = completed(invoke(v, "baseline.promote", publish_request(v, approval)))
    assert confirm(v, command)["status"] == "failed"
    assert v["client"].get(urls(v, fixed["plan_id"])[1], headers=v["headers"]).json() == old_plan
    new_fixed, new_plan = fixed_request(v, baseline_id=fixed["target_baseline_id"])
    assert new_fixed["plan_id"] != fixed["plan_id"]
    assert new_plan["proposal"]["intent"]["target"]["expected_head_id"] == published["result"]["object_refs"][0].split(":", 1)[1]
    built = confirm(v, prepare_structure(v, new_fixed))
    assert built["status"] == "completed", built


def test_an_existing_baseline_cannot_replace_the_original_work_target(evidence_api):
    v = evidence_api
    fixed, plan = fixed_request(v)
    with session_scope() as session:
        other = BaselineRecord(id=uuid4().hex, project_id=v["project_id"], kind="version_working", status="draft",
            updated_at="fixture")
        session.add(other)
        baseline_id = other.id
    command = prepare_structure(v, {**fixed, "target_baseline_id": baseline_id})
    assert confirm(v, command)["status"] == "failed"
    with session_scope() as session:
        assert session.get(StructureBuildArtifactRecord, command) is None
    assert v["client"].get(urls(v, fixed["plan_id"])[1], headers=v["headers"]).json() == plan


@pytest.mark.parametrize("change", ["version", "canonical-input"])
def test_target_and_command_are_rechecked_before_plan_commit(evidence_api, monkeypatch, change):
    v = evidence_api
    with session_scope() as session:
        baseline_id = session.scalar(select(BaselineRecord.id).where(BaselineRecord.project_id == v["project_id"]))
    target = v["client"].get(target_url(v, baseline_id), headers=v["headers"]).json()
    repository = app.state.container.build_plans.repository
    original = repository.record
    def modify_then_record(*args, **kwargs):
        if change == "version":
            changed_version(v, baseline_id)
        else:
            from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
            with session_scope() as session:
                row = session.get(ToolInvocationRecord, kwargs["invocation_id"])
                row.input_payload = {**row.input_payload, "objective": "Different canonical intent"}
        return original(*args, **kwargs)
    monkeypatch.setattr(repository, "record", modify_then_record)
    assert submit(v, target=target).json()["status"] == "failed"
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(BuildPlanRecord).where(BuildPlanRecord.project_id == v["project_id"])) == 0


def test_a_changed_version_cannot_receive_execution_consent(evidence_api):
    v = evidence_api
    fixed, _ = fixed_request(v)
    goal = goal_request(v, fixed, [("system_image.build.authorize", {**fixed, "budget": BUDGET}),
        ("system_image.build.structure", fixed)]).json()
    assert goal["pause_reason"] == "waiting_confirmation"
    changed_version(v, fixed["target_baseline_id"])
    result = resume(v, goal["id"], expected=goal)
    assert result["status"] == "failed", result
    with session_scope() as session:
        assert session.scalar(select(BuildAuthorizationRecord).where(BuildAuthorizationRecord.goal_id == goal["id"])) is None


def test_missing_version_is_rejected_before_a_target_is_displayed(evidence_api):
    v = evidence_api
    with session_scope() as session:
        baseline = session.scalar(select(BaselineRecord).where(BaselineRecord.project_id == v["project_id"]))
        baseline_id = baseline.id
        baseline.source_version_id = "missing-version"
    response = v["client"].get(target_url(v, baseline_id), headers=v["headers"])
    assert response.status_code == 502 and response.json()["detail"]["error"]["code"] == "build_plan_integrity_failed", response.text
    assert "missing-version" not in response.text


def test_corrupt_publication_head_is_not_reported_as_invalid_user_input(publication):
    v = publication
    approval, _ = review(v)
    completed(invoke(v, "baseline.promote", publish_request(v, approval)))
    with session_scope() as session:
        session.get(ImagePublicationHeadRecord, (v["project_id"], v["target"]["target_baseline_id"])).sequence += 1
    try:
        response = v["client"].get(target_url(v, v["target"]["target_baseline_id"]), headers=v["headers"])
        assert response.status_code == 502 and response.json()["detail"]["error"]["code"] == "build_target_integrity_failed", response.text
        assert "s3://" not in response.text and v["publication_image"]["image_revision_id"] not in response.text
    finally:
        with session_scope() as session:
            session.get(ImagePublicationHeadRecord, (v["project_id"], v["target"]["target_baseline_id"])).sequence -= 1


def test_publication_race_has_a_safe_retryable_target_response(evidence_api, monkeypatch):
    v = evidence_api
    fixed, _ = fixed_request(v)
    def changed(*args, **kwargs):
        raise PublicationChanged("Private target details must not appear in the response")
    monkeypatch.setattr(app.state.container.image_publications, "history", changed)
    response = v["client"].get(target_url(v, fixed["target_baseline_id"]), headers=v["headers"])
    assert response.status_code == 409 and response.json()["detail"]["error"]["code"] == "build_target_changed", response.text
    assert "Private target details" not in response.text


def test_a_version_target_remains_pinned_in_the_artifact_and_execution_consent(evidence_api):
    v = evidence_api
    with session_scope() as session:
        baseline_id = session.scalar(select(BaselineRecord.id).where(BaselineRecord.project_id == v["project_id"]))
    changed_version(v, baseline_id)
    fixed, plan = fixed_request(v, baseline_id=baseline_id)
    target = plan["proposal"]["intent"]["target"]
    assert target["target_version_id"] is not None
    goal = goal_request(v, fixed, [("system_image.build.authorize", {**fixed, "budget": BUDGET}),
        ("system_image.build.structure", fixed)]).json()
    built = resume(v, goal["id"], expected=goal)
    assert built["pause_reason"] == "structural_candidate_review", built
    saved = v["client"].get(urls(v, fixed["plan_id"])[1], headers=v["headers"]).json()
    assert saved["proposal"] == plan["proposal"]
    assert saved["execution_authorizations"][0]["target_version_id"] == target["target_version_id"]
    assert saved["structural_artifacts"][0]["target_baseline_id"] == target["target_baseline_id"]


def test_original_publication_permissions_are_required_even_for_a_code_only_plan(publication):
    v = publication
    approval, _ = review(v)
    completed(invoke(v, "baseline.promote", publish_request(v, approval)))
    fixed, plan = fixed_request(v, baseline_id=v["target"]["target_baseline_id"])
    assert {item["source_type"] for item in plan["proposal"]["intent"]["sources"]} == {"code"}
    grant_member(v)
    url = urls(v, fixed["plan_id"])[1]
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 200
    with session_scope() as session:
        binding = session.scalar(select(SourceBindingRecord.binding_id).where(
            SourceBindingRecord.project_id == v["project_id"], SourceBindingRecord.kind == "us_doc"))
    repository = SourceAccessRepository()
    scope = repository.load_snapshot(v["project_id"])
    repository.set_policy(v["project_id"], binding, SourceAccessRule("restricted"), expected_epoch=scope.acl_epoch,
        changed_by=v["owner"]["id"], invocation_id="fixture-" + uuid4().hex)
    for endpoint in (url, target_url(v, fixed["target_baseline_id"])):
        response = v["client"].get(endpoint, headers=v["member_headers"])
        assert response.status_code == 403, response.text
        assert fixed["plan_id"] not in response.text and "s3://" not in response.text
    assert v["client"].get(url, headers=v["headers"]).json() == plan
