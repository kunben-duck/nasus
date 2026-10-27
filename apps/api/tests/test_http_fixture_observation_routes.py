"""Production GET route and application ports; no app.main, database or target."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.app.domain.quality_loop.http_fixture_observation import HttpFixtureObservationChanged
from apps.api.app.domain.quality_loop.http_fixture_history import HttpFixtureHistoryUnavailable
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.interface.http.routers.run_plans import router
from apps.api.tests.test_http_fixture_observations import observation_specimen, history_specimen, native_grant, spec, observed_phase


@pytest.fixture
def observation_http(observation_specimen):
    app = FastAPI()
    app.state.container = SimpleNamespace(http_fixture_jobs=observation_specimen.jobs)
    app.include_router(router)
    with TestClient(app) as client: yield client, observation_specimen


def test_project_original_journal_get_retains_unknown_and_never_accepts_effect_writes(observation_http):
    client, v = observation_http
    observed_phase(v)
    path = f"/v1/projects/{v.target.project_id}/quality/http-fixture-operations/{v.target.invocation_id}/observation"
    result = client.get(path)
    assert result.status_code == 200 and result.headers["Cache-Control"] == "private, no-store"
    assert result.json() == v.observations.read(v.target).model_dump(mode="json")
    assert result.json()["state"] == "outcome_unknown" and result.json()["business_coverage_verified"] is False
    assert client.post(path).status_code == client.patch(path).status_code == client.delete(path).status_code == 405
    assert v.state["live"] == 0


@pytest.mark.parametrize("fault,status,code", [
    (SourceAccessDenied("private source body"), 403, "source_access_denied"),
    (HttpFixtureObservationChanged("private changed phase"), 409, "fixture_observation_changed"),
    (HttpFixtureInvalid("private journal bytes"), 502, "fixture_observation_invalid"),
    (HttpFixtureHistoryUnavailable("private database credentials"), 503, "fixture_history_unavailable"),
    (KeyError("private missing original"), 404, "not_found"),
])
def test_original_journal_error_is_private_and_not_empty_success(observation_http, fault, status, code, monkeypatch):
    client, v = observation_http
    def unavailable(*args): raise fault
    monkeypatch.setattr(v.observations, "read", unavailable)
    path = f"/v1/projects/{v.target.project_id}/quality/http-fixture-operations/{v.target.invocation_id}/observation"
    result = client.get(path)
    assert result.status_code == status and result.headers["Cache-Control"] == "private, no-store"
    assert result.json()["detail"]["error"]["code"] == code and "private" not in result.text
