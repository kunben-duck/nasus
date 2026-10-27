"""Browser contract specimen using explicit protocol doubles, never a live target."""

import asyncio
import json
from copy import deepcopy
from dataclasses import replace

from apps.api.tests.test_run_plan_case_execution import Artifacts, Journal, Runner, inputs
from apps.api.app.application.quality_loop.run_plan_case_execution import RunPlanCaseExecutionApplicationService
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.run_plan_case_preparation import CASE_PREPARATION_SCHEMA
from apps.api.app.domain.quality_loop.run_plan_observations import compile_case_jobs
from apps.api.app.infrastructure.runner.http_fixture_verifier import OwnedHttpFixtureObservationVerifier


def specimen():
    plan, scope, command, _ = inputs()
    command["input_payload"].update(
        idempotency_key="case-browser-key", case_claim_protocol=CASE_PREPARATION_SCHEMA,
    )
    scope = replace(scope, command_digest=acceptance_digest({
        "tool_id": command["tool_id"], "input_payload": command["input_payload"],
    }))
    core = RunPlanCaseExecutionApplicationService(
        Runner(), OwnedHttpFixtureObservationVerifier(), Journal(), Artifacts(),
    )
    history = asyncio.run(core.execute(plan, scope, require_current=lambda: None))
    archive = {
        "metadata": {"project_id": scope.project_id, "run_plan_id": scope.run_plan_id,
                     "artifact_hash": scope.run_plan_artifact_hash, "plan_digest": scope.plan_digest},
        "artifact": {"plan": plan}, "historical_not_live": True,
        "current_use": {"inputs_current": True, "target_verified": False, "execution_authorized": False},
    }
    command["status"] = "completed"
    command["result"] = {"invocation_id": command["id"], "status": "completed",
                         "summary": "Original observations; no formal coverage", "object_refs": []}
    view = {
        "project_id": scope.project_id, "invocation_id": scope.invocation_id,
        "run_id": scope.run_id, "status": "completed", "bound": True, "history": history,
        "historical_not_live": True, "business_coverage_verified": False,
        "canonical_execution_committed": False,
    }
    return {"plan": archive, "input": deepcopy(scope.selection), "command": command, "view": view,
            "jobs": compile_case_jobs(plan, run_id=scope.run_id, timeout_ms=scope.timeout_ms)}


if __name__ == "__main__":
    print(json.dumps(specimen()))
