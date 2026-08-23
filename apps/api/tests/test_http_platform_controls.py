from __future__ import annotations

from time import time

from fastapi.testclient import TestClient
from sqlalchemy import delete

from apps.api.app.application.platform.request_rate_limits import (
    RequestRateLimitApplicationService,
)
from apps.api.app.interface.http.auth import AuthConfig
from apps.api.app.infrastructure.config.rate_limit_config import RateLimitConfig
from apps.api.app.infrastructure.persistence.database import SessionLocal, init_database
from apps.api.app.infrastructure.persistence.db_models import ApiRateLimitWindowRecord
from apps.api.app.infrastructure.platform.request_rate_limiter import (
    SQLAlchemyFixedWindowRateLimiter,
)
from apps.api.app.main import app


def _clear_rate_limit_windows() -> None:
    init_database()
    with SessionLocal() as session:
        session.execute(delete(ApiRateLimitWindowRecord))
        session.commit()


def test_fixed_window_rate_limiter_uses_shared_persistent_budget() -> None:
    _clear_rate_limit_windows()
    service = RequestRateLimitApplicationService(
        SQLAlchemyFixedWindowRateLimiter(SessionLocal, cleanup_interval=1000)
    )
    occurred_at = int(time())

    first = service.consume(
        scope="auth",
        principal="ip:test-client",
        limit=2,
        window_seconds=60,
        occurred_at_epoch=occurred_at,
    )
    second = service.consume(
        scope="auth",
        principal="ip:test-client",
        limit=2,
        window_seconds=60,
        occurred_at_epoch=occurred_at,
    )
    rejected = service.consume(
        scope="auth",
        principal="ip:test-client",
        limit=2,
        window_seconds=60,
        occurred_at_epoch=occurred_at,
    )

    assert first.allowed is True
    assert first.remaining == 1
    assert second.allowed is True
    assert second.remaining == 0
    assert rejected.allowed is False
    assert rejected.retry_after_seconds > 0


def test_request_id_is_sanitized_propagated_and_exported_in_metrics() -> None:
    client = TestClient(app)

    supplied = client.get("/healthz", headers={"X-Request-ID": "request:test-123"})
    generated = client.get("/healthz", headers={"X-Request-ID": "invalid request id"})
    metrics = client.get("/metrics")

    assert supplied.headers["X-Request-ID"] == "request:test-123"
    assert generated.headers["X-Request-ID"].startswith("req_")
    assert metrics.status_code == 200
    assert metrics.headers["X-Request-ID"].startswith("req_")
    assert "nasus_http_requests_total" in metrics.text
    assert 'route="/healthz"' in metrics.text
    assert "nasus_operational_snapshot_up 1.0" in metrics.text
    assert "nasus_tool_invocations" in metrics.text
    assert "nasus_agent_goals" in metrics.text
    assert "nasus_raw_assets" in metrics.text
    assert "nasus_llm_calls" in metrics.text


def test_auth_rate_limit_fails_closed_with_retry_headers() -> None:
    _clear_rate_limit_windows()
    previous_config = app.state.rate_limit_config
    previous_limiter = app.state.request_rate_limiter
    app.state.rate_limit_config = RateLimitConfig(
        enabled=True,
        backend="postgres",
        window_seconds=60,
        auth_limit=1,
        agent_limit=20,
        api_limit=100,
    )
    app.state.request_rate_limiter = RequestRateLimitApplicationService(
        SQLAlchemyFixedWindowRateLimiter(SessionLocal, cleanup_interval=1000)
    )
    client = TestClient(app)
    try:
        first = client.post(
            "/v1/auth/login",
            json={"email": "missing@example.com", "password": "invalid-password"},
        )
        rejected = client.post(
            "/v1/auth/login",
            json={"email": "missing@example.com", "password": "invalid-password"},
        )
    finally:
        app.state.rate_limit_config = previous_config
        app.state.request_rate_limiter = previous_limiter

    assert first.status_code in {401, 404}
    assert first.headers["X-RateLimit-Scope"] == "auth"
    assert rejected.status_code == 429
    assert rejected.json()["error"]["code"] == "rate_limit_exceeded"
    assert rejected.headers["Retry-After"]
    assert rejected.headers["X-RateLimit-Remaining"] == "0"


def test_rate_limiter_dependency_failure_returns_503() -> None:
    class UnavailableLimiter:
        def consume(self, **kwargs):
            raise ConnectionError("database unavailable")

    previous_config = app.state.rate_limit_config
    previous_limiter = app.state.request_rate_limiter
    app.state.rate_limit_config = RateLimitConfig(
        enabled=True,
        backend="postgres",
        window_seconds=60,
        auth_limit=10,
        agent_limit=20,
        api_limit=100,
    )
    app.state.request_rate_limiter = UnavailableLimiter()
    try:
        response = TestClient(app).post(
            "/v1/auth/login",
            json={"email": "missing@example.com", "password": "invalid-password"},
        )
    finally:
        app.state.rate_limit_config = previous_config
        app.state.request_rate_limiter = previous_limiter

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "rate_limiter_unavailable"


def test_metrics_endpoint_requires_authentication_in_protected_mode() -> None:
    previous_config = app.state.auth_config
    app.state.auth_config = AuthConfig(
        mode="required",
        bearer_token="metrics-scrape-token",
        user_id="metrics_service",
        user_name="Metrics Service",
        user_email="metrics@example.com",
        user_role="platform_admin",
    )
    client = TestClient(app)
    try:
        anonymous = client.get("/metrics")
        authenticated = client.get(
            "/metrics",
            headers={"Authorization": "Bearer metrics-scrape-token"},
        )
    finally:
        app.state.auth_config = previous_config

    assert anonymous.status_code == 401
    assert authenticated.status_code == 200
    assert "nasus_http_requests_total" in authenticated.text
    assert "nasus_operational_snapshot_up 1.0" in authenticated.text
