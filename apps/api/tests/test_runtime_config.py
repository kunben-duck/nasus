from __future__ import annotations

import sys

import pytest

from apps.api.app.infrastructure.config.agent_runtime_config import TemporalGatewayConfig
from apps.api.app.infrastructure.persistence.settings_store import SettingsPersistence
from apps.api.app.infrastructure.workflow.agent_goal_workflow_worker import (
    build_nasus_agent_goal_workflow,
)
from apps.api.app.runtime_config import RuntimeConfigurationError, demo_seed_enabled, validate_runtime_configuration


PRODUCTION_ENV = {
    "NASUS_ENV": "production",
    "NASUS_DATABASE_URL": "postgresql+psycopg://nasus:secret@postgres:5432/nasus",
    "NASUS_AUTO_CREATE_TABLES": "false",
    "NASUS_AUTH_MODE": "required",
    "NASUS_AUTH_BEARER_TOKEN": "strong-test-token",
    "NASUS_CORS_ALLOW_ORIGINS": "https://nasus.example.com",
    "NASUS_SETTINGS_ENCRYPTION_SECRET": "strong-shared-settings-secret-1234567890",
    "NASUS_S3_ENDPOINT": "http://minio:9000",
    "NASUS_S3_BUCKET": "nasus-artifacts",
    "NASUS_S3_ACCESS_KEY": "nasus-access",
    "NASUS_S3_SECRET_KEY": "nasus-secret",
    "NASUS_GIT_ALLOWED_HOSTS": "github.com,git.example.com",
    "NASUS_GIT_ALLOWED_SCHEMES": "https,ssh",
    "NASUS_CODE_GRAPH_MODE": "required",
    "NASUS_CODE_GRAPH_BINARY": sys.executable,
    "NASUS_DEFAULT_PROVIDER": "openai_compatible",
    "NASUS_DEFAULT_BASE_URL": "https://llm.example.com/v1",
    "NASUS_DEFAULT_MODEL": "chat-model",
    "NASUS_DEFAULT_API_KEY": "chat-key",
    "NASUS_EMBEDDING_PROVIDER": "openai_compatible",
    "NASUS_EMBEDDING_BASE_URL": "https://embedding.example.com/v1",
    "NASUS_EMBEDDING_MODEL": "embedding-model",
    "NASUS_EMBEDDING_API_KEY": "embedding-key",
    "NASUS_RERANK_PROVIDER": "openai_compatible",
    "NASUS_RERANK_BASE_URL": "https://rerank.example.com/v1",
    "NASUS_RERANK_MODEL": "rerank-model",
    "NASUS_RERANK_API_KEY": "rerank-key",
    "NASUS_AGENT_WORKFLOW_RUNTIME": "temporal",
    "NASUS_AGENT_GRAPH_RUNTIME": "langgraph",
    "NASUS_LANGGRAPH_CHECKPOINT_BACKEND": "postgres",
    "NASUS_TEMPORAL_ADDRESS": "temporal:7233",
    "NASUS_TEMPORAL_NAMESPACE": "default",
    "NASUS_TEMPORAL_TASK_QUEUE": "nasus-agent-goals",
    "NASUS_TEMPORAL_AGENT_GOAL_WORKFLOW": "NasusAgentGoalWorkflow",
    "NASUS_RUNNER_MODE": "http",
    "NASUS_RUNNER_ENDPOINT": "http://runner:8090",
    "NASUS_RUNNER_SERVICE_TOKEN": "strong-runner-service-token",
    "NASUS_RUNNER_ALLOWED_HOSTS": "portal,app.example.com",
    "NASUS_RATE_LIMIT_ENABLED": "true",
    "NASUS_RATE_LIMIT_BACKEND": "postgres",
    "NASUS_RATE_LIMIT_WINDOW_SECONDS": "60",
    "NASUS_RATE_LIMIT_AUTH_PER_WINDOW": "10",
    "NASUS_RATE_LIMIT_AGENT_PER_WINDOW": "30",
    "NASUS_RATE_LIMIT_API_PER_WINDOW": "120",
    "NASUS_SEED_DEMO_DATA": "false",
}


