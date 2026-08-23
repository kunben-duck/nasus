from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_docker_compose_declares_required_external_components():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "pgvector/pgvector:pg16" in compose
    assert "./infra/docker/postgres/init:/docker-entrypoint-initdb.d:ro" in compose
    assert "minio/minio:latest" in compose
    assert "minio/mc:latest" in compose
    assert "mc mb --ignore-existing" in compose
    assert "mc version enable" in compose
    assert "container_name:" not in compose


def test_docker_compose_declares_production_like_app_topology():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "dockerfile: infra/docker/api/Dockerfile" in compose
    assert "dockerfile: infra/docker/runner/Dockerfile" in compose
    assert "dockerfile: infra/docker/portal/Dockerfile" in compose
    assert "api-migrate:" in compose
    assert "runner:" in compose
    assert "api:" in compose
    assert "portal:" in compose
    assert "temporal:" in compose
    assert "DB: postgres12" in compose
    assert "DB: postgresql" not in compose
    assert "DYNAMIC_CONFIG_FILE_PATH: config/dynamicconfig/docker.yaml" in compose
    assert "temporal-ui:" in compose
    assert 'profiles: ["app"]' in compose
    assert 'profiles: ["temporal"]' in compose
    assert "NASUS_DATABASE_URL: postgresql+psycopg://" in compose
    assert "NASUS_S3_ENDPOINT: http://minio:9000" in compose
    assert "NASUS_SOURCE_CACHE_DIR: /var/lib/nasus/source-cache" in compose
    assert "NASUS_GIT_ALLOWED_HOSTS:" in compose
    assert "NASUS_CODE_GRAPH_MODE:" in compose
    assert "NASUS_CODE_GRAPH_CACHE_DIR: /var/lib/nasus/code-graph-cache" in compose
    assert "nasus-source-cache:/var/lib/nasus/source-cache" in compose
    assert "NASUS_AGENT_WORKFLOW_RUNTIME:" in compose
    assert "NASUS_AGENT_WORKFLOW_RUNTIME: ${NASUS_AGENT_WORKFLOW_RUNTIME:-temporal}" in compose
    assert "NASUS_AGENT_GRAPH_RUNTIME: ${NASUS_AGENT_GRAPH_RUNTIME:-langgraph}" in compose
    assert "NASUS_LANGGRAPH_CHECKPOINT_BACKEND: ${NASUS_LANGGRAPH_CHECKPOINT_BACKEND:-postgres}" in compose
    assert 'profiles: ["app", "temporal"]' in compose
    assert "NASUS_TEMPORAL_ADDRESS:" in compose
    assert "NASUS_RUNNER_MODE:" in compose
    assert "NASUS_RUNNER_ENDPOINT:" in compose
    assert "NASUS_RUNNER_SERVICE_TOKEN:" in compose
    assert "NASUS_RUNNER_ALLOWED_HOSTS:" in compose
    assert "NASUS_SETTINGS_ENCRYPTION_SECRET:" in compose
    assert "no-new-privileges:true" in compose
    assert "cap_drop:" in compose
    assert "read_only: true" in compose
    assert 'curl -fsS http://127.0.0.1:8000/readyz' in compose


def test_api_and_portal_container_contracts_are_declared():
    api_dockerfile = (ROOT / "infra/docker/api/Dockerfile").read_text(encoding="utf-8")
    portal_dockerfile = (ROOT / "infra/docker/portal/Dockerfile").read_text(encoding="utf-8")
    runner_dockerfile = (ROOT / "infra/docker/runner/Dockerfile").read_text(encoding="utf-8")
    nginx = (ROOT / "infra/docker/portal/nginx.conf").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "FROM python:3.11-slim" in api_dockerfile
    assert "pip install -r /tmp/requirements.txt" in api_dockerfile
    assert 'CODEBASE_MEMORY_MCP_VERSION=0.8.1' in api_dockerfile
    assert 'codebase-memory-mcp==${CODEBASE_MEMORY_MCP_VERSION}' in api_dockerfile
    assert "codebase-memory-mcp --version" in api_dockerfile
    assert "ca-certificates curl git openssh-client" in api_dockerfile
    assert "uvicorn" in api_dockerfile
    assert "FROM node:22-alpine AS build" in portal_dockerfile
    assert "npm ci" in portal_dockerfile
    assert "npm run build" in portal_dockerfile
    assert "FROM nginx:" in portal_dockerfile
    assert "mcr.microsoft.com/playwright:v1.58.2-noble" in runner_dockerfile
    assert "USER pwuser" in runner_dockerfile
    assert "proxy_pass http://api:8000/v1/" in nginx
    assert "proxy_buffering off" in nginx
    assert "try_files $uri $uri/ /index.html" in nginx
    assert ".venv" in dockerignore
    assert "node_modules" in dockerignore


