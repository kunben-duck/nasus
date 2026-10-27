"""HTTP read-port contract specimens; native PG/MinIO verification is separate."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.app.interface.http.routers.run_plans import router
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.application.platform.errors import PlatformApplicationError


def client(port):
    app = FastAPI()
    app.include_router(router)
    app.state.container = SimpleNamespace(native_builds=port)
    return TestClient(app)


def test_native_build_read_uses_original_application_without_dispatch():
    calls = []
    expected = {"project_id": "p", "invocation_id": "original", "metadata": None,
                "status": "running", "execution_authorized": False}
    port = SimpleNamespace(read=lambda p, i: calls.append((p, i)) or expected)
    response = client(port).get("/v1/projects/p/quality/native-builds/original")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == expected and calls == [("p", "original")]


@pytest.mark.parametrize("fault,status", [(SourceAccessDenied("private"), 403),
    (KeyError("missing"), 404), (ValueError("private corrupted archive"), 502),
    (PlatformApplicationError("denied", "Original inputs are unavailable.", 403), 403)])
def test_native_build_read_preserves_denial_and_hides_internal_error(fault, status):
    def read(*args):
        raise fault
    response = client(SimpleNamespace(read=read)).get("/v1/projects/p/quality/native-builds/original")
    assert response.status_code == status
    assert response.headers["cache-control"] == "private, no-store"
    assert "private" not in response.text and "corrupted archive" not in response.text
