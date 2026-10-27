"""Production HTTP routing with an application-port specimen, no app.main/PG."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.quality_loop.http_fixture_history import HttpFixtureHistoryQuery, HttpFixtureHistoryTarget
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.domain.quality_loop.http_fixture_history import HttpFixtureHistoryUnavailable
from apps.api.app.domain.system_image.evidence import EvidenceIntegrityError, EvidenceUnavailableError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from apps.api.app.interface.http.routers.run_plans import router
from apps.api.tests.test_http_fixture_history import history_specimen, native_grant, spec


@pytest.fixture
def history_http(history_specimen):
    v = history_specimen
    app = FastAPI()
    app.state.container = SimpleNamespace(http_fixture_jobs=v.jobs)
    app.include_router(router)
    with TestClient(app) as client: yield client, v


def test_project_discovery_and_single_read_are_metadata_only_gets(history_http):
    client, v = history_http
    base = f"/v1/projects/{v.query.project_id}/quality/http-fixture-operations"
    response = client.get(base, params={"limit": 2})
    assert response.status_code == 200 and response.headers["Cache-Control"] == "private, no-store"
    assert response.json() == v.history.list(v.query).model_dump(mode="json")
    single = client.get(base + "/002-execute")
    assert single.status_code == 200 and single.headers["Cache-Control"] == "private, no-store"
    assert single.json() == v.history.read(v.target).model_dump(mode="json")
    assert single.json()["execution_authorized"] is False and "input_payload" not in single.json()
    assert client.post(base).status_code == client.post(base + "/002-execute").status_code == 405


@pytest.mark.parametrize("detail", [False, True])
@pytest.mark.parametrize("fault,status,code", [
    (SourceAccessDenied("private source body"), 403, "source_access_denied"),
    (StaleSourceAccessScope("private changed source scope"), 409, "source_access_changed"),
    (HttpFixtureInvalid("private damaged grant"), 502, "fixture_history_invalid"),
    (EvidenceIntegrityError("private damaged evidence"), 502, "evidence_integrity_failed"),
    (EvidenceUnavailableError("private storage credentials"), 503, "evidence_unavailable"),
    (HttpFixtureHistoryUnavailable("private database credentials"), 503, "fixture_history_unavailable"),
    (KeyError("private missing command"), 404, "not_found"),
    (PlatformApplicationError("history_changed", "Inspect the original commands again.", 409), 409, "history_changed"),
])
def test_history_faults_are_private_and_do_not_downgrade_or_return_stale_metadata(history_http, detail, fault, status, code, monkeypatch):
    client, v = history_http
    def unavailable(*args): raise fault
    monkeypatch.setattr(v.history, "read" if detail else "list", unavailable)
    path = f"/v1/projects/{v.query.project_id}/quality/http-fixture-operations" + ("/002-execute" if detail else "")
    response = client.get(path)
    assert response.status_code == status and response.headers["Cache-Control"] == "private, no-store"
    assert response.json()["detail"]["error"]["code"] == code and "private" not in response.text


@pytest.mark.parametrize("params", [{"limit": "0"}, {"limit": "6"}, {"limit": "true"}, {"after_id": "x" * 129}])
def test_http_rejects_unbounded_pages_before_reading_history(history_http, params):
    client, v = history_http
    response = client.get(f"/v1/projects/{v.query.project_id}/quality/http-fixture-operations", params=params)
    assert response.status_code == 422 and not v.history_state["queries"]