def test_postgres_init_enables_required_extensions():
    init_sql = (ROOT / "infra/docker/postgres/init/01-extensions.sql").read_text(encoding="utf-8").lower()

    assert "create extension if not exists vector" in init_sql
    assert "create extension if not exists pg_trgm" in init_sql


def test_docker_stack_verifier_checks_runtime_contracts():
    script = (ROOT / "scripts/verify-docker-stack.sh").read_text(encoding="utf-8")

    assert "docker compose" in script
    assert "pg_isready" in script
    assert "SELECT extname FROM pg_extension WHERE extname = 'vector';" in script
    assert "alembic -c apps/api/alembic.ini upgrade head" in script
    assert "mc version info" in script
    assert "mc cp" in script
    assert "mc cat" in script
    assert "uvicorn apps.api.app.main:app" in script
    assert "NASUS_DATABASE_URL=\"postgresql+psycopg://" in script
    assert "NASUS_AUTO_CREATE_TABLES=false" in script
    assert "NASUS_S3_ENDPOINT=" in script
    assert "NASUS_SOURCE_ALLOWED_LOCAL_ROOTS=" in script
    assert "NASUS_ENV=production" in script
    assert "NASUS_AUTH_MODE=required" in script
    assert "NASUS_SETTINGS_ENCRYPTION_SECRET=" in script
    assert "Restarting Temporal worker while AgentGoal is paused" in script
    assert "workflow_recovery.json" in script
    assert "tool.invocation.confirmed" in script
    assert "NASUS_DEFAULT_PROVIDER=openai_compatible" in script
    assert "NASUS_EMBEDDING_PROVIDER=openai_compatible" in script
    assert "NASUS_RERANK_PROVIDER=openai_compatible" in script
    assert "NASUS_CODE_GRAPH_MODE=required" in script
    assert 'NASUS_CODE_GRAPH_BINARY="$NASUS_CODE_GRAPH_BINARY"' in script
    assert "openai_compatible_server.py" in script
    assert "/v1/settings/test-connection" in script
    assert "/__stats" in script
    assert "Model protocol calls verified" in script
    assert "/v1/tools/catalog" in script
    assert "/v1/tool-invocations" in script
    assert "system_image.sources.register" in script
    assert "system_image.sources.ingest" in script
    assert "system_image.context.materialize" in script
    assert "system_image.baseline.initialize" in script
    assert 'readiness["checks"]["code_intelligence"]["details"]["backend"] == "tree-sitter"' in script
    assert '{"CodeClass", "CodeMethod", "USWorkItem", "TestCase"}.issubset(object_types)' in script
    assert "quality.scenario.generate" in script
    assert "quality.case.generate" in script
    assert "automation.generate" in script
    assert "release.assess" in script
    assert "execution_evidence" in script
    assert 'if item["evidence_type"] == "report"' in script
    assert "runner result report evidence was not produced" in script
    assert "s3://" in script
    assert "runner_status" in script
    assert "SELECT count(*) FROM runs" in script
    assert "SELECT count(*) FROM execution_evidence" in script


def test_v1_release_verifier_composes_required_gates():
    package = (ROOT / "package.json").read_text(encoding="utf-8")
    script = (ROOT / "scripts/verify-v1-release.sh").read_text(encoding="utf-8")

    assert '"verify:v1-release": "scripts/verify-v1-release.sh"' in package
    assert '"lint:portal": "npm --prefix apps/portal run lint"' in package
    assert "npm run lint:portal" in script
    assert "npm run build:portal" in script
    assert "npm run test:runner" in script
    assert "npm run verify:production-compose" in script
    assert "pytest apps/api/tests tests/test_docker_stack_contract.py tests/test_ddd_boundaries.py -q" in script
    assert "PLAYWRIGHT_API_PORT=" in script
    assert "PLAYWRIGHT_PORTAL_PORT=" in script
    assert "NASUS_PORTAL_API_PROXY=" in script
    assert "npm run test:e2e" in script
    assert "SMOKE_API_COMMAND=" in script
    assert "SMOKE_PORTAL_COMMAND=" in script
    assert "npm run test:smoke" in script
    assert "verify-docker-stack.sh" in script
    assert "NASUS_MODEL_PROVIDER_PORT=" in script
    assert "COMPOSE_PROJECT_NAME=" in script
    assert "NASUS_API_PORT=" in script
    assert "V1 release verification passed" in script


