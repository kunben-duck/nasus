from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from urllib.parse import urlparse


PRODUCTION_PROFILES = {"prod", "production", "staging", "stage"}
FALSE_VALUES = {"0", "false", "no", "off"}
PLACEHOLDER_VALUES = {
    "",
    "replace-with-a-random-production-token",
    "replace-with-the-api-bearer-token",
    "replace-with-your-chat-api-key",
    "replace-with-your-embedding-api-key",
    "replace-with-your-rerank-api-key",
    "your-chat-model",
    "your-embedding-model",
    "your-rerank-model",
    "replace-with-a-random-runner-service-token",
    "replace-with-a-random-32-byte-settings-encryption-secret",
    "nasus-local-shared-settings-secret-change-me",
}


class RuntimeConfigurationError(RuntimeError):
    """Raised when a staging/production process would start with dev defaults."""


@dataclass(frozen=True)
class RuntimeProfile:
    name: str

    @property
    def production_like(self) -> bool:
        return self.name in PRODUCTION_PROFILES


def current_runtime_profile() -> RuntimeProfile:
    profile = (
        os.getenv("NASUS_ENV")
        or os.getenv("NASUS_ENVIRONMENT")
        or os.getenv("NASUS_PROFILE")
        or "local"
    )
    return RuntimeProfile(name=profile.strip().lower() or "local")


def validate_runtime_configuration() -> None:
    """Fail fast before importing stateful app modules in staging/production."""

    profile = current_runtime_profile()
    if not profile.production_like:
        return

    errors: list[str] = []
    _require_postgres(errors)
    _require_alembic_owned_schema(errors)
    _require_auth(errors)
    _require_cors(errors)
    _require_shared_settings_encryption(errors)
    _require_object_storage(errors)
    _require_git_source_connector(errors)
    _require_code_graph(errors)
    _require_model_routes(errors)
    _require_durable_agent_runtime(errors)
    _require_runner(errors)
    _require_rate_limiting(errors)
    _require_no_demo_seed(errors)

    if errors:
        joined = "; ".join(errors)
        raise RuntimeConfigurationError(f"Invalid Nasus {profile.name} runtime configuration: {joined}")


def _require_postgres(errors: list[str]) -> None:
    database_url = os.getenv("NASUS_DATABASE_URL", "").strip()
    if not database_url:
        errors.append("NASUS_DATABASE_URL is required")
        return
    if database_url.startswith("sqlite"):
        errors.append("NASUS_DATABASE_URL must use PostgreSQL, not SQLite")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        errors.append("NASUS_DATABASE_URL must be a PostgreSQL SQLAlchemy URL")


def _require_alembic_owned_schema(errors: list[str]) -> None:
    if _truthy(os.getenv("NASUS_AUTO_CREATE_TABLES", "true")):
        errors.append("NASUS_AUTO_CREATE_TABLES must be false; run Alembic migrations instead")


def _require_auth(errors: list[str]) -> None:
    auth_mode = os.getenv("NASUS_AUTH_MODE", "").strip().lower()
    if auth_mode not in {"required", "prod", "production"}:
        errors.append("NASUS_AUTH_MODE must be required/prod/production")
    token = os.getenv("NASUS_AUTH_BEARER_TOKEN", "").strip()
    if _missing_or_placeholder(token):
        errors.append("NASUS_AUTH_BEARER_TOKEN must be configured with a non-placeholder value")


def _require_cors(errors: list[str]) -> None:
    raw_origins = os.getenv("NASUS_CORS_ALLOW_ORIGINS", "").strip()
    origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]
    if not origins:
        errors.append("NASUS_CORS_ALLOW_ORIGINS must explicitly allow trusted portal origins")
        return
    if "*" in origins:
        errors.append("NASUS_CORS_ALLOW_ORIGINS must not contain wildcard origins")
        return
    invalid = []
    for origin in origins:
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"}:
            invalid.append(origin)
    if invalid:
        errors.append(
            "NASUS_CORS_ALLOW_ORIGINS contains invalid HTTP(S) origins: "
            + ", ".join(invalid)
        )


