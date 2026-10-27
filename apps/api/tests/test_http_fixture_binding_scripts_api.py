"""Canonical PG/MinIO v3 drafts over fixed exweb; model/oracles are protocol specimens."""
from copy import deepcopy
from sqlalchemy import func, select

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.automation_script_inputs import ScriptExecutionSelection
from apps.api.app.application.quality_loop.run_plan_inputs import RunPlanSelection
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.tests.test_http_fixture_binding_scripts import fixture_script_output
from apps.api.tests.test_run_plans_api import (
    native_scripts, base_evidence_api, evidence_api, documents, publication, design_scope, generation_result, mapping,
    reviewed_plan_inputs, preview, submit, read,
)
from apps.api.tests.test_automation_scripts_api import (
    run_confirmed, read_draft, script_review_request, submit_script_review, read_script_review, verify_fixed_exweb_archive,
)
from apps.api.tests.test_semantic_evaluations_api import completed, count, confirm
from apps.api.app.infrastructure.persistence.db_models import ConversationRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.run_plan_models import RunPlanRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope


def project_tool_count(v):
    with session_scope() as session:
        return session.scalar(select(func.count()).select_from(ToolInvocationRecord)
            .join(ConversationRecord, ConversationRecord.id == ToolInvocationRecord.conversation_id)
            .where(ConversationRecord.space_type == "project", ConversationRecord.space_id == v["project_id"]))


def test_fixed_exweb_v3_script_review_plan_preserves_sources_and_original_obligations(native_scripts):
    v = native_scripts
    old_draft, old_review, reviewer, _ = reviewed_plan_inputs(v)
    old_bytes = deepcopy((old_draft, old_review))
    calls_before = len(v["script_calls"])
    v["script_transport"].output = fixture_script_output
    selection = ScriptExecutionSelection.model_validate({**v["script_selection"].model_dump(mode="json"),
        "http_protocol": "nasus.runner-http-execution.v3"})
    old_preview = deepcopy(v["script_preview"])
    with actor_scope(UserProfile.model_validate(v["owner"])):
        v["script_preview"] = v["script_service"].preview(selection)
    assert v["script_preview"]["request"]["execution"]["plan_digest"] != old_preview["request"]["execution"]["plan_digest"]
    pending, response = run_confirmed(v)
    command = completed(response)
    draft_response = read_draft(v, command)
    assert draft_response.status_code == 200, draft_response.text
    draft = draft_response.json()
    prepared, proposal = draft["result"]["prepared"], draft["result"]["proposal"]
    assert prepared == old_draft["result"]["prepared"]
    assert proposal["schema"] == "nasus.automation-script-proposal.v3"
    source_pin, members = verify_fixed_exweb_archive(v, prepared)
    assert source_pin["file_count"] == 126 and members > 0
    assert v["exweb_commit"] == "fe5827f6b76f77ef34918d8b452ee823142332dc"
    assert proposal["case_count"] == len(prepared["cases"]) and not proposal["gaps"]
    assert len(v["script_calls"]) == calls_before + 1
    assert completed(confirm(v, pending))["id"] == command["id"]
    assert len(v["script_calls"]) == calls_before + 1

    review_request = script_review_request(v, draft)
    assert len(review_request["actions"]) == sum(len(item["actions"]) for item in proposal["scripts"])
    assert len(review_request["assertions"]) == sum(len(item["assertions"]) for item in prepared["cases"])
    review_command = completed(submit_script_review(reviewer, review_request))
    review_id = review_command["result"]["object_refs"][0].split(":", 1)[1]
    review_response = read_script_review(v, review_id)
    assert review_response.status_code == 200, review_response.text
    review = review_response.json()
    assert review["assessment"]["review_complete"] and not review["assessment"]["execution_authorized"]
    assert review["revision"]["authority_actor"] == v["member"]["id"]
    with actor_scope(UserProfile.model_validate(v["owner"])):
        sources = app.state.container.run_plans.sources.run_plan_sources(prepared)
    from apps.api.tests.test_run_plans import selection_for
    selected = selection_for(draft, review, sources).model_dump(mode="json")
    selected["policy_revision"] = "nasus.run-plan.v3"
    selection = RunPlanSelection.model_validate(selected)
    prepared_response = preview(v, selection)
    assert prepared_response.status_code == 200, prepared_response.text
    plan_command = completed(submit(v, prepared_response.json()["request"]))
    plan_id = plan_command["result"]["object_refs"][0].split(":", 1)[1]
    saved_response = read(v, plan_id)
    assert saved_response.status_code == 200, saved_response.text
    saved = saved_response.json()
    plan = saved["artifact"]["plan"]
    assert saved["artifact"]["schema"] == "nasus.run-plan-artifact.v3" and plan["schema"] == "nasus.run-plan.v3"
    assert plan["prepared"] == prepared and plan["proposal"] == proposal and plan["source_pin"] == sources
    assert plan["automated_count"] == plan["executed_on_target_count"] == plan["passed_count"] == 0
    assert not plan["execution_authorized"]
    assert saved["metadata"]["artifact_hash"] == acceptance_digest(saved["artifact"])
    assert count(v, RunPlanRecord) == 1
    count_before = project_tool_count(v)
    wrong = {**selected, "review_revision_id": old_review["revision"]["revision_id"],
        "review_artifact_hash": old_review["revision"]["artifact_hash"]}
    assert preview(v, RunPlanSelection.model_validate(wrong)).status_code == 409
    assert project_tool_count(v) == count_before and count(v, RunPlanRecord) == 1
    assert read(v, plan_id).json() == saved and len(v["script_calls"]) == calls_before + 1
    assert read_script_review(v, old_review["revision"]["revision_id"]).json() == old_bytes[1]
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert v["script_service"].read(v["project_id"], old_draft["metadata"]["script_revision_id"]) == old_bytes[0]
