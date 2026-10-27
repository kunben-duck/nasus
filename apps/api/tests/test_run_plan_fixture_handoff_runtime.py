"""Configured worker handoff; journals/target are explicit protocol specimens."""
import asyncio
from copy import deepcopy

import pytest

from apps.api.app.application.quality_loop.run_plan_cases import RunPlanCaseApplicationService
from apps.api.app.domain.quality_loop.run_plan_case_execution import RunPlanCaseExecutionInvalid
from apps.api.app.infrastructure.runner import run_plan_case_runtime as runtime
from apps.api.app.infrastructure.runner.http_fixture_verifier import OwnedHttpFixtureObservationVerifier
from apps.api.tests.test_run_plan_case_execution import Journal, Artifacts
from apps.api.tests.test_run_plan_fixture_handoff import NativeRunner, fixture_inputs, spec


def configured_worker(monkeypatch):
    runner, configured = NativeRunner(), []

    def create(**kwargs):
        configured.append(kwargs)
        return runner

    monkeypatch.setattr(runtime, "ConfiguredOwnedTargetHttpRunner", create)
    worker = runtime.ConfiguredRunPlanCaseWorker(Journal(), OwnedHttpFixtureObservationVerifier(),
        Artifacts(), node_executable="/explicit-node-protocol-specimen")
    return worker, runner, configured


def test_actual_worker_adapter_passes_complete_original_inputs_on_execution_and_history(fixture_inputs, monkeypatch):
    v = fixture_inputs
    worker, runner, configured = configured_worker(monkeypatch)
    application = RunPlanCaseApplicationService(v.service, worker)
    prepared = v.service.prepare(v.selection, invocation_id=v.snapshot["id"])
    original = deepcopy(prepared.fixture_inputs)
    result = asyncio.run(application.execute(v.selection, invocation_id=v.snapshot["id"]))
    assert configured == [{"node_executable": "/explicit-node-protocol-specimen"}]
    assert len(runner.commands) == result["state"]["case_count"] == len(original)
    assert tuple(command.fixture_input for command in runner.commands) == original
    assert result["state"]["schema"] == "nasus.run-plan-case-state.v2"
    assert all(item["status"] == "failed" for item in result["observations"])
    assert result["state"]["passed_count"] == result["state"]["executed_on_target_count"] == 0
    assert result["state"]["business_coverage_verified"] is False
    worker.node_executable = ""
    monkeypatch.setattr(runtime, "ConfiguredOwnedTargetHttpRunner",
        lambda **kwargs: pytest.fail("historical read must not configure or dispatch the target"))
    assert application.read(worker.journal.scope) == result
    assert len(configured) == 1 and len(runner.commands) == len(original)
    assert prepared.fixture_inputs == original


@pytest.mark.parametrize("fault", ["missing", "wire", "pin"])
def test_configured_worker_cannot_hide_invalid_original_input_before_case_claim(fixture_inputs, monkeypatch, fault):
    v = fixture_inputs
    worker, runner, configured = configured_worker(monkeypatch)
    prepared = v.service.prepare(v.selection, invocation_id=v.snapshot["id"])
    values = deepcopy(prepared.fixture_inputs)
    if fault == "missing":
        values = None
    elif fault == "wire":
        values[0]["source_result_body_base64"] += "\n"
    else:
        values[0]["capture_set"]["captures"][0]["value"] = "invented-resource"
    with pytest.raises(RunPlanCaseExecutionInvalid):
        asyncio.run(worker.execute(prepared.plan, prepared.scope,
            fixture_inputs=values, require_current=lambda: None))
    assert len(configured) == 1 and not runner.commands
    assert worker.journal.scope is None and not worker.journal.claims and not worker.artifacts.values


def test_old_configured_worker_contract_does_not_add_empty_fixture_fields(monkeypatch):
    worker, _, configured = configured_worker(monkeypatch)
    calls = []

    class LegacyWorker:
        def __init__(self, runner, verifier, journal, artifacts):
            pass

        async def execute(self, plan, scope, *, require_current):
            require_current()
            calls.append(("execute", plan, scope))
            return "original-legacy-execution"

        def read(self, plan, scope, *, require_access):
            require_access()
            calls.append(("read", plan, scope))
            return "original-legacy-history"

    monkeypatch.setattr(runtime, "RunPlanCaseExecutionApplicationService", LegacyWorker)
    assert asyncio.run(worker.execute("old-plan", "old-scope", require_current=lambda: None)) == "original-legacy-execution"
    assert worker.read("old-plan", "old-scope", require_access=lambda: None) == "original-legacy-history"
    assert calls == [("execute", "old-plan", "old-scope"), ("read", "old-plan", "old-scope")]
    assert len(configured) == 1
