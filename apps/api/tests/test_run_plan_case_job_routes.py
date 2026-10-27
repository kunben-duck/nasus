"""Production read router with an explicit port double, not full authenticated PG HTTP."""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from apps.api.app.application.quality_loop.run_plan_case_jobs import RunPlanCaseJobTarget
from apps.api.app.domain.quality_loop.run_plan_case_execution import RunPlanCaseExecutionInvalid, RunPlanCaseWorkLost
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.interface.http.routers.run_plans import router


@pytest.mark.parametrize("fault,status", [(None, 200), (SourceAccessDenied("private source"), 403),
    (RunPlanCaseExecutionInvalid("private archive"), 502), (RunPlanCaseWorkLost("private changed history"), 409), (KeyError("private command"), 404)])
def test_private_original_case_read_is_no_store_read_only_and_redacts_failures(fault, status):
    calls = []
    def read(target):
        calls.append(target)
        if fault: raise fault
        return dict(project_id=target.project_id, invocation_id=target.invocation_id, status="failed",
            history={"state": {"state": "outcome_unknown"}}, historical_not_live=True, business_coverage_verified=False)
    app = FastAPI()
    app.state.container = SimpleNamespace(run_plan_case_jobs=SimpleNamespace(read=read))
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/v1/projects/project/quality/run-plan-case-executions/original-command")
        assert response.status_code == status and response.headers["Cache-Control"] == "private, no-store"
        assert "private" not in response.text
        assert client.post("/v1/projects/project/quality/run-plan-case-executions/original-command").status_code == 405
    assert calls == [RunPlanCaseJobTarget(project_id="project", invocation_id="original-command")]
