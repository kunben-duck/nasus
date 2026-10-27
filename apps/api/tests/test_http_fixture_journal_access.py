"""Saved-plan application specimens; no database or execution consent."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.http_fixture_journal_access import SavedRunPlanHttpFixtureAccess
from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureScope
from apps.api.app.application.quality_loop.run_plan_observation_archives import RunPlanObservationArchiveParent
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.domain.quality_loop.run_plan import compile_run_plan
from apps.api.tests.test_http_fixtures import manifest
from apps.api.tests.test_run_plans import plan_inputs


def saved_inputs(*, endpoint="http://127.0.0.1:8080"):
    draft, review, sources, selection = plan_inputs()
    value = selection.model_dump(mode="json")
    value["environment"]["base_url"] = endpoint
    declaration = value["fixtures"][0]
    recipe = {**manifest(), **{key: declaration[key] for key in ("case_id", "preconditions_digest", "setup", "cleanup")}}
    declaration["data_manifest_hash"] = acceptance_digest(recipe)
    plan = compile_run_plan(draft, review, value, sources)
    artifact = {"project_id": plan["project_id"], "run_plan_id": "original-plan", "plan": plan}
    parent = RunPlanObservationArchiveParent(project_id=plan["project_id"], run_plan_id="original-plan",
        run_plan_artifact_hash=acceptance_digest(artifact), plan_digest=plan["plan_digest"])
    view = {"metadata": {**parent.model_dump(mode="json"), "artifact_hash": parent.run_plan_artifact_hash}, "artifact": artifact}
    access = SavedRunPlanHttpFixtureAccess(SimpleNamespace(read=lambda _project, _plan: deepcopy(view)), parent, recipe)
    scope = HttpFixtureScope(plan["project_id"], "original-attempt", recipe["case_id"], plan["plan_digest"],
        acceptance_digest(recipe), value["environment"]["environment_id"], value["target_build"]["artifact_hash"],
        value["environment"]["inventory_hash"], 10000)
    return access, scope, recipe, view


def test_saved_fixture_scope_and_dynamic_cleanup_preserve_the_original_contract():
    access, scope, recipe, view = saved_inputs()
    original = deepcopy(view)
    assert access.require_scope(scope) == access.parent.model_dump(mode="json")
    command = access.command(scope, "setup")
    assert command.steps == tuple(recipe["setup_steps"])
    cleanup = access.command(scope, "cleanup:session", setup_receipt={"bindings": [{"binding_id": "session", "value": "native_id"}]})
    assert cleanup.steps[0]["path"] == "/sessions/native_id/close" and view == original
    assert command.metadata["business_coverage_verified"] is False


@pytest.mark.parametrize("field", ["project_id", "case_id", "parent_digest", "data_manifest_hash",
    "environment_id", "artifact_hash", "inventory_hash"])
def test_saved_fixture_rejects_rebound_parent_recipe_and_target(field):
    access, scope, _recipe, _view = saved_inputs()
    value = acceptance_digest("changed") if field.endswith(("digest", "hash")) else "another"
    with pytest.raises(HttpFixtureInvalid): access.require_scope(replace(scope, **{field: value}))


@pytest.mark.parametrize("phase", ["cleanup:session", "cleanup:foreign", "another", None])
def test_saved_fixture_cannot_invent_cleanup_or_use_an_unknown_phase(phase):
    access, scope, _recipe, _view = saved_inputs()
    with pytest.raises(HttpFixtureInvalid): access.command(scope, phase)


def test_saved_fixture_rechecks_original_bytes_and_current_source_access_each_time():
    access, scope, _recipe, view = saved_inputs()
    view["artifact"]["plan"]["selection"]["fixtures"][0]["setup"] = ["caller replacement"]
    with pytest.raises(HttpFixtureInvalid): access.require_scope(scope)
    access.plans.read = lambda *_args: (_ for _ in ()).throw(PermissionError("source access revoked"))
    with pytest.raises(PermissionError): access.require_scope(scope)


def test_saved_fixture_cannot_replace_the_plan_endpoint_with_a_different_loopback_target():
    access, scope, _recipe, view = saved_inputs(endpoint="http://127.0.0.1:19876")
    assert acceptance_digest(view["artifact"]) == access.parent.run_plan_artifact_hash
    with pytest.raises(HttpFixtureInvalid): access.require_scope(scope)


def test_saved_fixture_rejects_a_valid_plan_body_wrapped_in_another_project():
    access, scope, _recipe, view = saved_inputs()
    view["artifact"]["project_id"] = "another-project"
    digest = acceptance_digest(view["artifact"])
    access.parent = RunPlanObservationArchiveParent(**{**access.parent.model_dump(mode="json"),
        "project_id": "another-project", "run_plan_artifact_hash": digest})
    view["metadata"].update(project_id="another-project", artifact_hash=digest)
    with pytest.raises(HttpFixtureInvalid): access.require_scope(replace(scope, project_id="another-project"))