def test_direct_development_runtime_uses_durable_agent_components():
    package = (ROOT / "package.json").read_text(encoding="utf-8")
    env_script = (ROOT / "scripts/dev-runtime-env.sh").read_text(encoding="utf-8")
    up_script = (ROOT / "scripts/dev-up.sh").read_text(encoding="utf-8")
    down_script = (ROOT / "scripts/dev-down.sh").read_text(encoding="utf-8")

    assert '"dev:up": "scripts/dev-up.sh"' in package
    assert '"dev:foreground": "NASUS_DEV_FOREGROUND=true scripts/dev-up.sh"' in package
    assert "\"dev:api\": \"bash -lc 'source scripts/dev-runtime-env.sh" in package
    assert '"dev:down": "scripts/dev-down.sh"' in package
    assert '"dev:status": "scripts/dev-status.sh"' in package
    assert "NASUS_AGENT_WORKFLOW_RUNTIME" in env_script
    assert "NASUS_DEV_AGENT_WORKFLOW_RUNTIME:-temporal" in env_script
    assert "NASUS_DEV_AGENT_GRAPH_RUNTIME:-langgraph" in env_script
    assert "NASUS_DEV_LANGGRAPH_CHECKPOINT_BACKEND:-postgres" in env_script
    assert "NASUS_SETTINGS_ENCRYPTION_SECRET" in env_script
    assert "BASH_VERSION" in env_script
    assert "ZSH_VERSION" in env_script
    assert "${(%):-%N}" in env_script
    assert "docker compose --profile app --profile temporal up -d" in up_script
    assert "alembic" in up_script
    assert "apps.api.app.infrastructure.workflow.agent_goal_workflow_worker" in up_script
    assert "DescribeNamespaceRequest" in up_script
    assert "npm --prefix apps/runner start" in up_script
    assert "Supervising host application processes" in up_script
    assert 'FOREGROUND="${NASUS_DEV_FOREGROUND:-false}"' in up_script
    assert "/readyz" in up_script
    assert 'if [[ "${1:-}" == "--infra" ]]' in down_script


def test_model_protocol_fixture_covers_chat_embedding_and_rerank():
    fixture = (
        ROOT / "tests/fixtures/model-provider/openai_compatible_server.py"
    ).read_text(encoding="utf-8")

    assert "/v1/chat/completions" in fixture
    assert "/v1/embeddings" in fixture
    assert "/v1/rerank" in fixture
    assert "Authorization" in fixture
    assert "fallback_generation_output" in fixture
    assert "/__stats" in fixture


def test_production_compose_verifier_declares_app_and_temporal_profiles():
    package = (ROOT / "package.json").read_text(encoding="utf-8")
    script = (ROOT / "scripts/verify-production-compose.sh").read_text(encoding="utf-8")

    assert '"verify:production-compose": "scripts/verify-production-compose.sh"' in package
    assert "--profile app" in script
    assert "--profile temporal" in script
    assert "compose config" in script
    assert "api-migrate runner api portal temporal workflow-service temporal-ui" in script
    assert "workflow-service did not inherit required API runtime keys" in script
    assert "api durable Agent runtime is invalid" not in script
    assert '("api", api_environment)' in script
    assert '("workflow-service", workflow_environment)' in script
    assert '"NASUS_AGENT_WORKFLOW_RUNTIME": "temporal"' in script
    assert '"NASUS_AGENT_GRAPH_RUNTIME": "langgraph"' in script
    assert '"NASUS_LANGGRAPH_CHECKPOINT_BACKEND": "postgres"' in script
    assert '"NASUS_SETTINGS_ENCRYPTION_SECRET"' in script
    assert '"NASUS_RATE_LIMIT_ENABLED"' in script
    assert '"NASUS_RATE_LIMIT_BACKEND"' in script
    assert "differs from api" in script
    assert "NASUS_VERIFY_PRODUCTION_COMPOSE_BUILD" in script


