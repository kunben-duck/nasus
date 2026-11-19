"""Script/review/RunPlan provenance specimens, not RealWorld acceptance."""
from copy import deepcopy
import json

import pytest

from apps.api.app.application.quality_loop.automation_script_inputs import script_messages, validate_script_output
from apps.api.app.application.quality_loop.run_plan_inputs import RunPlanSelection
from apps.api.app.domain.quality_loop.automation_script_review import assess_script_review
from apps.api.app.domain.quality_loop.http_readback import HTTP_READBACK_SCHEMA
from apps.api.app.domain.quality_loop.run_plan import compile_run_plan, run_plan_artifact_schema
from apps.api.app.domain.quality_loop.run_plan_observations import compile_case_jobs, verify_plan
from apps.api.app.domain.quality_loop.run_plan_build import compile_run_plan_build
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage, ObjectStorageConfig
from apps.api.app.infrastructure.storage.run_plan_artifacts import RunPlanArtifacts
from apps.api.tests.test_automation_script_reviews import decisions
from apps.api.tests.test_automation_scripts import script_executor, script_output
from apps.api.tests.test_http_fixture_binding_scripts import fixture_plan_inputs, fixture_build_inputs


def readback_draft():
    _, _, _, prepared = script_executor()
    output = script_output(prepared, kind="http")
    for script in output["scripts"]:
        for action in script["actions"]:
            if action["action"] == "request":
                action["phase"] = "readback"
        before = {**script["actions"][0], "request_id": "before", "phase": "exercise"}
        snapshot = dict(action="capture_snapshot", request_id="before", snapshot_id="original",
            pointer="/article/title", source_step_indices=[0])
        script["actions"][:0] = [before, snapshot]
        for assertion in script["assertions"]:
            assertion["action_index"] += 2
            action = script["actions"][assertion["action_index"]]
            action.pop("value")
            action.update(action="assert_unchanged", pointer="/article/title", snapshot_id="original")
    return prepared, output


def test_snapshots_do_not_become_oracles_or_change_the_original_reviewed_rows():
    prepared, output = readback_draft()
    original = deepcopy(prepared)
    proposal = validate_script_output(prepared, json.dumps(output), http_protocol=HTTP_READBACK_SCHEMA)
    assert prepared == original
    assert proposal["schema"] == "nasus.automation-script-proposal.v4"
    assert proposal["script_count"] == len(prepared["cases"]) and proposal["gap_count"] == 0
    actions, assertions = decisions(proposal)
    assessment = assess_script_review(proposal, actions, assertions)
    assert assessment["review_complete"] is True
    assert len(assertions) == sum(len(case["assertions"]) for case in original["cases"])
    for case, script in zip(prepared["cases"], proposal["scripts"]):
        assert [row["oracle_digest"] for row in script["assertions"]] == [row["oracle_digest"] for row in case["assertions"]]
    assert proposal["execution_authorized"] is False
    prompt, content = script_messages(prepared, http_protocol=HTTP_READBACK_SCHEMA)
    assert "capture_snapshot" in prompt and "Every unchanged assertion requires its own approved oracle row" in prompt
    assert json.loads(content) == prepared


@pytest.mark.parametrize("fault", ["unbound_assertion", "snapshot_as_oracle", "changed_oracle", "legacy", "unsafe_readback"])
def test_readback_cannot_smuggle_new_authority_or_mutations(fault):
    prepared, output = readback_draft()
    script = output["scripts"][0]
    protocol = HTTP_READBACK_SCHEMA
    if fault == "unbound_assertion":
        script["actions"].append(deepcopy(script["actions"][-1]))
    elif fault == "snapshot_as_oracle":
        script["assertions"][0]["action_index"] = 1
    elif fault == "changed_oracle":
        script["assertions"][0]["oracle"]["expected_result"] = "invented expectation"
    elif fault == "legacy":
        protocol = "nasus.runner-http-execution.v3"
    else:
        script["actions"][2]["method"] = "DELETE"
    with pytest.raises(ValueError):
        validate_script_output(prepared, json.dumps(output), http_protocol=protocol)


def test_v4_native_generation_archive_independent_review_and_run_plan_keep_protocol():
    draft, review, sources, selection = fixture_plan_inputs(HTTP_READBACK_SCHEMA)
    RunPlanSelection.model_validate(selection)
    plan = compile_run_plan(draft, review, selection, sources)
    assert verify_plan(plan) == plan and plan["schema"] == "nasus.run-plan.v4"
    assert run_plan_artifact_schema(plan["schema"]) == "nasus.run-plan-artifact.v4"
    jobs = compile_case_jobs(plan, run_id="readback-iteration", timeout_ms=5000)
    assert len(jobs) == len(plan["prepared"]["cases"])
    for job in jobs:
        assert job["receipt_protocol"] == HTTP_READBACK_SCHEMA
        assert job["steps"][0]["action"] == "use_fixture_binding"
    selection["policy_revision"] = "nasus.run-plan.v3"
    with pytest.raises(ValueError, match="protocol"):
        compile_run_plan(draft, review, selection, sources)


@pytest.mark.parametrize("python_profile", [False, True])
def test_v4_plan_round_trips_real_artifact_adapter_and_keeps_build_binding_pins(tmp_path, python_profile):
    view, selection, builds = fixture_build_inputs(HTTP_READBACK_SCHEMA, python_profile=python_profile)
    original = deepcopy((view, selection, builds))
    storage = ObjectStorage(ObjectStorageConfig(endpoint=None, bucket="test-readback", access_key=None,
        secret_key=None, region="us-east-1", local_dir=tmp_path))
    artifacts = RunPlanArtifacts(storage)
    ref, digest = artifacts.put(view["artifact"]["project_id"], view["artifact"])
    assert digest == selection.run_plan_artifact_hash
    assert artifacts.read(view["artifact"]["project_id"], ref, digest) == view["artifact"]
    binding = compile_run_plan_build(view, selection.model_dump(mode="json"), builds)
    assert binding["run_plan_artifact_hash"] == digest
    assert binding["plan_digest"] == view["artifact"]["plan"]["plan_digest"]
    assert binding["native_build_source_attested"] and not binding["execution_authorized"]
    assert (view, selection, builds) == original
