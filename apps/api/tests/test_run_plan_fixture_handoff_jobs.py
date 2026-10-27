"""Canonical lifecycle/Node handoff specimens; no actual PG or owned target."""
import asyncio
from copy import deepcopy

import pytest

from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureLifecycleApplicationService, HttpFixturePhaseRecord
from apps.api.app.application.quality_loop.runner_port import FixtureBoundHttpCommand
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.run_plan_case_execution import RunPlanCaseExecutionInvalid
from apps.api.app.domain.quality_loop.run_plan_case_job import CASE_JOB_QUERY_TOOL
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_run_plan_case_jobs import case_job
from apps.api.tests.test_run_plan_fixture_handoff import NativeRunner, fixture_inputs, spec


@pytest.fixture
def fixture_job(fixture_inputs):
    return case_job(fixture_inputs, NativeRunner())


def test_full_v3_job_finalizes_only_after_original_archive_reread_and_never_resends(fixture_job):
    v = fixture_job
    original = deepcopy(v.v.v.saved)
    assert asyncio.run(v.application.run(v.target.invocation_id)) == "completed"
    size = len(v.v.selection.fixture_setups)
    receipt = v.state["finished"][0][1]
    assert receipt["state"]["schema"] == "nasus.run-plan-case-state.v2"
    assert receipt["state"]["case_count"] == receipt["state"]["observed_case_count"] == size
    assert len(v.runner.commands) == len(v.journal.claims) == len(v.journal.outcomes) == size
    assert all(type(command) is FixtureBoundHttpCommand for command in v.runner.commands)
    assert all(item["status"] == "failed" for item in receipt["observations"])
    assert receipt["state"]["passed_count"] == receipt["state"]["executed_on_target_count"] == 0
    assert not receipt["state"]["business_coverage_verified"]
    assert v.application.read(v.target)["history"] == receipt
    assert asyncio.run(v.application.run(v.target.invocation_id)) == "completed"
    assert len(v.runner.commands) == size and len(v.state["finished"]) == 1 and v.v.v.saved == original


def test_v3_lost_native_response_retry_keeps_full_roster_and_original_claim(fixture_job):
    v = fixture_job
    v.runner.fail = True
    assert asyncio.run(v.application.run(v.target.invocation_id)) == "failed"
    before = deepcopy(v.application.read(v.target))
    assert before["history"]["state"]["state"] == "outcome_unknown"
    assert before["history"]["state"]["not_dispatched_case_count"] == len(v.v.selection.fixture_setups) - 1
    epoch = v.journal.lease.epoch
    v.state["status"] = v.v.snapshot["status"] = "running"
    v.runner.fail = False
    assert asyncio.run(v.application.run(v.target.invocation_id)) == "failed"
    assert len(v.runner.commands) == len(v.journal.claims) == 1 and not v.journal.outcomes
    assert v.journal.lease.epoch == epoch and v.application.read(v.target) == before


def test_v3_history_after_cleanup_keeps_original_bytes_without_live_health_or_reexecution(fixture_job):
    v = fixture_job
    assert asyncio.run(v.application.run(v.target.invocation_id)) == "completed"
    before = v.application.read(v.target)
    cleanup = HttpFixtureLifecycleApplicationService._command(v.v.resolved.scope, "cleanup:session",
        tuple(v.v.resolved.manifest["cleanup_groups"]["session"]))
    v.v.state["phases"] = (v.v.state["phases"][0], ("cleanup:session", HttpFixturePhaseRecord(cleanup, None)))
    v.v.state["target_up"] = False
    v.v.v.saved["current_use"]["inputs_current"] = v.v.binding["current_use"]["inputs_current"] = False
    health = v.v.state["health_reads"]
    assert v.application.read(v.target) == before
    assert v.v.state["health_reads"] == health and len(v.runner.commands) == len(v.v.selection.fixture_setups)
    with pytest.raises(ValueError):
        v.v.service.require_current(v.prepared)


@pytest.mark.parametrize("fault", ["pin", "wire", "capture"])
def test_v3_original_archive_corruption_prevents_job_finalization_without_resending(fixture_job, fault):
    v = fixture_job
    execute = v.application.cases.execute

    async def execute_and_corrupt(*args, **kwargs):
        result = await execute(*args, **kwargs)
        entry = v.journal.outcomes[0]
        original = v.application.cases.execution.artifacts.values[entry["artifact_hash"]]
        if fault == "pin":
            original["fixture_input"]["capture_set_digest"] = acceptance_digest("other capture")
        elif fault == "wire":
            original["fixture_input"]["source_result_body_base64"] += "\n"
        else:
            original["fixture_input"]["capture_set"]["captures"][0]["value"] = "invented-resource"
        return result

    v.application.cases.execute = execute_and_corrupt
    with pytest.raises(RunPlanCaseExecutionInvalid):
        asyncio.run(v.application.run(v.target.invocation_id))
    assert not v.state["finished"] and v.state["status"] == "running"
    assert len(v.runner.commands) == len(v.v.selection.fixture_setups)
    with pytest.raises(RunPlanCaseExecutionInvalid):
        asyncio.run(v.application.run(v.target.invocation_id))
    assert len(v.runner.commands) == len(v.v.selection.fixture_setups) and not v.state["finished"]


@pytest.mark.parametrize("fault", [None, "authority", "private_input", "count", "state"])
def test_v3_query_receipt_cannot_expose_resources_or_inflate_formal_coverage(fixture_job, fault):
    v = fixture_job
    assert asyncio.run(v.application.run(v.target.invocation_id)) == "completed"
    receipt = v.application.metadata(v.target)
    assert not {"fixture_inputs", "fixture_input_pins", "history", "observations", "scope"} & set(receipt)
    if fault == "authority": receipt["business_coverage_verified"] = True
    elif fault == "private_input": receipt["fixture_inputs"] = v.prepared.fixture_inputs
    elif fault == "count": receipt["case_count"] -= 1
    elif fault == "state": receipt["execution_state"] = "partially_observed"
    invocation = ToolInvocation(id="v3-metadata-query", tool_id=CASE_JOB_QUERY_TOOL, status="completed", summary="",
        input_payload=v.target.model_dump(mode="json"), result=ToolResult(invocation_id="v3-metadata-query",
            status="completed", summary="Original metadata only", run_plan_case_job=receipt))
    if fault is None:
        v.application.authorize_receipts((invocation,))
    else:
        with pytest.raises(RunPlanCaseExecutionInvalid):
            v.application.authorize_receipts((invocation,))


def test_v3_history_rechecks_current_source_access_even_when_all_output_is_archived(fixture_job):
    v = fixture_job
    assert asyncio.run(v.application.run(v.target.invocation_id)) == "completed"
    v.v.v.state["revoked"] = True
    with pytest.raises(SourceAccessDenied):
        v.application.read(v.target)
    assert len(v.runner.commands) == len(v.v.selection.fixture_setups)


def test_v3_prebinding_cancel_does_not_materialize_new_resource_or_case_input(fixture_job):
    v = fixture_job
    v.workflow.failure = RuntimeError("explicit unknown cancellation delivery")
    assert asyncio.run(v.application.cancel(v.target, control_id="independent-v3-cancel")) == "cancelled"
    assert asyncio.run(v.application.run(v.target.invocation_id)) == "cancelled"
    assert not v.runner.commands and not v.journal.claims and not v.state["ack"]
    receipt = v.application.metadata(v.target)
    assert receipt["bound"] is False and receipt["case_count"] is None and receipt["execution_state"] == "cancelled"