def test_release_gate_exercises_version_aware_backup_and_restore():
    package = (ROOT / "package.json").read_text(encoding="utf-8")
    release_gate = (ROOT / "scripts/verify-v1-release.sh").read_text(encoding="utf-8")
    backup = (ROOT / "scripts/backup-data.sh").read_text(encoding="utf-8")
    restore = (ROOT / "scripts/restore-data.sh").read_text(encoding="utf-8")
    manifest = (ROOT / "scripts/backup-manifest.py").read_text(encoding="utf-8")
    object_snapshot = (ROOT / "scripts/object-storage-snapshot.py").read_text(
        encoding="utf-8"
    )

    assert '"backup:data": "scripts/backup-data.sh"' in package
    assert '"restore:data": "scripts/restore-data.sh"' in package
    assert '"verify:backup-restore": "scripts/verify-backup-restore.sh"' in package
    assert "npm run verify:backup-restore" in release_gate
    assert "pg_dump" in backup
    assert ".partial" in backup
    assert "NASUS_BACKUP_MANIFEST_HMAC_KEY" in manifest
    assert "pg_restore" in restore
    assert "NASUS_RESTORE_CONFIRM" in restore
    assert "NASUS_RESTORE_CLEAR_OBJECT_STORAGE" in restore
    assert '"DeleteMarkers"' in object_snapshot
    assert "list_object_versions" in object_snapshot
    assert "verify_live(snapshot_dir)" in object_snapshot


def test_api_declares_s3_object_storage_adapter():
    requirements = (ROOT / "apps/api/requirements.txt").read_text(encoding="utf-8")
    compatibility_adapter = (ROOT / "apps/api/app/object_storage.py").read_text(encoding="utf-8")
    adapter = (ROOT / "apps/api/app/infrastructure/storage/object_storage.py").read_text(encoding="utf-8")
    compatibility_orchestrator = (ROOT / "apps/api/app/run_orchestrator.py").read_text(encoding="utf-8")
    orchestrator = (
        ROOT / "apps/api/app/infrastructure/runner/run_orchestrator.py"
    ).read_text(encoding="utf-8")
    runner_port = (
        ROOT / "apps/api/app/application/quality_loop/runner_port.py"
    ).read_text(encoding="utf-8")
    composition = (ROOT / "apps/api/app/store.py").read_text(encoding="utf-8")

    assert "boto3" in requirements
    assert "NASUS_S3_ENDPOINT" in adapter
    assert "s3://" in adapter
    assert "local-object://" in adapter
    assert "from .infrastructure.storage.object_storage import *" in compatibility_adapter
    assert "from .infrastructure.runner.run_orchestrator import *" in compatibility_orchestrator
    assert "class EvidenceObjectStoragePort" in runner_port
    assert "self.evidence_storage.put_bytes" in orchestrator
    assert "self.object_storage," in composition
    assert "content_type=artifact.media_type" in orchestrator


def test_api_runtime_profile_fails_fast_before_store_import():
    main = (ROOT / "apps/api/app/main.py").read_text(encoding="utf-8")
    composition = (ROOT / "apps/api/app/composition.py").read_text(encoding="utf-8")
    compatibility_runtime_config = (ROOT / "apps/api/app/runtime_config.py").read_text(encoding="utf-8")
    runtime_config = (
        ROOT / "apps/api/app/infrastructure/config/runtime_config.py"
    ).read_text(encoding="utf-8")
    store = (ROOT / "apps/api/app/store.py").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    entrypoint_source = main + "\n" + composition
    assert "validate_runtime_configuration()" in entrypoint_source
    assert composition.index("validate_runtime_configuration()") < composition.index("from .bootstrap import get_application_container")
    assert "from .store import store" not in composition
    assert "from .infrastructure.config.runtime_config import *" in compatibility_runtime_config
    assert "PRODUCTION_PROFILES" in runtime_config
    assert "NASUS_DATABASE_URL must use PostgreSQL" in runtime_config
    assert "NASUS_AUTH_MODE must be required" in runtime_config
    assert "NASUS_SETTINGS_ENCRYPTION_SECRET must contain at least 32" in runtime_config
    assert "NASUS_AGENT_WORKFLOW_RUNTIME must be temporal" in runtime_config
    assert "NASUS_RUNNER_MODE must be http" in runtime_config
    assert "NASUS_RUNNER_ALLOWED_HOSTS" in runtime_config
    assert "NASUS_GIT_ALLOWED_HOSTS" in runtime_config
    assert "NASUS_CODE_GRAPH_BINARY must resolve to an executable" in runtime_config
    assert "NASUS_CODE_GRAPH_MODE must be required in staging/production" in runtime_config
    assert "NASUS_SEED_DEMO_DATA must be false" in runtime_config
    assert "if demo_seed_enabled():" in store
    assert "NASUS_ENV=local" in env_example
    assert "NASUS_SEED_DEMO_DATA=false" in env_example
    assert "NASUS_SETTINGS_ENCRYPTION_SECRET=" in env_example
    assert "NASUS_AGENT_WORKFLOW_RUNTIME=local" in env_example
    assert "NASUS_TEMPORAL_AGENT_GOAL_WORKFLOW=NasusAgentGoalWorkflow" in env_example
    assert "NASUS_RUNNER_MODE=http" in env_example
    assert "NASUS_RUNNER_ENDPOINT=http://127.0.0.1:8090" in env_example
    assert "NASUS_GIT_ALLOWED_HOSTS=github.com,gitlab.com,bitbucket.org" in env_example
    assert "NASUS_CODE_GRAPH_MODE=optional" in env_example
    assert "NASUS_CODE_GRAPH_INDEX_MODE=moderate" in env_example


