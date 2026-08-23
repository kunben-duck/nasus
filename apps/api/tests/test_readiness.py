from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from apps.api.app.application.platform.readiness import (
    ReadinessApplicationService,
    ReadinessCheck,
    ReadinessReport,
)
from apps.api.app.application.platform.model_settings import (
    ModelProviderProfile,
    StudioSettings,
)
from apps.api.app.infrastructure.config.agent_runtime_config import (
    LangGraphGatewayConfig,
    TemporalGatewayConfig,
)
from apps.api.app.infrastructure.llm.readiness import (
    ModelRoutesReadinessProbe,
    PromptRegistryReadinessProbe,
)
from apps.api.app.domain.platform.prompt_registry import builtin_prompt
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.runner.readiness import AutomationRunnerReadinessProbe
from apps.api.app.infrastructure.system_image.readiness import (
    CodeIntelligenceReadinessProbe,
)
from apps.api.app.infrastructure.workflow.readiness import (
    LangGraphCheckpointReadinessProbe,
    TemporalWorkflowReadinessProbe,
)
from apps.api.app.main import app


class HealthyProbe:
    name = "healthy"

    def check(self) -> dict[str, str]:
        return {"backend": "test"}


class FailingProbe:
    name = "failing"

    def check(self) -> dict[str, str]:
        raise ConnectionError("dependency is unavailable")


class StubReadinessService:
    def __init__(self, report: ReadinessReport) -> None:
        self._report = report

    def check(self) -> ReadinessReport:
        return self._report


def test_readiness_application_reports_all_mandatory_probes():
    report = ReadinessApplicationService((HealthyProbe(), FailingProbe())).check()

    assert report.ready is False
    assert report.status == "unavailable"
    assert report.checks["healthy"].status == "ready"
    assert report.checks["healthy"].details == {"backend": "test"}
    assert report.checks["failing"].status == "unavailable"
    assert report.checks["failing"].details["reason"] == "dependency is unavailable"


def test_readyz_returns_503_when_a_mandatory_dependency_is_unavailable():
    previous = app.state.readiness
    app.state.readiness = StubReadinessService(
        ReadinessReport(
            status="unavailable",
            checks={
                "database": ReadinessCheck(
                    status="unavailable",
                    details={"reason": "database is unavailable"},
                )
            },
        )
    )
    try:
        response = TestClient(app).get("/readyz")
    finally:
        app.state.readiness = previous

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["checks"]["database"]["status"] == "unavailable"


def test_readyz_is_public_and_returns_component_details():
    response = TestClient(app).get("/readyz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["checks"]["database"]["status"] == "ready"
    assert payload["checks"]["object_storage"]["status"] == "ready"
    assert payload["checks"]["git_source_connector"]["status"] == "ready"
    assert payload["checks"]["git_source_connector"]["details"]["backend"] == "git"
    assert payload["checks"]["code_intelligence"]["status"] == "ready"
    assert payload["checks"]["code_intelligence"]["details"]["backend"] == "tree-sitter"
    assert payload["checks"]["code_intelligence"]["details"]["graph_status"] == "disabled"
    assert payload["checks"]["automation_runner"]["status"] == "ready"
    assert payload["checks"]["automation_runner"]["details"]["backend"] in {
        "disabled",
        "protocol_stub",
    }


def test_code_intelligence_readiness_executes_tree_sitter_smoke_parse():
    details = CodeIntelligenceReadinessProbe().check()

    assert details["backend"] == "tree-sitter"
    assert "python" in details["languages"]
    assert details["fallback_policy"] == "explicit_lexical_evidence"


def test_http_runner_readiness_requires_runner_ready_payload(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "ready", "browser": "chromium"}

    monkeypatch.setattr(
        "apps.api.app.infrastructure.runner.readiness.httpx.get",
        lambda url, timeout: Response(),
    )

    details = AutomationRunnerReadinessProbe(
        mode="http",
        endpoint="http://runner:8090",
    ).check()

    assert details == {
        "backend": "http_playwright",
        "endpoint": "http://runner:8090",
        "browser": "chromium",
    }


def test_http_runner_readiness_rejects_non_ready_payload(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "not_ready", "browser": "unavailable"}

    monkeypatch.setattr(
        "apps.api.app.infrastructure.runner.readiness.httpx.get",
        lambda url, timeout: Response(),
    )

    with pytest.raises(RuntimeError, match="did not report ready"):
        AutomationRunnerReadinessProbe(
            mode="http",
            endpoint="http://runner:8090",
        ).check()


def _settings_with_runtime_mode(runtime_mode: str) -> StudioSettings:
    profiles = {
        route: ModelProviderProfile(
            route=route,
            model_preset="system_default",
            model_provider="openai_compatible",
            model_name=f"{route}-model",
            runtime_mode=runtime_mode,
        )
        for route in ("chat", "embedding", "rerank")
    }
    return StudioSettings(model_profiles=profiles)


def test_model_routes_readiness_allows_development_fallback():
    details = ModelRoutesReadinessProbe(
        lambda: _settings_with_runtime_mode("fallback"),
        require_live=False,
    ).check()

    assert details["backend"] == "development_fallback"
    assert details["chat"].startswith("fallback:")


def test_model_routes_readiness_requires_live_routes_in_production():
    probe = ModelRoutesReadinessProbe(
        lambda: _settings_with_runtime_mode("fallback"),
        require_live=True,
    )

    with pytest.raises(RuntimeError, match="production model routes are not live"):
        probe.check()


def test_prompt_registry_readiness_requires_all_active_templates():
    class Registry:
        def get_active(self, prompt_id: str):
            return builtin_prompt(prompt_id)

    details = PromptRegistryReadinessProbe(Registry()).check()  # type: ignore[arg-type]

    assert details["backend"] == "postgresql"
    assert int(details["active_count"]) >= 6
    assert "agent_loop_planner@1.1.0" in details["active_versions"]


def test_temporal_readiness_reports_local_runtime_as_development_only():
    details = TemporalWorkflowReadinessProbe(
        TemporalGatewayConfig(
            address="temporal:7233",
            namespace="default",
            task_queue="nasus-agent",
            workflow_type="NasusAgentGoalWorkflow",
        ),
        runtime_kind="local",
    ).check()

    assert details == {"backend": "local", "status": "development_only"}


def test_temporal_readiness_checks_frontend_reachability(monkeypatch):
    calls: list[tuple[tuple[str, int], float]] = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    def create_connection(address, timeout):
        calls.append((address, timeout))
        return Connection()

    monkeypatch.setattr(
        "apps.api.app.infrastructure.workflow.readiness.socket.create_connection",
        create_connection,
    )
    details = TemporalWorkflowReadinessProbe(
        TemporalGatewayConfig(
            address="temporal.internal:7233",
            namespace="nasus",
            task_queue="nasus-agent",
            workflow_type="NasusAgentGoalWorkflow",
        ),
        runtime_kind="temporal",
        timeout_seconds=2.0,
    ).check()

    assert calls == [(("temporal.internal", 7233), 2.0)]
    assert details["backend"] == "temporal"
    assert details["namespace"] == "nasus"


def test_langgraph_readiness_reports_memory_runtime_as_development_only():
    details = LangGraphCheckpointReadinessProbe(
        engine,
        LangGraphGatewayConfig(
            graph_name="nasus-agent-loop",
            checkpoint_backend="memory",
        ),
        runtime_kind="local",
    ).check()

    assert details == {"backend": "memory", "status": "development_only"}