def _require_shared_settings_encryption(errors: list[str]) -> None:
    secret = os.getenv("NASUS_SETTINGS_ENCRYPTION_SECRET", "").strip()
    if _missing_or_placeholder(secret) or len(secret) < 32:
        errors.append(
            "NASUS_SETTINGS_ENCRYPTION_SECRET must contain at least 32 "
            "non-placeholder characters shared by API and workflow workers"
        )


def _require_object_storage(errors: list[str]) -> None:
    required = [
        "NASUS_S3_ENDPOINT",
        "NASUS_S3_BUCKET",
        "NASUS_S3_ACCESS_KEY",
        "NASUS_S3_SECRET_KEY",
    ]
    missing = [name for name in required if _missing_or_placeholder(os.getenv(name, "").strip())]
    if missing:
        errors.append(f"S3/MinIO object storage is required; missing {', '.join(missing)}")


def _require_git_source_connector(errors: list[str]) -> None:
    allowed_hosts = os.getenv("NASUS_GIT_ALLOWED_HOSTS", "").strip()
    if not allowed_hosts:
        errors.append("NASUS_GIT_ALLOWED_HOSTS must explicitly allow production Git hosts")
    allowed_schemes = {
        item.strip().lower()
        for item in os.getenv("NASUS_GIT_ALLOWED_SCHEMES", "https,ssh").split(",")
        if item.strip()
    }
    if not allowed_schemes or not allowed_schemes.issubset({"git", "http", "https", "ssh"}):
        errors.append("NASUS_GIT_ALLOWED_SCHEMES contains an unsupported Git transport")


def _require_code_graph(errors: list[str]) -> None:
    mode = os.getenv("NASUS_CODE_GRAPH_MODE", "disabled").strip().lower()
    if mode not in {"disabled", "optional", "required"}:
        errors.append("NASUS_CODE_GRAPH_MODE must be disabled, optional, or required")
        return
    if mode != "required":
        errors.append("NASUS_CODE_GRAPH_MODE must be required in staging/production")
        return
    binary = os.getenv("NASUS_CODE_GRAPH_BINARY", "codebase-memory-mcp").strip()
    path = os.path.expanduser(binary)
    if not shutil.which(binary) and not (os.path.isfile(path) and os.access(path, os.X_OK)):
        errors.append(
            "NASUS_CODE_GRAPH_BINARY must resolve to an executable when code graph mode is required"
        )


def _require_model_routes(errors: list[str]) -> None:
    route_envs = {
        "chat": ("NASUS_DEFAULT_PROVIDER", "NASUS_DEFAULT_BASE_URL", "NASUS_DEFAULT_MODEL", "NASUS_DEFAULT_API_KEY"),
        "embedding": (
            "NASUS_EMBEDDING_PROVIDER",
            "NASUS_EMBEDDING_BASE_URL",
            "NASUS_EMBEDDING_MODEL",
            "NASUS_EMBEDDING_API_KEY",
        ),
        "rerank": ("NASUS_RERANK_PROVIDER", "NASUS_RERANK_BASE_URL", "NASUS_RERANK_MODEL", "NASUS_RERANK_API_KEY"),
    }
    for route, (provider_env, base_url_env, model_env, key_env) in route_envs.items():
        provider = os.getenv(provider_env, "").strip().lower().replace("-", "_")
        if provider in {"", "mock"}:
            errors.append(f"{provider_env} for {route} must not be mock or empty")
            continue
        if provider == "openai_compatible":
            missing = [
                name
                for name in (base_url_env, model_env, key_env)
                if _missing_or_placeholder(os.getenv(name, "").strip())
            ]
            if missing:
                errors.append(f"{route} OpenAI-compatible route is incomplete; missing {', '.join(missing)}")
        elif provider == "openai":
            if _missing_or_placeholder(os.getenv("OPENAI_API_KEY", "").strip()):
                errors.append(f"{route} OpenAI route requires OPENAI_API_KEY")
        elif provider == "gemini":
            if _missing_or_placeholder(os.getenv("GEMINI_API_KEY", "").strip()):
                errors.append(f"{route} Gemini route requires GEMINI_API_KEY")
        elif provider == "anthropic":
            if _missing_or_placeholder(os.getenv("ANTHROPIC_API_KEY", "").strip()):
                errors.append(f"{route} Anthropic route requires ANTHROPIC_API_KEY")
        else:
            errors.append(f"{provider_env} has unsupported provider {provider!r}")


