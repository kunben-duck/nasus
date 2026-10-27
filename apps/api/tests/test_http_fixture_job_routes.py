"""Actual HTTP router/container dependency with a port double, not full PG/RBAC."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.quality_loop.http_fixture_jobs import HttpFixtureJobTarget
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.domain.system_image.evidence import EvidenceIntegrityError, EvidenceUnavailableError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from apps.api.app.interface.http.routers.run_plans import router


@pytest.fixture
def fixture_job_http():
    calls, state = [], {"fault": None}
    def read(target):
        assert isinstance(target, HttpFixtureJobTarget)
        calls.append(target)
        if state["fault"] is not None: raise state["fault"]
        return {"schema": "nasus.http-fixture-job.v1", "project_id": target.project_id,
            "invocation_id": target.invocation_id, "status": "running", "phases": [{"state": "outcome_unknown"}],
            "execution_authorized": False, "canonical_execution_committed": False,
            "business_coverage_verified": False, "baseline_restored": False}
    app = FastAPI()
    app.state.container = SimpleNamespace(http_fixture_jobs=SimpleNamespace(read=read))
    app.include_router(router)
    with TestClient(app) as client: yield client, calls, state


def test_readonly_http_uses_exact_project_and_original_command_without_dispatch(fixture_job_http):
    client, calls, _ = fixture_job_http
    response = client.get("/v1/projects/project/quality/http-fixture-executions/original-command")
    assert response.status_code == 200 and response.headers["Cache-Control"] == "private, no-store"
    assert calls == [HttpFixtureJobTarget(project_id="project", invocation_id="original-command")]
    assert response.json()["phases"] == [{"state": "outcome_unknown"}]
    assert response.json()["business_coverage_verified"] is False
    denied_write = client.post("/v1/projects/project/quality/http-fixture-executions/original-command")
    assert denied_write.status_code == 405 and len(calls) == 1


@pytest.mark.parametrize("fault,status,code", [
    (SourceAccessDenied("private source text"), 403, "source_access_denied"),
    (StaleSourceAccessScope("private stale scope"), 409, "source_access_changed"),
    (HttpFixtureInvalid("private changed archive"), 502, "fixture_execution_invalid"),
    (EvidenceIntegrityError("private invalid evidence"), 502, "evidence_integrity_failed"),
    (EvidenceUnavailableError("private storage credentials"), 503, "evidence_unavailable"),
    (PlatformApplicationError("fixture_observation_changed", "Inspect the original observation again.", 409), 409, "fixture_observation_changed"),
    (KeyError("private missing command"), 404, "not_found"),
])
def test_read_errors_preserve_authorization_integrity_and_no_store_contract(fixture_job_http, fault, status, code):
    client, calls, state = fixture_job_http
    state["fault"] = fault
    response = client.get("/v1/projects/project/quality/http-fixture-executions/original-command")
    assert response.status_code == status and response.headers["Cache-Control"] == "private, no-store"
    assert response.json()["detail"]["error"]["code"] == code and "private" not in response.text
    assert len(calls) == 1