def set_env(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
    for key in {
        "NASUS_ENV",
        "NASUS_ENVIRONMENT",
        "NASUS_PROFILE",
        "NASUS_DATABASE_URL",
        "NASUS_AUTO_CREATE_TABLES",
        "NASUS_AUTH_MODE",
        "NASUS_AUTH_BEARER_TOKEN",
        "NASUS_CORS_ALLOW_ORIGINS",
        "NASUS_SETTINGS_ENCRYPTION_SECRET",
        "NASUS_S3_ENDPOINT",
        "NASUS_S3_BUCKET",
        "NASUS_S3_ACCESS_KEY",
        "NASUS_S3_SECRET_KEY",
        "NASUS_GIT_ALLOWED_HOSTS",
        "NASUS_GIT_ALLOWED_SCHEMES",
        "NASUS_CODE_GRAPH_MODE",
        "NASUS_CODE_GRAPH_BINARY",
        "NASUS_DEFAULT_PROVIDER",
        "NASUS_DEFAULT_BASE_URL",
        "NASUS_DEFAULT_MODEL",
        "NASUS_DEFAULT_API_KEY",
        "NASUS_EMBEDDING_PROVIDER",
        "NASUS_EMBEDDING_BASE_URL",
        "NASUS_EMBEDDING_MODEL",
        "NASUS_EMBEDDING_API_KEY",
        "NASUS_RERANK_PROVIDER",
        "NASUS_RERANK_BASE_URL",
        "NASUS_RERANK_MODEL",
        "NASUS_RERANK_API_KEY",
        "NASUS_AGENT_WORKFLOW_RUNTIME",
        "NASUS_AGENT_GRAPH_RUNTIME",
        "NASUS_LANGGRAPH_CHECKPOINT_BACKEND",
        "NASUS_TEMPORAL_ADDRESS",
        "NASUS_TEMPORAL_NAMESPACE",
        "NASUS_TEMPORAL_TASK_QUEUE",
        "NASUS_TEMPORAL_AGENT_GOAL_WORKFLOW",
        "NASUS_RUNNER_MODE",
        "NASUS_RUNNER_ENDPOINT",
        "NASUS_RUNNER_SERVICE_TOKEN",
        "NASUS_RUNNER_ALLOWED_HOSTS",
        "NASUS_RATE_LIMIT_ENABLED",
        "NASUS_RATE_LIMIT_BACKEND",
        "NASUS_RATE_LIMIT_WINDOW_SECONDS",
        "NASUS_RATE_LIMIT_AUTH_PER_WINDOW",
        "NASUS_RATE_LIMIT_AGENT_PER_WINDOW",
        "NASUS_RATE_LIMIT_API_PER_WINDOW",
        "NASUS_SEED_DEMO_DATA",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "ANTHROPIC_API_KEY",
    }:
        monkeypatch.delenv(key, raising=False)
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_local_runtime_allows_dev_defaults(monkeypatch: pytest.MonkeyPatch):
    set_env(monkeypatch, {"NASUS_ENV": "local"})

    validate_runtime_configuration()
    assert demo_seed_enabled() is True


def test_temporal_agent_goal_workflow_is_module_level_and_uses_canonical_protocol():
    workflow_class = build_nasus_agent_goal_workflow()

    assert workflow_class.__name__ == "NasusAgentGoalWorkflow"
    assert "<locals>" not in workflow_class.__qualname__

    with pytest.raises(RuntimeError, match="protocol names are fixed"):
        build_nasus_agent_goal_workflow(
            TemporalGatewayConfig(workflow_type="DriftedAgentGoalWorkflow")
        )


def test_production_runtime_rejects_dev_defaults(monkeypatch: pytest.MonkeyPatch):
    set_env(
        monkeypatch,
        {
            "NASUS_ENV": "production",
            "NASUS_DATABASE_URL": "sqlite+pysqlite:///tmp/nasus.db",
            "NASUS_AUTO_CREATE_TABLES": "true",
            "NASUS_AUTH_MODE": "dev",
            "NASUS_DEFAULT_PROVIDER": "mock",
            "NASUS_AGENT_WORKFLOW_RUNTIME": "local",
            "NASUS_AGENT_GRAPH_RUNTIME": "local",
            "NASUS_LANGGRAPH_CHECKPOINT_BACKEND": "memory",
            "NASUS_SEED_DEMO_DATA": "true",
        },
    )

    with pytest.raises(RuntimeConfigurationError) as exc_info:
        validate_runtime_configuration()

    message = str(exc_info.value)
    assert "PostgreSQL" in message
    assert "NASUS_AUTO_CREATE_TABLES must be false" in message
    assert "NASUS_AUTH_MODE must be required" in message
    assert "NASUS_AUTH_BEARER_TOKEN" in message
    assert "NASUS_CORS_ALLOW_ORIGINS" in message
    assert "NASUS_SETTINGS_ENCRYPTION_SECRET" in message
    assert "S3/MinIO object storage is required" in message
    assert "NASUS_GIT_ALLOWED_HOSTS" in message
    assert "NASUS_CODE_GRAPH_MODE must be required" in message
    assert "NASUS_DEFAULT_PROVIDER for chat must not be mock" in message
    assert "NASUS_AGENT_WORKFLOW_RUNTIME must be temporal" in message
    assert "NASUS_AGENT_GRAPH_RUNTIME must be langgraph" in message
    assert "NASUS_LANGGRAPH_CHECKPOINT_BACKEND must be postgres" in message
    assert "NASUS_RUNNER_MODE must be http" in message
    assert "NASUS_RATE_LIMIT_ENABLED must be true" in message
    assert "NASUS_RATE_LIMIT_BACKEND must be postgres" in message
    assert "NASUS_SEED_DEMO_DATA must be false" in message


def test_production_runtime_accepts_explicit_durable_configuration(monkeypatch: pytest.MonkeyPatch):
    set_env(monkeypatch, PRODUCTION_ENV)

    validate_runtime_configuration()
    assert demo_seed_enabled() is False


def test_production_required_code_graph_must_resolve_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_env(
        monkeypatch,
        {
            **PRODUCTION_ENV,
            "NASUS_CODE_GRAPH_MODE": "required",
            "NASUS_CODE_GRAPH_BINARY": "/missing/codebase-memory-mcp",
        },
    )

    with pytest.raises(RuntimeConfigurationError) as exc_info:
        validate_runtime_configuration()

    assert "NASUS_CODE_GRAPH_BINARY must resolve to an executable" in str(exc_info.value)


def test_staging_runtime_rejects_placeholder_secrets(monkeypatch: pytest.MonkeyPatch):
    env = {
        **PRODUCTION_ENV,
        "NASUS_ENV": "staging",
        "NASUS_AUTH_BEARER_TOKEN": "replace-with-a-random-production-token",
        "NASUS_SETTINGS_ENCRYPTION_SECRET": "replace-with-a-random-32-byte-settings-encryption-secret",
        "NASUS_DEFAULT_API_KEY": "replace-with-your-chat-api-key",
    }
    set_env(monkeypatch, env)

    with pytest.raises(RuntimeConfigurationError) as exc_info:
        validate_runtime_configuration()

    message = str(exc_info.value)
    assert "NASUS_AUTH_BEARER_TOKEN must be configured" in message
    assert "NASUS_SETTINGS_ENCRYPTION_SECRET must contain at least 32" in message
    assert "chat OpenAI-compatible route is incomplete" in message


def test_settings_encryption_secret_is_shared_across_process_state_dirs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    monkeypatch.setenv(
        "NASUS_SETTINGS_ENCRYPTION_SECRET",
        "shared-settings-secret-for-api-and-worker-123456",
    )
    monkeypatch.setenv("NASUS_STATE_DIR", str(tmp_path / "api-state"))
    api_persistence = SettingsPersistence()
    encrypted = api_persistence.encrypt_api_key("sk-cross-process-secret")

    monkeypatch.setenv("NASUS_STATE_DIR", str(tmp_path / "worker-state"))
    worker_persistence = SettingsPersistence()

    assert api_persistence.key_file != worker_persistence.key_file
    assert worker_persistence.decrypt_api_key(encrypted) == "sk-cross-process-secret"


@pytest.mark.parametrize(
    ("env_patch", "expected"),
    [
        ({"NASUS_CORS_ALLOW_ORIGINS": "*"}, "must not contain wildcard origins"),
        ({"NASUS_CORS_ALLOW_ORIGINS": "nasus.example.com"}, "invalid HTTP(S) origins"),
        ({"NASUS_RUNNER_MODE": "protocol_stub"}, "NASUS_RUNNER_MODE must be http"),
        ({"NASUS_RUNNER_ENDPOINT": ""}, "NASUS_RUNNER_ENDPOINT must be an HTTP(S) service URL"),
        ({"NASUS_RUNNER_SERVICE_TOKEN": "short"}, "at least 24 non-placeholder characters"),
        ({"NASUS_RUNNER_ALLOWED_HOSTS": ""}, "must explicitly allow automation target hosts"),
        ({"NASUS_RATE_LIMIT_ENABLED": "false"}, "NASUS_RATE_LIMIT_ENABLED must be true"),
        ({"NASUS_RATE_LIMIT_BACKEND": "memory"}, "NASUS_RATE_LIMIT_BACKEND must be postgres"),
        ({"NASUS_RATE_LIMIT_AUTH_PER_WINDOW": "0"}, "must be a positive integer"),
    ],
)
def test_production_runtime_rejects_unsafe_runner_configuration(
    monkeypatch: pytest.MonkeyPatch,
    env_patch: dict[str, str],
    expected: str,
):
    set_env(monkeypatch, {**PRODUCTION_ENV, **env_patch})

    with pytest.raises(RuntimeConfigurationError) as exc_info:
        validate_runtime_configuration()

    assert expected in str(exc_info.value)