def _require_durable_agent_runtime(errors: list[str]) -> None:
    workflow_runtime = os.getenv("NASUS_AGENT_WORKFLOW_RUNTIME", "local").strip().lower()
    graph_runtime = os.getenv("NASUS_AGENT_GRAPH_RUNTIME", "local").strip().lower()
    checkpoint_backend = os.getenv(
        "NASUS_LANGGRAPH_CHECKPOINT_BACKEND",
        "memory",
    ).strip().lower()
    if workflow_runtime != "temporal":
        errors.append("NASUS_AGENT_WORKFLOW_RUNTIME must be temporal")
    if graph_runtime != "langgraph":
        errors.append("NASUS_AGENT_GRAPH_RUNTIME must be langgraph")
    if checkpoint_backend != "postgres":
        errors.append("NASUS_LANGGRAPH_CHECKPOINT_BACKEND must be postgres")
    temporal_required = [
        "NASUS_TEMPORAL_ADDRESS",
        "NASUS_TEMPORAL_NAMESPACE",
        "NASUS_TEMPORAL_TASK_QUEUE",
        "NASUS_TEMPORAL_AGENT_GOAL_WORKFLOW",
    ]
    missing = [name for name in temporal_required if _missing_or_placeholder(os.getenv(name, "").strip())]
    if missing:
        errors.append(f"Temporal runtime is incomplete; missing {', '.join(missing)}")


def _require_runner(errors: list[str]) -> None:
    mode = os.getenv("NASUS_RUNNER_MODE", "").strip().lower()
    if mode != "http":
        errors.append("NASUS_RUNNER_MODE must be http")
        return

    endpoint = os.getenv("NASUS_RUNNER_ENDPOINT", "").strip()
    if _missing_or_placeholder(endpoint) or not endpoint.startswith(("http://", "https://")):
        errors.append("NASUS_RUNNER_ENDPOINT must be an HTTP(S) service URL")

    service_token = os.getenv("NASUS_RUNNER_SERVICE_TOKEN", "").strip()
    if _missing_or_placeholder(service_token) or len(service_token) < 24:
        errors.append("NASUS_RUNNER_SERVICE_TOKEN must contain at least 24 non-placeholder characters")

    allowed_hosts = {
        item.strip().lower()
        for item in os.getenv("NASUS_RUNNER_ALLOWED_HOSTS", "").split(",")
        if item.strip()
    }
    if not allowed_hosts:
        errors.append("NASUS_RUNNER_ALLOWED_HOSTS must explicitly allow automation target hosts")


def _require_no_demo_seed(errors: list[str]) -> None:
    if _truthy(os.getenv("NASUS_SEED_DEMO_DATA", "true")):
        errors.append("NASUS_SEED_DEMO_DATA must be false")


def _require_rate_limiting(errors: list[str]) -> None:
    if not _truthy(os.getenv("NASUS_RATE_LIMIT_ENABLED", "false")):
        errors.append("NASUS_RATE_LIMIT_ENABLED must be true")
    backend = os.getenv("NASUS_RATE_LIMIT_BACKEND", "").strip().lower()
    if backend != "postgres":
        errors.append("NASUS_RATE_LIMIT_BACKEND must be postgres")
    for name in (
        "NASUS_RATE_LIMIT_WINDOW_SECONDS",
        "NASUS_RATE_LIMIT_AUTH_PER_WINDOW",
        "NASUS_RATE_LIMIT_AGENT_PER_WINDOW",
        "NASUS_RATE_LIMIT_API_PER_WINDOW",
    ):
        raw_value = os.getenv(name, "").strip()
        try:
            value = int(raw_value)
        except ValueError:
            value = 0
        if value <= 0:
            errors.append(f"{name} must be a positive integer")


def demo_seed_enabled() -> bool:
    return _truthy(os.getenv("NASUS_SEED_DEMO_DATA", "true"))


def _truthy(value: str) -> bool:
    return value.strip().lower() not in FALSE_VALUES


def _missing_or_placeholder(value: str) -> bool:
    normalized = value.strip()
    return not normalized or normalized in PLACEHOLDER_VALUES