def test_readiness_endpoint_uses_application_ports_and_infrastructure_probes():
    composition = (ROOT / "apps/api/app/composition.py").read_text(encoding="utf-8")
    container = (ROOT / "apps/api/app/bootstrap/container.py").read_text(encoding="utf-8")
    router = (ROOT / "apps/api/app/interface/http/routers/health.py").read_text(encoding="utf-8")
    application = (ROOT / "apps/api/app/application/platform/readiness.py").read_text(encoding="utf-8")
    database_probe = (ROOT / "apps/api/app/infrastructure/persistence/readiness.py").read_text(encoding="utf-8")
    storage_probe = (ROOT / "apps/api/app/infrastructure/storage/readiness.py").read_text(encoding="utf-8")
    git_probe = (ROOT / "apps/api/app/infrastructure/system_image/readiness.py").read_text(encoding="utf-8")
    runner_probe = (ROOT / "apps/api/app/infrastructure/runner/readiness.py").read_text(encoding="utf-8")

    assert '@router.get("/readyz")' in router
    assert "readiness.check()" in router
    assert "ReadinessApp" in router
    assert "sqlalchemy" not in router
    assert "boto3" not in router
    assert "class ReadinessProbe(Protocol)" in application
    assert "sqlalchemy" not in application
    assert "boto3" not in application
    assert "class DatabaseReadinessProbe" in database_probe
    assert 'connection.execute(text("SELECT 1"))' in database_probe
    assert "class ObjectStorageReadinessProbe" in storage_probe
    assert "head_bucket" in storage_probe
    assert "class GitSourceConnectorReadinessProbe" in git_probe
    assert 'git_binary, "--version"' in git_probe
    assert "class AutomationRunnerReadinessProbe" in runner_probe
    assert 'f"{self._endpoint}/readyz"' in runner_probe
    assert "container.readiness" in composition
    assert "ReadinessApplicationService" in container
    assert "DatabaseReadinessProbe(engine)" in container
    assert "ObjectStorageReadinessProbe(ObjectStorage())" in container
    assert "GitSourceConnectorReadinessProbe()" in container
    assert "AutomationRunnerReadinessProbe()" in container


def test_portal_dev_proxy_is_configurable_for_isolated_e2e_ports():
    vite_config = (ROOT / "apps/portal/vite.config.ts").read_text(encoding="utf-8")

    assert "NASUS_PORTAL_API_PROXY" in vite_config
    assert "apiProxyTarget" in vite_config
    assert "'/v1': apiProxyTarget" in vite_config
    assert "'/healthz': apiProxyTarget" in vite_config


def test_alembic_revision_ids_fit_default_version_column():
    migration_files = sorted((ROOT / "apps/api/migrations/versions").glob("*.py"))

    assert migration_files
    for migration in migration_files:
        content = migration.read_text(encoding="utf-8")
        match = re.search(r'^revision\s*=\s*["\']([^"\']+)["\']', content, flags=re.MULTILINE)
        assert match, f"{migration.name} must declare a revision id"
        revision = match.group(1)
        assert len(revision) <= 32, f"{migration.name} revision id exceeds Alembic default version_num length"
