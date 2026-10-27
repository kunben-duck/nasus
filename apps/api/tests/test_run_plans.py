"""RunPlan protocol specimens, not target attestation or business gold."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from apps.api.app.application.quality_loop.run_plan_inputs import RunPlanSelection, RunPlanRequest
from apps.api.app.application.quality_loop.run_plans import RunPlanApplicationService
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.run_plan import compile_run_plan, RunPlanChanged, RunPlanIntegrityError, RunPlanInvalid
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_automation_script_reviews import review_service


def selection_for(draft, review, sources):
    return RunPlanSelection(project_id=draft["metadata"]["project_id"],
        script_revision_id=draft["metadata"]["script_revision_id"], script_artifact_hash=draft["metadata"]["artifact_hash"],
        review_revision_id=review["revision"]["revision_id"], review_artifact_hash=review["revision"]["artifact_hash"],
        target_build={"code_sources": [{"binding_id": member["binding_id"], "source_revision_id": member["source_revision_id"]}
            for member in sources["source_members"] if member["source_type"] == "code" and member["status"] == "captured"],
            "artifact_name": "explicit-protocol-build.jar", "artifact_hash": acceptance_digest("unverified-build-specimen"),
            "build_definition_hash": acceptance_digest("unverified-build-definition"),
            "runtime": "Java", "runtime_version": "21", "build_tool": "Maven", "build_tool_version": "3.9.11"},
        environment={"environment_id": "explicit-protocol-environment", "kind": "test", "base_url": "http://127.0.0.1:19876",
            "inventory_hash": acceptance_digest("unverified-environment"), "isolation": "Declaration only; no target process is started"},
        fixtures=[{"case_id": case["case_id"], "preconditions_digest": acceptance_digest(case["preconditions"]),
            "data_manifest_hash": acceptance_digest(["unverified-fixture", case["case_id"]]),
            "setup": ["Declared protocol setup, not executed"], "cleanup": ["Declared protocol cleanup, not executed"]}
            for case in draft["result"]["prepared"]["cases"]], reason="Explicit prepared inputs; not native execution or business approval")


def plan_inputs():
    app, draft, request, *_ = review_service()
    meta = app.review(request, invocation_id="independent-review-command", recorded_at="2026-10-10T00:00:00+00:00")
    review = app.read("p", meta["revision_id"])
    context = draft["result"]["prepared"]["context_pin"]
    sources = {"project_id": "p", "image_revision_id": context["image_revision_id"],
        "image_artifact_hash": context["image_artifact_hash"], "manifest_id": "manifest", "manifest_hash": acceptance_digest("manifest"),
        "source_members": [{"binding_id": "code", "source_revision_id": "code-revision", "source_type": "code", "status": "captured"},
            {"binding_id": "requirements", "source_revision_id": "requirements-revision", "source_type": "us_doc", "status": "captured"}]}
    return draft, review, sources, selection_for(draft, review, sources)


def test_plan_preserves_full_cases_actions_oracles_scope_and_unknown_target():
    draft, review, sources, selection = plan_inputs()
    original = deepcopy((draft, review, sources))
    plan = compile_run_plan(draft, review, selection.model_dump(mode="json"), sources)
    assert (draft, review, sources) == original
    assert plan["prepared"] == draft["result"]["prepared"] and plan["proposal"] == draft["result"]["proposal"]
    assert plan["review_pin"]["authority_actor"] == "independent-reviewer"
    assert plan["plan_digest"] == acceptance_digest({key: item for key, item in plan.items() if key != "plan_digest"})
    assert plan["target_verification"] == "declared_not_native_verified" and not plan["execution_authorized"]
    assert plan["automated_count"] == plan["executed_on_target_count"] == plan["passed_count"] == 0
    changed = selection.model_dump(mode="json")
    changed["environment"]["inventory_hash"] = acceptance_digest("another-environment")
    assert compile_run_plan(draft, review, changed, sources)["plan_digest"] != plan["plan_digest"]


@pytest.mark.parametrize("fault", ["missing_fixture", "foreign_fixture", "preconditions", "code_revision", "extra_source", "review_hash",
    "script_hash", "review_script", "incomplete_review", "truthy_review", "withdrawn", "image_hash", "source_project", "case_oracle", "script_step"])
def test_plan_rejects_unpinned_or_incomplete_dependencies(fault):
    draft, review, sources, selection = plan_inputs()
    value = selection.model_dump(mode="json")
    if fault == "missing_fixture": value["fixtures"].pop()
    elif fault == "foreign_fixture": value["fixtures"][0]["case_id"] = "foreign"
    elif fault == "preconditions": value["fixtures"][0]["preconditions_digest"] = acceptance_digest("different")
    elif fault == "code_revision": value["target_build"]["code_sources"][0]["source_revision_id"] = "latest"
    elif fault == "extra_source": value["target_build"]["code_sources"].append({"binding_id": "foreign", "source_revision_id": "foreign"})
    elif fault == "review_hash": value["review_artifact_hash"] = acceptance_digest("different")
    elif fault == "script_hash": value["script_artifact_hash"] = acceptance_digest("different")
    elif fault == "review_script": review["revision"]["script_revision_id"] = "foreign"
    elif fault == "incomplete_review": review["assessment"]["review_complete"] = False
    elif fault == "truthy_review": review["assessment"]["review_complete"] = "true"
    elif fault == "withdrawn": review["revision"]["status"] = "withdrawn"
    elif fault == "image_hash": sources["image_artifact_hash"] = acceptance_digest("different")
    elif fault == "source_project": sources["project_id"] = "foreign"
    elif fault == "case_oracle": draft["result"]["prepared"]["cases"][0]["assertions"][0]["oracle_digest"] = acceptance_digest("different")
    else: draft["result"]["proposal"]["scripts"][0]["actions"][0]["source_step_indices"] = [63]
    with pytest.raises(ValueError):
        compile_run_plan(draft, review, value, sources)


@pytest.mark.parametrize("origin", ["file:///etc/passwd", "http://user:secret@localhost", "http://localhost?api_key=secret",
    "http://localhost#secret", "http://localhost/api", "http://localhost:99999", "http://localhost\\evil", "http://local host"])
def test_target_declaration_cannot_include_credential_path_or_non_http_origin(origin):
    *_, selection = plan_inputs()
    value = selection.model_dump(mode="json")
    value["environment"]["base_url"] = origin
    with pytest.raises(ValidationError):
        RunPlanSelection.model_validate(value)


def test_plan_dto_rejects_imported_execution_authority_and_duplicate_fixtures():
    *_, selection = plan_inputs()
    value = selection.model_dump(mode="json")
    for changed in ({**value, "execution_authorized": True}, {**value, "fixtures": [*value["fixtures"], value["fixtures"][0]]},
            {**value, "environment": {**value["environment"], "kind": "production"}}):
        with pytest.raises(ValidationError):
            RunPlanSelection.model_validate(changed)


def test_complete_plan_byte_limit_fails_without_truncating(monkeypatch):
    import apps.api.app.domain.quality_loop.run_plan as policy
    draft, review, sources, selection = plan_inputs()
    monkeypatch.setattr(policy, "MAX_RUN_PLAN_BYTES", 128)
    with pytest.raises(RunPlanInvalid, match="never truncate"):
        compile_run_plan(draft, review, selection.model_dump(mode="json"), sources)


def test_application_preview_and_history_revalidate_live_access_and_current_review():
    draft, review, sources, selection = plan_inputs()
    class Authorization:
        revoked = False
        def scope(self, project):
            if self.revoked: raise SourceAccessDenied("revoked")
            return SimpleNamespace(actor_id="reviewer", effective_project_role="qa_lead", fingerprint=acceptance_digest("scope"))
        def require_current(self, access):
            if self.revoked: raise SourceAccessDenied("revoked")
    class Artifacts:
        def __init__(self): self.values = {}
        def put(self, project, payload):
            digest = acceptance_digest(payload)
            self.values[digest] = deepcopy(payload)
            return "private:" + digest, digest
        def read(self, project, ref, digest): return deepcopy(self.values[digest])
    class Repository:
        def __init__(self): self.values = {}
        def committed(self, *args, require_access, **kwargs): require_access(); return None
        def record(self, request, payload, ref, digest, *, require_current):
            require_current()
            meta = {key: payload[key] for key in ("project_id", "run_plan_id", "actor_id", "invocation_id", "recorded_at")}
            meta.update(artifact_hash=digest, plan_digest=request.plan_digest, request_hash=acceptance_digest(payload["request"]))
            meta.update({key: payload["plan"]["source_pin"][key] for key in ("image_revision_id", "manifest_id")})
            meta["context_id"] = payload["plan"]["prepared"]["context_pin"]["context_id"]
            self.values[payload["run_plan_id"]] = {"metadata": meta, "artifact_ref": ref, "request": payload["request"]}
            return meta
        def read(self, project, ident): return deepcopy(self.values[ident])
    auth, artifacts, repository = Authorization(), Artifacts(), Repository()
    app = RunPlanApplicationService(SimpleNamespace(read=lambda *args: deepcopy(draft)),
        SimpleNamespace(read=lambda *args: deepcopy(review)), SimpleNamespace(run_plan_sources=lambda *args: deepcopy(sources)),
        auth, repository, artifacts)
    request = RunPlanRequest.model_validate(app.preview(selection)["request"])
    changed = request.model_copy(update={"plan_digest": acceptance_digest("changed")})
    with pytest.raises(RunPlanChanged):
        app.prepare(changed, invocation_id="command", recorded_at="2026-10-10T00:00:00+00:00")
    meta = app.prepare(request, invocation_id="command", recorded_at="2026-10-10T00:00:00+00:00")
    original = app.read("p", meta["run_plan_id"])
    assert original["current_use"] == {"inputs_current": True, "target_verified": False, "execution_authorized": False}
    review["current_use"]["review_complete"] = False
    with pytest.raises(RunPlanChanged): app.preview(selection)
    historical = app.read("p", meta["run_plan_id"])
    assert historical["artifact"] == original["artifact"] and not historical["current_use"]["inputs_current"]
    artifacts.values[meta["artifact_hash"]]["plan"]["proposal"]["scripts"][0]["actions"][0]["source_step_indices"] = [63]
    with pytest.raises(RunPlanIntegrityError): app.read("p", meta["run_plan_id"])
    auth.revoked = True
    with pytest.raises(SourceAccessDenied): app.read("p", meta["run_plan_id"])
