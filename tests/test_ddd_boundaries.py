from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_backend_ddd_skeleton_and_http_boundary_are_present() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    required_paths = [
        app_root / "interface" / "http" / "routers",
        app_root / "interface" / "http" / "auth.py",
        app_root / "interface" / "sse",
        app_root / "application" / "system_image",
        app_root / "application" / "system_image" / "context_extraction.py",
        app_root / "application" / "system_image" / "embedding_records.py",
        app_root / "application" / "system_image" / "lifecycle.py",
        app_root / "application" / "system_image" / "memory_context.py",
        app_root / "application" / "system_image" / "persistence.py",
        app_root / "application" / "system_image" / "ports.py",
        app_root / "application" / "system_image" / "quality_contexts.py",
        app_root / "application" / "system_image" / "raw_asset_chunks.py",
        app_root / "application" / "system_image" / "retrieval.py",
        app_root / "application" / "system_image" / "retrieval_traces.py",
        app_root / "application" / "system_image" / "service.py",
        app_root / "application" / "system_image" / "snapshots.py",
        app_root / "application" / "system_image" / "source_bindings.py",
        app_root / "application" / "system_image" / "source_ingestion.py",
        app_root / "application" / "system_image" / "system_image_models.py",
        app_root / "application" / "system_image" / "us_work_items.py",
        app_root / "application" / "system_image" / "use_cases.py",
        app_root / "domain" / "system_image" / "build_state.py",
        app_root / "domain" / "system_image" / "chunking.py",
        app_root / "domain" / "system_image" / "materialization.py",
        app_root / "domain" / "system_image" / "quality_context.py",
        app_root / "domain" / "system_image" / "source_binding.py",
        app_root / "domain" / "system_image" / "us_work_items.py",
        app_root / "application" / "agent",
        app_root / "application" / "agent" / "agent_models.py",
        app_root / "application" / "agent" / "graph.py",
        app_root / "application" / "agent" / "explanations.py",
        app_root / "application" / "agent" / "goal_projection.py",
        app_root / "application" / "agent" / "loop.py",
        app_root / "application" / "agent" / "use_cases.py",
        app_root / "application" / "agent" / "workflow.py",
        app_root / "application" / "agent" / "conversation_fallbacks.py",
        app_root / "application" / "agent" / "messages.py",
        app_root / "application" / "agent" / "memory.py",
        app_root / "application" / "agent" / "orchestrator.py",
        app_root / "application" / "agent" / "planner.py",
        app_root / "application" / "agent" / "plans.py",
        app_root / "application" / "agent" / "replanning.py",
        app_root / "application" / "agent" / "reply_ports.py",
        app_root / "application" / "agent" / "replies.py",
        app_root / "application" / "agent" / "swarm.py",
        app_root / "application" / "quality_loop",
        app_root / "application" / "quality_loop" / "context_queries.py",
        app_root / "application" / "quality_loop" / "quality_models.py",
        app_root / "application" / "quality_loop" / "quality_steps.py",
        app_root / "application" / "quality_loop" / "release_decision_queries.py",
        app_root / "application" / "quality_loop" / "results.py",
        app_root / "application" / "quality_loop" / "project_versions.py",
        app_root / "application" / "quality_loop" / "run_execution.py",
        app_root / "application" / "quality_loop" / "version_context.py",
        app_root / "application" / "quality_loop" / "use_cases.py",
        app_root / "application" / "platform" / "use_cases.py",
        app_root / "application" / "platform" / "account_ports.py",
        app_root / "application" / "platform" / "account_models.py",
        app_root / "application" / "platform" / "accounts.py",
        app_root / "application" / "platform" / "approval_ports.py",
        app_root / "application" / "platform" / "audit_events.py",
        app_root / "application" / "platform" / "auth_service.py",
        app_root / "application" / "platform" / "demo_seed.py",
        app_root / "application" / "platform" / "demo_seed_ports.py",
        app_root / "application" / "platform" / "events.py",
        app_root / "application" / "platform" / "event_streams.py",
        app_root / "application" / "platform" / "errors.py",
        app_root / "application" / "platform" / "project_workspace.py",
        app_root / "application" / "platform" / "scope_resolution.py",
        app_root / "application" / "platform" / "project_models.py",
        app_root / "application" / "platform" / "governance.py",
        app_root / "application" / "platform" / "model_configurations.py",
        app_root / "application" / "platform" / "model_configuration_ports.py",
        app_root / "application" / "platform" / "model_config_test_grants.py",
        app_root / "application" / "platform" / "model_settings.py",
        app_root / "application" / "platform" / "query_tools.py",
        app_root / "application" / "platform" / "read_query_ports.py",
        app_root / "application" / "platform" / "read_models.py",
        app_root / "application" / "platform" / "runtime.py",
        app_root / "application" / "platform" / "state_hydration_ports.py",
        app_root / "application" / "platform" / "tool_catalog.py",
        app_root / "application" / "platform" / "tool_models.py",
        app_root / "application" / "platform" / "tool_invocations.py",
        app_root / "application" / "platform" / "tool_projection.py",
        app_root / "application" / "platform" / "tool_handlers",
        app_root / "application" / "platform" / "tool_handlers" / "registry.py",
        app_root / "application" / "platform" / "tool_handlers" / "system_image.py",
        app_root / "application" / "platform" / "tool_handlers" / "project_version.py",
        app_root / "application" / "platform" / "tool_handlers" / "quality_loop.py",
        app_root / "application" / "platform" / "tool_handlers" / "governance.py",
        app_root / "application" / "platform" / "tool_handlers" / "query.py",
        app_root / "domain" / "README.md",
        app_root / "domain" / "system_image",
        app_root / "domain" / "agent",
        app_root / "domain" / "agent" / "memory.py",
        app_root / "domain" / "agent" / "name_extraction.py",
        app_root / "domain" / "agent" / "runtime_models.py",
        app_root / "domain" / "agent" / "state_machine.py",
        app_root / "domain" / "quality_loop",
        app_root / "domain" / "quality_loop" / "failure_analysis.py",
        app_root / "domain" / "quality_loop" / "failure_loop_progress.py",
        app_root / "domain" / "quality_loop" / "quality_assets.py",
        app_root / "domain" / "quality_loop" / "quality_step_plan.py",
        app_root / "domain" / "quality_loop" / "release_decision.py",
        app_root / "domain" / "quality_loop" / "release_readiness.py",
        app_root / "domain" / "quality_loop" / "step_guidance.py",
        app_root / "domain" / "quality_loop" / "us_task_start.py",
        app_root / "domain" / "quality_loop" / "version_participants.py",
        app_root / "domain" / "quality_loop" / "version_risk.py",
        app_root / "domain" / "quality_loop" / "version_us_import.py",
        app_root / "domain" / "platform",
        app_root / "domain" / "platform" / "rbac.py",
        app_root / "domain" / "platform" / "tool_governance.py",
        app_root / "infrastructure" / "config",
        app_root / "infrastructure" / "config" / "agent_runtime_config.py",
        app_root / "infrastructure" / "config" / "runtime_config.py",
        app_root / "infrastructure" / "persistence",
        app_root / "infrastructure" / "persistence" / "model_config_test_grant_repository.py",
        app_root / "infrastructure" / "persistence" / "conversation_repository.py",
        app_root / "infrastructure" / "persistence" / "database.py",
        app_root / "infrastructure" / "persistence" / "db_models.py",
        app_root / "infrastructure" / "persistence" / "project_repository.py",
        app_root / "infrastructure" / "persistence" / "quality_loop_repository.py",
        app_root / "infrastructure" / "persistence" / "repositories.py",
        app_root / "infrastructure" / "persistence" / "settings_store.py",
        app_root / "infrastructure" / "persistence" / "system_image_repository.py",
        app_root / "infrastructure" / "llm",
        app_root / "infrastructure" / "llm" / "gateway.py",
        app_root / "infrastructure" / "system_image",
        app_root / "infrastructure" / "system_image" / "application_ports.py",
        app_root / "infrastructure" / "system_image" / "source_ingestion.py",
        app_root / "infrastructure" / "storage",
        app_root / "infrastructure" / "storage" / "object_storage.py",
        app_root / "infrastructure" / "workflow",
        app_root / "infrastructure" / "workflow" / "agent_graph_factory.py",
        app_root / "infrastructure" / "workflow" / "agent_workflow_factory.py",
        app_root / "infrastructure" / "workflow" / "agent_goal_workflow_worker.py",
        app_root / "infrastructure" / "workflow" / "temporal_agent_gateway.py",
        app_root / "infrastructure" / "workflow" / "langgraph_agent_gateway.py",
        app_root / "infrastructure" / "runner",
        app_root / "infrastructure" / "platform" / "query_read_model.py",
        app_root / "infrastructure" / "platform" / "model_configuration_state.py",
        app_root / "infrastructure" / "platform" / "demo_seed_workspace.py",
        app_root / "infrastructure" / "platform" / "account_identity.py",
        app_root / "infrastructure" / "runner" / "run_orchestrator.py",
        app_root / "composition.py",
        app_root / "DDD_BOUNDARIES.md",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required_paths if not path.exists()]
    assert missing == []


def test_backend_import_boundaries_follow_ddd_layers() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    layer_roots = {"domain", "application", "infrastructure", "interface"}
    violations: list[str] = []

    def target_layer_for_import(source_path: Path, level: int, module: str) -> str | None:
        relative = source_path.relative_to(app_root)
        if level == 0:
            if module.startswith("apps.api.app."):
                return module.removeprefix("apps.api.app.").split(".", 1)[0]
            return None

        base_parts = list(relative.parent.parts)
        up_count = level - 1
        if up_count > len(base_parts):
            return None
        target_parts = base_parts[: len(base_parts) - up_count]
        if module:
            target_parts.extend(module.split("."))
        return target_parts[0] if target_parts else None

    for source_path in app_root.rglob("*.py"):
        relative = source_path.relative_to(app_root)
        if not relative.parts or relative.parts[0] not in layer_roots:
            continue
        source_layer = relative.parts[0]
        tree = ast.parse(source_path.read_text())
        for node in ast.walk(tree):
            import_specs: list[tuple[int, str, int]] = []
            if isinstance(node, ast.ImportFrom):
                import_specs.append((node.level, node.module or "", node.lineno))
            elif isinstance(node, ast.Import):
                import_specs.extend((0, alias.name, node.lineno) for alias in node.names)

            for level, module, lineno in import_specs:
                target_layer = target_layer_for_import(source_path, level, module)
                if source_layer == "domain" and target_layer in {"application", "infrastructure", "interface"}:
                    violations.append(f"{source_path.relative_to(ROOT)}:{lineno} domain imports {target_layer}")
                if source_layer == "application" and target_layer == "interface":
                    violations.append(f"{source_path.relative_to(ROOT)}:{lineno} application imports interface")
                if source_layer == "interface" and target_layer == "infrastructure":
                    violations.append(f"{source_path.relative_to(ROOT)}:{lineno} interface imports infrastructure directly")

    assert violations == []


def test_system_image_application_depends_on_ports_not_compatibility_store() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    store_source = (app_root / "store.py").read_text()
    application_root = app_root / "application" / "system_image"
    adapter_source = (
        app_root / "infrastructure" / "system_image" / "application_ports.py"
    ).read_text()
    dependencies_source = (
        app_root
        / "infrastructure"
        / "system_image"
        / "workspace_dependencies.py"
    ).read_text()

    forbidden_fragments = [
        "ApplicationStore",
        "from ...store",
        "from ..store",
        "self._store",
        "self.store",
        "project_repository",
        "system_image_repository",
        "ModelConfigurationApplicationService",
        "ProjectReadModelRefreshApplicationService",
    ]
    violations: list[str] = []
    for source_path in application_root.rglob("*.py"):
        source = source_path.read_text()
        for fragment in forbidden_fragments:
            if fragment in source:
                violations.append(
                    f"{source_path.relative_to(ROOT)} contains {fragment}"
                )

    assert violations == []
    assert "class SystemImageWorkspacePort(Protocol)" in (
        application_root / "ports.py"
    ).read_text()
    assert "class LegacySystemImageWorkspace" in adapter_source
    durable_adapter_source = (
        app_root
        / "infrastructure"
        / "system_image"
        / "sqlalchemy_workspace.py"
    ).read_text()
    assert "class SQLAlchemySystemImageWorkspace" in durable_adapter_source
    assert "SystemImageProjectionState" not in durable_adapter_source
    for forbidden_adapter_dependency in [
        "ApplicationStore",
        "from ...store",
        "self._store",
        "ModelConfigurationApplicationService",
    ]:
        assert forbidden_adapter_dependency not in adapter_source
        assert forbidden_adapter_dependency not in dependencies_source
    assert "class SystemImageProjectionState" in dependencies_source
    assert "class SystemImageWorkspaceAdapters" in dependencies_source
    assert "self.system_image_projection_state = SystemImageProjectionState(" not in store_source
    assert "self.system_image_workspace_adapters = DurableSystemImageWorkspaceAdapters(" in store_source
    assert "self.system_image_workspace = SQLAlchemySystemImageWorkspace(" in store_source
    assert "self.system_image_workspace = LegacySystemImageWorkspace(" not in store_source
    assert "self.system_image_workspace_adapters," in store_source
    assert "require_live_model_routes=current_runtime_profile().production_like" in store_source
    assert "self.system_image_service = SystemImageService(" in store_source
    assert "self.system_image_app = SystemImageApplicationService(" in store_source


def test_system_image_production_model_routes_are_fail_closed_and_atomic() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    workspace_source = (
        app_root / "infrastructure" / "system_image" / "application_ports.py"
    ).read_text()
    policy_source = (
        app_root / "infrastructure" / "system_image" / "model_route_policy.py"
    ).read_text()
    service_source = (
        app_root / "application" / "system_image" / "service.py"
    ).read_text()
    snapshot_source = (
        app_root
        / "application"
        / "system_image"
        / "materialization_snapshot.py"
    ).read_text()

    assert "class SystemImageModelRouteUnavailableError" in policy_source
    assert 'require_live_system_image_result("embedding", result)' in workspace_source
    assert 'require_live_system_image_result("rerank", result)' in workspace_source
    assert "class SystemImageMaterializationSnapshot" in snapshot_source
    assert "snapshot = self._capture_materialization_snapshot(" in service_source
    assert "self._restore_materialization_snapshot(project_id, snapshot)" in service_source


def test_agent_conversation_application_depends_on_ports_not_compatibility_store() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    agent_root = app_root / "application" / "agent"
    ports_source = (agent_root / "ports.py").read_text()
    adapter_source = (
        app_root / "infrastructure" / "agent" / "application_ports.py"
    ).read_text()
    sqlalchemy_adapter_source = (
        app_root
        / "infrastructure"
        / "agent"
        / "sqlalchemy_application_ports.py"
    ).read_text()
    dependency_source = (
        app_root
        / "infrastructure"
        / "agent"
        / "application_port_dependencies.py"
    ).read_text()
    store_source = (app_root / "store.py").read_text()

    migrated_sources = [
        agent_root / "conversations.py",
        agent_root / "messages.py",
        agent_root / "goal_projection.py",
        agent_root / "lifecycle.py",
        agent_root / "graph.py",
        agent_root / "loop.py",
    ]
    forbidden_fragments = [
        "ApplicationStore",
        "from ...store",
        "from ..store",
        "self._store",
        "self.store",
        "conversation_repository",
        "ProjectScopeResolutionApplicationService",
        "PlatformEventApplicationService",
        "infrastructure.workflow",
    ]
    violations: list[str] = []
    for source_path in migrated_sources:
        source = source_path.read_text()
        for fragment in forbidden_fragments:
            if fragment in source:
                violations.append(
                    f"{source_path.relative_to(ROOT)} contains {fragment}"
                )

    assert violations == []
    for protocol_name in [
        "ConversationManagementStatePort",
        "ConversationMessageRuntimePort",
        "AgentGraphStatePort",
        "AgentGoalLifecycleStatePort",
        "AgentLoopStatePort",
        "AgentGoalProjectionStatePort",
        "AgentWorkflowStatePort",
    ]:
        assert f"class {protocol_name}(Protocol)" in ports_source
    for adapter_name in [
        "LegacyConversationManagementStateAdapter",
        "LegacyConversationMessageRuntimeAdapter",
        "LegacyAgentGraphStateAdapter",
        "LegacyAgentGoalLifecycleStateAdapter",
        "LegacyAgentLoopStateAdapter",
        "LegacyAgentGoalProjectionStateAdapter",
        "LegacyAgentWorkflowStateAdapter",
    ]:
        assert f"class {adapter_name}" in adapter_source
    for dependency_name in [
        "AgentApplicationProjectionState",
        "AgentApplicationPersistenceAdapters",
        "AgentApplicationRuntimeAdapters",
    ]:
        assert f"class {dependency_name}" in dependency_source
    assert "AgentApplicationRuntimeAdapters(" in store_source
    assert "AgentApplicationProjectionState(" not in store_source
    assert "AgentApplicationPersistenceAdapters(" not in store_source
    for forbidden_fragment in [
        "ApplicationStore",
        "self._store",
        "store.",
    ]:
        assert forbidden_fragment not in dependency_source
    assert "self.agent_application_ports = SQLAlchemyAgentApplicationPorts(" in store_source
    assert "LegacyAgentApplicationPorts(" not in store_source
    assert "class SQLAlchemyAgentApplicationPorts" in sqlalchemy_adapter_source
    assert "class SQLAlchemyConversationManagementState" in sqlalchemy_adapter_source
    assert "class SQLAlchemyAgentGoalLifecycleState" in sqlalchemy_adapter_source
    assert "class SQLAlchemyAgentMemoryState" in sqlalchemy_adapter_source
    assert "self.agent_application_ports.conversation_management" in store_source
    assert "self.agent_application_ports.conversation_runtime" in store_source
    assert "self.agent_application_ports.goal_projection" in store_source
    assert "self.agent_application_ports.graph_state" in store_source
    assert "self.agent_application_ports.loop_state" in store_source
    assert "self.agent_application_ports.workflow_state" in store_source


def test_backend_domain_layer_is_pure_and_adapter_free() -> None:
    domain_root = ROOT / "apps" / "api" / "app" / "domain"
    forbidden_imports = [
        "fastapi",
        "sqlalchemy",
        "pydantic",
        "boto3",
        "minio",
        "temporalio",
        "langgraph",
        "httpx",
        "requests",
    ]
    forbidden_fragments = [
        "ApplicationStore",
        "project_repository",
        "repositories",
        "db_models",
        "from ..models",
        "from ...models",
        "from apps.api.app.models",
        "runtime_config",
        "object_storage",
        "run_orchestrator",
        "tool_invocation_runtime",
        "os.environ",
        "getenv(",
    ]

    for path in domain_root.rglob("*.py"):
        source = path.read_text()
        import_lines = [
            line.strip()
            for line in source.splitlines()
            if line.startswith("import ") or line.startswith("from ")
        ]
        for line in import_lines:
            for forbidden in forbidden_imports:
                assert forbidden not in line, f"{path.relative_to(ROOT)} imports adapter dependency via {line}"
        for forbidden in forbidden_fragments:
            assert forbidden not in source, f"{path.relative_to(ROOT)} contains forbidden domain dependency {forbidden}"


def test_agent_graph_replanning_uses_application_port_not_llm_adapter() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    graph_source = (app_root / "application" / "agent" / "graph.py").read_text()
    replanning_source = (app_root / "application" / "agent" / "replanning.py").read_text()

    assert "from .replanning import" in graph_source
    assert "AgentReplanner" in graph_source
    assert "infrastructure.llm" not in graph_source
    assert "LLMGateway" not in graph_source
    assert "class AgentReplanner(Protocol)" in replanning_source


def test_root_models_is_compatibility_reexport_only() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    models_source = (app_root / "models.py").read_text()
    platform_read_models_source = (app_root / "application" / "platform" / "read_models.py").read_text()
    platform_init_source = (app_root / "application" / "platform" / "__init__.py").read_text()
    store_source = (app_root / "store.py").read_text()

    assert not re.search(r"^class\s+\w+", models_source, flags=re.MULTILINE)
    assert "pydantic" not in models_source
    assert "from .application.platform.read_models import (" in models_source
    for fragment in [
        "class DocumentationEntry",
        "class DashboardResponse",
        "class BuildResponse",
        "class WelcomeResponse",
        "class ProjectWorkspaceResponse",
    ]:
        assert fragment in platform_read_models_source
        assert fragment not in models_source

    for exported_name in [
        "DocumentationEntry",
        "DashboardResponse",
        "BuildResponse",
        "WelcomeResponse",
        "ProjectWorkspaceResponse",
    ]:
        assert exported_name in models_source
        assert exported_name in platform_init_source

    assert "from .application.platform.read_models import (" in store_source
    assert "from .models import" not in store_source

    for path in app_root.rglob("*.py"):
        if path.name == "models.py" or "__pycache__" in path.parts:
            continue
        source = path.read_text()
        assert not re.search(r"from\s+\.+models\s+import", source), str(path.relative_to(ROOT))


def test_top_level_content_read_models_live_in_platform_application_service() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    store_source = (app_root / "store.py").read_text()
    platform_use_cases_source = (app_root / "application" / "platform" / "use_cases.py").read_text()
    platform_init_source = (app_root / "application" / "platform" / "__init__.py").read_text()
    top_level_source = (
        app_root / "application" / "platform" / "top_level_content.py"
    ).read_text()

    assert "class TopLevelContentApplicationService" in top_level_source
    assert "def get_welcome" in top_level_source
    assert "def get_build" in top_level_source
    assert "def get_dashboard" in top_level_source
    assert "def list_documentation" in top_level_source
    for response_fragment in [
        "WelcomeResponse(",
        "BuildResponse(",
        "DashboardResponse(",
    ]:
        assert response_fragment in top_level_source

    assert "from .top_level_content import TopLevelContentApplicationService" in platform_use_cases_source
    assert "self._top_level_content = top_level_content" in platform_use_cases_source
    assert "return self._top_level_content.get_welcome()" in platform_use_cases_source
    assert "return self._top_level_content.get_build()" in platform_use_cases_source
    assert "return self._top_level_content.get_dashboard()" in platform_use_cases_source
    assert "return self._top_level_content.list_documentation()" in platform_use_cases_source
    assert "TopLevelContentApplicationService" in platform_init_source

    for method_name, next_method in [
        ("get_welcome", "get_build"),
        ("get_build", "get_dashboard"),
        ("get_dashboard", "get_settings"),
        ("list_documentation", "create_project"),
    ]:
        method_block = store_source.split(f"def {method_name}", 1)[1].split(f"\n    def {next_method}", 1)[0]
        assert "self.top_level_content." in method_block
        for forbidden_fragment in [
            "WelcomeResponse(",
            "BuildResponse(",
            "DashboardResponse(",
            "recent_conversations",
            "imports_health",
            "failed_runs=sum",
        ]:
            assert forbidden_fragment not in method_block
    assert "self.top_level_content = TopLevelContentApplicationService(" in store_source
    assert "SQLAlchemyTopLevelContentReadModel(" in store_source
    assert "projects=self.project_repository" in store_source
    assert "quality_loop=self.quality_loop_repository" in store_source
    assert "conversations=self.conversation_repository" in store_source
    assert "ApplicationStore" not in top_level_source
    assert "self._store" not in top_level_source


def test_agent_runtime_value_objects_live_in_domain_layer() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    root_runtime_models = (app_root / "agent_runtime_models.py").read_text()
    domain_runtime_models = (app_root / "domain" / "agent" / "runtime_models.py").read_text()
    domain_agent_init = (app_root / "domain" / "agent" / "__init__.py").read_text()

    assert "from .domain.agent.runtime_models import *" in root_runtime_models
    for compatibility_fragment in ["@dataclass", "class AgentGoalProposal", "class OrchestratorDecision"]:
        assert compatibility_fragment not in root_runtime_models
    for implementation_fragment in [
        "@dataclass",
        "class AgentGoalProposal",
        "class ToolPlanStep",
        "class OrchestratorDecision",
        "agent_goal_proposal_from_payload",
    ]:
        assert implementation_fragment in domain_runtime_models
    for export_fragment in [
        "AgentGoalProposal",
        "ToolPlanStep",
        "OrchestratorDecision",
        "agent_goal_proposal_from_payload",
    ]:
        assert export_fragment in domain_agent_init

    internal_sources = [
        path.read_text()
        for path in app_root.rglob("*.py")
        if path.name != "agent_runtime_models.py" and "tests" not in path.parts
    ]
    assert all(".agent_runtime_models import" not in source for source in internal_sources)


def test_agent_goal_state_machine_lives_in_domain_layer() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    root_state_machine = (app_root / "agent_goal_state_machine.py").read_text()
    domain_state_machine = (app_root / "domain" / "agent" / "state_machine.py").read_text()
    domain_agent_init = (app_root / "domain" / "agent" / "__init__.py").read_text()

    assert "from .domain.agent.state_machine import *" in root_state_machine
    for compatibility_fragment in ["from .models", "class AgentGoalStateMachine", "@dataclass"]:
        assert compatibility_fragment not in root_state_machine
    for implementation_fragment in [
        "class AgentGoalStateMachine",
        "class AgentGoalRuntimeCheckpoint",
        "class AgentGoalLike",
        "class AgentStepLike",
        "def checkpoint",
        "def pause_on_gate",
        "def complete_goal",
    ]:
        assert implementation_fragment in domain_state_machine
    for forbidden_fragment in ["from ..models", "from ...models", "from apps.api.app.models"]:
        assert forbidden_fragment not in domain_state_machine
    for export_fragment in ["AgentGoalStateMachine", "AgentGoalRuntimeCheckpoint", "AgentGoalPhase"]:
        assert export_fragment in domain_agent_init

    internal_sources = [
        path.read_text()
        for path in app_root.rglob("*.py")
        if path.name != "agent_goal_state_machine.py" and "tests" not in path.parts
    ]
    assert all(".agent_goal_state_machine import" not in source for source in internal_sources)


def test_agent_contract_models_live_in_agent_application_layer() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    agent_models_source = (app_root / "application" / "agent" / "agent_models.py").read_text()
    agent_init_source = (app_root / "application" / "agent" / "__init__.py").read_text()
    models_source = (app_root / "models.py").read_text()
    store_source = (app_root / "store.py").read_text()
    repositories_source = (app_root / "infrastructure" / "persistence" / "repositories.py").read_text()
    conversation_repository_source = (
        app_root / "infrastructure" / "persistence" / "conversation_repository.py"
    ).read_text()
    agent_router_source = (app_root / "interface" / "http" / "routers" / "agent.py").read_text()
    conversations_router_source = (app_root / "interface" / "http" / "routers" / "conversations.py").read_text()
    graph_source = (app_root / "application" / "agent" / "graph.py").read_text()
    workflow_source = (app_root / "application" / "agent" / "workflow.py").read_text()
    system_image_retrieval_source = (app_root / "application" / "system_image" / "retrieval.py").read_text()

    for fragment in [
        "SpaceType = Literal[",
        "class AgentStep",
        "class AgentGoal",
        "class AgentMemoryItem",
        "class AgentMemoryLink",
        "class AgentWorkerAssignment",
        "class AgentSwarmRun",
        "class MessageBlock",
        "class ConversationMessage",
        "class ConversationSummaryCheckpoint",
        "class ConversationLink",
        "class SessionKnowledgeBinding",
        "class ConversationSession",
        "class ConversationCreateRequest",
        "class ConversationMessageRequest",
        "class ConversationArchiveRequest",
        "class ConversationMergeRequest",
        "class AgentGoalCreateRequest",
        "class AgentGoalFeedbackRequest",
        "class AgentMemoryCheckpointRequest",
        "class AgentSwarmCreateRequest",
    ]:
        assert fragment in agent_models_source
        assert fragment not in models_source

    for exported_name in [
        "AgentGoal",
        "AgentGoalCreateRequest",
        "AgentMemoryItem",
        "AgentSwarmRun",
        "ConversationMessage",
        "ConversationSession",
        "ConversationSummaryCheckpoint",
        "SpaceType",
    ]:
        assert exported_name in models_source
        assert exported_name in agent_init_source

    assert "from .application.agent.agent_models import (" in models_source
    assert "from .application.agent.agent_models import (" in store_source
    assert "from ...application.agent.agent_models import (" in conversation_repository_source
    assert "from ...application.agent.agent_models import (" not in repositories_source
    assert "from ....application.agent.agent_models import (" in agent_router_source
    assert "from ....application.agent.agent_models import (" in conversations_router_source
    assert "from .agent_models import AgentGoal, AgentStep" in graph_source
    assert "from .agent_models import AgentGoal" in workflow_source
    assert "from ..agent.agent_models import ConversationSession" in system_image_retrieval_source


def test_agent_memory_context_value_object_lives_in_domain_layer() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    root_agent_memory = (app_root / "agent_memory.py").read_text()
    application_memory = (app_root / "application" / "agent" / "memory.py").read_text()
    domain_memory = (app_root / "domain" / "agent" / "memory.py").read_text()
    domain_agent_init = (app_root / "domain" / "agent" / "__init__.py").read_text()
    agent_graph_runtime = (app_root / "application" / "agent" / "graph.py").read_text()
    agent_planner = (app_root / "application" / "agent" / "planner.py").read_text()
    store_source = (app_root / "store.py").read_text()

    assert "from .application.agent.memory import *" in root_agent_memory
    for compatibility_fragment in [
        "class AgentMemoryContext",
        "class AgentMemoryManager",
        "def memory_context_hash",
        "def memory_context_summary",
    ]:
        assert compatibility_fragment not in root_agent_memory
    assert "from ...domain.agent.memory import AgentMemoryContext, memory_context_hash, memory_context_summary" in application_memory
    for implementation_fragment in [
        "class AgentMemoryContext",
        "def memory_context_hash",
        "def memory_context_summary",
        "hashlib.sha256",
        "retrieval_run_refs",
    ]:
        assert implementation_fragment in domain_memory
    for forbidden_fragment in ["ApplicationStore", "from ..models", "from ...models", "from apps.api.app.models"]:
        assert forbidden_fragment not in domain_memory
    for export_fragment in ["AgentMemoryContext", "memory_context_hash", "memory_context_summary"]:
        assert export_fragment in domain_agent_init
    assert "from ...domain.agent.memory import AgentMemoryContext, memory_context_hash, memory_context_summary" in agent_graph_runtime
    assert "from ...domain.agent.memory import AgentMemoryContext" in agent_planner
    assert "from ...domain.agent.memory import AgentMemoryContext, memory_context_hash, memory_context_summary" in application_memory
    assert "from .domain.agent.memory import" not in store_source


def test_agent_tool_catalog_context_is_bounded_in_application_layer() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    tool_context_source = (
        app_root / "application" / "agent" / "tool_context.py"
    ).read_text()
    memory_source = (app_root / "application" / "agent" / "memory.py").read_text()
    domain_memory_source = (app_root / "domain" / "agent" / "memory.py").read_text()

    assert "def compact_tool_catalog_json(" in tool_context_source
    assert '"available_tool_ids"' in tool_context_source
    assert '"relevant_tools"' in tool_context_source
    assert "relevant_limit: int = 12" in tool_context_source
    assert "compact_tool_catalog_json(tools, conversation)" in memory_source
    assert "tool.tool_id" not in memory_source.split(
        'sections.append("[tool_catalog]")', 1
    )[1].split('return "\\n".join(sections)', 1)[0]
    assert 're.fullmatch(r"\\[([a-z0-9_]+)\\]"' in domain_memory_source


def test_agent_name_extraction_policy_lives_in_domain_layer() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    store_source = (app_root / "store.py").read_text()
    name_extraction_source = (app_root / "domain" / "agent" / "name_extraction.py").read_text()
    domain_agent_init = (app_root / "domain" / "agent" / "__init__.py").read_text()
    for fragment in [
        "def extract_project_name",
        "def extract_version_name",
        "New Quality Project",
        "New Version",
        "Version {fallback_index}",
        "Project {fallback_index}",
        "名字叫",
        "版本",
    ]:
        assert fragment in name_extraction_source
    for export_fragment in ["extract_project_name", "extract_version_name"]:
        assert export_fragment in domain_agent_init

    assert "from .domain.agent.name_extraction import extract_project_name, extract_version_name" in store_source
    project_extract_block = store_source.split("def _extract_project_name", 1)[1].split(
        "\n    def _extract_version_name",
        1,
    )[0]
    version_extract_block = store_source.split("def _extract_version_name", 1)[1].split("\nInMemoryStore", 1)[0]
    assert "self.project_repository.list_projects()" in project_extract_block
    assert "self.project_repository.list_versions(project.id)" in version_extract_block
    assert "self.projects" not in project_extract_block
    assert "self.versions" not in version_extract_block
    for leaked_policy in ["re.search", "New Quality Project", "New Version", "名字叫", "版本"]:
        assert leaked_policy not in project_extract_block
        assert leaked_policy not in version_extract_block


def test_agent_memory_manager_lives_in_application_layer() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    root_agent_memory = (app_root / "agent_memory.py").read_text()
    application_memory = (app_root / "application" / "agent" / "memory.py").read_text()
    agent_ports_source = (app_root / "application" / "agent" / "ports.py").read_text()
    agent_adapters_source = (
        app_root / "infrastructure" / "agent" / "application_ports.py"
    ).read_text()
    memory_dependencies_source = (
        app_root
        / "infrastructure"
        / "agent"
        / "memory_state_dependencies.py"
    ).read_text()
    agent_use_cases_source = (app_root / "application" / "agent" / "use_cases.py").read_text()
    store_source = (app_root / "store.py").read_text()

    assert "from .application.agent.memory import *" in root_agent_memory
    assert "class AgentMemoryManager" not in root_agent_memory
    for implementation_fragment in [
        "class AgentMemoryManager",
        "ConversationSummaryCheckpointService",
        "def build_context",
        "def get_context_view",
        "def create_summary_checkpoint",
        "def record_item",
        "def _latest_checkpoint",
        "def _build_summary_checkpoint",
        "def _conversation_for_memory_query",
        "def _working_memory_view",
        "def _project_long_term_memory_view",
        "def _candidate_memory_view",
        "SystemImageMemoryContextApplicationService",
        "self.system_image_memory_context = SystemImageMemoryContextApplicationService(",
        "return self.system_image_memory_context.context_sections(conversation.project_id)",
        "view = self.system_image_memory_context.long_term_project_refs(project_id)",
        "self._state.persist_summary_checkpoint(conversation, checkpoint)",
        "await self._state.publish_memory_checkpointed(conversation, checkpoint)",
        "self._state.get_goal(agent_goal_id)",
    ]:
        assert implementation_fragment in application_memory
    assert "def _persist_system_image" not in application_memory
    for dependency_fragment in [
        "from .agent_models import (",
        "AgentGoal,",
        "AgentMemoryItem,",
        "AgentMemoryLink,",
        "ConversationMessage,",
        "ConversationSession,",
        "ConversationSummaryCheckpoint,",
        "from .conversation_summary import ConversationSummaryCheckpointService",
        "from .ports import AgentMemoryStatePort",
        "from ..system_image.memory_context import SystemImageMemoryContextApplicationService",
        "from ..platform.tool_models import ToolDefinition",
        "from ..system_image.retrieval import SystemImageMemoryHit, SystemImageRetriever",
    ]:
        assert dependency_fragment in application_memory
    for forbidden_dependency in [
        "ApplicationStore",
        "PlatformEventApplicationService",
        "self.store",
        "conversation_repository",
        "agent_memory_items",
        "session_knowledge_bindings",
        "context_object_overlays",
        "self._state.projects",
    ]:
        assert forbidden_dependency not in application_memory
    for port_fragment in [
        "class AgentMemoryStatePort(Protocol)",
        "def available_tools(",
        "def persist_summary_checkpoint(",
        "async def publish_memory_checkpointed(",
        "def persist_memory_item(",
        "def project_snapshot(",
        "def us_snapshot(",
    ]:
        assert port_fragment in agent_ports_source
    for adapter_fragment in [
        "class LegacyAgentMemoryStateAdapter(AgentMemoryStatePort)",
        "self.memory_state = LegacyAgentMemoryStateAdapter(",
        "def persist_memory_item(",
        "def candidate_overlay_refs(",
        "def recent_run_snapshots(",
    ]:
        assert adapter_fragment in agent_adapters_source
    memory_adapter_block = agent_adapters_source.split(
        "class LegacyAgentMemoryStateAdapter",
        1,
    )[1].split("class LegacyAgentSwarmStateAdapter", 1)[0]
    assert "self._store" not in memory_adapter_block
    assert "ApplicationStore" not in memory_adapter_block
    for dependency_fragment in [
        "class AgentMemoryProjectionState",
        "class AgentMemoryPersistenceAdapters",
        "class AgentMemoryRuntimeAdapters",
        "class AgentMemoryEventAdapters",
        "class AgentMemoryCandidateProjectionState",
        "class AgentMemoryWorkspaceProjectionState",
        "class CompatibilityAgentMemoryCandidateQueries",
        "class CompatibilityAgentMemoryWorkspaceQueries",
    ]:
        assert dependency_fragment in memory_dependencies_source
    assert "ApplicationStore" not in memory_dependencies_source
    for composition_fragment in [
        "AgentMemoryProjectionState(",
        "AgentMemoryPersistenceAdapters(",
        "AgentMemoryRuntimeAdapters(",
        "AgentMemoryEventAdapters(",
        "AgentMemoryCandidateProjectionState(",
        "AgentMemoryWorkspaceProjectionState(",
    ]:
        assert composition_fragment in agent_adapters_source
    assert "DefaultSystemImageRetriever" not in application_memory
    assert "infrastructure.system_image" not in application_memory
    assert "self.store._push_event" not in application_memory
    assert "self.store.agent_goals" not in application_memory
    assert "self.store._latest_checkpoint_for_conversation" not in application_memory
    assert "self.store._build_summary_checkpoint" not in application_memory
    assert "self.conversation_summaries.latest_checkpoint(" in application_memory
    assert "self.conversation_summaries.build_checkpoint(" in application_memory
    system_image_context_block = application_memory.split("def _system_image_context", 1)[1].split(
        "\n    def _project_long_term_memory_context",
        1,
    )[0]
    project_long_term_view_block = application_memory.split("def _project_long_term_memory_view", 1)[1].split(
        "\n    def _project_memory_items",
        1,
    )[0]
    for leaked_system_image_read in [
        "self.store.baselines",
        "self.store.raw_assets",
        "self.store.knowledge_objects",
        "self.store.context_relationships",
        "self.store.quality_metric_snapshots",
    ]:
        assert leaked_system_image_read not in system_image_context_block
        assert leaked_system_image_read not in project_long_term_view_block
    assert "await self.system_image_retriever.search_project_memory(" in application_memory
    assert "trace=trace," in application_memory
    for migrated_system_image_trace_helper in [
        "def _retrieval_baseline_id",
        "def _retrieval_strategy",
        "def _ready_embedding_record_ids",
        "def _latest_rerank_record_id",
        "def _retrieval_fallback_used",
    ]:
        assert migrated_system_image_trace_helper not in application_memory
    assert "from .application.agent.memory import AgentMemoryManager" in store_source
    assert "from .memory import AgentMemoryManager" in agent_use_cases_source
    assert "self._memory = memory" in agent_use_cases_source
    assert "self.system_image_retrieval_state = SystemImageRetrievalState(" not in store_source
    assert "self.system_image_memory_retriever = SQLAlchemySystemImageRetriever(" in store_source
    assert "system_images=self.system_image_repository," in store_source
    assert "conversations=self.conversation_repository," in store_source
    assert "retrieval_index=self.system_image_retrieval_index," in store_source
    assert "self.system_image_workspace = SQLAlchemySystemImageWorkspace(" in store_source
    assert "require_live_model_routes=current_runtime_profile().production_like" in store_source
    assert "self.agent_memory = AgentMemoryManager(" in store_source
    assert "self.agent_application_ports.memory_state," in store_source
    assert "self.system_image_workspace," in store_source
    assert "self.conversation_summaries," in store_source
    assert "return await self._memory.get_context_view(" in agent_use_cases_source
    assert "return await self._memory.create_summary_checkpoint(" in agent_use_cases_source
    assert "def list_items(" in application_memory

    for method_name, next_method in [
        ("get_agent_memory_context", "create_agent_memory_checkpoint"),
        ("create_agent_memory_checkpoint", "record_agent_memory_item"),
        ("record_agent_memory_item", "list_agent_memory_items"),
        ("list_agent_memory_items", "get_agent_swarm"),
    ]:
        method_block = store_source.split(f"def {method_name}", 1)[1].split(f"\n    def {next_method}", 1)[0]
        assert "self.agent_memory." in method_block
        for forbidden_fragment in [
            "memory_context_hash(",
            "memory_context_summary(",
            "AgentMemoryItem(",
            "AgentMemoryLink(",
            "event_type=\"agent.memory.checkpointed\"",
            "session_only_refs",
            "candidate_overlay_refs",
            "project_long_term_memory",
        ]:
            assert forbidden_fragment not in method_block

    for migrated_helper in [
        "def _conversation_for_memory_query",
        "def _working_memory_view",
        "def _project_long_term_memory_view",
        "def _project_memory_items",
        "def _candidate_memory_view",
    ]:
        assert migrated_helper not in store_source

    internal_sources = [
        path.read_text()
        for path in app_root.rglob("*.py")
        if path.name != "agent_memory.py" and "tests" not in path.parts
    ]
    assert all(".agent_memory import AgentMemoryManager" not in source for source in internal_sources)


def test_agent_swarm_coordinator_uses_declared_state_port() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    swarm_source = (app_root / "application" / "agent" / "swarm.py").read_text()
    ports_source = (app_root / "application" / "agent" / "ports.py").read_text()
    adapter_source = (
        app_root / "infrastructure" / "agent" / "application_ports.py"
    ).read_text()
    swarm_dependencies_source = (
        app_root
        / "infrastructure"
        / "agent"
        / "swarm_state_dependencies.py"
    ).read_text()
    store_source = (app_root / "store.py").read_text()
    model_source = (
        app_root / "application" / "agent" / "agent_models.py"
    ).read_text()

    for fragment in [
        "class AgentSwarmCoordinator",
        "state: AgentSwarmStatePort",
        "self._state = state",
        "self._state.get_swarm(swarm_id)",
        "self._state.persist_swarm(swarm)",
        'await self._state.publish_swarm_event(swarm, "agent.swarm.updated", event_patch)',
        "await self._state.publish_swarm_event(swarm, event_type, event_patch)",
        '"transition_event_type": event_type',
        "asyncio.wait_for(",
        'swarm.status = "partially_failed" if failed else "completed"',
        'budget_ref=f"agent_goal:{parent_goal_id}:budget"',
    ]:
        assert fragment in swarm_source
    for forbidden in [
        "ApplicationStore",
        "PlatformEventApplicationService",
        "conversation_repository",
        "self.store",
        "self._store",
    ]:
        assert forbidden not in swarm_source
    for fragment in [
        "class AgentSwarmStatePort(Protocol)",
        "def get_swarm(",
        "def persist_swarm(",
        "async def publish_swarm_event(",
    ]:
        assert fragment in ports_source
    for fragment in [
        "class LegacyAgentSwarmStateAdapter(AgentSwarmStatePort)",
        "self.swarm_state = LegacyAgentSwarmStateAdapter(",
        "def persist_swarm(",
        "async def publish_swarm_event(",
    ]:
        assert fragment in adapter_source
    swarm_adapter_block = adapter_source.split(
        "class LegacyAgentSwarmStateAdapter",
        1,
    )[1].split("class LegacyAgentGoalProjectionStateAdapter", 1)[0]
    assert "self._store" not in swarm_adapter_block
    assert "ApplicationStore" not in swarm_adapter_block
    for dependency_fragment in [
        "class AgentSwarmProjectionState",
        "class AgentSwarmPersistenceAdapters",
        "class AgentSwarmEventAdapters",
    ]:
        assert dependency_fragment in swarm_dependencies_source
    assert "ApplicationStore" not in swarm_dependencies_source
    for composition_fragment in [
        "AgentSwarmProjectionState(",
        "AgentSwarmPersistenceAdapters(",
        "AgentSwarmEventAdapters(",
    ]:
        assert composition_fragment in adapter_source
    assert "self.agent_application_ports.swarm_state" in store_source
    assert '"partially_failed",' in model_source
    assert "timeout_seconds: int = Field(default=120" in model_source
    assert "budget_ref: Optional[str] = None" in model_source


def test_system_image_retriever_port_and_adapter_respect_ddd_layers() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    root_retriever = (app_root / "system_image_retriever.py").read_text()
    application_retrieval = (app_root / "application" / "system_image" / "retrieval.py").read_text()
    infrastructure_retrieval = (
        app_root / "infrastructure" / "system_image" / "memory_retriever.py"
    ).read_text()
    durable_retrieval = (
        app_root / "infrastructure" / "system_image" / "sqlalchemy_memory_retriever.py"
    ).read_text()
    store_source = (app_root / "store.py").read_text()
    application_agent_memory = (app_root / "application" / "agent" / "memory.py").read_text()
    application_system_image_init = (app_root / "application" / "system_image" / "__init__.py").read_text()
    infrastructure_system_image_init = (app_root / "infrastructure" / "system_image" / "__init__.py").read_text()

    assert "from .application.system_image.retrieval import *" in root_retriever
    for compatibility_fragment in [
        "class DefaultSystemImageRetriever",
        "class SystemImageRetriever",
        "class SystemImageMemoryHit",
        "@dataclass",
    ]:
        assert compatibility_fragment not in root_retriever
    for implementation_fragment in [
        "class SystemImageMemoryHit",
        "class SystemImageMemorySearchResult",
        "class SystemImageRetriever",
        "async def search_project_memory",
    ]:
        assert implementation_fragment in application_retrieval
    for forbidden_application_fragment in [
        "ApplicationStore",
        "DefaultSystemImageRetriever",
        "knowledge_objects",
        "raw_asset_chunks",
        "agent_memory_items",
    ]:
        assert forbidden_application_fragment not in application_retrieval

    for implementation_fragment in [
        "class DefaultSystemImageRetriever",
        "SystemImageRetriever",
        "def search_project_memory",
        "def _query_terms",
        "def _embedding_subject_text",
    ]:
        assert implementation_fragment in infrastructure_retrieval
    for forbidden_retriever_dependency in [
        "ApplicationStore",
        "from ...store",
        "self._store",
    ]:
        assert forbidden_retriever_dependency not in infrastructure_retrieval
    assert "SystemImageRetrievalState" in infrastructure_retrieval
    assert "self._chunk_text_reader" in infrastructure_retrieval
    assert "SystemImageMemorySearchResult" in infrastructure_retrieval
    assert "from ..system_image.retrieval import SystemImageMemoryHit, SystemImageRetriever" in application_agent_memory
    assert "DefaultSystemImageRetriever" not in application_agent_memory
    for export_fragment in [
        "SystemImageMemoryHit",
        "SystemImageRetriever",
    ]:
        assert export_fragment in application_system_image_init
    assert "DefaultSystemImageRetriever" not in application_system_image_init
    assert "from .memory_retriever import DefaultSystemImageRetriever" in infrastructure_system_image_init
    assert '"DefaultSystemImageRetriever"' in infrastructure_system_image_init
    for durable_fragment in [
        "class SQLAlchemySystemImageRetriever",
        "async def search_project_memory",
        "HybridRetrievalQuery(",
        "await self._workspace.embed_texts(",
        "await self._workspace.rerank_candidates(",
        "self._system_images.append_retrieval_trace(",
        "self._conversations.list_agent_memory_items(",
    ]:
        assert durable_fragment in durable_retrieval
    assert "SQLAlchemySystemImageRetriever" in infrastructure_system_image_init
    assert "DefaultSystemImageRetriever" not in store_source
    assert "SystemImageRetrievalState(" not in store_source

    internal_sources = [
        path.read_text()
        for path in app_root.rglob("*.py")
        if path.name != "system_image_retriever.py" and "tests" not in path.parts
    ]
    assert all(".system_image_retriever import" not in source for source in internal_sources)


def test_agent_goal_plan_compiler_lives_in_application_layer() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    root_compiler = (app_root / "agent_goal_plan_compiler.py").read_text()
    application_plans = (app_root / "application" / "agent" / "plans.py").read_text()
    agent_graph_runtime = (app_root / "application" / "agent" / "graph.py").read_text()
    application_agent_init = (app_root / "application" / "agent" / "__init__.py").read_text()
    store_source = (app_root / "store.py").read_text()

    assert "from .application.agent.plans import *" in root_compiler
    for compatibility_fragment in ["class AgentGoalPlanCompiler", "@dataclass", "ApplicationStore"]:
        assert compatibility_fragment not in root_compiler
    for implementation_fragment in [
        "class AgentGoalPlanCompiler",
        "def compile_tool_plan",
        "def compile_followup_tool_plan",
        "def _compile_system_image_plan_for_project",
        "def _validate_known_tools",
    ]:
        assert implementation_fragment in application_plans
    assert "from ...domain.agent.runtime_models import AgentGoalProposal, ToolPlanStep" in application_plans
    assert "from .ports import AgentPlanStatePort" in application_plans
    assert 'state: AgentPlanStatePort' in application_plans
    assert "ApplicationStore" not in application_plans
    assert "self.store." not in application_plans
    assert "from .plans import AgentGoalPlanCompiler" in agent_graph_runtime
    assert "plan_compiler: AgentGoalPlanCompiler" in agent_graph_runtime
    assert "self.plan_compiler = plan_compiler" in agent_graph_runtime
    assert "self.agent_goal_plan_compiler = AgentGoalPlanCompiler(" in store_source
    assert "self.agent_application_ports.plan_state" in store_source
    assert "AgentGoalPlanCompiler" in application_agent_init

    internal_sources = [
        path.read_text()
        for path in app_root.rglob("*.py")
        if path.name != "agent_goal_plan_compiler.py" and "tests" not in path.parts
    ]
    assert all(".agent_goal_plan_compiler import" not in source for source in internal_sources)


def test_agent_low_risk_application_services_depend_on_explicit_ports() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    ports_source = (app_root / "application" / "agent" / "ports.py").read_text()
    adapter_source = (
        app_root / "infrastructure" / "agent" / "application_ports.py"
    ).read_text()
    planning_dependencies = (
        app_root / "infrastructure" / "agent" / "planning_dependencies.py"
    ).read_text()
    conversation_runtime_dependencies = (
        app_root
        / "infrastructure"
        / "agent"
        / "conversation_runtime_dependencies.py"
    ).read_text()
    conversation_management_dependencies = (
        app_root
        / "infrastructure"
        / "agent"
        / "conversation_management_dependencies.py"
    ).read_text()
    scope_resolution_application = (
        app_root / "application" / "platform" / "scope_resolution.py"
    ).read_text()
    scope_resolution_infrastructure = (
        app_root / "infrastructure" / "platform" / "scope_resolution.py"
    ).read_text()
    conversation_state_dependencies = (
        app_root
        / "infrastructure"
        / "agent"
        / "conversation_state_dependencies.py"
    ).read_text()
    goal_state_dependencies = (
        app_root
        / "infrastructure"
        / "agent"
        / "goal_state_dependencies.py"
    ).read_text()
    graph_state_dependencies = (
        app_root
        / "infrastructure"
        / "agent"
        / "graph_state_dependencies.py"
    ).read_text()
    workflow_state_dependencies = (
        app_root
        / "infrastructure"
        / "agent"
        / "workflow_state_dependencies.py"
    ).read_text()
    application_port_dependencies = (
        app_root
        / "infrastructure"
        / "agent"
        / "application_port_dependencies.py"
    ).read_text()
    store_source = (app_root / "store.py").read_text()

    for port_name in [
        "ConversationMessageStatePort",
        "ConversationSummaryStatePort",
        "AgentConversationEventPublisherPort",
        "AgentGoalExplanationQueryPort",
        "AgentPlannerContextPort",
        "AgentPlanStatePort",
    ]:
        assert f"class {port_name}(Protocol)" in ports_source

    for service_name in [
        "planner_context.py",
        "message_writer.py",
        "conversation_summary.py",
        "explanations.py",
        "plans.py",
    ]:
        service_source = (app_root / "application" / "agent" / service_name).read_text()
        assert "ApplicationStore" not in service_source
        assert "from ...store" not in service_source

    for adapter_name in [
        "LegacyConversationMessageStateAdapter",
        "LegacyConversationSummaryStateAdapter",
        "LegacyAgentConversationEventPublisher",
        "LegacyAgentGoalExplanationQueryAdapter",
        "LegacyAgentPlannerContextAdapter",
        "LegacyAgentPlanStateAdapter",
        "LegacyAgentApplicationPorts",
    ]:
        assert f"class {adapter_name}" in adapter_source

    planner_context_block = adapter_source.split(
        "class LegacyAgentPlannerContextAdapter",
        1,
    )[1].split("class LegacyAgentPlanStateAdapter", 1)[0]
    plan_state_block = adapter_source.split(
        "class LegacyAgentPlanStateAdapter",
        1,
    )[1].split("class LegacyAgentApplicationPorts", 1)[0]
    for adapter_block in [planner_context_block, plan_state_block]:
        assert "ApplicationStore" not in adapter_block
        assert "self._store" not in adapter_block
    for dependency_fragment in [
        "class AgentPlannerContextAdapters",
        "class AgentPlanningProjectionState",
        "class AgentPlanningRuntimeAdapters",
    ]:
        assert dependency_fragment in planning_dependencies
    assert "ApplicationStore" not in planning_dependencies
    assert "AgentPlanningProjectionState(" in adapter_source
    assert "AgentPlanningRuntimeAdapters(" in adapter_source
    assert "AgentPlannerContextAdapters(" in adapter_source
    conversation_runtime_block = adapter_source.split(
        "class LegacyConversationMessageRuntimeAdapter",
        1,
    )[1].split("class LegacyConversationSummaryStateAdapter", 1)[0]
    assert "self._store" not in conversation_runtime_block
    assert "ApplicationStore" not in conversation_runtime_block
    assert "ReadModelSummaryService" not in conversation_runtime_block
    assert (
        "class AgentConversationRuntimeAdapters"
        in conversation_runtime_dependencies
    )
    assert "ApplicationStore" not in conversation_runtime_dependencies
    assert "AgentConversationRuntimeAdapters(" in adapter_source

    conversation_management_block = adapter_source.split(
        "class LegacyConversationManagementStateAdapter",
        1,
    )[1].split("class LegacyConversationMessageStateAdapter", 1)[0]
    for forbidden_fragment in [
        "self._store",
        "ApplicationStore",
        "ProjectScopeResolutionApplicationService",
    ]:
        assert forbidden_fragment not in conversation_management_block
    for dependency_fragment in [
        "class AgentConversationManagementProjectionState",
        "class AgentConversationManagementPersistenceAdapters",
        "class AgentConversationManagementRuntimeAdapters",
    ]:
        assert dependency_fragment in conversation_management_dependencies
    assert "ApplicationStore" not in conversation_management_dependencies
    assert "class ProjectScopeReadPort(Protocol)" in scope_resolution_application
    assert "ApplicationStore" not in scope_resolution_application
    assert "self._store" not in scope_resolution_application
    assert (
        "class CompatibilityProjectScopeProjection"
        in scope_resolution_infrastructure
    )
    assert "class SQLAlchemyProjectScopeReadModel" in scope_resolution_infrastructure
    assert "select(VersionRecord.project_id)" in scope_resolution_infrastructure
    assert "select(USWorkItemRecord.project_id)" in scope_resolution_infrastructure
    assert "select(VersionRecord.id)" in scope_resolution_infrastructure
    assert "ApplicationStore" not in scope_resolution_infrastructure
    assert "SQLAlchemyProjectScopeReadModel," in store_source
    assert "SQLAlchemyProjectScopeReadModel()" in store_source
    assert "CompatibilityProjectScopeProjection(" not in store_source
    assert "AgentConversationManagementProjectionState(" in adapter_source
    assert "AgentConversationManagementPersistenceAdapters(" in adapter_source
    assert "AgentConversationManagementRuntimeAdapters(" in adapter_source

    conversation_message_state_block = adapter_source.split(
        "class LegacyConversationMessageStateAdapter",
        1,
    )[1].split("class LegacyAgentMemoryStateAdapter", 1)[0]
    conversation_summary_state_block = adapter_source.split(
        "class LegacyConversationSummaryStateAdapter",
        1,
    )[1].split("class LegacyAgentConversationEventPublisher", 1)[0]
    conversation_event_block = adapter_source.split(
        "class LegacyAgentConversationEventPublisher",
        1,
    )[1].split("class LegacyAgentGoalExplanationQueryAdapter", 1)[0]
    goal_explanation_block = adapter_source.split(
        "class LegacyAgentGoalExplanationQueryAdapter",
        1,
    )[1].split("class LegacyAgentPlannerContextAdapter", 1)[0]
    for adapter_block in [
        conversation_message_state_block,
        conversation_summary_state_block,
        conversation_event_block,
        goal_explanation_block,
    ]:
        assert "self._store" not in adapter_block
        assert "ApplicationStore" not in adapter_block

    for dependency_fragment in [
        "class AgentConversationProjectionState",
        "class AgentConversationPersistenceAdapters",
        "class AgentConversationCheckpointAdapters",
        "class AgentConversationEventAdapters",
        "class AgentGoalExplanationAdapters",
    ]:
        assert dependency_fragment in conversation_state_dependencies
    assert "ApplicationStore" not in conversation_state_dependencies
    assert "AgentConversationProjectionState(" in adapter_source
    assert "AgentConversationPersistenceAdapters(" in adapter_source
    assert "AgentConversationCheckpointAdapters(" in adapter_source
    assert "AgentConversationEventAdapters(" in adapter_source
    assert "AgentGoalExplanationAdapters(" in adapter_source

    goal_projection_block = adapter_source.split(
        "class LegacyAgentGoalProjectionStateAdapter",
        1,
    )[1].split("class LegacyAgentGoalLifecycleStateAdapter", 1)[0]
    goal_lifecycle_block = adapter_source.split(
        "class LegacyAgentGoalLifecycleStateAdapter",
        1,
    )[1].split("class LegacyAgentLoopStateAdapter", 1)[0]
    goal_loop_block = adapter_source.split(
        "class LegacyAgentLoopStateAdapter",
        1,
    )[1].split("class LegacyAgentGraphStateAdapter", 1)[0]
    for adapter_block in [
        goal_projection_block,
        goal_lifecycle_block,
        goal_loop_block,
    ]:
        assert "self._store" not in adapter_block
        assert "ApplicationStore" not in adapter_block

    for dependency_fragment in [
        "class AgentGoalProjectionState",
        "class AgentGoalLifecycleState",
        "class AgentGoalProjectionPersistenceAdapters",
        "class AgentGoalLifecycleAdapters",
        "class AgentLoopRuntimeAdapters",
    ]:
        assert dependency_fragment in goal_state_dependencies
    assert "ApplicationStore" not in goal_state_dependencies
    assert "AgentGoalProjectionState(" in adapter_source
    assert "AgentGoalProjectionPersistenceAdapters(" in adapter_source
    assert "AgentGoalLifecycleAdapters(" in adapter_source
    assert "AgentLoopRuntimeAdapters(" in adapter_source

    graph_state_block = adapter_source.split(
        "class LegacyAgentGraphStateAdapter",
        1,
    )[1].split("class LegacyAgentWorkflowStateAdapter", 1)[0]
    assert "self._store" not in graph_state_block
    assert "ApplicationStore" not in graph_state_block
    for dependency_fragment in [
        "class AgentGraphLookupAdapters",
        "class AgentGraphToolRuntimeAdapters",
        "class AgentGraphMemoryAdapters",
    ]:
        assert dependency_fragment in graph_state_dependencies
    assert "ApplicationStore" not in graph_state_dependencies
    assert "AgentGraphLookupAdapters(" in adapter_source
    assert "AgentGraphToolRuntimeAdapters(" in adapter_source
    assert "AgentGraphMemoryAdapters(" in adapter_source

    workflow_state_block = adapter_source.split(
        "class LegacyAgentWorkflowStateAdapter",
        1,
    )[1].split("class LegacyConversationMessageRuntimeAdapter", 1)[0]
    assert "self._store" not in workflow_state_block
    assert "ApplicationStore" not in workflow_state_block
    assert "getattr(" not in workflow_state_block
    assert "class AgentWorkflowRuntimeAdapters" in workflow_state_dependencies
    assert "ApplicationStore" not in workflow_state_dependencies
    assert "AgentWorkflowRuntimeAdapters(" in adapter_source

    for dependency_fragment in [
        "class AgentApplicationProjectionState",
        "class AgentApplicationPersistenceAdapters",
        "class AgentApplicationRuntimeAdapters",
    ]:
        assert dependency_fragment in application_port_dependencies
    for forbidden_fragment in ["ApplicationStore", "self._store", "store."]:
        assert forbidden_fragment not in application_port_dependencies
    assert "self.agent_application_ports = SQLAlchemyAgentApplicationPorts(" in store_source
    assert "LegacyAgentApplicationPorts(" not in store_source
    assert "AgentApplicationProjectionState(" not in store_source
    assert "AgentApplicationPersistenceAdapters(" not in store_source
    assert "AgentApplicationRuntimeAdapters(" in store_source
    assert "self.projects: Dict[str, ProjectCard] = {}" not in store_source
    assert "self.agent_application_ports = SQLAlchemyAgentApplicationPorts(" in store_source


def test_distributed_state_sync_uses_explicit_repository_dependencies() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    synchronization_source = (
        app_root / "application" / "platform" / "distributed_state_sync.py"
    ).read_text()
    store_source = (app_root / "store.py").read_text()

    for required_fragment in [
        "class DistributedStateSynchronizationDependencies",
        "persist_goal: Callable[[AgentGoal], None]",
        "get_conversation: Callable[[str], ConversationSession | None]",
        "self._dependencies.persist_goal(goal)",
        "self._dependencies.get_conversation(goal.conversation_id)",
    ]:
        assert required_fragment in synchronization_source
    assert "refresh_project_state" not in synchronization_source
    for forbidden_fragment in [
        "ApplicationStore",
        "from ...store",
        "self._store",
        "getattr(",
        "refresh_runtime_state",
        "mutation_guard",
    ]:
        assert forbidden_fragment not in synchronization_source
    assert "MutableMapping" not in synchronization_source
    assert "self._dependencies.goals" not in synchronization_source
    assert "self._dependencies.conversations" not in synchronization_source
    assert "DistributedStateSynchronizationDependencies(" in store_source
    assert "persist_goal=self.conversation_repository.upsert_goal" in store_source
    assert "get_conversation=self.conversation_repository.get_conversation" in store_source


def test_agent_swarm_coordinator_lives_in_application_layer() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    root_swarm = (app_root / "agent_swarm.py").read_text()
    application_swarm = (app_root / "application" / "agent" / "swarm.py").read_text()
    store_source = (app_root / "store.py").read_text()
    application_agent_init = (app_root / "application" / "agent" / "__init__.py").read_text()

    assert "from .application.agent.swarm import *" in root_swarm
    for compatibility_fragment in ["class AgentSwarmCoordinator", "AgentSwarmRun", "ApplicationStore"]:
        assert compatibility_fragment not in root_swarm
    for implementation_fragment in [
        "class AgentSwarmCoordinator",
        "def run_system_image_materialization_swarm",
        "def get_swarm",
        "def _persist",
        "def _emit_swarm_event",
        "agent.swarm.completed",
        "AgentSwarmStatePort",
        "self._state = state",
        "self._state.persist_swarm(swarm)",
        'await self._state.publish_swarm_event(swarm, "agent.swarm.updated", event_patch)',
        "await self._state.publish_swarm_event(swarm, event_type, event_patch)",
        '"transition_event_type": event_type',
    ]:
        assert implementation_fragment in application_swarm
    assert "from .agent_models import AgentSwarmRun, AgentWorkerAssignment" in application_swarm
    assert "from .ports import AgentSwarmStatePort" in application_swarm
    assert "from ..system_image.system_image_models import RawAssetRecord" in application_swarm
    for forbidden_fragment in [
        "ApplicationStore",
        "PlatformEventApplicationService",
        "conversation_repository",
        "self.store",
        "self._store",
    ]:
        assert forbidden_fragment not in application_swarm
    assert "from .application.agent.swarm import AgentSwarmCoordinator" in store_source
    assert "AgentSwarmCoordinator" in application_agent_init

    internal_sources = [
        path.read_text()
        for path in app_root.rglob("*.py")
        if path.name != "agent_swarm.py" and "tests" not in path.parts
    ]
    assert all(".agent_swarm import" not in source for source in internal_sources)


def test_agent_loop_runtime_lives_in_application_layer() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    root_loop = (app_root / "agent_loop_runtime.py").read_text()
    application_loop = (app_root / "application" / "agent" / "loop.py").read_text()
    store_source = (app_root / "store.py").read_text()

    assert "from .application.agent.loop import *" in root_loop
    for compatibility_fragment in ["class AgentLoopRuntime", "AgentGoalCreateRequest", "ApplicationStore"]:
        assert compatibility_fragment not in root_loop
    for implementation_fragment in [
        "class AgentLoopRuntime",
        "def start_goal",
        "def resume_goal",
        "def checkpoint",
        "AgentLoopStatePort",
        "self._state = state",
        "self._state.create_goal(",
        "self._state.record_goal_audit(",
        "await self._state.publish_goal_proposed(",
        "await self._state.append_assistant_message(",
    ]:
        assert implementation_fragment in application_loop
    assert "from ...domain.agent.runtime_models import AgentGoalProposal" in application_loop
    assert "from ...domain.agent.state_machine import AgentGoalRuntimeCheckpoint, AgentGoalStateMachine" in application_loop
    for forbidden_fragment in [
        "ApplicationStore",
        "self.store",
        "PlatformEventApplicationService",
        "build_agent_graph_runtime",
        "infrastructure.workflow",
    ]:
        assert forbidden_fragment not in application_loop
    assert "from .application.agent.loop import AgentLoopRuntime" in store_source
    assert "self.agent_application_ports.loop_state" in store_source
    assert "self.agent_graph_runtime" in store_source

    internal_sources = [
        path.read_text()
        for path in app_root.rglob("*.py")
        if path.name != "agent_loop_runtime.py" and "tests" not in path.parts
    ]
    assert all(".agent_loop_runtime import" not in source for source in internal_sources)


def test_agent_graph_runtime_split_between_application_and_infrastructure() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    root_graph_runtime = (app_root / "agent_graph_runtime.py").read_text()
    application_graph = (app_root / "application" / "agent" / "graph.py").read_text()
    application_loop = (app_root / "application" / "agent" / "loop.py").read_text()
    application_agent_init = (app_root / "application" / "agent" / "__init__.py").read_text()
    infra_factory = (app_root / "infrastructure" / "workflow" / "agent_graph_factory.py").read_text()
    infra_gateway = (app_root / "infrastructure" / "workflow" / "langgraph_agent_gateway.py").read_text()
    infra_workflow_init = (app_root / "infrastructure" / "workflow" / "__init__.py").read_text()

    assert "from .application.agent.graph import *" in root_graph_runtime
    assert "from .infrastructure.workflow.agent_graph_factory import *" in root_graph_runtime
    for compatibility_fragment in [
        "class LocalAgentGraphRuntime",
        "class LangGraphAgentGraphRuntime",
        "def build_agent_graph_runtime",
        "def selected_agent_graph_runtime_kind",
        "os.getenv",
    ]:
        assert compatibility_fragment not in root_graph_runtime

    for implementation_fragment in [
        "class AgentGraphRuntime",
        "class LangGraphGateway",
        "class LangGraphAgentGraphRuntime",
        "class LocalAgentGraphRuntime",
        "def steps_for_proposal",
        "ToolInvocationRequest",
        "AgentGraphStatePort",
        "self._state = state",
        "await self._state.publish_goal_event(",
        "await self._state.create_tool_invocation(",
        "await self._state.confirm_tool_invocation(",
        "self._state.persist_goal(goal)",
        "def _tool_invocation_or_none",
        "self._state.get_tool_invocation_or_none(invocation_id)",
    ]:
        assert implementation_fragment in application_graph
    for forbidden_fragment in [
        "ApplicationStore",
        "self.store",
        "PlatformEventApplicationService",
        "AgentGoalProjectionApplicationService",
        "os.getenv",
        "NASUS_AGENT_GRAPH_RUNTIME",
        "LangGraphAgentLoopGateway",
        "from langgraph.graph",
    ]:
        assert forbidden_fragment not in application_graph

    for factory_fragment in [
        "def selected_agent_graph_runtime_kind",
        "def build_agent_graph_runtime",
        "NASUS_AGENT_GRAPH_RUNTIME",
        "LangGraphAgentLoopGateway",
        "LocalAgentGraphRuntime",
        "LangGraphAgentGraphRuntime",
    ]:
        assert factory_fragment in infra_factory
    assert "from .graph import AgentGraphRuntime" in application_loop
    assert "infrastructure.workflow" not in application_loop
    assert "from ...application.agent.graph import LocalAgentGraphRuntime" in infra_gateway
    assert "AgentGraphStatePort" in infra_gateway
    assert "self._state = state" in infra_gateway
    assert "self.store" not in infra_gateway

    for export_fragment in [
        "AgentGraphRuntime",
        "LangGraphAgentGraphRuntime",
        "LangGraphGateway",
        "LocalAgentGraphRuntime",
    ]:
        assert export_fragment in application_agent_init
    for export_fragment in ["build_agent_graph_runtime", "selected_agent_graph_runtime_kind"]:
        assert export_fragment in infra_workflow_init

    internal_sources = [
        path.read_text()
        for path in app_root.rglob("*.py")
        if path.name != "agent_graph_runtime.py" and "tests" not in path.parts
    ]
    assert all(".agent_graph_runtime import" not in source for source in internal_sources)


def test_agent_planner_lives_in_application_layer() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    root_planner = (app_root / "agent_planner.py").read_text()
    application_planner = (app_root / "application" / "agent" / "planner.py").read_text()
    prompt_registry_source = (
        app_root / "domain" / "platform" / "prompt_registry.py"
    ).read_text()
    domain_plan_policy = (app_root / "domain" / "agent" / "plan_policy.py").read_text()
    planner_context_source = (
        app_root / "application" / "agent" / "planner_context.py"
    ).read_text()
    agent_package_source = (
        app_root / "application" / "agent" / "__init__.py"
    ).read_text()
    store_source = (app_root / "store.py").read_text()

    assert "from .application.agent.planner import *" in root_planner
    for compatibility_fragment in ["class LLMStructuredAgentPlanner", "class DeterministicAgentPlanner", "ConversationOrchestrator"]:
        assert compatibility_fragment not in root_planner
    for implementation_fragment in [
        "class AgentPlanner",
        "class DeterministicAgentPlanner",
        "class LLMStructuredAgentPlanner",
        "def _decision_from_payload",
        "def _planner_system_prompt",
    ]:
        assert implementation_fragment in application_planner
    for registry_fragment in [
        "class PromptDefinition",
        'prompt_id="agent_loop_planner"',
        "You are the Nasus structured agent planner",
        "Never invent project_id",
        "Keep a plan to at most 12 tool actions",
    ]:
        assert registry_fragment in prompt_registry_source
    for prompt_resolution_fragment in [
        "PromptRegistryPort",
        "def _active_prompt",
        'self._active_prompt("agent_loop_planner")',
        "prompt_id=prompt.prompt_id",
        "prompt_version=prompt.version",
    ]:
        assert prompt_resolution_fragment in application_planner
    assert "from ...domain.agent.memory import AgentMemoryContext" in application_planner
    assert "from ...domain.agent.plan_policy import (" in application_planner
    assert "from ...domain.agent.runtime_models import (" in application_planner
    for policy_fragment in [
        "class AgentPlanPolicy",
        "class AgentPlanPolicyViolation",
        "class AgentPlanScope",
        "class AgentToolContract",
        "def bind_and_validate",
        "_reserved_runtime_keys",
        "scope_conflict",
        "step_budget_exceeded",
        "duplicate_action",
    ]:
        assert policy_fragment in domain_plan_policy
    for application_leak in [
        "application.",
        "infrastructure.",
        "ToolDefinition",
        "ConversationSession",
    ]:
        assert application_leak not in domain_plan_policy
    for governed_planner_fragment in [
        "self.plan_policy.bind_and_validate(",
        "def _govern_decision",
        "def _clarification_for_policy_violation",
        "definitions_by_id[step.tool_id].tool_kind != \"query\"",
    ]:
        assert governed_planner_fragment in application_planner
    assert "def _allows_live_write_planning" not in application_planner
    assert "from .application.agent.planner import DeterministicAgentPlanner, LLMStructuredAgentPlanner" in store_source
    assert "allow_deterministic_write_fallback=not current_runtime_profile().production_like" in store_source
    for production_fallback_fragment in [
        "def _safe_deterministic_fallback",
        "def _has_write_effect",
        "planner_provider_unavailable",
        "missing_context=[\"live_chat_model\"]",
    ]:
        assert production_fallback_fragment in application_planner
    assert "class AgentPlannerContextApplicationService" in planner_context_source
    for planner_context_fragment in [
        "def memory_context",
        "def conversation_summary_fallback",
        "def quality_state",
        "AgentPlannerContextPort",
        "await self._context.memory_context(conversation)",
        "self._context.conversation_summary_fallback(conversation)",
        "self._context.quality_state(project_id, us_id)",
    ]:
        assert planner_context_fragment in planner_context_source
    for leaked_planner_dependency in [
        "ApplicationStore",
        "ReadModelSummaryService",
        "QualityLoopContextQueryApplicationService",
        "from ...store",
        "self.store.",
    ]:
        assert leaked_planner_dependency not in planner_context_source
    assert "AgentPlannerContextApplicationService" in agent_package_source
    assert "from .application.agent.planner_context import AgentPlannerContextApplicationService" in store_source
    assert "self.agent_application_ports.planner_context" in store_source
    assert "summary_builder=self.planner_context.conversation_summary_fallback" in store_source
    assert "quality_state_resolver=self.planner_context.quality_state" in store_source
    assert "memory_context_builder=self.planner_context.memory_context" in store_source
    assert "prompt_registry=self.prompt_registry" in store_source
    for leaked_planner_context_method in [
        "def _planner_memory_context",
        "def _conversation_summary_fallback",
        "def _quality_state_for_planner",
    ]:
        assert leaked_planner_context_method not in store_source

    internal_sources = [
        path.read_text()
        for path in app_root.rglob("*.py")
        if path.name != "agent_planner.py" and "tests" not in path.parts
    ]
    assert all(".agent_planner import" not in source for source in internal_sources)


def test_conversation_orchestrator_lives_in_agent_application_layer() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    root_orchestrator = (app_root / "conversation_orchestrator.py").read_text()
    application_orchestrator = (app_root / "application" / "agent" / "orchestrator.py").read_text()
    application_agent_init = (app_root / "application" / "agent" / "__init__.py").read_text()
    planner_source = (app_root / "application" / "agent" / "planner.py").read_text()
    messages_source = (app_root / "application" / "agent" / "messages.py").read_text()
    store_source = (app_root / "store.py").read_text()

    assert "from .application.agent.orchestrator import *" in root_orchestrator
    for compatibility_fragment in ["class ConversationOrchestrator", "@dataclass", "def plan", "re.compile"]:
        assert compatibility_fragment not in root_orchestrator
    for implementation_fragment in [
        "class ConversationOrchestrator",
        "def plan",
        "def _system_image_initialization_plan",
        "def _quality_loop_goal",
        "def _extract_system_image_source_specs",
    ]:
        assert implementation_fragment in application_orchestrator
    assert "from ...domain.agent.runtime_models import (" in application_orchestrator
    assert "from .agent_models import ConversationMessage, ConversationSession" in application_orchestrator
    assert "from ..platform.tool_models import ToolDefinition" in application_orchestrator
    assert "ConversationOrchestrator" in application_agent_init
    assert "from .orchestrator import ConversationOrchestrator, QualityStateResolver" in planner_source
    assert "from .orchestrator import ConversationOrchestrator" in messages_source
    assert "ConversationOrchestrator" not in store_source

    internal_sources = [
        path.read_text()
        for path in app_root.rglob("*.py")
        if path.name != "conversation_orchestrator.py" and "tests" not in path.parts
    ]
    assert all(".conversation_orchestrator import" not in source for source in internal_sources)


def test_conversation_fallback_text_lives_in_agent_application_service() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    fallback_source = (app_root / "application" / "agent" / "conversation_fallbacks.py").read_text()
    messages_source = (app_root / "application" / "agent" / "messages.py").read_text()
    agent_init_source = (app_root / "application" / "agent" / "__init__.py").read_text()

    for fragment in [
        "class ConversationFallbackApplicationService",
        "ReadModelSummaryService",
        "def __init__(self, summaries: ReadModelSummaryService)",
        "def fallback_text",
        "self.summaries.conversation_summary_fallback(conversation)",
    ]:
        assert fragment in fallback_source
    for forbidden_fragment in ["ApplicationStore", "self._store", "ReadModelSummaryService(store)"]:
        assert forbidden_fragment not in fallback_source

    assert "self._runtime.fallback_text(conversation)" in messages_source
    for leaked_fallback_dependency in [
        "ConversationFallbackApplicationService",
        "ReadModelSummaryService",
        "conversation_summary_fallback(conversation)",
        "_read_model_summaries()",
    ]:
        assert leaked_fallback_dependency not in messages_source

    assert "ConversationFallbackApplicationService" in agent_init_source
    assert '"ConversationFallbackApplicationService": ".conversation_fallbacks"' in agent_init_source


def test_persistence_implementation_lives_under_infrastructure_layer() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    root_database = (app_root / "database.py").read_text()
    root_db_models = (app_root / "db_models.py").read_text()
    root_repositories = (app_root / "repositories.py").read_text()
    root_settings_store = (app_root / "settings_store.py").read_text()
    infra_database = (app_root / "infrastructure" / "persistence" / "database.py").read_text()
    infra_db_models = (app_root / "infrastructure" / "persistence" / "db_models.py").read_text()
    infra_conversation_repository = (
        app_root / "infrastructure" / "persistence" / "conversation_repository.py"
    ).read_text()
    infra_project_repository = (
        app_root / "infrastructure" / "persistence" / "project_repository.py"
    ).read_text()
    infra_quality_loop_repository = (
        app_root / "infrastructure" / "persistence" / "quality_loop_repository.py"
    ).read_text()
    infra_repositories = (app_root / "infrastructure" / "persistence" / "repositories.py").read_text()
    infra_settings_repository = (
        app_root / "infrastructure" / "persistence" / "settings_repository.py"
    ).read_text()
    infra_system_image_repository = (
        app_root / "infrastructure" / "persistence" / "system_image_repository.py"
    ).read_text()
    infra_unit_of_work = (app_root / "infrastructure" / "persistence" / "unit_of_work.py").read_text()
    infra_settings_store = (app_root / "infrastructure" / "persistence" / "settings_store.py").read_text()
    infra_init = (app_root / "infrastructure" / "persistence" / "__init__.py").read_text()

    assert "from .infrastructure.persistence.database import *" in root_database
    assert "from .infrastructure.persistence.db_models import *" in root_db_models
    assert "from .infrastructure.persistence.repositories import *" in root_repositories
    assert "from .infrastructure.persistence.settings_store import *" in root_settings_store
    for compatibility_source in [root_database, root_db_models, root_repositories, root_settings_store]:
        assert "class " not in compatibility_source
        assert "mapped_column" not in compatibility_source
        assert "select(" not in compatibility_source
    for compatibility_fragment in ["create_engine", "declarative_base", "sessionmaker", "_ensure_sqlite_additive_schema"]:
        assert compatibility_fragment not in root_database

    for fragment in ["DATABASE_URL", "create_engine", "SessionLocal", "Base = declarative_base()", "init_database"]:
        assert fragment in infra_database
    for fragment in ["class UserIdentityRecord", "mapped_column", "from .database import Base"]:
        assert fragment in infra_db_models
    for fragment in [
        "from .conversation_repository import ConversationRepository",
        "from .project_repository import ProjectRepository",
        "from .settings_repository import SettingsRepository",
        "from .unit_of_work import session_scope",
        '__all__ = ["ConversationRepository", "ProjectRepository", "SettingsRepository", "session_scope"]',
    ]:
        assert fragment in infra_repositories
    for forbidden_fragment in [
        "class ProjectRepository",
        "select(",
        "delete(",
        "ProjectRecord",
        "QualityAssetPackRecord",
        "BaselineRecord as BaselineRow",
    ]:
        assert forbidden_fragment not in infra_repositories
    for fragment in [
        "class ProjectRepository",
        "QualityLoopRepository",
        "ProjectRecord",
        "SystemImageRepository",
        "VersionRecord",
        '__all__ = ["ProjectRepository"]',
        "session_scope",
    ]:
        assert fragment in infra_project_repository
    for forbidden_fragment in [
        "BaselineRecord as BaselineRow",
        "RawAssetRecord as RawAssetRow",
        "KnowledgeObjectRecord",
        "ContextRelationshipRecord",
        "EmbeddingRecord as EmbeddingRow",
        "QualityAssetPackRecord",
        "USWorkItemRecord",
        "RunRecord",
        "ApprovalRecord",
        "session.execute(delete(RawAssetRow)",
        "session.execute(delete(RunRecord)",
    ]:
        assert forbidden_fragment not in infra_project_repository
    for fragment in [
        "class QualityLoopRepository",
        "QualityAssetPackRecord",
        "USWorkItemRecord",
        "RunRecord",
        "ApprovalRecord",
        "replace_execution_evidence",
        "upsert_release_readiness",
        '__all__ = ["QualityLoopRepository"]',
        "session_scope",
    ]:
        assert fragment in infra_quality_loop_repository
    for fragment in [
        "class SystemImageRepository",
        "BaselineRecord as BaselineRow",
        "RawAssetRecord as RawAssetRow",
        "KnowledgeObjectRecord",
        "ContextRelationshipRecord",
        "EmbeddingRecord as EmbeddingRow",
        "replace_system_image",
            '__all__ = ["SystemImageProjectSnapshot", "SystemImageRepository"]',
        "session_scope",
    ]:
        assert fragment in infra_system_image_repository
    assert "class ConversationRepository" not in infra_repositories
    for fragment in [
        "class ConversationRepository",
        "ConversationRecord",
        "ConversationMessageRecord",
        "AgentGoalRecord",
        "ToolInvocationRecord",
        "AuditEventRecord",
        '__all__ = ["ConversationRepository"]',
        "session_scope",
    ]:
        assert fragment in infra_conversation_repository
    for fragment in [
        "class SettingsRepository",
        "SavedModelConfig",
        "ModelProviderConfigRecord",
        "ModelRouteSelectionRecord",
        "SettingsRecord",
        "session_scope",
    ]:
        assert fragment in infra_settings_repository
    assert "from .database import SessionLocal" in infra_unit_of_work
    assert "def session_scope" in infra_unit_of_work
    assert "Base" in infra_init
    assert "ConversationRepository" in infra_init
    assert "ProjectRepository" in infra_init
    assert "QualityLoopRepository" in infra_init
    assert "SessionLocal" in infra_init
    assert "init_database" in infra_init
    assert "SettingsRepository" in infra_init
    assert "SystemImageRepository" in infra_init
    assert "session_scope" in infra_init
    assert "SettingsPersistence" in infra_init
    store_source = (app_root / "store.py").read_text()
    assert "from .infrastructure.persistence.database import init_database" in store_source
    assert "from .infrastructure.persistence.conversation_repository import ConversationRepository" in store_source
    assert "from .infrastructure.persistence.project_repository import ProjectRepository" in store_source
    assert "from .infrastructure.persistence.settings_repository import SettingsRepository" in store_source
    assert "from .infrastructure.persistence.repositories import ProjectRepository" not in store_source
    assert "from .infrastructure.persistence.repositories import ConversationRepository, ProjectRepository, SettingsRepository" not in store_source
    assert "from .database import init_database" not in store_source
    assert "from .repositories import " not in store_source
    for fragment in ["class SettingsPersistence", "openssl", "settings.json", "encrypt_api_key", "decrypt_api_key"]:
        assert fragment in infra_settings_store


def test_runtime_configuration_guard_lives_under_infrastructure_layer() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    root_runtime_config = (app_root / "runtime_config.py").read_text()
    root_agent_runtime_config = (app_root / "agent_runtime_config.py").read_text()
    infra_runtime_config = (app_root / "infrastructure" / "config" / "runtime_config.py").read_text()
    infra_agent_runtime_config = (app_root / "infrastructure" / "config" / "agent_runtime_config.py").read_text()
    infra_config_init = (app_root / "infrastructure" / "config" / "__init__.py").read_text()
    composition_source = (app_root / "composition.py").read_text()
    store_source = (app_root / "store.py").read_text()
    temporal_gateway_source = (app_root / "infrastructure" / "workflow" / "temporal_agent_gateway.py").read_text()
    langgraph_gateway_source = (app_root / "infrastructure" / "workflow" / "langgraph_agent_gateway.py").read_text()
    root_workflow_worker = (app_root / "agent_goal_workflow_worker.py").read_text()
    workflow_worker_source = (
        app_root / "infrastructure" / "workflow" / "agent_goal_workflow_worker.py"
    ).read_text()
    workflow_activity_source = (
        app_root / "application" / "agent" / "activities.py"
    ).read_text()

    assert "from .infrastructure.config.runtime_config import *" in root_runtime_config
    assert "from .infrastructure.config.agent_runtime_config import *" in root_agent_runtime_config
    for compatibility_fragment in ["os.getenv", "PRODUCTION_PROFILES", "RuntimeConfigurationError", "demo_seed_enabled"]:
        assert compatibility_fragment not in root_runtime_config
    for compatibility_fragment in ["os.getenv", "TemporalGatewayConfig", "LangGraphGatewayConfig"]:
        assert compatibility_fragment not in root_agent_runtime_config
    for implementation_fragment in [
        "PRODUCTION_PROFILES",
        "RuntimeConfigurationError",
        "NASUS_DATABASE_URL must use PostgreSQL",
        "NASUS_AGENT_WORKFLOW_RUNTIME must be temporal",
        "NASUS_SEED_DEMO_DATA must be false",
        "demo_seed_enabled",
    ]:
        assert implementation_fragment in infra_runtime_config
        assert implementation_fragment in infra_config_init or implementation_fragment != "RuntimeConfigurationError"
    for implementation_fragment in [
        "TemporalGatewayConfig",
        "LangGraphGatewayConfig",
        "NASUS_TEMPORAL_ADDRESS",
        "NASUS_LANGGRAPH_AGENT_LOOP_GRAPH",
    ]:
        assert implementation_fragment in infra_agent_runtime_config
    for export_fragment in [
        "TemporalGatewayConfig",
        "LangGraphGatewayConfig",
        "temporal_gateway_config_from_env",
        "langgraph_gateway_config_from_env",
    ]:
        assert export_fragment in infra_config_init
    assert "from .infrastructure.config.runtime_config import validate_runtime_configuration" in composition_source
    assert "from .infrastructure.config.runtime_config import demo_seed_enabled" in store_source
    assert "from ..config.agent_runtime_config import TemporalGatewayConfig" in temporal_gateway_source
    assert "from ..config.agent_runtime_config import LangGraphGatewayConfig" in langgraph_gateway_source
    assert "from .infrastructure.workflow.agent_goal_workflow_worker import *" in root_workflow_worker
    assert "from ..config.agent_runtime_config import TemporalGatewayConfig" in workflow_worker_source


def test_demo_seed_data_lives_in_platform_application_service() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    store_source = (app_root / "store.py").read_text()
    demo_seed_source = (app_root / "application" / "platform" / "demo_seed.py").read_text()
    demo_seed_ports_source = (
        app_root / "application" / "platform" / "demo_seed_ports.py"
    ).read_text()
    demo_seed_workspace_source = (
        app_root / "infrastructure" / "platform" / "demo_seed_workspace.py"
    ).read_text()
    documentation_catalog_source = (
        app_root / "application" / "platform" / "documentation_catalog.py"
    ).read_text()
    platform_init_source = (app_root / "application" / "platform" / "__init__.py").read_text()

    seed_block = store_source.split("def _seed", 1)[1].split("def get_welcome", 1)[0]
    assert "from .application.platform.demo_seed import DemoSeedApplicationService" in store_source
    assert "self.demo_seed_workspace = SQLAlchemyDemoSeedWorkspace(" in store_source
    assert "DemoSeedProjectionState(" not in store_source
    assert "DemoSeedWorkspaceAdapters(" not in store_source
    assert "self.demo_seed = DemoSeedApplicationService(self.demo_seed_workspace)" in store_source
    assert "self.demo_seed.seed()" in seed_block
    assert "DemoSeedApplicationService(self).seed()" not in seed_block

    for fragment in [
        "class DemoSeedApplicationService",
        "def seed",
        "proj_payment",
        "ver_payment_q2",
        "run_9021",
        "approval_442",
        "OBJ-CHECKOUT",
        "DemoSeedBaseline(",
        "self._workspace.seed_baseline(",
        "self._workspace.ensure_conversation(",
    ]:
        assert fragment in demo_seed_source
    assert "DOC-START" in documentation_catalog_source
    assert "product_documentation_entries()" in demo_seed_source

    for fragment in [
        "class DemoSeedWorkspacePort",
        "class DemoSeedBaseline",
        "class DemoSeedSystemImage",
    ]:
        assert fragment in demo_seed_ports_source

    for fragment in [
        "class CompatibilityDemoSeedWorkspace",
        "class SQLAlchemyDemoSeedWorkspace",
        "replace_asset_lanes",
        "replace_runs",
        "replace_approvals",
        "replace_knowledge_objects",
        "replace_system_image",
        "upsert_release_readiness",
        "get_or_create_conversation",
    ]:
        assert fragment in demo_seed_workspace_source

    for forbidden_fragment in [
        "ApplicationStore",
        "store: Any",
        "self._store",
    ]:
        assert forbidden_fragment not in demo_seed_source
        assert forbidden_fragment not in demo_seed_workspace_source

    for leaked_fragment in [
        "ProjectCard(",
        "VersionSummary(",
        "USItem(",
        "AssetLane(",
        "RunDetail(",
        "ApprovalDetail(",
        "KnowledgeObject(",
        "ReleaseReadiness(",
        "proj_payment",
        "run_9021",
        "approval_442",
        "OBJ-CHECKOUT",
        "DOC-START",
    ]:
        assert leaked_fragment not in seed_block

    assert "DemoSeedApplicationService" in platform_init_source
    assert '"DemoSeedApplicationService": ".demo_seed"' in platform_init_source


def test_object_storage_adapter_lives_under_infrastructure_layer() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    root_object_storage = (app_root / "object_storage.py").read_text()
    infra_object_storage = (app_root / "infrastructure" / "storage" / "object_storage.py").read_text()
    store_source = (app_root / "store.py").read_text()

    assert "from .infrastructure.storage.object_storage import *" in root_object_storage
    for compatibility_fragment in ["class ObjectStorage", "boto3", "NASUS_S3_ENDPOINT", "local-object://"]:
        assert compatibility_fragment not in root_object_storage
    for implementation_fragment in [
        "class ObjectStorage",
        "ObjectStorageConfig",
        "NASUS_S3_ENDPOINT",
        "local-object://",
        "boto3",
    ]:
        assert implementation_fragment in infra_object_storage
    assert "from .infrastructure.storage import ObjectStorage" in store_source
    assert "from .object_storage import ObjectStorage" not in store_source


def test_llm_provider_adapter_lives_under_infrastructure_layer() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    root_llm = (app_root / "llm.py").read_text()
    infra_llm = (app_root / "infrastructure" / "llm" / "gateway.py").read_text()
    infra_init = (app_root / "infrastructure" / "llm" / "__init__.py").read_text()
    store_source = (app_root / "store.py").read_text()
    agent_planner_source = (app_root / "application" / "agent" / "planner.py").read_text()

    assert "from .infrastructure.llm.gateway import *" in root_llm
    for compatibility_fragment in ["class LLMGateway", "httpx", "generate_reply", "NASUS_DEFAULT"]:
        assert compatibility_fragment not in root_llm
    for implementation_fragment in [
        "class LLMGateway",
        "httpx",
        "generate_reply",
        "embed_texts",
        "rerank_candidates",
        "NASUS_DEFAULT",
    ]:
        assert implementation_fragment in infra_llm
    assert "LLMGateway" in infra_init
    assert "from .infrastructure.llm import LLMGateway" in store_source
    assert "from .llm import LLMGateway" not in store_source
    assert "AgentReplyGenerationPort" in agent_planner_source
    assert "llm: AgentReplyGenerationPort" in agent_planner_source
    assert "infrastructure" not in agent_planner_source
    assert "LLMGateway" not in agent_planner_source
    assert "from ...llm import LLMGateway" not in agent_planner_source


def test_runner_and_workflow_adapters_live_under_infrastructure_layer() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    root_run = (app_root / "run_orchestrator.py").read_text()
    runner_port = (
        app_root / "application" / "quality_loop" / "runner_port.py"
    ).read_text()
    infra_run = (app_root / "infrastructure" / "runner" / "run_orchestrator.py").read_text()
    quality_loop_ports = (
        app_root / "infrastructure" / "quality_loop" / "application_ports.py"
    ).read_text()
    durable_quality_workspaces = (
        app_root / "infrastructure" / "quality_loop" / "sqlalchemy_workspaces.py"
    ).read_text()
    quality_loop_repository = (
        app_root / "infrastructure" / "persistence" / "quality_loop_repository.py"
    ).read_text()
    root_workflow_runtime = (app_root / "agent_workflow_runtime.py").read_text()
    app_workflow_runtime = (app_root / "application" / "agent" / "workflow.py").read_text()
    infra_workflow_factory = (
        app_root / "infrastructure" / "workflow" / "agent_workflow_factory.py"
    ).read_text()
    root_temporal = (app_root / "temporal_agent_gateway.py").read_text()
    infra_temporal = (
        app_root / "infrastructure" / "workflow" / "temporal_agent_gateway.py"
    ).read_text()
    root_langgraph = (app_root / "langgraph_agent_gateway.py").read_text()
    infra_langgraph = (
        app_root / "infrastructure" / "workflow" / "langgraph_agent_gateway.py"
    ).read_text()
    root_worker = (app_root / "agent_goal_workflow_worker.py").read_text()
    infra_worker = (
        app_root / "infrastructure" / "workflow" / "agent_goal_workflow_worker.py"
    ).read_text()
    runner_init = (app_root / "infrastructure" / "runner" / "__init__.py").read_text()
    workflow_init = (app_root / "infrastructure" / "workflow" / "__init__.py").read_text()

    assert "from .infrastructure.runner.run_orchestrator import *" in root_run
    assert "class RunOrchestrator" not in root_run
    assert "class RunOrchestrator" in infra_run
    assert "class RunTaskContextProvider" in infra_run
    assert "class QualityRunWorkspacePort" in runner_port
    assert "class EvidenceObjectStoragePort" in runner_port
    assert "ApplicationStore" not in infra_run
    assert "self.store" not in infra_run
    assert "self.workspace.us_title(project_id, us_id)" in infra_run
    assert "self.workspace.save_run_detail(project_id, run)" in infra_run
    assert "self.workspace.replace_run_evidence(" in infra_run
    assert "self.task_context_provider.current_task_context(project_id, us_id)" in infra_run
    assert "self.store._current_task_context" not in infra_run
    assert "self.evidence_storage.put_bytes(" in infra_run
    assert "class LegacyQualityRunWorkspace" in quality_loop_ports
    assert "self._adapters.quality_loop_repository.replace_runs(" in quality_loop_ports
    assert (
        "self._adapters.quality_loop_repository.replace_execution_evidence("
        in quality_loop_ports
    )
    assert "ApplicationStore" not in quality_loop_ports
    assert "self._store" not in quality_loop_ports
    assert "class SQLAlchemyQualityRunWorkspace" in durable_quality_workspaces
    assert "self._repository.upsert_run_detail(" in durable_quality_workspaces
    assert (
        "self._repository.replace_execution_evidence_for_run("
        in durable_quality_workspaces
    )
    assert "def upsert_run_detail(" in quality_loop_repository
    assert "def replace_execution_evidence_for_run(" in quality_loop_repository
    assert "class SQLAlchemyQualityFailureWorkspace" in durable_quality_workspaces
    assert "self._repository.upsert_failure_analysis(" in durable_quality_workspaces
    assert "def upsert_failure_analysis(" in quality_loop_repository
    store_source = (app_root / "store.py").read_text()
    assert "from .infrastructure.runner import RunOrchestrator" in store_source
    assert "from .run_orchestrator import RunOrchestrator" not in store_source
    assert "self.quality_loop_projection_state" not in store_source
    assert "self.quality_loop_workspace_adapters" not in store_source
    assert "self.quality_loop_context_workspace = SQLAlchemyQualityLoopContextWorkspace(" in store_source
    assert "self.quality_loop_context_workspace = LegacyQualityLoopContextWorkspace(" not in store_source
    assert "self.quality_loop_context_queries = QualityLoopContextQueryApplicationService(" in store_source
    assert "self.quality_loop_context_workspace" in store_source
    assert "self.quality_run_workspace = SQLAlchemyQualityRunWorkspace(" in store_source
    assert "self.quality_run_workspace = LegacyQualityRunWorkspace(" not in store_source
    assert "self.quality_failure_workspace = SQLAlchemyQualityFailureWorkspace(" in store_source
    assert "self.quality_failure_workspace = LegacyQualityFailureWorkspace(" not in store_source
    assert "self.run_orchestrator = RunOrchestrator(" in store_source
    assert "self.quality_run_workspace," in store_source
    assert "self.object_storage," in store_source
    assert "content_type=artifact.media_type" in infra_run

    assert "from .application.agent.workflow import *" in root_workflow_runtime
    assert "from .infrastructure.workflow.agent_workflow_factory import *" in root_workflow_runtime
    for compatibility_fragment in [
        "class AgentWorkflowRuntime",
        "class LocalAgentWorkflowRuntime",
        "def build_agent_workflow_runtime",
        "os.getenv",
    ]:
        assert compatibility_fragment not in root_workflow_runtime
    for implementation_fragment in [
        "class AgentWorkflowRuntime",
        "class TemporalWorkflowGateway",
        "class LocalAgentWorkflowRuntime",
        "class TemporalAgentWorkflowRuntime",
        "AgentWorkflowRuntimeKind",
    ]:
        assert implementation_fragment in app_workflow_runtime
    for forbidden_fragment in ["os.getenv", "TemporalClientWorkflowGateway", "temporalio"]:
        assert forbidden_fragment not in app_workflow_runtime
    for implementation_fragment in [
        "def selected_agent_workflow_runtime_kind",
        "def build_agent_workflow_runtime",
        "NASUS_AGENT_WORKFLOW_RUNTIME",
        "TemporalClientWorkflowGateway",
        "LocalAgentWorkflowRuntime",
        "TemporalAgentWorkflowRuntime",
    ]:
        assert implementation_fragment in infra_workflow_factory

    assert "from .infrastructure.workflow.temporal_agent_gateway import *" in root_temporal
    assert "class TemporalClientWorkflowGateway" not in root_temporal
    assert "class TemporalClientWorkflowGateway" in infra_temporal
    assert "temporalio.client" in infra_temporal

    assert "from .infrastructure.workflow.langgraph_agent_gateway import *" in root_langgraph
    assert "class LangGraphAgentLoopGateway" not in root_langgraph
    assert "class LangGraphAgentLoopGateway" in infra_langgraph
    assert "langgraph.graph" in infra_langgraph

    assert "from .infrastructure.workflow.agent_goal_workflow_worker import *" in root_worker
    for compatibility_fragment in ["class AgentGoalWorkflowActivityService", "temporalio", "Client.connect"]:
        assert compatibility_fragment not in root_worker
    for implementation_fragment in [
        "class AgentGoalWorkflowActivityService",
        "def build_temporal_activity_definitions",
        "def build_nasus_agent_goal_workflow",
        "def run_temporal_agent_goal_worker",
        "temporalio.client",
        "temporalio.worker",
    ]:
        assert implementation_fragment in infra_worker

    assert "RunOrchestrator" in runner_init
    assert "build_agent_workflow_runtime" in workflow_init
    assert "selected_agent_workflow_runtime_kind" in workflow_init
    assert "AgentGoalWorkflowActivityService" in workflow_init
    assert "build_nasus_agent_goal_workflow" in workflow_init
    assert "TemporalClientWorkflowGateway" in workflow_init
    assert "LangGraphAgentLoopGateway" in workflow_init


def test_platform_rbac_rules_live_in_domain_policy() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    root_rbac = (app_root / "rbac.py").read_text()
    domain_rbac = (app_root / "domain" / "platform" / "rbac.py").read_text()
    domain_init = (app_root / "domain" / "platform" / "__init__.py").read_text()
    root_runtime = (app_root / "tool_invocation_runtime.py").read_text()
    runtime_source = (app_root / "application" / "platform" / "runtime.py").read_text()
    authorization_source = (
        app_root / "application" / "platform" / "tool_authorization.py"
    ).read_text()

    assert "from .domain.platform.rbac import *" in root_rbac
    for compatibility_fragment in ["class ToolRBAC", "ROLE_ORDER", "from .models"]:
        assert compatibility_fragment not in root_rbac

    for implementation_fragment in [
        "class ToolRBAC",
        "class AuthorizationDecision",
        "ROLE_ORDER",
        "ROLE_ALIASES",
        "class UserRoleSubject",
        "class ToolAuthorizationSubject",
        "def required_roles",
    ]:
        assert implementation_fragment in domain_rbac
    assert "from ...models" not in domain_rbac
    assert "from .rbac import AuthorizationDecision, ToolRBAC" in domain_init
    assert "from .application.platform.runtime import *" in root_runtime
    assert "from ...domain.platform.rbac import AuthorizationDecision" in runtime_source
    assert "from .rbac import AuthorizationDecision, ToolRBAC" not in runtime_source
    assert "from ...domain.platform.rbac import AuthorizationDecision, ToolRBAC" in authorization_source
    assert "self._authorization.authorize(" in runtime_source
    assert "ToolRBAC(" not in runtime_source


def test_platform_tool_governance_rules_live_in_domain_policy() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    root_governance = (app_root / "tool_governance.py").read_text()
    domain_governance = (app_root / "domain" / "platform" / "tool_governance.py").read_text()
    domain_init = (app_root / "domain" / "platform" / "__init__.py").read_text()
    platform_init = (app_root / "application" / "platform" / "__init__.py").read_text()
    approval_verifier_source = (
        app_root / "application" / "platform" / "approval_verifier.py"
    ).read_text()
    approval_ports_source = (
        app_root / "application" / "platform" / "approval_ports.py"
    ).read_text()
    approval_adapter_source = (
        app_root / "infrastructure" / "platform" / "approval_verification.py"
    ).read_text()
    store_source = (app_root / "store.py").read_text()
    runtime_source = (app_root / "application" / "platform" / "runtime.py").read_text()

    assert "from .domain.platform.tool_governance import *" in root_governance
    for compatibility_fragment in ["class ToolGovernance", "ToolInvocation", "ToolDefinition", "GateStatus"]:
        assert compatibility_fragment not in root_governance

    for implementation_fragment in [
        "class ToolGovernance",
        "class ToolGateDecision",
        "class ToolGateSubject",
        "class InvocationGateSubject",
        "waiting_confirmation",
        "waiting_approval",
        "is_confirmation_message",
        "def evaluate",
    ]:
        assert implementation_fragment in domain_governance
    assert "from ...models" not in domain_governance
    assert "from .models" not in domain_governance
    assert "ToolInvocation" not in domain_governance
    assert "ToolDefinition" not in domain_governance
    assert "from .tool_governance import ToolGateDecision, ToolGovernance" in domain_init
    assert "class ToolApprovalVerifierApplicationService" in approval_verifier_source
    for verifier_fragment in [
        "def allows_tool_invocation",
        "Approval {approval_id} cannot be verified without project context.",
        "Approval {approval_id} is not attached to project {project_id}.",
        "Approval {approval_id} is approved.",
        "approved status is required.",
        "self._state.project_id_for_invocation(invocation)",
        "self._state.approval_status(project_id, approval_id)",
    ]:
        assert verifier_fragment in approval_verifier_source
    assert "class ToolApprovalVerificationStatePort(Protocol)" in approval_ports_source
    for adapter_fragment in [
        "class ToolApprovalVerificationFacts",
        "class ProjectedToolApprovalVerificationState",
        "class SQLAlchemyToolApprovalVerificationState",
        "self._facts.conversations.get",
        "self._facts.approvals.get",
        "self._facts.approval_details.get",
        "self._conversations.get_conversation(",
        "self._approvals.get_approval_detail(project_id, approval_id)",
    ]:
        assert adapter_fragment in approval_adapter_source
    for forbidden_fragment in ["ApplicationStore", "self._store", "from ...store"]:
        assert forbidden_fragment not in approval_verifier_source
        assert forbidden_fragment not in approval_ports_source
        assert forbidden_fragment not in approval_adapter_source
    assert "ToolApprovalVerifierApplicationService" in platform_init
    assert "from .domain.platform.tool_governance import ToolGovernance" in store_source
    assert "from .application.platform.approval_verifier import ToolApprovalVerifierApplicationService" in store_source
    assert "self.tool_approval_verification_state = SQLAlchemyToolApprovalVerificationState(" in store_source
    assert "self.conversation_repository," in store_source
    assert "self.quality_loop_repository," in store_source
    assert "self.tool_approval_verification_state = ProjectedToolApprovalVerificationState(" not in store_source
    assert "self.tool_approval_verifier = ToolApprovalVerifierApplicationService(" in store_source
    assert "self.tool_approval_verification_state" in store_source
    assert "approval_verifier=self.tool_approval_verifier.allows_tool_invocation" in store_source
    assert "def _approval_allows_tool_invocation" not in store_source
    assert "from .tool_governance import ToolGovernance" not in store_source
    assert "self._governance.evaluate(" in runtime_source
    assert "governance=self.tool_governance" in store_source


def test_main_is_only_application_entrypoint() -> None:
    main_source = (ROOT / "apps" / "api" / "app" / "main.py").read_text()
    assert "create_app" in main_source
    assert "@app." not in main_source
    assert "FastAPI(" not in main_source


def test_http_auth_boundary_lives_under_interface_layer() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    root_auth = (app_root / "auth.py").read_text()
    interface_auth = (app_root / "interface" / "http" / "auth.py").read_text()
    composition_source = (app_root / "composition.py").read_text()

    assert "from .interface.http.auth import *" in root_auth
    for compatibility_fragment in ["class AuthConfig", "Request", "JSONResponse", "AuthService"]:
        assert compatibility_fragment not in root_auth

    for implementation_fragment in [
        "class AuthConfig",
        "def authenticate_request",
        "def auth_error",
        "Request",
        "JSONResponse",
        "TokenAuthenticator",
    ]:
        assert implementation_fragment in interface_auth
    assert "AuthService" not in interface_auth
    assert "token_authenticator(token)" in interface_auth
    assert "from .interface.http.auth import authenticate_request" in composition_source
    assert "auth_config: AuthConfig" in (
        app_root / "bootstrap" / "container.py"
    ).read_text()
    assert "from .auth import AuthConfig" not in composition_source
    assert "request.app.state.container.platform.authenticate_token" in composition_source
    assert "from .application.platform.actor_context import bind_actor, reset_actor" in composition_source
    assert "actor_token = bind_actor(" in composition_source
    assert "reset_actor(actor_token)" in composition_source
    assert "bind_authenticated_user" not in composition_source
    assert "store.user = auth_result" not in composition_source


def test_http_routers_use_application_services_instead_of_global_store() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    routers_root = ROOT / "apps" / "api" / "app" / "interface" / "http" / "routers"
    router_sources = {
        path.name: path.read_text()
        for path in routers_root.glob("*.py")
        if path.name != "__init__.py"
    }
    dependency_source = (app_root / "interface" / "http" / "dependencies.py").read_text()

    for name, source in router_sources.items():
        assert "from ....store import store" not in source, name
        assert "from ...store import store" not in source, name
        assert "store." not in source, name
        assert "request.app.state" not in source, name
        assert "AuthService" not in source, name

    agent_source = router_sources["agent.py"]
    conversations_source = router_sources["conversations.py"]
    platform_source = router_sources["platform.py"]
    projects_source = router_sources["projects.py"]
    composition_source = (ROOT / "apps" / "api" / "app" / "composition.py").read_text()
    project_workspace_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "project_workspace.py"
    ).read_text()

    assert "AgentApp" in agent_source
    assert "AgentApp" in conversations_source
    assert "PlatformApp" in platform_source
    assert "PlatformApplicationError" in platform_source
    assert "ProjectWorkspaceApp" in projects_source
    assert "SystemImageApp" in projects_source
    for fragment in [
        "def get_agent_application(request: Request) -> AgentApplicationService:",
        "def get_platform_application(request: Request) -> PlatformApplicationService:",
        "def get_project_workspace_application(request: Request) -> ProjectWorkspaceApplicationService:",
        "def get_system_image_application(request: Request) -> SystemImageApplicationService:",
        "AgentApp = Annotated[AgentApplicationService, Depends(get_agent_application)]",
        "PlatformApp = Annotated[PlatformApplicationService, Depends(get_platform_application)]",
        "return request.app.state.container.agent",
        "return request.app.state.container.platform",
        "return request.app.state.container.project_workspace",
        "return request.app.state.container.system_image",
    ]:
        assert fragment in dependency_source
    assert "container = get_application_container()" in composition_source
    assert "app.state.container = container" in composition_source
    assert "from .store import store" not in composition_source
    assert ".list_knowledge_objects(" not in project_workspace_source
    assert ".get_system_image(" not in project_workspace_source
    assert ".get_knowledge_object(" not in project_workspace_source


def test_production_entrypoints_resolve_explicit_application_container() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    composition_source = (app_root / "composition.py").read_text()
    container_source = (app_root / "bootstrap" / "container.py").read_text()
    dependency_source = (app_root / "interface" / "http" / "dependencies.py").read_text()
    worker_source = (
        app_root
        / "infrastructure"
        / "workflow"
        / "agent_goal_workflow_worker.py"
    ).read_text()
    activity_source = (
        app_root / "application" / "agent" / "activities.py"
    ).read_text()
    store_source = (app_root / "store.py").read_text()

    assert "class ApplicationContainer" in container_source
    assert "container = get_application_container()" in composition_source
    assert "app.state.container = container" in composition_source
    assert "request.app.state.container." in dependency_source
    assert "get_application_container().agent_workflow_activities" in worker_source
    assert "from .store import store" not in composition_source
    assert "from ...store import store" not in worker_source
    assert "ApplicationStore" not in activity_source
    assert "infrastructure" not in activity_source
    assert "\nstore = ApplicationStore()" not in store_source
    assert "class RuntimeAssembly:" in store_source
    assert "class ApplicationRuntime:" in store_source
    assert "ApplicationRuntime(RuntimeAssembly)" not in store_source
    assert 'object.__setattr__(self, "_assembly", assembly or RuntimeAssembly())' in store_source
    assert "def get_application_store() -> ApplicationStore:" in store_source
    assert "class _LazyApplicationStoreProxy:" in store_source
    assert "from ..store import get_runtime_assembly" in container_source
    assert "get_application_runtime" not in container_source
    assert "get_application_store" not in container_source

    assembly_block = store_source.split("class RuntimeAssembly:", 1)[1].split(
        "class ApplicationRuntime:",
        1,
    )[0]
    assert "def get_welcome(" not in assembly_block
    assert "def update_settings(" not in assembly_block
    assert "def list_projects(" not in assembly_block


def test_application_container_does_not_expose_compatibility_runtime() -> None:
    container_source = (
        ROOT / "apps" / "api" / "app" / "bootstrap" / "container.py"
    ).read_text()
    dataclass_block = container_source.split("class ApplicationContainer:", 1)[1].split(
        "_container:", 1
    )[0]

    assert "legacy_store" not in dataclass_block
    assert "compatibility_store" not in dataclass_block
    assert "runtime:" not in dataclass_block
    for service_name in [
        "platform",
        "agent",
        "project_workspace",
        "system_image",
        "source_uploads",
        "governance",
        "readiness",
        "agent_workflow_activities",
    ]:
        assert f"{service_name}:" in dataclass_block


def test_project_http_commands_use_application_dtos_not_raw_dicts() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    projects_router_source = (
        app_root / "interface" / "http" / "routers" / "projects.py"
    ).read_text()
    project_models_source = (
        app_root / "application" / "platform" / "project_models.py"
    ).read_text()
    project_workspace_source = (
        app_root / "application" / "platform" / "project_workspace.py"
    ).read_text()

    assert "class ProjectCreateRequest(BaseModel)" in project_models_source
    assert "class VersionCreateRequest(BaseModel)" in project_models_source
    assert "ProjectCreateRequest" in projects_router_source
    assert "VersionCreateRequest" in projects_router_source
    assert "async def create_project(payload: ProjectCreateRequest" in projects_router_source
    assert "async def create_version(" in projects_router_source
    assert "payload: VersionCreateRequest" in projects_router_source
    assert "project_workspace: ProjectWorkspaceApp" in projects_router_source
    assert "async def create_project(self, payload: ProjectCreateRequest)" in project_workspace_source
    assert "async def create_version(self, project_id: str, payload: VersionCreateRequest)" in project_workspace_source
    for source in [projects_router_source, project_workspace_source]:
        assert "payload: dict[str, str]" not in source
        assert 'payload.get("name")' not in source


def test_agent_application_service_composes_subservices_not_store_facade() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    use_case_source = (app_root / "application" / "agent" / "use_cases.py").read_text()
    lifecycle_source = (app_root / "application" / "agent" / "lifecycle.py").read_text()

    for fragment in [
        "from ..platform.events import PlatformEventApplicationService",
        "self._conversations = conversations",
        "self._events = events",
        "self._goals = goals",
        "self._swarm = swarm",
        "return await self._goals.create_manual_goal(payload)",
        "goal = self._goals.get_goal(goal_id)",
        "self._conversations.get_conversation(goal.conversation_id)",
        "return self._goals.get_checkpoint(goal_id)",
        "self._events.stream_conversation_events(conversation_id, last_event_id)",
        "self._events.stream_goal_events(goal_id, last_event_id)",
        "self._events.stream_swarm_events(swarm_id, last_event_id)",
        "swarm = self._swarm.get_swarm(swarm_id)",
        "self._conversations.get_conversation(swarm.conversation_id)",
        "return await self._swarm.run_system_image_materialization_swarm(",
        "return await self._goals.interrupt_goal(goal_id)",
        "return await self._goals.resume_goal(goal_id)",
        "return await self._goals.add_feedback(goal_id, payload.feedback)",
    ]:
        assert fragment in use_case_source

    for fragment in ["def has_goal", "def get_goal", "def get_checkpoint"]:
        assert fragment in lifecycle_source

    for leaked_store_path in [
        "self._store",
        "AgentGoalLifecycleApplicationService(",
        "self._store.stream_events(",
        "self._store.stream_goal_events(",
        "self._store.stream_swarm_events(",
        "self._store.interrupt_agent_goal(",
        "self._store.resume_agent_goal(",
        "self._store.add_goal_feedback(",
        "PlatformEventApplicationService(store)",
        "store.agent_service",
        "store.agent_swarm_coordinator",
    ]:
        assert leaked_store_path not in use_case_source


def test_platform_application_service_composes_subservices_not_store_facade() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    use_case_source = (app_root / "application" / "platform" / "use_cases.py").read_text()

    for fragment in [
        "self._accounts = accounts",
        "self._audit_events = audit_events",
        "self._model_configurations = model_configurations",
        "self._top_level_content = top_level_content",
        "self._tool_invocations = tool_invocations",
        "return self._accounts.current_user()",
        "return self._model_configurations.get_settings()",
        "return self._top_level_content.get_build()",
        "return await self._tool_invocations.create_tool_invocation(payload)",
    ]:
        assert fragment in use_case_source

    for leaked_store_path in [
        "self._store",
        "return store",
        "AccountApplicationService(store)",
        "PlatformAuditApplicationService(store)",
        "ModelConfigurationApplicationService(store)",
        "TopLevelContentApplicationService(store)",
        "ToolInvocationApplicationService(store)",
    ]:
        assert leaked_store_path not in use_case_source


def test_project_workspace_read_models_live_in_platform_application_service() -> None:
    project_workspace_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "project_workspace.py"
    ).read_text()
    store_source = (ROOT / "apps" / "api" / "app" / "store.py").read_text()

    for fragment in [
        "class ProjectWorkspaceApplicationService",
        "read_model: ProjectWorkspaceReadPort",
        "authorization: ProjectWorkspaceAuthorizationPort",
        "tool_invocations: ProjectWorkspaceToolPort",
        "conversations: ProjectWorkspaceConversationPort",
        "self._read_model = read_model",
        "snapshot = self._workspace(project_id)",
        "ProjectWorkspaceResponse(",
        "def select_project_workspace_us",
        "release_candidates",
        "pack_candidates",
        "evidence_candidates",
        "def current_task_context",
        "def current_quality_profile",
        "def current_quality_asset_pack",
        "def current_release_decision",
        "def quality_loop_state",
        "lane_status_by_key",
        "def get_workspace_data",
        "def get_run_detail",
        "def get_approval_detail",
        "def get_release_readiness",
    ]:
        assert fragment in project_workspace_source
    for forbidden_fragment in [
        "self._store",
        "ApplicationStore",
        "ProjectReadModelRefreshApplicationService",
        "refresh_project(",
    ]:
        assert forbidden_fragment not in project_workspace_source

    for method_name, delegated_call, next_method in [
        ("get_project_workspace", ".get_project_workspace(project_id)", "list_knowledge_objects"),
        ("get_run_detail", ".get_run_detail(project_id, run_id)", "get_approval_detail"),
        ("get_approval_detail", ".get_approval_detail(project_id, approval_id)", "get_release_readiness"),
        ("get_release_readiness", ".get_release_readiness(project_id)", "create_version"),
        ("get_workspace_data", ".get_workspace_data(project_id, us_id)", "_resolve_conversation_scope"),
    ]:
        method_block = store_source.split(f"def {method_name}", 1)[1].split(f"\n    def {next_method}", 1)[0]
        assert "self.project_workspace." in method_block
        assert delegated_call in method_block
        for leaked_rule in [
            "ProjectWorkspaceResponse(",
            "release_candidates",
            "pack_candidates",
            "evidence_candidates",
            "lane_status_by_key",
            "QualityLoopState(",
            "run_details[run_id]",
            "approval_details[approval_id]",
            "release_readiness[version.id]",
        ]:
            assert leaked_rule not in method_block

    for removed_facade in [
        "def _project_workspace_app",
        "def _select_project_workspace_us",
        "def _current_task_context",
        "def _current_quality_profile",
        "def _current_quality_asset_pack",
        "def _current_release_decision",
        "def _quality_loop_state",
    ]:
        assert removed_facade not in store_source
    assert "self.project_workspace = ProjectWorkspaceApplicationService(" in store_source
    assert "read_model=self.project_workspace_read_model" in store_source
    assert "authorization=self.project_access" in store_source
    assert "tool_invocations=self.tool_invocations_app" in store_source
    assert "conversations=self.conversation_management" in store_source
    assert "ProjectReadModelRefreshApplicationService(store)" not in project_workspace_source


def test_project_access_application_depends_on_explicit_authorization_ports() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    source = (app_root / "application" / "platform" / "project_access.py").read_text()

    assert "ProjectAccessReadPort" in source
    assert "actor_provider" in source
    assert "self._store" not in source
    assert "ApplicationStore" not in source


def test_project_access_read_model_is_postgresql_backed_infrastructure() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    source = (
        app_root / "infrastructure" / "platform" / "project_access_read_model.py"
    ).read_text()

    assert "SQLAlchemyProjectAccessReadModel" in source
    assert "ProjectRecord" in source
    assert "ConversationRecord" in source
    assert "ToolInvocationRecord" in source
    assert "ApplicationStore" not in source


def test_project_read_model_refresh_lives_in_platform_application_service() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    store_source = (app_root / "store.py").read_text()
    refresh_source = (app_root / "application" / "platform" / "read_model_refresh.py").read_text()
    port_source = (
        app_root / "application" / "platform" / "read_model_ports.py"
    ).read_text()
    projection_source = (
        app_root / "infrastructure" / "platform" / "read_model_projection.py"
    ).read_text()
    project_workspace_source = (
        app_root / "application" / "platform" / "project_workspace.py"
    ).read_text()
    ingestion_projection_source = (
        app_root / "infrastructure" / "system_image" / "ingestion_projection.py"
    ).read_text()
    platform_init_source = (app_root / "application" / "platform" / "__init__.py").read_text()

    assert "class ProjectReadModelRefreshApplicationService" in refresh_source
    assert "def refresh_project" in refresh_source
    assert "ProjectReadModelProjectionPort" in refresh_source
    assert "self._projection.refresh_project(project_id)" in refresh_source
    assert "_refresh_project_read_models(" not in refresh_source
    assert "ApplicationStore" not in refresh_source
    assert "project_repository" not in refresh_source
    assert "quality_loop_repository" not in refresh_source
    assert "system_image_repository" not in refresh_source
    assert "class ProjectReadModelProjectionPort(Protocol)" in port_source
    assert "def refresh_project(self, project_id: str)" in port_source
    assert "class CompatibilityProjectReadModelProjection" in projection_source
    assert "class RepositoryBackedProjectReadModelProjection" in projection_source
    assert "class ProjectReadModelProjectionState" in projection_source
    assert "class ProjectReadModelProjectionAdapters" in projection_source
    for fragment in [
        "project_repository = self._adapters.project_repository",
        "quality_loop_repository = self._adapters.quality_loop_repository",
        "system_image_repository = self._adapters.system_image_repository",
        "project_repository.load_projects()",
        "project_repository.load_versions()",
        "system_image_repository.load_raw_assets()",
        "system_image_repository.load_task_contexts()",
        "quality_loop_repository.load_quality_asset_packs()",
        "quality_loop_repository.load_release_decisions()",
        "state.release_readiness.update(",
    ]:
        assert fragment in projection_source
    for forbidden_fragment in [
        "ApplicationStore",
        "self._store",
        "store.project_repository",
        "store.quality_loop_repository",
        "store.system_image_repository",
    ]:
        assert forbidden_fragment not in projection_source
    for forbidden_fragment in [
        "project_repository.load_raw_assets()",
        "project_repository.load_quality_asset_packs()",
        "project_repository.load_release_decisions()",
    ]:
        assert forbidden_fragment not in projection_source
    assert "ProjectReadModelRefreshApplicationService" in platform_init_source
    assert "ProjectReadModelProjectionPort" in platform_init_source
    assert "self.project_read_model_projection = RepositoryBackedProjectReadModelProjection()" in store_source
    assert "self.project_read_model_projection_state" not in store_source
    assert "ProjectReadModelProjectionAdapters(" not in store_source
    assert "self.project_read_model_refresh = ProjectReadModelRefreshApplicationService(" in store_source
    assert "self.project_read_model_projection" in store_source
    assert "self.project_read_model_refresh.refresh_project(project_id)" in store_source
    assert "ProjectReadModelRefreshApplicationService(self).refresh_project(project_id)" not in store_source
    for forbidden_fragment in [
        "read_model_refresh",
        "ProjectReadModelRefreshApplicationService",
        "self._store",
    ]:
        assert forbidden_fragment not in project_workspace_source
    assert "self._read_model_refresh = read_model_refresh" in ingestion_projection_source
    assert "ProjectReadModelRefreshApplicationService(store)" not in ingestion_projection_source
    for forbidden_ingestion_dependency in [
        "ApplicationStore",
        "self._store",
        "store: Any",
    ]:
        assert forbidden_ingestion_dependency not in ingestion_projection_source
    assert "self._mutation_guard = mutation_guard" in ingestion_projection_source
    assert "return self._mutation_guard(project_id)" in ingestion_projection_source
    assert "SQLAlchemyProjectMutationLock(" in store_source
    assert "self.system_image_ingestion_lock.acquire" in store_source
    for fragment in [
        "self.system_image_repository = SystemImageRepository()",
        "self.quality_loop_repository = QualityLoopRepository()",
        "self.project_read_model_projection = RepositoryBackedProjectReadModelProjection()",
        "self.project_read_model_refresh = ProjectReadModelRefreshApplicationService(",
    ]:
        assert fragment in store_source
    for forbidden_fragment in [
        "self.raw_assets = defaultdict(list, self.project_repository.load_raw_assets())",
        "self.quality_asset_packs = self.project_repository.load_quality_asset_packs()",
        "self.release_decisions = self.project_repository.load_release_decisions()",
    ]:
        assert forbidden_fragment not in store_source

    for path in (app_root / "application").rglob("*.py"):
        source = path.read_text()
        assert "_refresh_project_read_models(" not in source, str(path)


def test_production_composition_does_not_hydrate_process_local_project_state() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    store_source = (app_root / "store.py").read_text()
    project_loader_source = (
        app_root / "application" / "platform" / "project_state_loader.py"
    ).read_text()
    hydration_source = (
        app_root / "application" / "platform" / "projection_hydration.py"
    ).read_text()
    hydration_ports_source = (
        app_root / "application" / "platform" / "state_hydration_ports.py"
    ).read_text()
    projection_source = (
        app_root / "infrastructure" / "platform" / "read_model_projection.py"
    ).read_text()
    platform_init_source = (app_root / "application" / "platform" / "__init__.py").read_text()

    assert "class ProjectStateLoaderApplicationService" in project_loader_source
    assert "ProjectStateHydrationPort" in project_loader_source
    assert "self._hydration.hydrate_all()" in project_loader_source
    assert "ApplicationStore" not in project_loader_source
    assert "store: Any" not in project_loader_source
    assert "self._store" not in project_loader_source
    assert "class ProjectStateHydrationPort" in hydration_ports_source
    assert "def replace_projection(" in hydration_source
    assert "target.clear()" in hydration_source
    assert "target.update(source)" in hydration_source
    assert "def hydrate_all(self) -> None" in projection_source
    assert "from ...application.platform.projection_hydration import replace_projection" in projection_source
    for replaced_shared_projection in [
        "store.projects =",
        "store.versions =",
        "store.us_items =",
        "store.asset_lanes =",
        "store.knowledge_objects =",
        "store.raw_assets =",
        "store.raw_asset_chunks =",
        "store.baselines =",
        "store.context_relationships =",
        "store.context_object_overlays =",
        "store.quality_metric_snapshots =",
        "store.embedding_records =",
        "store.retrieval_runs =",
        "store.rerank_records =",
        "store.task_contexts =",
        "store.quality_profiles =",
    ]:
        assert replaced_shared_projection not in projection_source
    assert "def load(self) -> None" in project_loader_source
    for fragment in [
        "project_repository.load_projects()",
        "project_repository.load_versions()",
        "quality_loop_repository.list_us_items(",
        "quality_loop_repository.load_runs()",
        "quality_loop_repository.load_quality_asset_packs()",
        "quality_loop_repository.load_release_decisions()",
        "quality_loop_repository.load_merged_resolutions()",
        "system_image_repository.load_knowledge_objects()",
        "system_image_repository.load_raw_assets()",
        "system_image_repository.load_task_contexts()",
        "system_image_repository.load_quality_profiles()",
    ]:
        assert fragment in projection_source
    assert "ProjectStateLoaderApplicationService" in platform_init_source
    assert "ProjectStateLoaderApplicationService" not in store_source
    assert "def _load_persisted_project_state" not in store_source
    assert "self.project_state_loader" not in store_source
    assert "RepositoryBackedProjectReadModelProjection()" in store_source
    for removed_projection in [
        "self.projects:",
        "self.versions:",
        "self.us_items:",
        "self.asset_lanes:",
        "self.quality_asset_packs:",
        "self.raw_assets:",
        "self.task_contexts:",
        "self.release_readiness:",
    ]:
        assert removed_projection not in store_source


def test_agent_runtime_facts_do_not_use_process_local_hydration() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    store_source = (app_root / "store.py").read_text()
    hydration_ports_source = (
        app_root / "application" / "platform" / "state_hydration_ports.py"
    ).read_text()
    platform_init_source = (app_root / "application" / "platform" / "__init__.py").read_text()

    assert not (app_root / "application" / "platform" / "runtime_state_loader.py").exists()
    assert not (app_root / "infrastructure" / "platform" / "runtime_state_hydration.py").exists()
    assert "RuntimeStateHydrationPort" not in hydration_ports_source
    assert "RuntimeStateLoaderApplicationService" not in platform_init_source
    for forbidden_fragment in [
        "self.conversations:",
        "self.conversation_index:",
        "AgentCompatibilityProjectionSink",
        "CompatibilityRuntimeStateHydration",
        "RuntimeStateHydrationProjection",
        "RuntimeStateHydrationAdapters",
        "runtime_state_loader",
        "_load_persisted_runtime_state",
    ]:
        assert forbidden_fragment not in store_source
    for durable_platform_fact in [
        "tool_invocations=self.tool_invocations,",
        "audit_events=self.audit_events,",
    ]:
        assert durable_platform_fact not in store_source


def test_conversation_links_have_durable_repository_and_migration() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    db_models_source = (
        app_root / "infrastructure" / "persistence" / "db_models.py"
    ).read_text()
    repository_source = (
        app_root
        / "infrastructure"
        / "persistence"
        / "conversation_repository.py"
    ).read_text()
    migration_source = (
        ROOT
        / "apps"
        / "api"
        / "migrations"
        / "versions"
        / "0022_conversation_links.py"
    ).read_text()

    assert "class ConversationLinkRecord(Base)" in db_models_source
    assert '__tablename__ = "conversation_links"' in db_models_source
    assert "def load_conversation_links" in repository_source
    assert "def upsert_conversation_link" in repository_source
    assert 'revision = "0022_conversation_links"' in migration_source
    assert 'down_revision = "0021_swarm_runtime_controls"' in migration_source
    assert 'op.create_table(\n        "conversation_links"' in migration_source


def test_system_image_read_models_live_in_system_image_application_service() -> None:
    system_image_source = (
        ROOT / "apps" / "api" / "app" / "application" / "system_image" / "use_cases.py"
    ).read_text()
    knowledge_queries_source = (
        ROOT / "apps" / "api" / "app" / "application" / "system_image" / "knowledge_queries.py"
    ).read_text()
    snapshots_source = (
        ROOT / "apps" / "api" / "app" / "application" / "system_image" / "snapshots.py"
    ).read_text()
    memory_context_source = (
        ROOT / "apps" / "api" / "app" / "application" / "system_image" / "memory_context.py"
    ).read_text()
    retrieval_traces_source = (
        ROOT / "apps" / "api" / "app" / "application" / "system_image" / "retrieval_traces.py"
    ).read_text()
    system_image_init = (
        ROOT / "apps" / "api" / "app" / "application" / "system_image" / "__init__.py"
    ).read_text()
    store_source = (ROOT / "apps" / "api" / "app" / "store.py").read_text()

    for fragment in [
        "class SystemImageApplicationService",
        "SystemImageKnowledgeQueryApplicationService",
        "self.knowledge_queries = SystemImageKnowledgeQueryApplicationService(workspace)",
        "SystemImageSnapshotQueryApplicationService",
        "self.snapshots = SystemImageSnapshotQueryApplicationService(operations)",
        "def list_knowledge_objects",
        "return self.knowledge_queries.list_knowledge_objects(project_id)",
        "def get_knowledge_object",
        "return self.knowledge_queries.get_knowledge_object(project_id, object_id)",
        "def get_system_image",
        "return self.snapshots.get_system_image(project_id)",
    ]:
        assert fragment in system_image_source
    for leaked_rule in [
        "ProjectReadModelRefreshApplicationService",
        "self.read_model_refresh.refresh_project(project_id)",
        "return self._store.knowledge_objects[project_id]",
        "return next(item for item in self._store.knowledge_objects[project_id] if item.id == object_id)",
        "self._store.system_image_service.get(project_id)",
    ]:
        assert leaked_rule not in system_image_source
    for fragment in [
        "class SystemImageKnowledgeQueryApplicationService",
        "SystemImageWorkspacePort",
        "self._workspace.refresh_project_read_model(project_id)",
        "return self._workspace.list_knowledge_objects(project_id)",
        "for item in self._workspace.list_knowledge_objects(project_id)",
    ]:
        assert fragment in knowledge_queries_source
    assert "SystemImageKnowledgeQueryApplicationService" in system_image_init
    assert "SystemImageSnapshotQueryApplicationService" in system_image_init
    assert "SystemImageMemoryContextApplicationService" in system_image_init
    assert "SystemImageRetrievalTraceApplicationService" in system_image_init
    assert '"SystemImageKnowledgeQueryApplicationService": ".knowledge_queries"' in system_image_init
    assert '"SystemImageSnapshotQueryApplicationService": ".snapshots"' in system_image_init
    assert '"SystemImageMemoryContextApplicationService": ".memory_context"' in system_image_init
    assert '"SystemImageRetrievalTraceApplicationService": ".retrieval_traces"' in system_image_init
    assert "self._store._refresh_project_read_models(project_id)" not in system_image_source
    for fragment in [
        "class SystemImageSnapshotQueryApplicationService",
        "def get_system_image",
        "return self._operations.get(project_id)",
    ]:
        assert fragment in snapshots_source
    for fragment in [
        "class SystemImageMemoryContextApplicationService",
        "def context_sections",
        "def long_term_project_refs",
        "self._workspace.list_baselines(project_id)",
        "self._workspace.list_raw_assets(project_id)",
        "self._workspace.list_knowledge_objects(project_id)",
        "self._workspace.list_context_relationships(project_id)",
        "self._workspace.list_quality_metric_snapshots(project_id)",
    ]:
        assert fragment in memory_context_source
    for fragment in [
        "class SystemImageRetrievalTraceApplicationService",
        "def record_agent_memory_retrieval",
        "RetrievalRun(",
        "self._workspace.append_retrieval_run(project_id, retrieval_run)",
        "self._persistence.persist(project_id)",
        "def _retrieval_baseline_id",
        "def _retrieval_strategy",
        "def _ready_embedding_record_ids",
        "def _latest_rerank_record_id",
        "def _retrieval_fallback_used",
    ]:
        assert fragment in retrieval_traces_source

    for method_name, delegated_call, next_method in [
        ("list_knowledge_objects", ".list_knowledge_objects(project_id)", "get_knowledge_object"),
        ("get_knowledge_object", ".get_knowledge_object(project_id, object_id)", "get_system_image"),
        ("get_system_image", ".get_system_image(project_id)", "get_run_detail"),
    ]:
        method_block = store_source.split(f"def {method_name}", 1)[1].split(f"\n    def {next_method}", 1)[0]
        assert "self.system_image_app." in method_block
        assert delegated_call in method_block
        for leaked_rule in [
            "_refresh_project_read_models(project_id)",
            "knowledge_objects[project_id]",
            "system_image_service.get(project_id)",
        ]:
            assert leaked_rule not in method_block
    assert "self.system_image_workspace = SQLAlchemySystemImageWorkspace(" in store_source
    assert "require_live_model_routes=current_runtime_profile().production_like" in store_source
    assert "self.system_image_app = SystemImageApplicationService(" in store_source
    assert "self.system_image_workspace," in store_source
    assert "self.system_image_service," in store_source
    assert "def _system_image_app" not in store_source


def test_system_image_source_binding_use_cases_live_in_source_application_service() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    use_case_source = (app_root / "application" / "system_image" / "use_cases.py").read_text()
    source_bindings_source = (
        app_root / "application" / "system_image" / "source_bindings.py"
    ).read_text()
    system_image_init = (app_root / "application" / "system_image" / "__init__.py").read_text()

    for fragment in [
        "class SystemImageSourceBindingApplicationService",
        "def has_project",
        "def normalize_source_specs",
        "def source_binding_incomplete",
        "def missing_source_types",
        "def register_sources",
        "def ingest_sources",
        "self._workspace.has_project(project_id)",
        "self._operations.source_ingestion.normalize_specs(payload)",
        "self._operations.source_binding_incomplete(project_id)",
        "self._operations.missing_source_types(project_id)",
        "self._operations.register_sources(",
        "self._operations.ingest_sources(project_id)",
    ]:
        assert fragment in source_bindings_source

    for fragment in [
        "SystemImageSourceBindingApplicationService",
        "self.source_bindings = SystemImageSourceBindingApplicationService(",
        "workspace,",
        "operations,",
        "return self.source_bindings.has_project(project_id)",
        "return self.source_bindings.normalize_source_specs(payload)",
        "return self.source_bindings.source_binding_incomplete(project_id)",
        "return self.source_bindings.missing_source_types(project_id)",
        "return self.source_bindings.register_sources(",
        "return self.source_bindings.ingest_sources(project_id)",
    ]:
        assert fragment in use_case_source

    for leaked_fragment in [
        "project_id in self._store.projects",
        "self._store.system_image_service.source_ingestion",
        "self._store.system_image_service.source_binding_incomplete",
        "self._store.system_image_service.missing_source_types",
        "self._store.system_image_service.register_sources",
        "self._store.system_image_service.ingest_sources",
    ]:
        assert leaked_fragment not in use_case_source

    assert "SystemImageSourceBindingApplicationService" in system_image_init
    assert '"SystemImageSourceBindingApplicationService": ".source_bindings"' in system_image_init


def test_system_image_lifecycle_use_cases_live_in_lifecycle_application_service() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    use_case_source = (app_root / "application" / "system_image" / "use_cases.py").read_text()
    lifecycle_source = (app_root / "application" / "system_image" / "lifecycle.py").read_text()
    system_image_init = (app_root / "application" / "system_image" / "__init__.py").read_text()

    for fragment in [
        "class SystemImageLifecycleApplicationService",
        "async def materialize_context",
        "async def initialize_baseline",
        "await self._operations.materialize_context(project_id)",
        "await self._operations.initialize_baseline(project_id)",
    ]:
        assert fragment in lifecycle_source

    for fragment in [
        "SystemImageLifecycleApplicationService",
        "self.lifecycle = SystemImageLifecycleApplicationService(operations)",
        "return await self.lifecycle.materialize_context(project_id)",
        "return await self.lifecycle.initialize_baseline(project_id)",
    ]:
        assert fragment in use_case_source

    for leaked_fragment in [
        "self._store.system_image_service.materialize_context",
        "self._store.system_image_service.initialize_baseline",
    ]:
        assert leaked_fragment not in use_case_source

    assert "SystemImageLifecycleApplicationService" in system_image_init
    assert '"SystemImageLifecycleApplicationService": ".lifecycle"' in system_image_init


def test_quality_loop_current_context_queries_live_in_quality_loop_application_service() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    query_source = (app_root / "application" / "quality_loop" / "context_queries.py").read_text()
    use_case_source = (app_root / "application" / "quality_loop" / "use_cases.py").read_text()
    project_version_source = (app_root / "application" / "quality_loop" / "project_versions.py").read_text()
    asset_pack_source = (app_root / "application" / "quality_loop" / "asset_packs.py").read_text()
    quality_loop_init = (app_root / "application" / "quality_loop" / "__init__.py").read_text()
    ports_source = (app_root / "application" / "quality_loop" / "ports.py").read_text()
    adapter_source = (
        app_root
        / "infrastructure"
        / "quality_loop"
        / "application_ports.py"
    ).read_text()
    durable_adapter_source = (
        app_root
        / "infrastructure"
        / "quality_loop"
        / "sqlalchemy_workspaces.py"
    ).read_text()
    store_source = (app_root / "store.py").read_text()
    agent_adapter_source = (
        app_root
        / "infrastructure"
        / "agent"
        / "application_ports.py"
    ).read_text()

    for fragment in [
        "class QualityLoopContextQueryApplicationService",
        "def current_task_context",
        "def current_quality_profile",
        "def current_quality_asset_pack",
        "def planner_quality_state",
        "QualityLoopContextWorkspacePort",
        "self._workspace.list_task_contexts(project_id)",
        "self._workspace.list_quality_profiles(project_id)",
        "self._workspace.get_quality_asset_pack(project_id, us_id)",
        "self._workspace.list_quality_asset_packs(project_id)",
        "self._workspace.list_us_items(resolved_project_id)",
        "self._workspace.project_id_for_us(resolved_us_id)",
        "self._workspace.list_asset_lanes(resolved_us_id)",
    ]:
        assert fragment in query_source
    for leaked_dependency in [
        "ApplicationStore",
        "self._store",
        "project_repository",
        "quality_loop_repository",
    ]:
        assert leaked_dependency not in query_source

    for fragment in [
        "context_queries: QualityLoopContextQueryApplicationService",
        "self.context_queries = context_queries",
    ]:
        assert fragment in use_case_source

    for fragment in [
        "QualityLoopContextReadPort",
        "context_queries: QualityLoopContextReadPort",
        "self.context_queries = context_queries",
        "self.context_queries.current_task_context(project_id, item_decision.us_id)",
        "self.context_queries.current_quality_profile(project_id, item_decision.us_id)",
    ]:
        assert fragment in project_version_source

    for fragment in [
        "QualityLoopContextQueryApplicationService",
        "self._workspace.get_quality_asset_pack(project_id, us_id)",
        "self._context_queries.current_task_context(project_id, us_id)",
    ]:
        assert fragment in asset_pack_source

    for leaked_private_call in [
        "_current_task_context(",
        "_current_quality_profile(",
        "_current_quality_asset_pack(",
    ]:
        assert leaked_private_call not in use_case_source
        assert leaked_private_call not in project_version_source

    assert "QualityLoopContextQueryApplicationService" in quality_loop_init
    assert '"QualityLoopContextQueryApplicationService": ".context_queries"' in quality_loop_init
    assert '"QualityLoopContextWorkspacePort": ".ports"' in quality_loop_init
    assert "class QualityLoopContextWorkspacePort(Protocol)" in ports_source
    assert "class LegacyQualityLoopContextWorkspace" in adapter_source
    assert "self._state.task_contexts.get(project_id, [])" in adapter_source
    assert "self._state.quality_profiles.get(project_id, [])" in adapter_source
    assert "class SQLAlchemyQualityLoopContextWorkspace" in durable_adapter_source
    assert "self._system_image.list_task_contexts(project_id)" in durable_adapter_source
    assert "self._quality_loop.list_quality_asset_packs(project_id)" in durable_adapter_source
    assert "self.quality_loop_context_workspace = SQLAlchemyQualityLoopContextWorkspace(" in store_source
    assert "self.quality_loop_context_workspace = LegacyQualityLoopContextWorkspace(" not in store_source
    assert "LegacyQualityLoopContextWorkspace(store)" not in agent_adapter_source
    assert "quality_state=runtime.quality_state" in agent_adapter_source
    assert "self.quality_loop_context_queries.planner_quality_state(" in store_source


def test_quality_loop_scope_queries_live_in_quality_loop_application_service() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    query_source = (app_root / "application" / "quality_loop" / "scope_queries.py").read_text()
    use_case_source = (app_root / "application" / "quality_loop" / "use_cases.py").read_text()
    quality_loop_init = (app_root / "application" / "quality_loop" / "__init__.py").read_text()
    ports_source = (app_root / "application" / "quality_loop" / "ports.py").read_text()
    adapter_source = (
        app_root
        / "infrastructure"
        / "quality_loop"
        / "application_ports.py"
    ).read_text()
    durable_adapter_source = (
        app_root
        / "infrastructure"
        / "quality_loop"
        / "sqlalchemy_workspaces.py"
    ).read_text()
    store_source = (app_root / "store.py").read_text()

    for fragment in [
        "class QualityLoopScopeQueryApplicationService",
        "def resolve_scope",
        "def resolve_failure_scope",
        "def query_keys_for",
        "QualityLoopScopeWorkspacePort",
        "self._workspace.conversation_scope(",
        "self._workspace.project_id_for_us(us_id)",
        "self._workspace.project_id_for_run(run_id)",
        "self._workspace.list_run_details(project_id)",
        "self._workspace.us_id_for_run_evidence(project_id, run.id)",
        "if project_id and project_id != owner_project_id:",
        "if owner_project_id is None or owner_project_id != project_id:",
        "[\"conversation\", invocation.conversation_id]",
    ]:
        assert fragment in query_source
    for leaked_dependency in [
        "ApplicationStore",
        "self._store",
        "project_repository",
        "quality_loop_repository",
    ]:
        assert leaked_dependency not in query_source

    for fragment in [
        "scope_queries: QualityLoopScopeQueryApplicationService",
        "self.scope_queries = scope_queries",
        "return self.scope_queries.resolve_scope(invocation)",
        "return self.scope_queries.resolve_failure_scope(invocation)",
        "return self.scope_queries.query_keys_for(invocation, project_id, us_id)",
    ]:
        assert fragment in use_case_source

    scope_block = use_case_source.split("def resolve_scope", 1)[1].split("def resolve_failure_scope", 1)[0]
    failure_scope_block = use_case_source.split("def resolve_failure_scope", 1)[1].split("def query_keys_for", 1)[0]
    query_key_block = use_case_source.split("def resolve_failure_scope", 1)[1].split("def query_keys_for", 1)[1].split(
        "def _active_or_create_version", 1
    )[0]
    delegated_scope_blocks = "\n".join([scope_block, failure_scope_block, query_key_block])
    for leaked_scope_rule in [
        "for candidate_project_id, items in self._store.us_items.items()",
        "for candidate_project_id, runs in self._store.runs.items()",
        "self._store.execution_evidence.get(project_id, [])",
        "self._store.conversations.get(invocation.conversation_id or \"\")",
    ]:
        assert leaked_scope_rule not in delegated_scope_blocks

    assert "QualityLoopScopeQueryApplicationService" in quality_loop_init
    assert '"QualityLoopScopeQueryApplicationService": ".scope_queries"' in quality_loop_init
    assert '"QualityLoopConversationScope": ".ports"' in quality_loop_init
    assert '"QualityLoopScopeWorkspacePort": ".ports"' in quality_loop_init
    assert "class QualityLoopConversationScope:" in ports_source
    assert "class QualityLoopScopeWorkspacePort(Protocol)" in ports_source
    assert "class LegacyQualityLoopScopeWorkspace" in adapter_source
    assert "self._state.conversations.get(conversation_id)" in adapter_source
    assert "for project_id, items in self._state.us_items.items()" in adapter_source
    assert "for project_id, runs in self._state.runs.items()" in adapter_source
    assert "self._state.execution_evidence.get(project_id, [])" in adapter_source
    assert "class SQLAlchemyQualityLoopScopeWorkspace" in durable_adapter_source
    assert "self._conversations.get_conversation(conversation_id)" in durable_adapter_source
    assert "self._quality_loop.project_id_for_run(run_id)" in durable_adapter_source
    assert "self.quality_loop_scope_workspace = SQLAlchemyQualityLoopScopeWorkspace(" in store_source
    assert "self.quality_loop_scope_workspace = LegacyQualityLoopScopeWorkspace(" not in store_source
    assert "self.quality_loop_scope_queries = QualityLoopScopeQueryApplicationService(" in store_source


def test_quality_loop_version_context_lives_in_application_service() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    version_context_source = (app_root / "application" / "quality_loop" / "version_context.py").read_text()
    project_version_source = (app_root / "application" / "quality_loop" / "project_versions.py").read_text()
    use_case_source = (app_root / "application" / "quality_loop" / "use_cases.py").read_text()
    quality_loop_init = (app_root / "application" / "quality_loop" / "__init__.py").read_text()

    for fragment in [
        "class QualityLoopVersionContextApplicationService",
        "def active_or_create_version",
        "ProjectVersionWorkspacePort",
        "ProjectVersionApplicationService",
        "self._project_versions.active_or_create_quality_version(project_id)",
    ]:
        assert fragment in version_context_source
    for fragment in [
        "def active_or_create_quality_version",
        "unversioned_items = self._workspace.list_us_items(project_id)",
        'self.create_version_record(project_id, "Initial Quality Loop")',
        "self._workspace.save_us_items(",
    ]:
        assert fragment in project_version_source
    for leaked_dependency in [
        "ApplicationStore",
        "self._store",
        "project_repository",
    ]:
        assert leaked_dependency not in version_context_source

    for fragment in [
        "version_context: QualityLoopVersionContextApplicationService",
        "self.version_context = version_context",
    ]:
        assert fragment in use_case_source
    for fragment in [
        "self.quality_loop_version_context = (",
        "QualityLoopVersionContextApplicationService(",
        "self.project_version_workspace,",
        "self.project_versions,",
    ]:
        assert fragment in (app_root / "store.py").read_text()

    quality_loop_block = use_case_source.split("class QualityLoopApplicationService", 1)[1]
    for leaked_version_rule in [
        "def _active_or_create_version",
        'ProjectVersionApplicationService(self._store).create_version_record(project_id, "Initial Quality Loop")',
        "versions = self._store.versions.get(project_id, [])",
    ]:
        assert leaked_version_rule not in quality_loop_block

    assert "QualityLoopVersionContextApplicationService" in quality_loop_init
    assert '"QualityLoopVersionContextApplicationService": ".version_context"' in quality_loop_init
    assert '"ProjectVersionApplicationService": ".project_versions"' in quality_loop_init
    assert '"ProjectVersionApplicationError": ".project_versions"' in quality_loop_init
    assert '"ProjectVersionUseCaseResult": ".project_versions"' in quality_loop_init
    assert '"ProjectVersionWorkspacePort": ".ports"' in quality_loop_init
    assert '"QualityLoopContextReadPort": ".ports"' in quality_loop_init


def test_project_version_use_cases_depend_on_ports_not_compatibility_store() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    application_source = (
        app_root / "application" / "quality_loop" / "project_versions.py"
    ).read_text()
    ports_source = (
        app_root / "application" / "quality_loop" / "ports.py"
    ).read_text()
    adapter_source = (
        app_root
        / "infrastructure"
        / "quality_loop"
        / "application_ports.py"
    ).read_text()
    runtime_source = (
        app_root / "application" / "platform" / "runtime.py"
    ).read_text()
    durable_adapter_source = (
        app_root
        / "infrastructure"
        / "quality_loop"
        / "sqlalchemy_workspaces.py"
    ).read_text()
    project_repository_source = (
        app_root
        / "infrastructure"
        / "persistence"
        / "project_repository.py"
    ).read_text()
    quality_loop_repository_source = (
        app_root
        / "infrastructure"
        / "persistence"
        / "quality_loop_repository.py"
    ).read_text()
    store_source = (app_root / "store.py").read_text()

    for fragment in [
        "ProjectVersionWorkspacePort",
        "QualityLoopContextReadPort",
        "SystemImageOperationsPort",
        "self._workspace.initialize_project(project)",
        "self._workspace.prepend_version(",
        "self._workspace.save_version(",
        "self._workspace.save_us_items(",
        "self._workspace.save_us_item(",
        "self._workspace.save_release_readiness(",
        "self._workspace.conversation_project_id(",
        "self._workspace.has_indexed_system_image_evidence(project_id)",
    ]:
        assert fragment in application_source
    for leaked_dependency in [
        "ApplicationStore",
        "self._store",
        "project_repository",
        "system_image_repository",
        "conversation_repository",
    ]:
        assert leaked_dependency not in application_source

    assert "class ProjectVersionWorkspacePort(Protocol)" in ports_source
    assert "class QualityLoopContextReadPort(Protocol)" in ports_source
    assert "class LegacyProjectVersionWorkspace" in adapter_source
    assert "ApplicationStore" not in adapter_source
    assert "self._store" not in adapter_source
    assert "QualityLoopProjectionState" in adapter_source
    assert "QualityLoopWorkspaceAdapters" in adapter_source
    assert "class SQLAlchemyProjectVersionWorkspace" in durable_adapter_source
    assert "self._projects.prepend_version(" in durable_adapter_source
    assert "self._projects.save_version(" in durable_adapter_source
    assert "self._quality_loop.upsert_us_items(" in durable_adapter_source
    assert "self._quality_loop.upsert_us_item(" in durable_adapter_source
    assert "def prepend_version(" in project_repository_source
    assert "def save_version(" in project_repository_source
    assert "def upsert_us_items(" in quality_loop_repository_source
    assert "project_versions=" not in runtime_source
    assert "ProjectVersionApplicationService(store)" not in runtime_source
    for fragment in [
        "self.project_version_workspace = SQLAlchemyProjectVersionWorkspace(",
        "self.project_versions = ProjectVersionApplicationService(",
        "self.project_version_workspace,",
        "self.system_image_app,",
        "self.quality_loop_context_queries,",
        "project_versions=self.project_versions,",
    ]:
        assert fragment in store_source
    assert "self.project_version_workspace = LegacyProjectVersionWorkspace(" not in store_source


def test_quality_asset_progress_lives_in_quality_loop_application_service() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    progress_source = (app_root / "application" / "quality_loop" / "asset_progress.py").read_text()
    use_case_source = (app_root / "application" / "quality_loop" / "use_cases.py").read_text()
    quality_steps_source = (app_root / "application" / "quality_loop" / "quality_steps.py").read_text()
    quality_loop_init = (app_root / "application" / "quality_loop" / "__init__.py").read_text()
    ports_source = (app_root / "application" / "quality_loop" / "ports.py").read_text()
    adapter_source = (
        app_root
        / "infrastructure"
        / "quality_loop"
        / "application_ports.py"
    ).read_text()
    durable_adapter_source = (
        app_root
        / "infrastructure"
        / "quality_loop"
        / "sqlalchemy_workspaces.py"
    ).read_text()
    repository_source = (
        app_root
        / "infrastructure"
        / "persistence"
        / "quality_loop_repository.py"
    ).read_text()
    store_source = (app_root / "store.py").read_text()

    for fragment in [
        "class QualityAssetProgressApplicationService",
        "QualityAssetProgressWorkspacePort",
        "def ensure_asset_lanes",
        "def update_lane",
        "def touch_us",
        "default_asset_lane_templates()",
        "matches_asset_lane(",
        "self._workspace.ensure_asset_lanes(project_id, us_id, missing)",
        "self._workspace.save_asset_lane(project_id, us_id, lane)",
        "self._workspace.get_us_item(project_id, us_id)",
        "self._workspace.save_us_item(",
    ]:
        assert fragment in progress_source
    for leaked_dependency in [
        "ApplicationStore",
        "self._store",
        "project_repository",
        "asset_lanes.get(",
        "us_items.get(",
    ]:
        assert leaked_dependency not in progress_source

    for fragment in [
        "asset_progress: QualityAssetProgressApplicationService",
        "self.asset_progress = asset_progress",
    ]:
        assert fragment in use_case_source

    for fragment in [
        "QualityAssetProgressApplicationService",
        "self.asset_progress.ensure_asset_lanes(project_id, us_id)",
        "self.asset_progress.update_lane(",
        "self.asset_progress.touch_us(",
    ]:
        assert fragment in quality_steps_source

    quality_loop_block = use_case_source.split("class QualityLoopApplicationService", 1)[1]
    for leaked_progress_rule in [
        "def _ensure_asset_lanes",
        "def _update_lane",
        "def _find_lane",
        "def _touch_us",
        "default_asset_lane_templates()",
        "matches_asset_lane(",
        "replace_asset_lanes(project_id, us_id, lanes)",
        "replace_us_items(project_id, version_id, updated_items)",
    ]:
        assert leaked_progress_rule not in quality_loop_block

    assert "QualityAssetProgressApplicationService" in quality_loop_init
    assert '"QualityAssetProgressApplicationService": ".asset_progress"' in quality_loop_init
    assert '"QualityAssetProgressWorkspacePort": ".ports"' in quality_loop_init
    assert "class QualityAssetProgressWorkspacePort(Protocol)" in ports_source
    assert "class LegacyQualityAssetProgressWorkspace" in adapter_source
    assert "self._state.asset_lanes.get(us_id, [])" in adapter_source
    assert "self._state.us_items.get(project_id, [])" in adapter_source
    assert "self._adapters.quality_loop_repository.ensure_asset_lanes(" in adapter_source
    assert "self._adapters.quality_loop_repository.upsert_asset_lane(" in adapter_source
    assert "self._adapters.quality_loop_repository.upsert_us_item_preserving_version(" in adapter_source
    assert "class SQLAlchemyQualityAssetProgressWorkspace" in durable_adapter_source
    assert "self._repository.upsert_asset_lane(" in durable_adapter_source
    assert "self._repository.upsert_us_item_preserving_version(" in durable_adapter_source
    assert "def ensure_asset_lanes(" in repository_source
    assert "def upsert_asset_lane(" in repository_source
    assert "def upsert_us_item_preserving_version(" in repository_source
    assert "self.quality_asset_progress_workspace = (" in store_source
    assert "SQLAlchemyQualityAssetProgressWorkspace(" in store_source
    assert "LegacyQualityAssetProgressWorkspace(" not in store_source
    assert "self.quality_asset_progress = QualityAssetProgressApplicationService(" in store_source


def test_quality_loop_release_decision_query_lives_in_quality_loop_application_service() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    query_source = (app_root / "application" / "quality_loop" / "release_decision_queries.py").read_text()
    governance_source = (app_root / "application" / "platform" / "governance.py").read_text()
    quality_loop_init = (app_root / "application" / "quality_loop" / "__init__.py").read_text()
    ports_source = (app_root / "application" / "quality_loop" / "ports.py").read_text()
    repository_source = (
        app_root
        / "infrastructure"
        / "persistence"
        / "quality_loop_repository.py"
    ).read_text()
    for fragment in [
        "class QualityLoopReleaseDecisionQueryApplicationService",
        "def current_release_decision",
        "QualityLoopReleaseDecisionReadPort",
        "self._reader.find_release_decision(",
    ]:
        assert fragment in query_source
    for leaked_dependency in [
        "ApplicationStore",
        "self._store",
        "release_decisions.values()",
        "release_decisions.get(",
    ]:
        assert leaked_dependency not in query_source

    for fragment in [
        "GovernanceWorkspacePort",
        "self._workspace.find_release_decision(project_id, us_id or None, version_id)",
    ]:
        assert fragment in governance_source
    assert "_current_release_decision(" not in governance_source
    assert "ApplicationStore" not in governance_source
    assert "self._store" not in governance_source

    assert "QualityLoopReleaseDecisionQueryApplicationService" in quality_loop_init
    assert '"QualityLoopReleaseDecisionQueryApplicationService": ".release_decision_queries"' in quality_loop_init
    assert '"QualityLoopReleaseDecisionReadPort": ".ports"' in quality_loop_init
    assert "class QualityLoopReleaseDecisionReadPort(Protocol)" in ports_source
    assert "def find_release_decision(" in repository_source
    assert "ReleaseDecisionRecord.project_id == project_id" in repository_source
    assert "ReleaseDecisionRecord.created_at.desc()" in repository_source


def test_platform_http_routes_call_application_service_not_store_directly() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    platform_router = app_root / "interface" / "http" / "routers" / "platform.py"
    dependencies = app_root / "interface" / "http" / "dependencies.py"
    source = platform_router.read_text()
    dependency_source = dependencies.read_text()
    assert "PlatformApp" in source
    assert "PlatformApplicationService" in dependency_source
    assert "request.app.state.container.platform" in dependency_source
    assert "from ....store import store" not in source
    assert "request.app.state" not in source
    assert ".create_tool_invocation(" in source
    assert ".list_audit_events(" in source


def test_platform_account_rules_live_in_account_application_service() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    root_auth_service = (app_root / "auth_service.py").read_text()
    platform_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "use_cases.py"
    ).read_text()
    accounts_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "accounts.py"
    ).read_text()
    account_ports_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "account_ports.py"
    ).read_text()
    account_adapter_source = (
        ROOT / "apps" / "api" / "app" / "infrastructure" / "platform" / "account_runtime.py"
    ).read_text()
    account_identity_source = (
        ROOT
        / "apps"
        / "api"
        / "app"
        / "infrastructure"
        / "platform"
        / "account_identity.py"
    ).read_text()
    bootstrap_source = (
        ROOT / "apps" / "api" / "app" / "bootstrap" / "container.py"
    ).read_text()
    errors_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "errors.py"
    ).read_text()
    auth_service_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "auth_service.py"
    ).read_text()
    platform_init = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "__init__.py"
    ).read_text()

    assert "from .application.platform.auth_service import *" in root_auth_service
    for compatibility_fragment in ["class AuthService", "class AuthServiceError", "SessionLocal", "ObjectStorage"]:
        assert compatibility_fragment not in root_auth_service
    assert "AccountApplicationService" in platform_source
    assert "self._accounts = accounts" in platform_source
    assert "def authenticate_token" in platform_source
    assert "self._accounts.authenticate_token(token)" in platform_source
    assert "AuthServiceError" not in platform_source
    assert "AuthService(" not in platform_source
    for method_name in [
        "current_user",
        "authenticate_token",
        "register_user",
        "login_user",
        "logout_user",
        "update_user_avatar",
        "get_user_avatar_content",
    ]:
        assert f"self._accounts.{method_name}" in platform_source

    for fragment in [
        "class AccountApplicationService",
        "CurrentUserProviderPort",
        "AccountIdentityPort",
        "AuthServiceError",
        "AuthSessionResponse",
        "authenticate_token",
        "update_avatar",
        "get_avatar_content",
        "PlatformApplicationError",
    ]:
        assert fragment in accounts_source
    assert "class CurrentUserProviderPort(Protocol)" in account_ports_source
    assert "class AccountIdentityPort(Protocol)" in account_ports_source
    assert "class CallableCurrentUserProvider" in account_adapter_source
    for forbidden_fragment in ["ApplicationStore", "self._store", "AuthService()"]:
        assert forbidden_fragment not in accounts_source
        assert forbidden_fragment not in account_ports_source
        assert forbidden_fragment not in account_adapter_source
    for composition_fragment in [
        "accounts=AccountApplicationService(",
        "current_user=CallableCurrentUserProvider(lambda: runtime.user)",
        "identities=SQLAlchemyAccountIdentityService()",
    ]:
        assert composition_fragment in bootstrap_source
    assert "bind_authenticated_user" not in accounts_source
    assert "class PlatformApplicationError" in errors_source
    for fragment in [
        "class AuthServiceError",
        "class AuthSessionResult",
        "class AvatarImageContent",
    ]:
        assert fragment in auth_service_source
    for forbidden_fragment in [
        "sqlalchemy",
        "SessionLocal",
        "UserIdentityRecord",
        "AccessSessionRecord",
        "ObjectStorage",
        "infrastructure",
    ]:
        assert forbidden_fragment not in auth_service_source
    for fragment in [
        "class SQLAlchemyAccountIdentityService",
        "SessionLocal",
        "UserIdentityRecord",
        "AccessSessionRecord",
        "ObjectStorage",
        "pbkdf2_hmac",
        "AVATAR_PRESET_IDS",
        "AuthServiceError",
        "AuthSessionResult",
        "AvatarImageContent",
    ]:
        assert fragment in account_identity_source
    assert "from ..persistence.database import SessionLocal" in account_identity_source
    assert "from ..storage.object_storage import ObjectStorage" in account_identity_source
    assert "SQLAlchemyAccountIdentityService" in bootstrap_source
    assert '"AuthService",' not in platform_init


def test_platform_account_contract_lives_in_application_layer() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    account_models_source = (app_root / "application" / "platform" / "account_models.py").read_text()
    models_source = (app_root / "models.py").read_text()
    http_auth_source = (app_root / "interface" / "http" / "auth.py").read_text()
    platform_router_source = (app_root / "interface" / "http" / "routers" / "platform.py").read_text()
    accounts_source = (app_root / "application" / "platform" / "accounts.py").read_text()
    auth_service_source = (app_root / "application" / "platform" / "auth_service.py").read_text()
    use_cases_source = (app_root / "application" / "platform" / "use_cases.py").read_text()
    store_source = (app_root / "store.py").read_text()
    platform_init = (app_root / "application" / "platform" / "__init__.py").read_text()

    for fragment in [
        "class UserProfile",
        "class AuthRegisterRequest",
        "class AuthLoginRequest",
        "class AuthSessionResponse",
        "class UserAvatarUpdateRequest",
    ]:
        assert fragment in account_models_source
        assert fragment not in models_source

    for exported_name in [
        "UserProfile",
        "AuthRegisterRequest",
        "AuthLoginRequest",
        "AuthSessionResponse",
        "UserAvatarUpdateRequest",
    ]:
        assert exported_name in models_source
        assert exported_name in platform_init

    assert "from .application.platform.account_models import" in models_source
    assert "from ...application.platform.account_models import UserProfile" in http_auth_source
    assert "from ....application.platform.account_models import AuthLoginRequest, AuthRegisterRequest, UserAvatarUpdateRequest" in platform_router_source
    assert "from .account_models import AuthLoginRequest, AuthRegisterRequest, AuthSessionResponse, UserAvatarUpdateRequest" in accounts_source
    assert "from .account_models import UserProfile" in auth_service_source
    assert "from .account_models import (" in use_cases_source
    assert "from .application.platform.account_models import UserProfile" in store_source
    assert "from .accounts import" not in platform_init


def test_platform_model_configuration_rules_live_in_application_service() -> None:
    store_source = (ROOT / "apps" / "api" / "app" / "store.py").read_text()
    platform_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "use_cases.py"
    ).read_text()
    model_config_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "model_configurations.py"
    ).read_text()
    grant_port_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "model_config_test_grants.py"
    ).read_text()
    grant_repository_source = (
        ROOT
        / "apps"
        / "api"
        / "app"
        / "infrastructure"
        / "persistence"
        / "model_config_test_grant_repository.py"
    ).read_text()
    model_config_ports_source = (
        ROOT
        / "apps"
        / "api"
        / "app"
        / "application"
        / "platform"
        / "model_configuration_ports.py"
    ).read_text()
    model_config_state_source = (
        ROOT
        / "apps"
        / "api"
        / "app"
        / "infrastructure"
        / "platform"
        / "model_configuration_state.py"
    ).read_text()

    assert "ModelConfigurationApplicationService" in platform_source
    assert "self._model_configurations = model_configurations" in platform_source
    for method_name in [
        "get_settings",
        "update_settings",
        "test_settings_connection",
        "test_model_config_connection",
        "create_model_config",
        "update_model_config",
        "list_model_configurations",
        "activate_model_config",
        "use_system_default_model_config",
    ]:
        assert f"self._model_configurations.{method_name}" in platform_source

    for fragment in [
        "class ModelConfigurationApplicationService",
        "ModelConfigurationStatePort",
        "ModelConfigurationRepositoryPort",
        "ModelConfigurationSecretPort",
        "ModelConfigurationGatewayPort",
        "ModelConfigurationTestGrantPort",
        "test_token",
        "secrets.token_urlsafe",
        "_model_config_fingerprint",
        "hashlib.sha256",
        "save_model_config",
        "save_model_route_selection",
        "active_source=\"custom\"",
        "active_source=\"system_default\"",
        "migrate_legacy_model_configs_if_needed",
        "get_custom_model_api_key",
    ]:
        assert fragment in model_config_source
    for port_name in [
        "ModelConfigurationStatePort",
        "ModelConfigurationRepositoryPort",
        "ModelConfigurationSecretPort",
        "ModelConfigurationGatewayPort",
    ]:
        assert f"class {port_name}(Protocol)" in model_config_ports_source
    assert "ModelConfigurationTestGrantPort = ModelConfigTestGrantRepositoryPort" in model_config_ports_source
    assert "class ProjectedModelConfigurationState" in model_config_state_source
    assert "class SQLAlchemyModelConfigurationState" in model_config_state_source
    assert "self._repository.load()" in model_config_state_source
    for forbidden_dependency in ["ApplicationStore", "self._store", "store: Any"]:
        assert forbidden_dependency not in model_config_source
        assert forbidden_dependency not in model_config_ports_source
    assert "model_config_test_tokens" not in model_config_source
    assert "class ModelConfigTestGrantRepositoryPort(Protocol)" in grant_port_source
    for fragment in [
        "class SQLAlchemyModelConfigTestGrantRepository",
        "hashlib.sha256",
        "delete(ModelConfigTestGrantRecord).where(",
        "ModelConfigTestGrantRecord.expires_at > consumed_at",
        "return result.rowcount == 1",
    ]:
        assert fragment in grant_repository_source

    for fragment in [
        "self.model_configuration_state = SQLAlchemyModelConfigurationState(",
        "self.settings_repository,",
        "self.llm,",
        "self.model_configuration = ModelConfigurationApplicationService(",
        "state=self.model_configuration_state",
        "repository=self.settings_repository",
        "secrets=self.settings_persistence",
        "gateway=self.llm",
        "test_grants=self.model_config_test_grant_repository",
        "self.model_configuration.migrate_legacy_model_configs_if_needed(",
        "custom_api_key_provider=self.model_configuration.get_custom_model_api_key",
    ]:
        assert fragment in store_source
    for obsolete_projection in [
        "self.model_configuration_state = ProjectedModelConfigurationState(",
        "self.settings = self.llm.build_settings(",
        "self.custom_model_api_keys_encrypted =",
    ]:
        assert obsolete_projection not in store_source
    assert "model_config_test_tokens" not in store_source

    def method_block(method_name: str) -> str:
        match = re.search(
            rf"\n    (?:async\s+)?def {method_name}\b.*?(?=\n    (?:async\s+)?def |\nclass |\Z)",
            store_source,
            re.S,
        )
        assert match is not None, method_name
        return match.group(0)

    for method_name in [
        "get_settings",
        "update_settings",
        "test_settings_connection",
        "test_model_config_connection",
        "create_model_config",
        "update_model_config",
        "list_model_configurations",
        "activate_model_config",
        "use_system_default_model_config",
    ]:
        block = method_block(method_name)
        assert "self.model_configuration." in block
        for leaked_rule in [
            "model_config_test_tokens[",
            "secrets.token_urlsafe",
            "hashlib.sha256",
            "json.dumps",
            "save_model_config(",
            "save_model_route_selection(",
            "ModelRouteSelection(",
            "SavedModelConfig(",
            "llm.build_settings(",
        ]:
            assert leaked_rule not in block

    for removed_facade in [
        "def _model_configuration_app",
        "def _current_model_profiles",
        "def _current_model_configurations",
        "def _settings_for_unsaved_model",
        "def _resolve_model_config_raw_api_key",
        "def _model_config_fingerprint",
        "def _migrate_legacy_model_configs_if_needed",
        "def _get_custom_model_api_key",
        "def _is_display_name_only_model_config_update",
    ]:
        assert removed_facade not in store_source


def test_platform_model_settings_contract_lives_in_application_layer() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    model_settings_source = (app_root / "application" / "platform" / "model_settings.py").read_text()
    models_source = (app_root / "models.py").read_text()
    platform_router_source = (app_root / "interface" / "http" / "routers" / "platform.py").read_text()
    model_config_source = (app_root / "application" / "platform" / "model_configurations.py").read_text()
    use_cases_source = (app_root / "application" / "platform" / "use_cases.py").read_text()
    store_source = (app_root / "store.py").read_text()
    repositories_source = (app_root / "infrastructure" / "persistence" / "repositories.py").read_text()
    settings_repository_source = (
        app_root / "infrastructure" / "persistence" / "settings_repository.py"
    ).read_text()
    settings_store_source = (app_root / "infrastructure" / "persistence" / "settings_store.py").read_text()
    llm_gateway_source = (app_root / "infrastructure" / "llm" / "gateway.py").read_text()
    agent_planner_source = (app_root / "application" / "agent" / "planner.py").read_text()

    for fragment in [
        "class StudioSettings",
        "class ModelProviderProfile",
        "class SavedModelConfig",
        "class ModelRouteConfigurations",
        "class ModelConfigTestRequest",
        "class StudioSettingsConnectionTestResponse",
        "ModelRoute = Literal",
    ]:
        assert fragment in model_settings_source

    for moved_class in [
        "ProviderStatus",
        "CustomModelConfig",
        "ModelProviderProfile",
        "SavedModelConfig",
        "ModelConfigTestRequest",
        "StudioSettings",
        "StudioSettingsPatch",
    ]:
        assert f"class {moved_class}" not in models_source
        assert moved_class in models_source

    assert "from ....application.platform.model_settings import" in platform_router_source
    assert "from .model_settings import" in model_config_source
    assert "from .model_settings import" in use_cases_source
    for source in [
        store_source,
        settings_repository_source,
        settings_store_source,
        llm_gateway_source,
        agent_planner_source,
    ]:
        assert "application.platform.model_settings" in source
    assert "application.platform.model_settings" not in repositories_source


def test_quality_loop_contract_models_live_in_quality_loop_application_layer() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    quality_models_source = (app_root / "application" / "quality_loop" / "quality_models.py").read_text()
    quality_init_source = (app_root / "application" / "quality_loop" / "__init__.py").read_text()
    models_source = (app_root / "models.py").read_text()
    use_cases_source = (app_root / "application" / "quality_loop" / "use_cases.py").read_text()
    project_version_source = (app_root / "application" / "quality_loop" / "project_versions.py").read_text()
    store_source = (app_root / "store.py").read_text()
    quality_loop_repository_source = (
        app_root / "infrastructure" / "persistence" / "quality_loop_repository.py"
    ).read_text()
    runner_source = (app_root / "infrastructure" / "runner" / "run_orchestrator.py").read_text()
    quality_loop_ports_source = (
        app_root / "infrastructure" / "quality_loop" / "application_ports.py"
    ).read_text()
    governance_source = (app_root / "application" / "platform" / "governance.py").read_text()

    for fragment in [
        "class USItem",
        "class AssetLane",
        "class QualityAssetPart",
        "class QualityAssetPack",
        "class RunSummary",
        "class RunDetail",
        "class ExecutionEvidence",
        "class FailureReport",
        "class ReleaseDecision",
        "class ApprovalSummary",
        "class ApprovalDetail",
        "class ReleaseReadiness",
        "class QualityLoopState",
    ]:
        assert fragment in quality_models_source
        assert fragment not in models_source

    for exported_name in [
        "USItem",
        "QualityLoopState",
        "QualityAssetPack",
        "ExecutionEvidence",
        "FailureReport",
        "ReleaseDecision",
        "ApprovalDetail",
        "ReleaseReadiness",
    ]:
        assert exported_name in models_source
        assert exported_name in quality_init_source

    assert "from .application.quality_loop.quality_models import (" in models_source
    assert "from .quality_models import RunDetail" in use_cases_source
    assert "from .quality_models import ReleaseReadiness, USItem" in project_version_source
    assert "from .application.quality_loop.quality_models import (" in store_source
    assert "from ...application.quality_loop.quality_models import (" in quality_loop_repository_source
    assert (
        "from ...application.quality_loop.quality_models import ExecutionEvidence, RunDetail"
        in runner_source
    )
    assert "RunSummary," in quality_loop_ports_source
    assert "from ..quality_loop.quality_models import ApprovalDetail, ReleaseDecision" in governance_source


def test_system_image_contract_models_live_in_system_image_application_layer() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    system_models_source = (app_root / "application" / "system_image" / "system_image_models.py").read_text()
    system_init_source = (app_root / "application" / "system_image" / "__init__.py").read_text()
    project_models_source = (app_root / "application" / "platform" / "project_models.py").read_text()
    platform_init_source = (app_root / "application" / "platform" / "__init__.py").read_text()
    models_source = (app_root / "models.py").read_text()
    service_source = (app_root / "application" / "system_image" / "service.py").read_text()
    extraction_source = (app_root / "application" / "system_image" / "context_extraction.py").read_text()
    ingestion_source = (app_root / "infrastructure" / "system_image" / "source_ingestion.py").read_text()
    system_image_repository_source = (
        app_root / "infrastructure" / "persistence" / "system_image_repository.py"
    ).read_text()
    store_source = (app_root / "store.py").read_text()
    governance_source = (app_root / "application" / "platform" / "governance.py").read_text()
    quality_loop_source = (app_root / "application" / "quality_loop" / "use_cases.py").read_text()
    quality_image_source = (app_root / "application" / "quality_loop" / "quality_image_updates.py").read_text()
    agent_memory_source = (app_root / "application" / "agent" / "memory.py").read_text()
    agent_swarm_source = (app_root / "application" / "agent" / "swarm.py").read_text()
    retrieval_traces_source = (
        app_root / "application" / "system_image" / "retrieval_traces.py"
    ).read_text()

    for fragment in [
        "class KnowledgeObject",
        "class RawAssetRecord",
        "class RawAssetChunk",
        "class BaselineRecord",
        "class ContextRelationship",
        "class ContextObjectOverlay",
        "class QualityMetricSnapshot",
        "class EmbeddingRecord",
        "class RetrievalRun",
        "class RerankRecord",
        "class TaskContext",
        "class QualityProfile",
        "class SystemImageBuildState",
        "class SystemImageResponse",
    ]:
        assert fragment in system_models_source
        assert fragment not in models_source

    for fragment in [
        "class ProjectCard",
        "class VersionSummary",
    ]:
        assert fragment in project_models_source
        assert fragment not in models_source

    for exported_name in [
        "RawAssetRecord",
        "BaselineRecord",
        "ContextRelationship",
        "QualityMetricSnapshot",
        "TaskContext",
        "QualityProfile",
        "SystemImageResponse",
        "ProjectCard",
        "VersionSummary",
    ]:
        assert exported_name in models_source

    for exported_name in [
        "RawAssetRecord",
        "SystemImageResponse",
        "TaskContext",
    ]:
        assert exported_name in system_init_source
    assert "ProjectCard" in platform_init_source
    assert "VersionSummary" in platform_init_source

    assert "from .application.system_image.system_image_models import (" in models_source
    assert "from .application.platform.project_models import ProjectCard, VersionSummary" in models_source
    assert "from .system_image_models import (" in service_source
    assert "from .system_image_models import ContextRelationship, KnowledgeObject, QualityMetricSnapshot, RawAssetRecord" in extraction_source
    assert "from ...application.system_image.system_image_models import RawAssetRecord" in ingestion_source
    assert "from ...application.system_image.system_image_models import (" in system_image_repository_source
    assert "from .application.system_image.system_image_models import (" in store_source
    assert "from ..system_image.system_image_models import BaselineRecord" in governance_source
    assert "from ..system_image.system_image_models import ContextObjectOverlay, QualityMetricSnapshot" in quality_image_source
    assert "from ..system_image.system_image_models import ContextObjectOverlay, QualityMetricSnapshot" not in quality_loop_source
    assert "from .system_image_models import RetrievalRun" in retrieval_traces_source
    assert "from ..system_image.system_image_models import RetrievalRun" not in agent_memory_source
    assert "from ..system_image.system_image_models import RawAssetRecord" in agent_swarm_source


def test_platform_tool_contract_lives_in_application_layer() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    tool_models_source = (app_root / "application" / "platform" / "tool_models.py").read_text()
    models_source = (app_root / "models.py").read_text()
    store_source = (app_root / "store.py").read_text()
    runtime_source = (app_root / "application" / "platform" / "runtime.py").read_text()
    tool_invocations_source = (app_root / "application" / "platform" / "tool_invocations.py").read_text()
    tool_projection_source = (app_root / "application" / "platform" / "tool_projection.py").read_text()
    tool_catalog_source = (app_root / "application" / "platform" / "tool_catalog.py").read_text()
    platform_router_source = (app_root / "interface" / "http" / "routers" / "platform.py").read_text()
    repositories_source = (app_root / "infrastructure" / "persistence" / "repositories.py").read_text()
    conversation_repository_source = (
        app_root / "infrastructure" / "persistence" / "conversation_repository.py"
    ).read_text()
    agent_graph_source = (app_root / "application" / "agent" / "graph.py").read_text()
    quality_loop_source = (app_root / "application" / "quality_loop" / "use_cases.py").read_text()
    platform_init_source = (app_root / "application" / "platform" / "__init__.py").read_text()

    for fragment in [
        "class ToolDefinition",
        "class ToolResult",
        "class ToolInvocation",
        "class AuditEvent",
        "class ToolInvocationRequest",
        "class EventPayload",
    ]:
        assert fragment in tool_models_source
        assert fragment not in models_source
    assert "payload: Dict[str, Any] = Field(default_factory=dict)" in tool_models_source

    for exported_name in [
        "ToolDefinition",
        "ToolResult",
        "ToolInvocation",
        "AuditEvent",
        "ToolInvocationRequest",
        "EventPayload",
    ]:
        assert exported_name in models_source
        assert exported_name in platform_init_source

    assert "from .application.platform.tool_models import" in models_source
    assert "from .application.platform.tool_models import (" in store_source
    assert "from .tool_models import AuditEvent, ToolDefinition, ToolInvocation, ToolInvocationRequest, ToolResult" in runtime_source
    assert "from .tool_models import AuditEvent, ToolDefinition, ToolInvocation, ToolInvocationRequest, ToolResult" in tool_invocations_source
    assert "from .tool_models import ToolInvocation" in tool_projection_source
    assert "from .tool_models import ToolDefinition" in tool_catalog_source
    assert "from ....application.platform.tool_models import ToolInvocationRequest" in platform_router_source
    assert "from ...application.platform.tool_models import AuditEvent, ToolInvocation, ToolResult" in conversation_repository_source
    assert "from ...application.platform.tool_models import AuditEvent, ToolInvocation, ToolResult" not in repositories_source
    assert "from ..platform.tool_models import ToolInvocation, ToolInvocationRequest" in agent_graph_source
    assert "from ..platform.tool_models import ToolInvocation" in quality_loop_source


def test_platform_tool_invocation_rules_live_in_application_service() -> None:
    store_source = (ROOT / "apps" / "api" / "app" / "store.py").read_text()
    platform_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "use_cases.py"
    ).read_text()
    tool_invocation_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "tool_invocations.py"
    ).read_text()
    platform_init_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "__init__.py"
    ).read_text()
    root_runtime = (ROOT / "apps" / "api" / "app" / "tool_invocation_runtime.py").read_text()
    runtime_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "runtime.py"
    ).read_text()
    projection_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "tool_projection.py"
    ).read_text()
    projection_ports_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "projection_ports.py"
    ).read_text()
    projection_adapter_source = (
        ROOT / "apps" / "api" / "app" / "infrastructure" / "platform" / "tool_projection.py"
    ).read_text()
    runtime_ports_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "runtime_ports.py"
    ).read_text()
    authorization_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "tool_authorization.py"
    ).read_text()
    runtime_adapter_source = (
        ROOT / "apps" / "api" / "app" / "infrastructure" / "platform" / "tool_runtime.py"
    ).read_text()
    application_ports_source = (
        ROOT
        / "apps"
        / "api"
        / "app"
        / "application"
        / "platform"
        / "tool_invocation_ports.py"
    ).read_text()
    application_state_source = (
        ROOT
        / "apps"
        / "api"
        / "app"
        / "infrastructure"
        / "platform"
        / "tool_invocation_state.py"
    ).read_text()
    event_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "events.py"
    ).read_text()

    assert "ToolInvocationApplicationService" in platform_source
    assert "self._tool_invocations = tool_invocations" in platform_source
    for method_name in [
        "list_tools",
        "list_audit_events",
        "create_tool_invocation",
        "list_tool_invocations",
        "get_tool_invocation",
        "confirm_tool_invocation",
    ]:
        assert f"self._tool_invocations.{method_name}" in platform_source

    for fragment in [
        "class ToolInvocationApplicationService",
        "state: ToolInvocationApplicationStatePort",
        "runtime: ToolInvocationExecutionPort",
        "authorization: ToolInvocationAccessPort",
        "events: ToolStatusEventPort",
        "self._state = state",
        "self._runtime = runtime",
        "self._authorization = authorization",
        "self._events = events",
        "self._runtime.create",
        "self._runtime.confirm",
        "self._runtime.execute",
        "self._runtime.gate_if_needed",
        "canonical_tool_id",
        "tool_invocation_created_at",
        "list_audit_events",
        "tool.invocation.created",
        "emit_tool_invocation_update",
        "self._events.emit_tool_status",
        "self._events.emit_tool_invocation_update",
    ]:
        assert fragment in tool_invocation_source
    for leaked_event_dependency in [
        "ApplicationStore",
        "self._store",
        "self.store",
        "PlatformEventApplicationService(",
        "self._events.push_event",
    ]:
        assert leaked_event_dependency not in tool_invocation_source
    for port_name in [
        "ToolInvocationApplicationStatePort",
        "ToolInvocationExecutionPort",
        "ToolInvocationAccessPort",
        "ToolStatusEventPort",
    ]:
        assert f"class {port_name}(Protocol)" in application_ports_source
        assert port_name in tool_invocation_source
    for adapter_fragment in [
        "class ToolInvocationApplicationProjectionState",
        "class ToolInvocationApplicationProjectionAdapters",
        "class ProjectedToolInvocationApplicationState",
        "class ToolInvocationFactRepository(Protocol)",
        "class SQLAlchemyToolInvocationApplicationState",
        "self._repository.get_tool_invocation(invocation_id)",
        "self._repository.load_tool_invocations()",
        "self._repository.load_audit_events()",
        "def list_tools(",
        "def get_conversation(",
        "def get_invocation(",
        "def list_invocations(",
        "def list_audit_events(",
    ]:
        assert adapter_fragment in application_state_source
    for forbidden_fragment in ["ApplicationStore", "self._store", "from ...store"]:
        assert forbidden_fragment not in application_state_source
    assert "def emit_tool_invocation_update(" in event_source

    for port_name in [
        "ToolInvocationRuntimeStatePort",
        "ToolCatalogRuntimePort",
        "ToolAuthorizationRuntimePort",
        "ToolGovernanceRuntimePort",
        "ToolAuditRuntimePort",
        "AgentReplyRuntimePort",
        "ToolInvocationEventRuntimePort",
    ]:
        assert f"class {port_name}(Protocol)" in runtime_ports_source
        assert port_name in runtime_source
    for runtime_dependency in [
        "self._state = state",
        "self._catalog = catalog",
        "self._authorization = authorization",
        "self._governance = governance",
        "self._audit_events = audit_events",
        "self._agent_replies = agent_replies",
        "self._events = events",
        "self.handlers = handlers",
        "self._state.persist_invocation(invocation)",
        "self._agent_replies.append_assistant_message",
        "self._events.emit_tool_invocation_update",
        "self._audit_events.record_audit_event",
    ]:
        assert runtime_dependency in runtime_source
    for forbidden_runtime_dependency in [
        "ApplicationStore",
        "self.store",
        "AgentReplyApplicationService(",
        "ToolInvocationApplicationService(",
        "ToolInvocationProjectionApplicationService(",
        "build_tool_handler_registry(",
        "ToolHandlerDependencies(",
    ]:
        assert forbidden_runtime_dependency not in runtime_source

    for authorization_fragment in [
        "class ToolInvocationAuthorizationApplicationService",
        "ProjectAccessApplicationService",
        "def authorize(",
        "def current_actor_id(",
        "self._project_access.project_id_for_invocation(invocation)",
        "self._project_access.effective_user_for_project(project_id, actor)",
    ]:
        assert authorization_fragment in authorization_source
    assert "ApplicationStore" not in authorization_source
    assert "self._store" not in authorization_source

    for adapter_fragment in [
        "class ToolInvocationRuntimeProjectionState",
        "class ToolInvocationRuntimeAdapters",
        "class ProjectedToolInvocationRuntimeState",
        "class ToolInvocationRuntimeRepository(Protocol)",
        "class SQLAlchemyToolInvocationRuntimeState",
        "class StaticToolCatalogRuntimeAdapter",
        "def create_invocation(",
        "def get_invocation(",
        "def list_invocations(",
        "def find_idempotent_invocation(",
        "def claim_for_execution(",
        "def persist_invocation(",
        "def tool_definition(",
    ]:
        assert adapter_fragment in runtime_adapter_source
    assert "ApplicationStore" not in runtime_adapter_source
    assert "from ...store" not in runtime_adapter_source
    assert "from .application.platform.runtime import *" in root_runtime
    for compatibility_fragment in [
        "class ToolInvocationRuntime",
        "ToolInvocationHandlerRegistry",
        "ToolRBAC",
        "build_tool_handler_registry",
    ]:
        assert compatibility_fragment not in root_runtime
    assert "from .application.platform.runtime import ToolInvocationRuntime" in store_source
    assert "from .tool_invocation_runtime import ToolInvocationRuntime" not in store_source
    for leaked_runtime_gate_dependency in [
        "append_message(",
        "_push_event",
        "_upsert_invocation_in_conversation",
    ]:
        assert leaked_runtime_gate_dependency not in runtime_source

    for projection_fragment in [
        "class ToolInvocationProjectionApplicationService",
        "state: ToolInvocationProjectionStatePort",
        "self._state = state",
        "def persist_and_project",
        "def upsert_in_conversation",
        "self._state.persist_and_project(invocation)",
    ]:
        assert projection_fragment in projection_source
    for forbidden_projection_dependency in [
        "ApplicationStore",
        "self._store",
        "conversation_repository",
        "from ...store",
    ]:
        assert forbidden_projection_dependency not in projection_source
    assert "class ToolInvocationProjectionStatePort(Protocol)" in projection_ports_source
    for adapter_fragment in [
        "class ToolInvocationProjectionFacts",
        "class ToolInvocationProjectionAdapters",
        "class ProjectedToolInvocationProjectionState",
        "class SQLAlchemyToolInvocationProjectionState",
        "class ToolInvocationProjectionRepository(Protocol)",
        "self._facts.invocations[invocation.id] = invocation",
        "self._adapters.persist_invocation(invocation)",
        "conversation.tool_invocations.append(invocation)",
        "conversation.tool_invocations[existing_index] = invocation",
        "self._adapters.persist_conversation(conversation)",
        "self._repository.upsert_tool_invocation(invocation)",
    ]:
        assert adapter_fragment in projection_adapter_source
    assert "ApplicationStore" not in projection_adapter_source
    assert "from ...store" not in projection_adapter_source

    assert "ToolInvocationProjectionApplicationService" in platform_init_source
    assert '"ToolInvocationProjectionApplicationService": ".tool_projection"' in platform_init_source

    def method_block(method_name: str) -> str:
        match = re.search(
            rf"\n    (?:async\s+)?def {method_name}\b.*?(?=\n    (?:async\s+)?def |\nclass |\Z)",
            store_source,
            re.S,
        )
        assert match is not None, method_name
        return match.group(0)

    for method_name in [
        "create_tool_invocation",
        "_execute_tool_invocation",
        "_gate_tool_invocation_if_needed",
        "_tool_definition",
        "confirm_tool_invocation",
        "get_tool_invocation",
        "list_tool_invocations",
        "_tool_invocation_created_at",
        "list_audit_events",
    ]:
        block = method_block(method_name)
        assert "self.tool_invocations_app." in block
        for leaked_rule in [
            "tool_invocation_runtime.create(",
            "tool_invocation_runtime.confirm(",
            "tool_invocation_runtime.execute(",
            "tool_invocation_runtime.gate_if_needed(",
            "tool_invocations.values()",
            "canonical_tool_id(",
            "audit_events.values()",
            "event.action == \"tool.invocation.created\"",
        ]:
            assert leaked_rule not in block

    for fragment in [
        "self.tool_projection_state = SQLAlchemyToolInvocationProjectionState(",
        "self.tool_projection = ToolInvocationProjectionApplicationService(",
        "self.audit_event_persistence = SQLAlchemyAuditEventPersistence(",
        "self.platform_audit = PlatformAuditApplicationService(",
        "self.event_stream_buffer = SSEWakeUpBuffer(",
        "EventStreamWakeUpState(",
        "self.event_streams = PlatformEventStreamApplicationService(",
        "self.platform_event_entities = CallablePlatformEventEntityReader(",
        "self.platform_events = PlatformEventApplicationService(",
        "self.agent_replies = AgentReplyApplicationService(",
        "memory=self.agent_memory",
        "generation=self.llm",
        "model_settings=self.model_configuration",
        "messages=self.conversation_message_writer",
        "self.tool_handler_registry = build_tool_handler_registry(",
        "tool_invocations=self.platform_events",
        "self.tool_runtime_state = SQLAlchemyToolInvocationRuntimeState(",
        "self.tool_runtime_catalog = StaticToolCatalogRuntimeAdapter(self.tools)",
        "self.tool_runtime_authorization = ToolInvocationAuthorizationApplicationService(",
        "self.tool_invocation_runtime = ToolInvocationRuntime(",
        "state=self.tool_runtime_state",
        "catalog=self.tool_runtime_catalog",
        "authorization=self.tool_runtime_authorization",
        "governance=self.tool_governance",
        "audit_events=self.platform_audit",
        "events=self.platform_events",
        "handlers=self.tool_handler_registry",
        "self.tool_application_state = SQLAlchemyToolInvocationApplicationState(",
        "repository=self.conversation_repository",
        "self.tool_invocations_app = ToolInvocationApplicationService(",
        "state=self.tool_application_state",
        "runtime=self.tool_invocation_runtime",
        "authorization=self.project_access",
    ]:
        assert fragment in store_source
    for obsolete_query_composition in [
        "self.tool_application_state = ProjectedToolInvocationApplicationState(",
        "ToolInvocationApplicationProjectionState(\n                tools=self.tools",
        "self.tool_runtime_state = ProjectedToolInvocationRuntimeState(",
        "self.tool_projection_state = ProjectedToolInvocationProjectionState(",
        "mirror_invocation=self.tool_projection_state.mirror_invocation",
        "self.audit_event_persistence = ProjectedAuditEventPersistence(",
        "self.event_stream_buffer = ProjectedEventStreamBuffer(",
    ]:
        assert obsolete_query_composition not in store_source
    assert "def _tool_invocation_app" not in store_source

    projection_delegate_block = method_block("_upsert_invocation_in_conversation")
    assert "self.tool_projection.upsert_in_conversation(invocation)" in projection_delegate_block
    assert "ToolInvocationProjectionApplicationService(self).upsert_in_conversation(invocation)" not in projection_delegate_block
    for leaked_projection_rule in [
        "existing_index",
        "conversation.tool_invocations.append",
        "conversation.tool_invocations[",
        "conversation_repository.upsert_conversation(conversation)",
    ]:
        assert leaked_projection_rule not in projection_delegate_block


def test_production_tool_runtime_uses_postgres_command_state() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    store_source = (app_root / "store.py").read_text()
    runtime_source = (
        app_root / "infrastructure" / "platform" / "tool_runtime.py"
    ).read_text()
    repository_source = (
        app_root
        / "infrastructure"
        / "persistence"
        / "conversation_repository.py"
    ).read_text()
    model_source = (
        app_root / "infrastructure" / "persistence" / "db_models.py"
    ).read_text()
    migration_source = (
        ROOT
        / "apps"
        / "api"
        / "migrations"
        / "versions"
        / "0025_tool_invocation_runtime_state.py"
    ).read_text()

    assert "self.tool_runtime_state = SQLAlchemyToolInvocationRuntimeState(" in store_source
    assert "self.tool_runtime_state = ProjectedToolInvocationRuntimeState(" not in store_source
    assert "get_tool_invocation=self.tool_application_state.get_invocation" in store_source
    for fragment in [
        "class SQLAlchemyToolInvocationRuntimeState",
        "self._repository.create_tool_invocation(invocation)",
        "self._repository.find_idempotent_tool_invocation(",
        "self._repository.claim_tool_invocation_for_execution(",
    ]:
        assert fragment in runtime_source
    for fragment in [
        "def create_tool_invocation(",
        "except IntegrityError:",
        "def claim_tool_invocation_for_execution(",
        ".with_for_update()",
    ]:
        assert fragment in repository_source
    assert 'name="uq_tool_invocation_idempotency"' in model_source
    assert '"uq_tool_invocation_idempotency"' in migration_source


def test_platform_audit_event_writes_live_in_application_service() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    store_source = (app_root / "store.py").read_text()
    platform_source = (app_root / "application" / "platform" / "use_cases.py").read_text()
    platform_init_source = (app_root / "application" / "platform" / "__init__.py").read_text()
    audit_source = (app_root / "application" / "platform" / "audit_events.py").read_text()
    projection_ports_source = (
        app_root / "application" / "platform" / "projection_ports.py"
    ).read_text()
    audit_adapter_source = (
        app_root / "infrastructure" / "platform" / "audit_persistence.py"
    ).read_text()

    for fragment in [
        "class PlatformAuditApplicationService",
        "persistence: AuditEventPersistencePort",
        "self._persistence = persistence",
        "def record_audit_event",
        "def record_agent_goal_audit_event",
        "self._persistence.persist_audit_event(event)",
        "AuditEvent(",
        'entity_type="agent_goal"',
        '"workflow_id": goal.workflow_id',
    ]:
        assert fragment in audit_source
    for forbidden_audit_dependency in [
        "ApplicationStore",
        "self._store",
        "conversation_repository",
        "from ...store",
    ]:
        assert forbidden_audit_dependency not in audit_source
    assert "class AuditEventPersistencePort(Protocol)" in projection_ports_source
    for adapter_fragment in [
        "class AuditEventProjectionFacts",
        "class AuditEventPersistenceAdapters",
        "class ProjectedAuditEventPersistence",
        "self._facts.audit_events[event.id] = event",
        "self._adapters.persist_audit_event(event)",
        "class SQLAlchemyAuditEventPersistence",
        "self._repository.append_audit_event(event)",
    ]:
        assert adapter_fragment in audit_adapter_source
    assert "ApplicationStore" not in audit_adapter_source
    assert "from ...store" not in audit_adapter_source

    assert "self._audit_events = audit_events" in platform_source
    assert "self._audit_events.record_audit_event(event)" in platform_source
    assert "self._audit_events.record_agent_goal_audit_event(" in platform_source
    assert "PlatformAuditApplicationService" in platform_init_source

    def method_block(method_name: str) -> str:
        match = re.search(
            rf"\n    def {method_name}\b.*?(?=\n    (?:async\s+)?def |\nclass |\Z)",
            store_source,
            re.S,
        )
        assert match is not None, method_name
        return match.group(0)

    for method_name, delegated_call in [
        ("record_audit_event", "self.platform_audit.record_audit_event(event)"),
        ("record_agent_goal_audit_event", "self.platform_audit.record_agent_goal_audit_event("),
    ]:
        block = method_block(method_name)
        assert delegated_call in block
        for leaked_audit_fragment in [
            "AuditEvent(",
            "conversation_repository.upsert_audit_event",
            "audit_events[event.id]",
            "object_refs.append",
            "workflow_id",
            "autonomy_level",
            "uuid4().hex",
        ]:
            assert leaked_audit_fragment not in block
    assert "self.audit_event_persistence = SQLAlchemyAuditEventPersistence(" in store_source
    assert "self.audit_event_persistence = ProjectedAuditEventPersistence(" not in store_source
    assert "self.platform_audit = PlatformAuditApplicationService(" in store_source
    assert "def _audit_app" not in store_source


def test_platform_event_publication_lives_in_application_service() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    store_source = (app_root / "store.py").read_text()
    platform_init_source = (app_root / "application" / "platform" / "__init__.py").read_text()
    event_source = (app_root / "application" / "platform" / "events.py").read_text()
    event_stream_source = (app_root / "application" / "platform" / "event_streams.py").read_text()
    tool_invocation_source = (app_root / "application" / "platform" / "tool_invocations.py").read_text()
    projection_source = (app_root / "application" / "platform" / "tool_projection.py").read_text()
    event_ports_source = (app_root / "application" / "platform" / "event_ports.py").read_text()
    event_runtime_source = (
        app_root / "infrastructure" / "platform" / "event_runtime.py"
    ).read_text()

    for fragment in [
        "class PlatformEventApplicationService",
        "streams: PlatformEventStreamPort",
        "entities: PlatformEventEntityReaderPort",
        "tool_projection: ToolInvocationEventProjectionPort",
        "self.streams = streams",
        "self.entities = entities",
        "self.tool_projection = tool_projection",
        "def _agent_goal_or_none",
        "def _tool_invocation_or_none",
        "def _tool_invocation",
        "def _agent_swarm",
        "self.entities.get_agent_goal(goal_id)",
        "self.entities.get_tool_invocation(invocation_id)",
        "self.entities.get_agent_swarm(swarm_id)",
        "async def push_event",
        "async def push_goal_event",
        "def event_payload",
        "async def emit_tool_status",
        "async def stream_conversation_events",
        "async def stream_goal_events",
        "async def stream_swarm_events",
        "def swarm_snapshot_event",
        "EventPayload(",
        "self.streams.publish_conversation_event(conversation_id, event)",
        "self.streams.publish_goal_event(goal_id, event)",
        "self.streams.stream_conversation_events(conversation_id, last_event_id)",
        "self.streams.stream_goal_events(goal_id, last_event_id)",
        "self.streams.stream_swarm_events(swarm_id, last_event_id)",
        "self.tool_projection.persist_and_project(invocation)",
        'event_type="agent.swarm.snapshot"',
        'payload={"agent_swarm": swarm.model_dump()}',
    ]:
        assert fragment in event_source
    for event_queue_leak in [
        "_get_or_create_event_queue",
        "_get_or_create_goal_queue",
        "_get_or_create_swarm_queue",
        "queue.get()",
    ]:
        assert event_queue_leak not in event_source
    for leaked_snapshot_read in [
        "ApplicationStore",
        "self._store",
        "self._store.agent_goals.get(",
        "self._store.agent_goals[",
        "self._store.tool_invocations.get(",
        "self._store.tool_invocations[",
        "self._store.agent_swarms[",
    ]:
        assert leaked_snapshot_read not in event_source

    for stream_fragment in [
        "class PlatformEventStreamApplicationService",
        "outbox: EventOutboxPort",
        "buffer: EventStreamBufferPort",
        "self._outbox = outbox",
        "self._buffer = buffer",
        "def conversation_queue",
        "def goal_queue",
        "def swarm_queue",
        "async def publish_conversation_event",
        "async def publish_goal_event",
        "async def stream_conversation_events",
        "async def stream_goal_events",
        "async def stream_swarm_events",
        "self._buffer.conversation_queue(conversation_id)",
        "self._buffer.goal_queue(goal_id)",
        "self._buffer.swarm_queue(swarm_id)",
        "self._buffer.remember_entity_version(event)",
        "await asyncio.to_thread(self._outbox.append, event)",
        "await self.conversation_queue(conversation_id).put(event)",
        "await self.swarm_queue(event.swarm_run_id).put(event)",
        "await self.goal_queue(goal_id).put(event)",
        "self._outbox.list_after",
        "after_event_id=cursor",
        "await asyncio.wait_for(queue.get(), timeout=self._poll_seconds)",
        "yield None",
    ]:
        assert stream_fragment in event_stream_source
    for forbidden_stream_dependency in [
        "ApplicationStore",
        "self._store",
        "event_outbox_repository",
        "os.getenv",
        "from ...store",
    ]:
        assert forbidden_stream_dependency not in event_stream_source
    for port_name in [
        "EventStreamBufferPort",
        "PlatformEventStreamPort",
        "PlatformEventEntityReaderPort",
        "ToolInvocationEventProjectionPort",
    ]:
        assert f"class {port_name}(Protocol)" in event_ports_source
    for runtime_fragment in [
        "class EventStreamRuntimeSettings",
        "def event_stream_runtime_settings_from_env",
        "class EventStreamWakeUpState",
        "class SSEWakeUpBuffer",
        "Queues reduce delivery latency only.",
        "class PlatformEventEntityAdapters",
        "class CallablePlatformEventEntityReader",
        "queues[stream_id] = queue",
        "self._facts.entity_versions[",
    ]:
        assert runtime_fragment in event_runtime_source
    assert "ApplicationStore" not in event_runtime_source
    assert "from ...store" not in event_runtime_source
    assert event_stream_source.index("self._outbox.append") < event_stream_source.index(
        "self.conversation_queue(conversation_id).put(event)"
    )
    assert "conversation_repository.upsert_tool_invocation(invocation)" not in event_source
    assert "_upsert_invocation_in_conversation(invocation)" not in event_source
    assert "ToolInvocationProjectionApplicationService" in projection_source

    assert "PlatformEventApplicationService" in platform_init_source
    assert "PlatformEventStreamApplicationService" in platform_init_source
    assert '"PlatformEventStreamApplicationService": ".event_streams"' in platform_init_source
    assert "ToolInvocationProjectionApplicationService" in platform_init_source
    assert "events: ToolStatusEventPort" in tool_invocation_source
    assert "self._events = events" in tool_invocation_source
    assert "self._events.emit_tool_status" in tool_invocation_source
    assert "self._events.emit_tool_invocation_update" in tool_invocation_source
    assert "PlatformEventApplicationService(store)" not in tool_invocation_source
    assert "self._events.push_event" not in tool_invocation_source

    def store_method_block(method_name: str) -> str:
        match = re.search(
            rf"\n    (?:async\s+)?def {method_name}\b.*?(?=\n    (?:async\s+)?def |\nclass |\Z)",
            store_source,
            re.S,
        )
        assert match is not None, method_name
        return match.group(0)

    for removed_event_facade in [
        "async def _push_event",
        "async def _push_goal_event",
        "def _event_payload",
        "async def _emit_tool_status",
        "async def _emit_simple_answer",
    ]:
        assert removed_event_facade not in store_source

    for method_name, delegated_call in [
        ("stream_goal_events", "self.platform_events.stream_goal_events(goal_id, last_event_id)"),
        ("stream_swarm_events", "self.platform_events.stream_swarm_events(swarm_id, last_event_id)"),
        ("_swarm_snapshot_event", "self.platform_events.swarm_snapshot_event(swarm_id)"),
        (
            "stream_events",
            "self.platform_events.stream_conversation_events(conversation_id, last_event_id)",
        ),
    ]:
        block = store_method_block(method_name)
        assert delegated_call in block
        for leaked_event_fragment in [
            "EventPayload(",
            "_get_or_create_event_queue",
            "_get_or_create_goal_queue",
            "_get_or_create_swarm_queue",
            "entity_versions[",
            "conversation_repository.upsert_tool_invocation",
            "_upsert_invocation_in_conversation",
            "agent.swarm.snapshot",
            "swarm.model_dump()",
            "queue.get()",
        ]:
            assert leaked_event_fragment not in block

    for removed_event_store_facade in [
        "def _event_app",
        "def _get_or_create_event_queue",
        "def _get_or_create_goal_queue",
        "def _get_or_create_swarm_queue",
    ]:
        assert removed_event_store_facade not in store_source
    for composition_fragment in [
        "self.event_stream_buffer = SSEWakeUpBuffer(",
        "EventStreamWakeUpState(",
        "self.event_streams = PlatformEventStreamApplicationService(",
        "self.platform_event_entities = CallablePlatformEventEntityReader(",
        "self.platform_events = PlatformEventApplicationService(",
        "self.event_streams",
        "self.platform_event_entities",
        "self.tool_projection",
    ]:
        assert composition_fragment in store_source


def test_platform_tool_catalog_lives_in_platform_application_package() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    root_catalog = (app_root / "system_image_tool_catalog.py").read_text()
    platform_catalog = (app_root / "application" / "platform" / "tool_catalog.py").read_text()
    platform_init = (app_root / "application" / "platform" / "__init__.py").read_text()
    store_source = (app_root / "store.py").read_text()

    assert "from .application.platform.tool_catalog import *" in root_catalog
    for compatibility_fragment in ["def system_image_tool_definitions", "ToolDefinition(", "system_image.sources.register"]:
        assert compatibility_fragment not in root_catalog

    assert "def system_image_tool_definitions" in platform_catalog
    assert "def core_tool_definitions" in platform_catalog
    assert "ToolDefinition(" in platform_catalog
    for tool_id in [
        "project.create",
        "version.create",
        "us.task.start",
        "quality.scenario.generate",
        "automation.generate",
        "release.assess",
        "approval.request",
        "query.answer",
        "query.dashboard.progress",
        "system_image.sources.register",
        "system_image.sources.ingest",
        "system_image.context.materialize",
        "system_image.baseline.initialize",
    ]:
        assert tool_id in platform_catalog
    assert "from .tool_models import ToolDefinition" in platform_catalog
    assert "core_tool_definitions" in platform_init
    assert "system_image_tool_definitions" in platform_init
    assert "from .application.platform.tool_catalog import core_tool_definitions, system_image_tool_definitions" in store_source
    assert "self.tools = core_tool_definitions()" in store_source
    assert "self.tools.extend(system_image_tool_definitions())" in store_source
    assert "ToolDefinition(" not in store_source
    assert "from .system_image_tool_catalog import" not in store_source

    internal_sources = [
        path.read_text()
        for path in app_root.rglob("*.py")
        if path.name != "system_image_tool_catalog.py" and "tests" not in path.parts
    ]
    assert all(".system_image_tool_catalog import" not in source for source in internal_sources)


def test_tool_invocation_handlers_live_in_platform_application_package() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    root_facades = {
        "tool_invocation_handlers.py": "from .application.platform.tool_handlers import *",
        "system_image_tool_handlers.py": "from .application.platform.tool_handlers.system_image import *",
        "project_version_tool_handlers.py": "from .application.platform.tool_handlers.project_version import *",
        "quality_loop_tool_handlers.py": "from .application.platform.tool_handlers.quality_loop import *",
        "governance_tool_handlers.py": "from .application.platform.tool_handlers.governance import *",
        "query_tool_handlers.py": "from .application.platform.tool_handlers.query import *",
    }
    for filename, expected_import in root_facades.items():
        root_source = (app_root / filename).read_text()
        assert expected_import in root_source
        for implementation_fragment in [
            "class ",
            "def ",
            "ApplicationStore",
            "ToolInvocationApplicationService",
            "build_tool_handler_registry",
        ]:
            assert implementation_fragment not in root_source

    registry_source = (app_root / "application" / "platform" / "tool_handlers" / "registry.py").read_text()
    runtime_source = (app_root / "application" / "platform" / "runtime.py").read_text()
    assert "from .tool_handlers import ToolInvocationHandlerRegistry" in runtime_source
    assert "from ...tool_invocation_handlers import" not in runtime_source
    assert "build_tool_handler_registry" not in runtime_source
    assert "handlers: ToolInvocationHandlerRegistry" in runtime_source
    assert "class ToolHandlerDependencies" in registry_source
    assert "class ToolInvocationHandlerRegistry" in registry_source
    assert "build_tool_handler_registry" in registry_source
    assert "ApplicationStore" not in registry_source


def test_system_image_tool_handler_uses_application_service_for_write_side() -> None:
    handler_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "tool_handlers" / "system_image.py"
    ).read_text()
    registry_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "tool_handlers" / "registry.py"
    ).read_text()
    use_case_source = (
        ROOT / "apps" / "api" / "app" / "application" / "system_image" / "use_cases.py"
    ).read_text()
    agent_use_case_source = (
        ROOT / "apps" / "api" / "app" / "application" / "agent" / "use_cases.py"
    ).read_text()

    assert "SystemImageApplicationService" in handler_source
    assert "ToolStatusEventPort" in handler_source
    assert "ToolInvocationApplicationService" not in handler_source
    assert "AgentReplyApplicationService" in handler_source
    assert "AgentApplicationService" in handler_source
    assert "ApplicationStore" not in handler_source
    assert "self.store" not in handler_source
    assert "_emit_tool_status" not in handler_source
    assert "append_message" not in handler_source
    assert "agent_swarm_coordinator" not in handler_source
    assert "agent_goals" not in handler_source
    assert "class ToolHandlerDependencies" in registry_source
    assert "ApplicationStore" not in registry_source
    assert "build_store_tool_handler_registry" not in registry_source
    assert "SystemImageToolHandler(" in registry_source
    assert "dependencies.system_image," in registry_source
    assert "dependencies.tool_invocations," in registry_source
    assert "dependencies.agent_replies," in registry_source
    assert "dependencies.agent," in registry_source
    for method_name in [
        "normalize_source_specs",
        "source_binding_incomplete",
        "missing_source_types",
        "register_sources",
        "ingest_sources",
        "materialize_context",
        "initialize_baseline",
    ]:
        assert f"def {method_name}" in use_case_source
        assert f"self.system_image_app.{method_name}" in handler_source
    assert "self.tool_invocations.emit_tool_status" in handler_source
    assert "self.agent_replies.append_assistant_message" in handler_source
    assert "self.agent_app.run_system_image_materialization_swarm" in handler_source
    assert "def run_system_image_materialization_swarm" in agent_use_case_source
    assert "self._swarm.run_system_image_materialization_swarm" in agent_use_case_source
    assert "self._store.agent_swarm_coordinator.run_system_image_materialization_swarm" not in agent_use_case_source

    for leaked_dependency in [
        "self.store",
        "self.store.system_image_service.source_ingestion",
        "self.store.system_image_service.source_binding_incomplete",
        "self.store.system_image_service.missing_source_types",
        "self.store.system_image_service.register_sources",
        "self.store.system_image_service.ingest_sources",
        "self.store.system_image_service.materialize_context",
        "self.store.system_image_service.initialize_baseline",
        "self.store.agent_swarm_coordinator",
        "self.store.agent_goals",
    ]:
        assert leaked_dependency not in handler_source


def test_system_image_source_binding_rules_live_in_domain_policy() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    root_service = (app_root / "system_image_service.py").read_text()
    service_source = (app_root / "application" / "system_image" / "service.py").read_text()
    policy_source = (
        ROOT / "apps" / "api" / "app" / "domain" / "system_image" / "source_binding.py"
    ).read_text()

    assert "from .application.system_image.service import *" in root_service
    assert "class SystemImageService" not in root_service
    assert "from ...domain.system_image.source_binding import" in service_source
    assert "REQUIRED_SOURCE_TYPES" in policy_source
    assert "def default_source_uri" in policy_source
    assert "def missing_source_types" in policy_source
    assert "def source_binding_incomplete" in policy_source
    assert "git://{slug}" in policy_source
    assert "docs://{slug}/historical-us" in policy_source
    assert "tests://{slug}/regression" in policy_source

    service_binding_block = service_source.split("def source_binding_incomplete", 1)[1].split(
        "def register_sources", 1
    )[0]
    assert "source_binding_incomplete(self.workspace.list_raw_assets" in service_binding_block
    assert "missing_source_types(self.workspace.list_raw_assets" in service_binding_block
    assert '("code", "us_doc", "test_asset")' not in service_binding_block
    assert "source.source_uri ==" not in service_binding_block


def test_system_image_ingestion_and_extraction_live_in_system_image_packages() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    root_source_ingestion = (app_root / "source_ingestion.py").read_text()
    root_context_extraction = (app_root / "context_extraction.py").read_text()
    ingestion_adapter = (
        app_root / "infrastructure" / "system_image" / "source_ingestion.py"
    ).read_text()
    ingestion_ports = (
        app_root / "application" / "system_image" / "source_ports.py"
    ).read_text()
    git_connector = (
        app_root / "infrastructure" / "system_image" / "git_source_connector.py"
    ).read_text()
    code_intelligence_adapter = (
        app_root
        / "infrastructure"
        / "system_image"
        / "tree_sitter_code_intelligence.py"
    ).read_text()
    extraction_service = (
        app_root / "application" / "system_image" / "context_extraction.py"
    ).read_text()
    embedding_records = (
        app_root / "application" / "system_image" / "embedding_records.py"
    ).read_text()
    quality_contexts = (
        app_root / "application" / "system_image" / "quality_contexts.py"
    ).read_text()
    system_image_service = (
        app_root / "application" / "system_image" / "service.py"
    ).read_text()
    system_image_init = (
        app_root / "application" / "system_image" / "__init__.py"
    ).read_text()

    assert "from .application.system_image.source_ports import *" in root_source_ingestion
    assert "from .infrastructure.system_image.source_ingestion import *" in root_source_ingestion
    assert "from .application.system_image.context_extraction import *" in root_context_extraction
    for root_source in [root_source_ingestion, root_context_extraction]:
        for implementation_fragment in ["class ", "@dataclass", "def ", "Path(", "hashlib"]:
            assert implementation_fragment not in root_source

    assert "class SourceIngestionService" in ingestion_adapter
    assert "class SourceSpec" not in ingestion_adapter
    assert "class SourceTextUnit" not in ingestion_adapter
    assert "class SourceSpec" in ingestion_ports
    assert "class SourceTextUnit" in ingestion_ports
    assert "class SourceIngestionPort(Protocol)" in ingestion_ports
    assert "class SourceConnector(Protocol)" in ingestion_ports
    assert "class CodeIntelligencePort(Protocol)" in ingestion_ports
    assert "class CodeIntelligenceResult" in ingestion_ports
    assert "Path" in ingestion_adapter
    assert "read_bytes()" in ingestion_adapter
    assert "from ...application.system_image.source_ports import (" in ingestion_adapter
    assert "from ...application.system_image.system_image_models import RawAssetRecord" in ingestion_adapter
    assert "class GitSourceConnector" in git_connector
    assert "git:revision:" in git_connector
    assert "NASUS_GIT_ALLOWED_HOSTS" in git_connector
    assert "credential_ref" in git_connector
    assert "class TreeSitterCodeIntelligenceAdapter" in code_intelligence_adapter
    assert "from tree_sitter import Language, Node, Parser" in code_intelligence_adapter
    assert "tree_sitter_python" in code_intelligence_adapter
    assert "tree_sitter_typescript" in code_intelligence_adapter

    assert "class ContextExtractionService" in extraction_service
    assert "class ExtractedContext" in extraction_service
    assert "def _extract_source_context" in extraction_service
    assert "def _code_relationships" in extraction_service
    assert "def _us_anchors" in extraction_service
    assert "def _test_anchors" in extraction_service
    assert "from .system_image_models import ContextRelationship" in extraction_service
    assert "SourceIngestionPort" in extraction_service
    assert "CodeIntelligencePort" in extraction_service
    assert "self._code_intelligence.analyze(units)" in extraction_service
    assert "Path(" not in extraction_service
    assert "import ast" not in extraction_service
    assert "tree_sitter" not in extraction_service
    assert "self._source_reader.extract_text_units(source)" in extraction_service

    assert "from .context_extraction import ContextExtractionService" in system_image_service
    assert "from .ports import SystemImageWorkspacePort" in system_image_service
    assert "self._workspace.embed_texts(" in embedding_records
    assert "self._workspace.rerank_candidates(" in quality_contexts
    assert "ModelConfigurationApplicationService" not in system_image_service
    assert "self.store._get_custom_model_api_key" not in system_image_service
    assert "SourceIngestionPort" in system_image_service
    assert "CodeIntelligencePort" in system_image_service
    assert "SystemImageIngestionProjectionPort" in system_image_service
    assert "infrastructure.system_image" not in system_image_service
    assert "self.context_extraction = ContextExtractionService(" in system_image_service
    assert "code_intelligence," in system_image_service
    assert "from ...context_extraction import" not in system_image_service
    assert "from ...source_ingestion import" not in system_image_service
    assert "ContextExtractionService" in system_image_init

    internal_sources = {
        path: path.read_text()
        for path in app_root.rglob("*.py")
        if path.name not in {"source_ingestion.py", "context_extraction.py"} and "tests" not in path.parts
    }
    assert all("from ...source_ingestion import" not in source for source in internal_sources.values())
    assert all("from ...context_extraction import" not in source for source in internal_sources.values())
    for path, source in internal_sources.items():
        if path.parent == app_root:
            assert "source_ingestion import" not in source
            assert "context_extraction import" not in source


def test_system_image_source_ingestion_writes_live_in_application_component() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    service_source = (app_root / "application" / "system_image" / "service.py").read_text()
    source_ingestion_source = (
        app_root / "application" / "system_image" / "source_ingestion.py"
    ).read_text()
    system_image_init = (app_root / "application" / "system_image" / "__init__.py").read_text()

    for fragment in [
        "class SystemImageSourceIngestionApplicationService",
        "def register_sources",
        "def ingest_sources",
        "def _clear_derived_context",
        "def _registered_actor",
        "def _ingestion_failure_reason",
        "RawAssetRecord(",
        "current.ingestion_status = \"pending\"",
        "source.ingestion_status = \"ingesting\"",
        "source.ingestion_status = \"failed\"",
        "source.ingestion_status = \"indexed\"",
        "source.permission_status = \"denied\" if isinstance(exc, PermissionError) else \"allowed\"",
        "self._raw_asset_chunks.materialize(project_id, captured_at=now)",
        "self._projection.persist(project_id)",
        "self._projection.refresh(project_id)",
    ]:
        assert fragment in source_ingestion_source

    assert "self._store" not in source_ingestion_source
    assert "SystemImageIngestionProjectionPort" in source_ingestion_source

    for fragment in [
        "from .source_ingestion import SystemImageSourceIngestionApplicationService",
        "self.source_ingestion_use_cases = SystemImageSourceIngestionApplicationService(",
        "self.source_ingestion_use_cases.register_sources(",
        "self.source_ingestion_use_cases.ingest_sources(",
        "ensure_draft_state=lambda: self.ensure_state(project_id, ready=False)",
    ]:
        assert fragment in service_source

    register_block = service_source.split("def register_sources", 1)[1].split("def ingest_sources", 1)[0]
    ingest_block = service_source.split("def ingest_sources", 1)[1].split("async def materialize_context", 1)[0]
    source_use_case_blocks = register_block + ingest_block
    for leaked_fragment in [
        "def _ingestion_failure_reason",
        "self.store.raw_asset_chunks[project_id] = []",
        "self.store.embedding_records[project_id] = []",
        "current.ingestion_status = \"pending\"",
        "source.ingestion_status = \"ingesting\"",
        "source.ingestion_status = \"failed\"",
        "source.ingestion_status = \"indexed\"",
        "self.source_ingestion.ingest(source)",
        "self.raw_asset_chunks.materialize(project_id, captured_at=now)",
        "source.permission_status = \"denied\" if isinstance(exc, PermissionError) else \"allowed\"",
    ]:
        assert leaked_fragment not in source_use_case_blocks

    assert "SystemImageSourceIngestionApplicationService" in system_image_init
    assert '"SystemImageSourceIngestionApplicationService": ".source_ingestion"' in system_image_init


def test_system_image_chunking_rules_live_in_domain_policy() -> None:
    service_source = (
        ROOT / "apps" / "api" / "app" / "application" / "system_image" / "service.py"
    ).read_text()
    raw_asset_chunks_source = (
        ROOT / "apps" / "api" / "app" / "application" / "system_image" / "raw_asset_chunks.py"
    ).read_text()
    source_ingestion_source = (
        ROOT / "apps" / "api" / "app" / "application" / "system_image" / "source_ingestion.py"
    ).read_text()
    system_image_init = (
        ROOT / "apps" / "api" / "app" / "application" / "system_image" / "__init__.py"
    ).read_text()
    policy_source = (
        ROOT / "apps" / "api" / "app" / "domain" / "system_image" / "chunking.py"
    ).read_text()

    assert "from ...domain.system_image.chunking import" in raw_asset_chunks_source
    assert "from .raw_asset_chunks import SystemImageRawAssetChunkApplicationService" in service_source
    assert "self.raw_asset_chunks = SystemImageRawAssetChunkApplicationService(workspace, self.source_ingestion)" in service_source
    assert "self._raw_asset_chunks.materialize(project_id, captured_at=" in source_ingestion_source
    assert "SystemImageRawAssetChunkApplicationService" in system_image_init
    assert '"SystemImageRawAssetChunkApplicationService": ".raw_asset_chunks"' in system_image_init
    for fragment in [
        "def split_chunk_text",
        "def content_hash",
        "def stable_hash",
        "def chunk_id",
        "def chunk_kind",
        "def estimate_tokens",
        "DEFAULT_CHUNK_MAX_CHARS",
    ]:
        assert fragment in policy_source

    for leaked_method in [
        "def _split_chunk_text",
        "def _chunk_id",
        "def _chunk_kind",
        "def _estimate_tokens",
        "def _stable_hash",
    ]:
        assert leaked_method not in service_source
        assert leaked_method not in raw_asset_chunks_source

    for leaked_service_implementation in [
        "def _materialize_raw_asset_chunks",
        "def _chunk_text",
        "split_chunk_text(unit.text)",
        "content_hash(chunk_text)",
        "chunk_id(project_id, source.id, unit.relative_path, chunk_index, chunk_hash)",
        "chunk_kind(source.source_type)",
        "estimate_tokens(chunk_text)",
    ]:
        assert leaked_service_implementation not in service_source

    for delegated_rule in [
        "split_chunk_text(unit.text)",
        "content_hash(chunk_text)",
        "chunk_id(project_id, source.id, unit.relative_path, chunk_index, chunk_hash)",
        "chunk_kind(source.source_type)",
        "estimate_tokens(chunk_text)",
    ]:
        assert delegated_rule in raw_asset_chunks_source


def test_system_image_embedding_records_live_in_application_component() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    service_source = (app_root / "application" / "system_image" / "service.py").read_text()
    embedding_source = (app_root / "application" / "system_image" / "embedding_records.py").read_text()
    quality_contexts_source = (
        app_root / "application" / "system_image" / "quality_contexts.py"
    ).read_text()
    system_image_init = (app_root / "application" / "system_image" / "__init__.py").read_text()

    for fragment in [
        "class SystemImageEmbeddingRecordApplicationService",
        "async def materialize",
        "self._raw_asset_chunks.chunk_text(chunk)",
        "self._workspace.embed_texts(",
        "stable_hash([source.source_type, source.source_uri])",
        "stable_hash([item.id, item.name, item.type, *item.evidence])",
        "def vector_ref",
        "pgvector",
        "local-hash-vector",
    ]:
        assert fragment in embedding_source

    for fragment in [
        "from .embedding_records import SystemImageEmbeddingRecordApplicationService",
        "self.embedding_records = SystemImageEmbeddingRecordApplicationService(",
    ]:
        assert fragment in service_source
    assert "self._embedding_records.materialize(" in quality_contexts_source

    for leaked_fragment in [
        "async def _materialize_embedding_records",
        "self.store.llm.embed_texts(",
        "self.model_configurations.get_custom_model_api_key(\"embedding\")",
        "def _embedding_status",
        "def _embedding_provider",
        "def _embedding_model_name",
        "def _vector_ref",
        "stable_hash([source.source_type, source.source_uri])",
        "stable_hash([item.id, item.name, item.type, *item.evidence])",
    ]:
        assert leaked_fragment not in service_source

    assert "SystemImageEmbeddingRecordApplicationService" in system_image_init
    assert '"SystemImageEmbeddingRecordApplicationService": ".embedding_records"' in system_image_init


def test_system_image_quality_context_rules_live_in_domain_policy() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    service_source = (
        app_root / "application" / "system_image" / "service.py"
    ).read_text()
    quality_contexts_source = (
        app_root / "application" / "system_image" / "quality_contexts.py"
    ).read_text()
    system_image_init = (
        app_root / "application" / "system_image" / "__init__.py"
    ).read_text()
    policy_source = (
        app_root / "domain" / "system_image" / "quality_context.py"
    ).read_text()

    assert "from ...domain.system_image.quality_context import" in quality_contexts_source
    assert "from .quality_contexts import SystemImageQualityContextApplicationService" in service_source
    assert "self.quality_contexts = SystemImageQualityContextApplicationService(" in service_source
    assert "await self.quality_contexts.materialize(" in service_source
    assert "self.quality_contexts.materialize(" in service_source
    assert "SystemImageQualityContextApplicationService" in system_image_init
    assert '"SystemImageQualityContextApplicationService": ".quality_contexts"' in system_image_init
    for fragment in [
        "def missing_quality_context",
        "def context_hash",
        "def context_confidence",
        "def risk_score",
        "def coverage_score",
        "def automation_feasibility",
        "def release_score",
        "def risk_drivers",
        "REQUIRED_QUALITY_SOURCE_TYPES",
    ]:
        assert fragment in policy_source

    for leaked_method in [
        "def _missing_quality_context",
        "def _context_hash",
        "def _context_confidence",
        "def _metric_by_group",
        "def _risk_score",
        "def _coverage_score",
        "def _automation_feasibility",
        "def _release_score",
        "def _risk_drivers",
        "async def _materialize_quality_contexts",
        "def _candidate_text",
        "def _rerank_status",
        "def _rerank_model_name",
        "self.store.llm.rerank_candidates(",
    ]:
        assert leaked_method not in service_source

    for delegated_rule in [
        "class SystemImageQualityContextApplicationService",
        "async def materialize",
        "self._embedding_records.materialize(",
        "self._workspace.rerank_candidates(",
        "missing_quality_context(sources, target_us_id)",
        "context_hash(",
        "context_confidence(sources, relationships, metrics)",
        "risk_score(metrics)",
        "coverage_score(metrics)",
        "release_score(",
        "automation_feasibility(metrics)",
        "risk_drivers(metrics, relationships)",
        "def candidate_text",
    ]:
        assert delegated_rule in quality_contexts_source


def test_system_image_materialization_fails_closed_without_source_evidence() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    service_source = (app_root / "application" / "system_image" / "service.py").read_text()
    policy_source = (app_root / "domain" / "system_image" / "materialization.py").read_text()
    system_image_init = (app_root / "application" / "system_image" / "__init__.py").read_text()

    for fragment in [
        "class SystemImageMaterializationDecision",
        "class InsufficientSystemImageEvidenceError",
        "def assess_materialized_evidence",
        "def require_materialized_evidence",
        "SYNTHETIC_EVIDENCE_MARKERS",
        '"seeded-fixture"',
        '"synthetic-fixture"',
        '"system-image:fallback"',
    ]:
        assert fragment in policy_source

    for fragment in [
        "from ...domain.system_image.materialization import require_materialized_evidence",
        "require_materialized_evidence(",
        "self.workspace.replace_knowledge_objects(project_id, extracted.objects)",
        "self.workspace.replace_context_relationships(project_id, extracted.relationships)",
        "self.workspace.replace_quality_metric_snapshots(project_id, extracted.metrics)",
    ]:
        assert fragment in service_source

    for forbidden_fragment in [
        "SystemImageSeedContextApplicationService",
        "seed_contexts",
        "materialize_fallback",
        "seeded-fixture",
        "synthetic-fixture",
    ]:
        assert forbidden_fragment not in service_source

    assert "SystemImageSeedContextApplicationService" not in system_image_init
    assert not (app_root / "application" / "system_image" / "seed_contexts.py").exists()


def test_system_image_persistence_lives_in_application_component() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    service_source = (app_root / "application" / "system_image" / "service.py").read_text()
    persistence_source = (app_root / "application" / "system_image" / "persistence.py").read_text()
    agent_memory_source = (app_root / "application" / "agent" / "memory.py").read_text()
    retrieval_traces_source = (
        app_root / "application" / "system_image" / "retrieval_traces.py"
    ).read_text()
    quality_image_source = (app_root / "application" / "quality_loop" / "quality_image_updates.py").read_text()
    governance_source = (app_root / "application" / "platform" / "governance.py").read_text()
    system_image_init = (app_root / "application" / "system_image" / "__init__.py").read_text()

    for fragment in [
        "class SystemImagePersistenceApplicationService",
        "def persist",
        "self._workspace.persist_system_image(project_id)",
    ]:
        assert fragment in persistence_source

    for source in [service_source, retrieval_traces_source]:
        assert "SystemImagePersistenceApplicationService" in source
        assert ".persist(project_id)" in source
        assert "_persist_system_image" not in source
    assert "self._workspace.persist_system_image(project_id)" in governance_source
    assert "SystemImagePersistenceApplicationService" not in governance_source
    assert "QualityImageWorkspacePort" in quality_image_source
    assert "self._workspace.persist_system_image(project_id)" in quality_image_source
    assert "_persist_system_image" not in quality_image_source
    assert "SystemImagePersistenceApplicationService" not in agent_memory_source
    assert ".persist(project_id)" not in agent_memory_source

    for source in [service_source, retrieval_traces_source, agent_memory_source, quality_image_source, governance_source]:
        assert "project_repository.replace_system_image(" not in source

    assert "SystemImagePersistenceApplicationService" in system_image_init
    assert '"SystemImagePersistenceApplicationService": ".persistence"' in system_image_init


def test_system_image_build_state_rules_live_in_domain_policy() -> None:
    service_source = (
        ROOT / "apps" / "api" / "app" / "application" / "system_image" / "service.py"
    ).read_text()
    policy_source = (
        ROOT / "apps" / "api" / "app" / "domain" / "system_image" / "build_state.py"
    ).read_text()

    assert "from ...domain.system_image.build_state import resolve_build_state" in service_source
    for fragment in [
        "class SystemImageBuildStateDecision",
        "def resolve_build_state",
        "status=\"partially_failed\"",
        "status=\"source_required\"",
        "status=\"ready\"",
        "status=\"materialized\"",
        "status=\"indexed\"",
        "status=\"ingesting\"",
        "status=\"sources_registered\"",
    ]:
        assert fragment in policy_source

    build_state_block = service_source.split("def _build_state", 1)[1].split(
        "def _ensure_sources_ready", 1
    )[0]
    assert "resolve_build_state(" in build_state_block
    assert "SystemImageBuildState(**decision.to_api_kwargs())" in build_state_block
    for leaked_rule in [
        "Source ingestion partially failed",
        "Source bindings required",
        "Official System Image ready",
        "Context materialized, waiting for baseline promotion",
        "Sources indexed, context not materialized",
        "Source ingestion in progress",
        "Sources registered, ingestion pending",
        "status=\"partially_failed\"",
        "status=\"source_required\"",
        "status=\"ready\"",
        "status=\"materialized\"",
        "status=\"indexed\"",
        "status=\"ingesting\"",
        "status=\"sources_registered\"",
    ]:
        assert leaked_rule not in build_state_block


def test_system_image_us_work_item_rules_live_in_domain_policy() -> None:
    service_source = (
        ROOT / "apps" / "api" / "app" / "application" / "system_image" / "service.py"
    ).read_text()
    application_source = (
        ROOT / "apps" / "api" / "app" / "application" / "system_image" / "us_work_items.py"
    ).read_text()
    system_image_init = (
        ROOT / "apps" / "api" / "app" / "application" / "system_image" / "__init__.py"
    ).read_text()
    policy_source = (
        ROOT / "apps" / "api" / "app" / "domain" / "system_image" / "us_work_items.py"
    ).read_text()

    for fragment in [
        "def derive_us_work_items_from_context",
        "def default_asset_lanes_for_us",
        "PRIMARY_US_OBJECT_TYPE",
        "FALLBACK_US_OBJECT_TYPES",
        "DEFAULT_US_NEXT_ACTION",
        "class USWorkItemDecision",
        "class AssetLaneDecision",
    ]:
        assert fragment in policy_source

    for fragment in [
        "class SystemImageUSWorkItemApplicationService",
        "def sync_from_context",
        "from ...domain.system_image.us_work_items import",
        "derive_us_work_items_from_context(",
        "default_asset_lanes_for_us(us_item.id)",
        "USItem(**decision.__dict__)",
        "AssetLane(",
        "replace_us_items(project_id, version_id, us_items)",
        "replace_asset_lanes(project_id, us_item.id, lanes)",
    ]:
        assert fragment in application_source

    for fragment in [
        "from .us_work_items import SystemImageUSWorkItemApplicationService",
        "self.us_work_items = SystemImageUSWorkItemApplicationService(workspace)",
        "self.us_work_items.sync_from_context(project_id, version_id=version_id)",
    ]:
        assert fragment in service_source

    for leaked_fragment in [
        "def _sync_us_work_items_from_context",
        "from ...domain.system_image.us_work_items import",
        "derive_us_work_items_from_context(",
        "default_asset_lanes_for_us(",
        "USItem(**decision.__dict__)",
        "AssetLane(",
        "replace_us_items(project_id, version_id, us_items)",
        "replace_asset_lanes(project_id, us_item.id, lanes)",
    ]:
        assert leaked_fragment not in service_source

    assert "SystemImageUSWorkItemApplicationService" in system_image_init
    assert '"SystemImageUSWorkItemApplicationService": ".us_work_items"' in system_image_init
    for leaked_rule in [
        "RequirementSection",
        "RequirementDocument",
        "Generate scenarios",
        "Release Assessment",
        "Waiting for scenario generation",
        "Waiting for approved scenario structure",
        "Waiting for reviewed cases",
        "Waiting for execution evidence",
        "re.search",
        "slugify_project_name",
    ]:
        assert leaked_rule not in application_source


def test_project_version_tool_handler_uses_application_service_for_write_side() -> None:
    handler_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "tool_handlers" / "project_version.py"
    ).read_text()
    registry_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "tool_handlers" / "registry.py"
    ).read_text()
    use_case_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "use_cases.py"
    ).read_text()
    quality_steps_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "quality_steps.py"
    ).read_text()
    quality_steps_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "quality_steps.py"
    ).read_text()
    project_version_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "project_versions.py"
    ).read_text()
    asset_progress_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "asset_progress.py"
    ).read_text()
    failure_report_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "failure_reports.py"
    ).read_text()
    release_readiness_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "release_readiness.py"
    ).read_text()
    quality_image_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "quality_image_updates.py"
    ).read_text()
    store_source = (ROOT / "apps" / "api" / "app" / "store.py").read_text()

    assert "ProjectVersionApplicationService" in handler_source
    assert "ToolStatusEventPort" in handler_source
    assert "ToolInvocationApplicationService" not in handler_source
    assert "AgentReplyApplicationService" in handler_source
    assert "ApplicationStore" not in handler_source
    assert "self.store" not in handler_source
    assert "_emit_tool_status" not in handler_source
    assert "append_message" not in handler_source
    assert "class ToolHandlerDependencies" in registry_source
    assert "ApplicationStore" not in registry_source
    assert "ProjectVersionToolHandler(" in registry_source
    assert "dependencies.project_versions," in registry_source
    assert "dependencies.tool_invocations," in registry_source
    assert "dependencies.agent_replies," in registry_source
    for method_name in [
        "create_project",
        "create_version",
        "connect_project_assets",
        "import_version_inputs",
        "bind_version_branch",
        "assign_version_participants",
        "initialize_version_risk",
        "start_us_task",
    ]:
        assert f"def {method_name}" in project_version_source
        assert f"self.project_version_app.{method_name}" in handler_source
    assert "class ProjectVersionApplicationService" in project_version_source
    assert "def create_project_record" in project_version_source
    assert "def create_version_record" in project_version_source
    assert "ProjectCard(" in project_version_source
    assert "VersionSummary(" in project_version_source
    assert "ReleaseReadiness(" in project_version_source
    assert "self.create_project_record(project_name)" in project_version_source
    assert "self.create_version_record(project_id, version_name)" in project_version_source
    assert "def active_or_create_quality_version" in project_version_source
    assert "return self.active_or_create_quality_version(project_id)" in project_version_source
    assert "class ProjectVersionApplicationService" not in use_case_source
    assert "def create_project_record" not in use_case_source
    assert "def create_version_record" not in use_case_source
    assert "ProjectCard(" not in use_case_source
    assert "VersionSummary(" not in use_case_source
    assert "self.tool_invocations.emit_tool_status" in handler_source
    assert "self.agent_replies.append_assistant_message" in handler_source

    create_project_block = store_source.split("def create_project", 1)[1].split(
        "\n    def get_project_workspace",
        1,
    )[0]
    create_version_block = store_source.split("def create_version", 1)[1].split(
        "\n    def get_workspace_data",
        1,
    )[0]
    for block in [create_project_block, create_version_block]:
        assert "self.project_versions." in block
        assert "ProjectVersionApplicationService(self)" not in block
        for leaked_rule in [
            "ProjectCard(",
            "VersionSummary(",
            "ReleaseReadiness(",
            "project_repository.",
            "system_image_service.ensure_state",
            "_slugify(",
        ]:
            assert leaked_rule not in block
    assert "def _slugify" not in store_source

    for leaked_dependency in [
        "self.store",
        "self.store.create_project",
        "self.store.create_version",
        "self.store.system_image_service",
        "self.store.project_repository",
        "self.store.us_items",
        "self.store.versions",
        "self.store.projects",
        "USItem",
        "uuid4",
    ]:
        assert leaked_dependency not in handler_source


def test_quality_loop_version_risk_rules_live_in_domain_policy() -> None:
    project_version_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "project_versions.py"
    ).read_text()
    policy_source = (
        ROOT / "apps" / "api" / "app" / "domain" / "quality_loop" / "version_risk.py"
    ).read_text()

    assert "from ...domain.quality_loop.version_risk import decide_version_risk" in project_version_source
    for fragment in [
        "class VersionRiskDecision",
        "class USRiskDecision",
        "def decide_us_risk",
        "def decide_version_risk",
        "HIGH_RISK_STATUSES",
        "DEFAULT_QUALITY_LOOP_NEXT_ACTION",
        "PROJECT_PROGRESS_FLOOR_AFTER_RISK_INIT",
        "Initialized version risk",
    ]:
        assert fragment in policy_source

    risk_block = project_version_source.split("def initialize_version_risk", 1)[1].split("async def start_us_task", 1)[0]
    assert "decision = decide_version_risk(items)" in risk_block
    assert "decision_by_id" in risk_block
    assert "project.risk = decision.project_risk" in risk_block
    assert "decision.project_progress_floor" in risk_block
    assert "summary=decision.summary" in risk_block
    for leaked_rule in [
        'item.status in {"blocked", "execution_failed"}',
        "item.progress < 20",
        "item.progress < 60",
        '"Start quality loop"',
        '"high" if',
        "max(project.progress, 34)",
        "Initialized version risk:",
    ]:
        assert leaked_rule not in risk_block


def test_quality_loop_version_participant_rules_live_in_domain_policy() -> None:
    project_version_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "project_versions.py"
    ).read_text()
    policy_source = (
        ROOT / "apps" / "api" / "app" / "domain" / "quality_loop" / "version_participants.py"
    ).read_text()

    assert "from ...domain.quality_loop.version_participants import" in project_version_source
    for fragment in [
        "class VersionParticipantDecision",
        "class USParticipantDecision",
        "def owner_assignments_from_payload",
        "def decide_us_participant",
        "def decide_version_participants",
        "UNASSIGNED_OWNER",
    ]:
        assert fragment in policy_source

    participant_block = project_version_source.split("def assign_version_participants", 1)[1].split(
        "def initialize_version_risk",
        1,
    )[0]
    assert "owner_assignments_from_payload(invocation.input_payload.get(\"assignments\"))" in participant_block
    assert "decision = decide_version_participants(" in participant_block
    assert "decision_by_id" in participant_block
    assert "decision.assigned_count" in participant_block
    for leaked_rule in [
        "def _owner_assignments",
        "owner_by_us.get(item.id)",
        "or item.owner",
        "owner or \"Unassigned\"",
        "isinstance(raw, dict)",
        "isinstance(raw, list)",
        "item.get(\"assignee\")",
    ]:
        assert leaked_rule not in participant_block
    assert "def _owner_assignments" not in project_version_source


def test_quality_loop_version_us_import_rules_live_in_domain_policy() -> None:
    project_version_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "project_versions.py"
    ).read_text()
    policy_source = (
        ROOT / "apps" / "api" / "app" / "domain" / "quality_loop" / "version_us_import.py"
    ).read_text()

    assert "from ...domain.quality_loop.version_us_import import" in project_version_source
    for fragment in [
        "class VersionUSImportDecision",
        "class USImportItemDecision",
        "def raw_us_items_from_payload",
        "def normalize_us_import_item",
        "def merge_us_import_item",
        "def decide_version_us_import",
        "US_INPUT_KEYS",
        "DEFAULT_US_OWNER",
        "DEFAULT_US_STATUS",
        "DEFAULT_US_RISK",
        "DEFAULT_US_PROGRESS",
        "DEFAULT_US_NEXT_ACTION",
    ]:
        assert fragment in policy_source

    import_block = project_version_source.split("def import_version_inputs", 1)[1].split(
        "def bind_version_branch",
        1,
    )[0]
    upsert_block = project_version_source.split("def _upsert_us_items", 1)[1].split("def _version", 1)[0]
    assert "raw_items = raw_us_items_from_payload(invocation.input_payload)" in import_block
    assert "decision = decide_version_us_import(" in upsert_block
    assert "id_factory=lambda: f\"us_{uuid4().hex[:8]}\"" in upsert_block
    assert "_us_item_from_import_decision(item)" in upsert_block
    assert "save_us_items(project_id, version_id, ordered)" in upsert_block
    for leaked_rule in [
        "def _raw_us_items",
        "isinstance(raw, dict)",
        "raw.get(\"us_id\")",
        "raw.get(\"summary\")",
        "Imported US",
        "Unassigned",
        '"imported"',
        "medium",
        "Start quality loop",
        "int(raw.get(\"progress\")",
        "max(item.progress, progress)",
        "item.model_copy",
        "existing = {item.id",
    ]:
        assert leaked_rule not in upsert_block
    assert "def _raw_us_items" not in project_version_source


def test_quality_loop_us_task_start_rules_live_in_domain_policy() -> None:
    project_version_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "project_versions.py"
    ).read_text()
    policy_source = (
        ROOT / "apps" / "api" / "app" / "domain" / "quality_loop" / "us_task_start.py"
    ).read_text()

    assert "from ...domain.quality_loop.us_task_start import" in project_version_source
    for fragment in [
        "class USStartTaskDecision",
        "class USStartTaskItemDecision",
        "def requested_or_first_us_id",
        "def find_start_task_target",
        "def decide_us_task_item_start",
        "def decide_us_task_start",
        "US_TASK_ANALYSIS_STATUS",
        "US_TASK_PROGRESS_FLOOR",
        "US_TASK_NEXT_ACTION",
        "US_TASK_READY_NEXT_TOOLS",
        "US_TASK_MISSING_CONTEXT_NEXT_TOOLS",
    ]:
        assert fragment in policy_source

    start_block = project_version_source.split("async def start_us_task", 1)[1].split("def query_keys_for", 1)[0]
    assert "target = find_start_task_target(items, requested_us_id)" in start_block
    assert "item_decision = decide_us_task_item_start(target)" in start_block
    assert "decision = decide_us_task_start(target, has_task_context=context is not None)" in start_block
    assert "summary=decision.summary" in start_block
    assert "assistant_message=decision.assistant_message" in start_block
    assert "next_tools=decision.next_tools" in start_block
    assert "requires_followup=decision.requires_followup" in start_block
    for leaked_rule in [
        "next(iter(",
        '"status": "analysis"',
        "max(item.progress, 18)",
        '"Generate test scope"',
        '"quality.scope.generate"',
        '"quality.scenario.generate"',
        '"system_image.context.materialize"',
        "Started quality task for",
        "Next I can generate scope",
    ]:
        assert leaked_rule not in start_block


def test_quality_loop_tool_handler_delegates_run_failure_and_release_use_cases() -> None:
    handler_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "tool_handlers" / "quality_loop.py"
    ).read_text()
    registry_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "tool_handlers" / "registry.py"
    ).read_text()
    use_case_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "use_cases.py"
    ).read_text()
    quality_steps_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "quality_steps.py"
    ).read_text()
    asset_progress_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "asset_progress.py"
    ).read_text()
    failure_report_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "failure_reports.py"
    ).read_text()
    run_execution_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "run_execution.py"
    ).read_text()
    runner_port_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "runner_port.py"
    ).read_text()
    quality_ports_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "ports.py"
    ).read_text()
    quality_repository_source = (
        ROOT
        / "apps"
        / "api"
        / "app"
        / "infrastructure"
        / "persistence"
        / "quality_loop_repository.py"
    ).read_text()
    store_source = (ROOT / "apps" / "api" / "app" / "store.py").read_text()
    release_readiness_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "release_readiness.py"
    ).read_text()
    quality_image_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "quality_image_updates.py"
    ).read_text()

    assert "QualityLoopApplicationService" in handler_source
    assert "ToolStatusEventPort" in handler_source
    assert "ToolInvocationApplicationService" not in handler_source
    assert "AgentReplyApplicationService" in handler_source
    assert "ApplicationStore" not in handler_source
    assert "self.store" not in handler_source
    assert "_emit_tool_status" not in handler_source
    assert "append_message" not in handler_source
    assert "class ToolHandlerDependencies" in registry_source
    assert "ApplicationStore" not in registry_source
    assert "QualityLoopToolHandler(" in registry_source
    assert "dependencies.quality_loop," in registry_source
    assert "dependencies.tool_invocations," in registry_source
    assert "dependencies.agent_replies," in registry_source
    for method_name in [
        "refresh_asset_pack",
        "start_run",
        "get_release_advice",
        "complete_failure_step",
        "complete_quality_step",
        "resolve_failure_scope",
        "query_keys_for",
        "running_summary",
    ]:
        assert f"def {method_name}" in use_case_source
    assert "self.tool_invocations.emit_tool_status" in handler_source
    assert "self.agent_replies.append_assistant_message" in handler_source

    migrated_blocks = [
        handler_source.split("async def refresh_asset_pack", 1)[1].split("async def generate_automation", 1)[0],
        handler_source.split("async def start_run", 1)[1].split("async def analyze_failure", 1)[0],
        handler_source.split("async def get_release_advice", 1)[1].split("async def _complete_failure_step", 1)[0],
        handler_source.split("async def _complete_failure_step", 1)[1].split("async def _complete_quality_step", 1)[0],
        handler_source.split("async def _complete_quality_step", 1)[1].split("async def _fail_missing_us", 1)[0],
    ]
    for block in migrated_blocks:
        assert "self.quality_loop_app." in block
        assert "self.store.run_orchestrator" not in block
        assert "self.store.project_repository" not in block
        assert "self.store.system_image_service" not in block
        assert "self._upsert_failure_report" not in block
        assert "self._upsert_release_readiness" not in block
        assert "self._upsert_quality_asset_part" not in block

    for migrated_helper in ["record_quality_image_update"]:
        assert f"def {migrated_helper}" not in handler_source
        assert f"def {migrated_helper}" in quality_image_source

    for migrated_helper in ["upsert_release_readiness"]:
        assert f"def {migrated_helper}" not in handler_source
        assert f"def {migrated_helper}" in release_readiness_source

    for migrated_helper in ["upsert_failure_report"]:
        assert f"def {migrated_helper}" not in handler_source
        assert f"def {migrated_helper}" in failure_report_source
    assert "QualityFailureWorkspacePort" in failure_report_source
    assert "QualityExecutionEvidenceReadPort" in failure_report_source
    assert "QualityAutomationExecutionPort" in failure_report_source
    assert "self._workspace.save_failure_analysis(" in failure_report_source
    assert "self._evidence.list_execution_evidence(project_id)" in failure_report_source
    assert "self._evidence_materializer.materialize_evidence(" in failure_report_source
    assert "ApplicationStore" not in failure_report_source
    assert "self._store" not in failure_report_source

    for migrated_helper in ["execute_automation"]:
        assert f"def {migrated_helper}" in run_execution_source
        assert "QualityRunExecutionApplicationService" in run_execution_source
        assert "QualityAutomationExecutionPort" in run_execution_source
        assert "QualityAssetPackReadPort" in run_execution_source
        assert "QualityExecutionEvidenceReadPort" in run_execution_source
        assert "self._executor.execute_automation(" in run_execution_source
        assert "self._asset_packs.get_quality_asset_pack(" in run_execution_source
        assert 'evidence_refs=[f"execution_evidence:{item.id}" for item in evidence]' in run_execution_source
        assert "ApplicationStore" not in run_execution_source
        assert "self._store" not in run_execution_source
        assert "run_execution: QualityRunExecutionApplicationService" in use_case_source
        assert "self.run_execution = run_execution" in use_case_source
        assert "self.run_execution.execute_automation(" in use_case_source
    assert "def evidence_refs_for_us" in run_execution_source
    assert "self._evidence.list_execution_evidence(project_id)" in run_execution_source
    assert "self.run_execution.evidence_refs_for_us(" in quality_steps_source
    assert "quality_steps: QualityStepCompletionApplicationService" in use_case_source
    assert "self.quality_steps = quality_steps" in use_case_source
    assert "self.quality_steps = QualityStepCompletionApplicationService(" in store_source
    assert "return await self.quality_steps.complete_quality_step(invocation, step=step)" in use_case_source
    assert "class QualityAutomationExecutionPort(Protocol)" in runner_port_source
    assert "class AutomationExecutionOutcome" in runner_port_source
    assert "class QualityAssetPackReadPort(Protocol)" in quality_ports_source
    assert "class QualityExecutionEvidenceReadPort(Protocol)" in quality_ports_source
    assert "def get_quality_asset_pack(" in quality_repository_source
    assert "def list_execution_evidence(" in quality_repository_source
    assert "self.quality_run_execution = QualityRunExecutionApplicationService(" in store_source
    assert "self.run_orchestrator," in store_source

    quality_loop_block = use_case_source.split("class QualityLoopApplicationService", 1)[1]
    assert "self._store.run_orchestrator.execute_automation(" not in quality_loop_block
    assert "self._store.execution_evidence.get(project_id, [])" not in quality_loop_block

    for migrated_helper in ["ensure_asset_lanes", "update_lane"]:
        assert f"def {migrated_helper}" not in handler_source
        assert f"def {migrated_helper}" in asset_progress_source


def test_quality_loop_release_readiness_rules_live_in_domain_policy() -> None:
    use_case_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "use_cases.py"
    ).read_text()
    release_readiness_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "release_readiness.py"
    ).read_text()
    quality_loop_init = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "__init__.py"
    ).read_text()
    store_source = (
        ROOT / "apps" / "api" / "app" / "store.py"
    ).read_text()
    policy_source = (
        ROOT / "apps" / "api" / "app" / "domain" / "quality_loop" / "release_readiness.py"
    ).read_text()

    assert "from .release_readiness import QualityReleaseReadinessApplicationService" in use_case_source
    assert "from ...domain.quality_loop.release_readiness import (" in release_readiness_source
    assert "ReleaseReadinessEvidence" in release_readiness_source
    assert "decide_release_readiness" in release_readiness_source
    assert "ReleaseReadinessRepository" in release_readiness_source
    assert "self._store" not in release_readiness_source
    assert "self._repository.load_snapshot(" in release_readiness_source
    assert "self._repository.save_assessment(" in release_readiness_source
    for fragment in [
        "class ReleaseReadinessEvidence",
        "class ReleaseReadinessDecision",
        "def decide_release_readiness",
        "REQUIRED_ASSET_PARTS",
        "execution_score",
        "quality_asset_score",
        "system_context_score",
        "governance_score",
        "score_breakdown",
        'status = "Blocked by failure analysis"',
        'status = "Ready for release review"',
        "score = min(score, 39 if fallback_count else 59)",
        "score = min(score, 84)",
        "progress_floor = 76",
        "progress_floor = 82",
    ]:
        assert fragment in policy_source

    for fragment in [
        "class QualityReleaseReadinessApplicationService",
        "def upsert_release_readiness",
        "release_readiness: QualityReleaseReadinessApplicationService",
        "self.release_readiness = release_readiness",
        "self.release_readiness.upsert_release_readiness(project_id, us_id)",
    ]:
        assert fragment in (release_readiness_source + use_case_source)
    assert (
        "self.quality_release_readiness = QualityReleaseReadinessApplicationService("
        in store_source
    )
    assert (
        "self.quality_loop_version_context.active_or_create_version"
        in store_source
    )

    release_block = release_readiness_source.split("def upsert_release_readiness", 1)[1].split(
        "__all__", 1
    )[0]
    assert "decision = decide_release_readiness(" in release_block
    assert "ReleaseReadinessEvidence(" in release_block
    assert "ReleaseReadiness(**decision.to_api_kwargs(version_id=version.id))" in release_block
    assert "decision.progress_floor" in release_block
    assert "decision.blockers" in release_block
    for leaked_rule in [
        "Blocked by failure analysis",
        "Ready for release review",
        "Release readiness is blocked because",
        "Quality loop reached release-review readiness",
        "Latest generated automation evidence passed",
        "fallback_count",
        "score=42",
        "score=86",
    ]:
        assert leaked_rule not in release_block

    quality_loop_block = use_case_source.split("class QualityLoopApplicationService", 1)[1]
    for leaked_release_rule in [
        "def _upsert_release_readiness",
        "decide_release_readiness(",
        "upsert_release_readiness(project_id, release)",
        "decision.progress_floor",
        "decision.blockers",
        "project.blocked_items",
    ]:
        assert leaked_release_rule not in quality_loop_block

    assert "QualityReleaseReadinessApplicationService" in quality_loop_init
    assert '"QualityReleaseReadinessApplicationService": ".release_readiness"' in quality_loop_init


def test_quality_loop_quality_image_updates_live_in_application_service() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    use_case_source = (app_root / "application" / "quality_loop" / "use_cases.py").read_text()
    quality_steps_source = (app_root / "application" / "quality_loop" / "quality_steps.py").read_text()
    quality_image_source = (
        app_root / "application" / "quality_loop" / "quality_image_updates.py"
    ).read_text()
    quality_loop_init = (app_root / "application" / "quality_loop" / "__init__.py").read_text()

    for fragment in [
        "class QualityImageUpdateApplicationService",
        "def record_quality_image_update",
        "def _baseline_id",
        "ContextObjectOverlay(",
        "QualityMetricSnapshot(",
        "workspace: QualityImageWorkspacePort",
        "self._workspace.list_quality_metric_snapshots(project_id)",
        "self._workspace.replace_quality_metric_snapshots(",
        "self._workspace.list_context_object_overlays(project_id)",
        "self._workspace.replace_context_object_overlays(project_id, overlays)",
        "baseline.metric_snapshot_count = len(metric_snapshots)",
        "self._workspace.persist_system_image(project_id)",
        "self._baseline_initializer(",
    ]:
        assert fragment in quality_image_source

    for fragment in [
        "from .quality_image_updates import QualityImageUpdateApplicationService",
        "quality_image_updates: QualityImageUpdateApplicationService",
        "self.quality_image_updates = quality_image_updates",
    ]:
        assert fragment in use_case_source

    for leaked_store_dependency in [
        "ApplicationStore",
        "self._store",
        "store:",
        "store.",
    ]:
        assert leaked_store_dependency not in quality_image_source
        assert leaked_store_dependency not in quality_steps_source
        assert leaked_store_dependency not in use_case_source

    for fragment in [
        "QualityImageUpdateApplicationService",
        "self.quality_image_updates.record_quality_image_update(",
    ]:
        assert fragment in quality_steps_source

    quality_loop_block = use_case_source.split("class QualityLoopApplicationService", 1)[1]
    for leaked_image_rule in [
        "def _record_quality_image_update",
        "def _baseline_id",
        "ContextObjectOverlay(",
        "QualityMetricSnapshot(",
        "quality_metric_snapshots[project_id]",
        "context_object_overlays[project_id]",
        "_persist_system_image(project_id)",
        "system_image_service._persist_system_image",
        "metric_snapshot_count =",
    ]:
        assert leaked_image_rule not in quality_loop_block

    assert "_persist_system_image" not in quality_image_source

    assert "QualityImageUpdateApplicationService" in quality_loop_init
    assert '"QualityImageUpdateApplicationService": ".quality_image_updates"' in quality_loop_init


def test_quality_loop_release_decision_rules_live_in_domain_policy() -> None:
    governance_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "governance.py"
    ).read_text()
    policy_source = (
        ROOT / "apps" / "api" / "app" / "domain" / "quality_loop" / "release_decision.py"
    ).read_text()

    assert "from ...domain.quality_loop.release_decision import decide_release_decision" in governance_source
    for fragment in [
        "class ReleaseDecisionDraft",
        "def decide_release_decision",
        "def release_decision_id",
        "def release_decision_status",
        "def release_decision_rationale",
        'return "blocked"',
        'return "conditional"',
        'return "needs_evidence"',
        'return "ready"',
        "Release decision is {status}",
    ]:
        assert fragment in policy_source

    decision_block = governance_source.split("def _decision_from_readiness", 1)[1].split(
        "def _create_merge_decision", 1
    )[0]
    assert "draft = decide_release_decision(" in decision_block
    assert "id=draft.id" in decision_block
    assert "status=draft.status" in decision_block
    assert "evidence_refs=draft.evidence_refs" in decision_block
    for leaked_rule in [
        "readiness.score < 60",
        "readiness.score < 80",
        "readiness.blockers",
        "readiness.approvals_open",
        "readiness.pending_merge",
        "not evidence_refs",
        "Release decision is",
        "evidence_count=",
        "release_decision_{project_id}",
    ]:
        assert leaked_rule not in decision_block


def test_quality_loop_quality_asset_rules_live_in_domain_policy() -> None:
    use_case_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "use_cases.py"
    ).read_text()
    quality_steps_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "quality_steps.py"
    ).read_text()
    asset_pack_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "asset_packs.py"
    ).read_text()
    asset_progress_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "asset_progress.py"
    ).read_text()
    quality_loop_init = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "__init__.py"
    ).read_text()
    policy_source = (
        ROOT / "apps" / "api" / "app" / "domain" / "quality_loop" / "quality_assets.py"
    ).read_text()
    ports_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "ports.py"
    ).read_text()
    adapter_source = (
        ROOT
        / "apps"
        / "api"
        / "app"
        / "infrastructure"
        / "quality_loop"
        / "application_ports.py"
    ).read_text()
    durable_adapter_source = (
        ROOT
        / "apps"
        / "api"
        / "app"
        / "infrastructure"
        / "quality_loop"
        / "sqlalchemy_workspaces.py"
    ).read_text()
    store_source = (
        ROOT / "apps" / "api" / "app" / "store.py"
    ).read_text()

    assert "asset_packs: QualityAssetPackApplicationService" in use_case_source
    assert "self.asset_packs = asset_packs" in use_case_source
    assert "from ...domain.quality_loop.quality_assets import" in asset_pack_source
    assert "from ...domain.quality_loop.quality_assets import" in asset_progress_source
    for fragment in [
        "class AssetLaneTemplate",
        "DEFAULT_ASSET_LANE_TEMPLATES",
        "def matches_asset_lane",
        "def next_quality_asset_part_revision",
        "def quality_asset_pack_status",
        "def quality_asset_pack_current_revision",
        "def quality_asset_pack_evidence_refs",
        "Waiting for scenario generation from system image, US, and test evidence.",
        "Waiting for approved scenario coverage and execution planning.",
        "Waiting for an approved verification plan.",
        "Waiting for reviewed cases before script generation.",
        "Waiting for quality assets and execution evidence to summarize the change.",
        "Waiting for execution evidence, the change document, and quality scoring.",
    ]:
        assert fragment in policy_source

    for fragment in [
        "class QualityAssetPackApplicationService",
        "QualityAssetPackWorkspacePort",
        "def refresh_pack",
        "def upsert_part",
        "self._workspace.get_quality_asset_pack(project_id, us_id)",
        "self._workspace.save_quality_asset_pack(pack)",
        "self.asset_packs = asset_packs",
        "self.asset_packs.refresh_pack(project_id, us_id)",
    ]:
        assert fragment in (asset_pack_source + use_case_source)
    for leaked_dependency in [
        "ApplicationStore",
        "self._store",
        "project_repository",
        "quality_asset_packs.get(",
    ]:
        assert leaked_dependency not in asset_pack_source

    assert "class QualityAssetPackWorkspacePort(Protocol)" in ports_source
    assert '"QualityAssetPackWorkspacePort": ".ports"' in quality_loop_init
    assert "class LegacyQualityAssetPackWorkspace" in adapter_source
    assert "self._state.quality_asset_packs.get(" in adapter_source
    assert "self._adapters.project_repository.upsert_quality_asset_pack(stored_pack)" in adapter_source
    assert "class SQLAlchemyQualityAssetPackWorkspace" in durable_adapter_source
    assert "self._repository.upsert_quality_asset_pack(" in durable_adapter_source
    assert "self.quality_asset_pack_workspace = SQLAlchemyQualityAssetPackWorkspace(" in store_source
    assert "self.quality_asset_pack_workspace = LegacyQualityAssetPackWorkspace(" not in store_source
    assert "self.quality_asset_pack_app = QualityAssetPackApplicationService(" in store_source

    for fragment in [
        "QualityAssetPackApplicationService",
        "self.asset_packs.upsert_part(",
    ]:
        assert fragment in quality_steps_source

    ensure_lanes_block = asset_progress_source.split("def ensure_asset_lanes", 1)[1].split(
        "def update_lane", 1
    )[0]
    assert "default_asset_lane_templates()" in ensure_lanes_block
    for leaked_rule in [
        "Waiting for scenario generation from system image, US, and test evidence.",
        "Waiting for approved scenario structure.",
        "Waiting for reviewed cases before script generation.",
        "Waiting for execution evidence and quality scoring.",
    ]:
        assert leaked_rule not in ensure_lanes_block

    asset_part_block = asset_pack_source.split("def upsert_part", 1)[1].split("def _now", 1)[0]
    for delegated_call in [
        "next_quality_asset_part_revision(parts, part_type)",
        "quality_asset_pack_status(parts)",
        "quality_asset_pack_current_revision(parts)",
        "quality_asset_pack_evidence_refs(parts)",
    ]:
        assert delegated_call in asset_part_block
    for leaked_rule in [
        "part_statuses =",
        "release_assessment\") == \"completed\"",
        "ready_for_review\", \"approved\", \"completed",
        "max(item.revision for item in parts)",
        "sorted({ref for item in parts for ref in item.evidence_refs})",
    ]:
        assert leaked_rule not in asset_part_block

    quality_loop_block = use_case_source.split("class QualityLoopApplicationService", 1)[1]
    for leaked_pack_rule in [
        "def _upsert_quality_asset_part",
        "next_quality_asset_part_revision(",
        "quality_asset_pack_status(",
        "quality_asset_pack_current_revision(",
        "quality_asset_pack_evidence_refs(",
        "upsert_quality_asset_pack(pack)",
    ]:
        assert leaked_pack_rule not in quality_loop_block

    assert "QualityAssetPackApplicationService" in quality_loop_init
    assert '"QualityAssetPackApplicationService": ".asset_packs"' in quality_loop_init


def test_quality_loop_deterministic_quality_step_plans_live_in_domain_policy() -> None:
    use_case_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "use_cases.py"
    ).read_text()
    quality_steps_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "quality_steps.py"
    ).read_text()
    policy_source = (
        ROOT / "apps" / "api" / "app" / "domain" / "quality_loop" / "quality_step_plan.py"
    ).read_text()

    assert "from ...domain.quality_loop.quality_step_plan import" in quality_steps_source
    assert "deterministic_quality_step_plan" in quality_steps_source
    assert "release_quality_step_plan" in quality_steps_source
    assert "deterministic_quality_step_plan" not in use_case_source
    assert "release_quality_step_plan" not in use_case_source
    assert "return await self.quality_steps.complete_quality_step(invocation, step=step)" in use_case_source
    for fragment in [
        "class QualityStepPlan",
        "class QualityStepLaneUpdate",
        "class QualityStepUSUpdate",
        "class QualityStepMetricUpdate",
        "class QualityStepAssetPartUpdate",
        "class ReleaseReadinessLike",
        "SUPPORTED_DETERMINISTIC_QUALITY_STEPS",
        "def automation_generation_quality_step_plan",
        "def automation_quality_step_plan",
        "def deterministic_quality_step_plan",
        "def scope_quality_step_plan",
        "def scenario_quality_step_plan",
        "def case_quality_step_plan",
        "def release_quality_step_plan",
        "Generated test scope",
        "Generated scenario pack",
        "Generated test case pack",
        "Assessed release readiness",
    ]:
        assert fragment in policy_source

    step_block = quality_steps_source.split("def complete_quality_step", 1)[1].split(
        "def _generation_request",
        1,
    )[0]
    assert "deterministic_plan = deterministic_quality_step_plan(step, us_id=us_id)" in step_block
    assert "for lane_update in deterministic_plan.lane_updates" in step_block
    assert "deterministic_plan.us_update.progress" in step_block
    assert "deterministic_plan.metric_update.metric_dict()" in step_block
    assert "deterministic_plan.asset_part_update.part_type" in step_block
    assert "next_tools = list(deterministic_plan.next_tools)" in step_block
    for leaked_rule in [
        "Generated test scope",
        "Generated scenario pack",
        "Generated test case pack",
        "Test scope is ready:",
        "8 scenario groups",
        "14 structured cases",
        "regression_focus",
        "scenario_coverage",
        "assertion_coverage",
        "Generate scenarios",
        "Generate test cases",
        "Generate automation",
        "quality.scenario.generate",
        "quality.case.generate",
        "automation.generate",
        "scope_pack",
        "scenario_set",
        "case_set",
    ]:
        assert leaked_rule not in step_block

    automation_block = use_case_source.split("def start_run", 1)[1].split(
        "def get_release_advice",
        1,
    )[0]
    assert "plan = automation_quality_step_plan(" in automation_block
    assert "if plan.requires_failure_report" in automation_block
    assert "for lane_update in plan.lane_updates" in automation_block
    assert "plan.us_update.progress" in automation_block
    assert "plan.metric_update.metric_dict()" in automation_block
    assert "plan.asset_part_update.part_type" in automation_block
    assert "next_tools=list(plan.next_tools)" in automation_block
    for leaked_rule in [
        "Generated automation",
        "Analyze failed run",
        "Assess release quality",
        "Generated Playwright-style automation",
        "Release assessment is blocked",
        "Execution evidence is ready",
        "automation_coverage",
        "latest_run_status",
        "runner_job_id",
        "task_context_id",
        "healing_required",
        "automation_blueprint",
        "Automation blueprint and smoke run",
        "release.assess",
        "healing.propose",
        "query.run.status",
    ]:
        assert leaked_rule not in automation_block

    release_block = quality_steps_source.split("elif step == \"release\"", 1)[1].split(
        "\n\n        else:",
        1,
    )[0]
    assert "release_plan = release_quality_step_plan(" in release_block
    assert "for lane_update in release_plan.lane_updates" in release_block
    assert "release_plan.us_update.progress" in release_block
    assert "release_plan.metric_update.metric_dict()" in release_block
    assert "release_plan.asset_part_update.part_type" in release_block
    assert "next_tools = list(release_plan.next_tools)" in release_block
    for leaked_rule in [
        "status=\"completed\" if not release.blockers else \"blocked\"",
        "Release readiness score is complete",
        "Formal ReleaseDecision still requires approval",
        "progress=92",
        "release_ready",
        "Request release approval",
        "Assessed release readiness",
        "release_score",
        "approvals_open",
        "pending_merge",
        "execution_health",
        "release_assessment",
        "Release readiness assessment",
        "approval.request",
        "query.version.status",
        "query.governance.status",
    ]:
        assert leaked_rule not in release_block


def test_quality_loop_failure_analysis_rules_live_in_domain_policy() -> None:
    use_case_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "use_cases.py"
    ).read_text()
    failure_report_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "failure_reports.py"
    ).read_text()
    quality_loop_init = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "__init__.py"
    ).read_text()
    policy_source = (
        ROOT / "apps" / "api" / "app" / "domain" / "quality_loop" / "failure_analysis.py"
    ).read_text()

    assert "from .failure_reports import QualityFailureReportApplicationService" in use_case_source
    assert "from ...domain.quality_loop.failure_analysis import" in failure_report_source
    for fragment in [
        "class FailureIdentity",
        "class FailureReportDecision",
        "def identify_failure",
        "def classify_failure_kind",
        "def decide_failure_report",
        "hashlib.sha256",
        "Repeated failure fingerprint reached the automatic healing limit",
        "Failure appears tied to selector/assertion drift",
    ]:
        assert fragment in policy_source

    for fragment in [
        "class QualityFailureReportApplicationService",
        "def upsert_failure_report",
        "failure_reports: QualityFailureReportApplicationService",
        "self.failure_reports = failure_reports",
        "self.failure_reports.upsert_failure_report(",
    ]:
        assert fragment in (failure_report_source + use_case_source)

    failure_block = failure_report_source.split("def upsert_failure_report", 1)[1].split(
        "@staticmethod", 1
    )[0]
    assert "identity = identify_failure(project_id, us_id, updated_run)" in failure_block
    assert "decision = decide_failure_report(" in failure_block
    assert "decision.identity.report_id" in failure_block
    assert "decision.failure_kind" in failure_block
    assert "decision.run_healing_status" in failure_block
    assert "self._workspace.list_failure_reports(project_id)" in failure_block
    assert "self._workspace.save_failure_analysis(" in failure_block
    assert "self._evidence.list_execution_evidence(project_id)" in failure_block
    assert "self._evidence_materializer.materialize_evidence(" in failure_block
    assert "replace_failure_reports(" not in failure_block
    assert "replace_runs(" not in failure_block
    for leaked_rule in [
        "hashlib.sha256",
        "def _classify_failure_kind",
        "if \"selector\" in text",
        "if \"timeout\" in text",
        "if \"network\" in text",
        "attempt_count += 1",
        "fallback_to_human = attempt_count >=",
        "Repeated failure fingerprint reached the automatic healing limit",
        "Failure appears tied to selector/assertion drift",
    ]:
        assert leaked_rule not in failure_block

    quality_loop_block = use_case_source.split("class QualityLoopApplicationService", 1)[1]
    for leaked_failure_rule in [
        "def _upsert_failure_report",
        "def _persist_run_detail",
        "identify_failure(",
        "decide_failure_report(",
        "replace_failure_reports(",
        "materialize_evidence(project_id, us_id, run)",
    ]:
        assert leaked_failure_rule not in quality_loop_block

    assert "QualityFailureReportApplicationService" in quality_loop_init
    assert '"QualityFailureReportApplicationService": ".failure_reports"' in quality_loop_init


def test_quality_loop_failure_progress_rules_live_in_domain_policy() -> None:
    use_case_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "use_cases.py"
    ).read_text()
    policy_source = (
        ROOT / "apps" / "api" / "app" / "domain" / "quality_loop" / "failure_loop_progress.py"
    ).read_text()

    assert "from ...domain.quality_loop.failure_loop_progress import decide_failure_loop_progress" in use_case_source
    for fragment in [
        "class FailureLoopProgressDecision",
        "def failure_loop_summary",
        "def failure_loop_next_tools",
        "def decide_failure_loop_progress",
        "FAILURE_LOOP_PLANNER_KIND",
        "FAILURE_ANALYSIS_SUMMARY",
        "FAILURE_HEALING_SUMMARY",
        "FAILURE_FALLBACK_SUMMARY",
        "FAILURE_ANALYSIS_NEXT_TOOLS",
        "FAILURE_FALLBACK_NEXT_TOOLS",
    ]:
        assert fragment in policy_source

    failure_block = use_case_source.split("def complete_failure_step", 1)[1].split(
        "def complete_quality_step",
        1,
    )[0]
    assert "decision = decide_failure_loop_progress(" in failure_block
    assert "summary=decision.summary" in failure_block
    assert "next_tools=decision.next_tools" in failure_block
    assert "assistant_message=decision.assistant_message" in failure_block
    assert '"planner_kind": decision.planner_kind' in failure_block
    assert '"fallback_to_human": decision.fallback_to_human' in failure_block
    for leaked_rule in [
        "Healing proposal reached max depth",
        "Prepared bounded healing proposal",
        "Analyzed failed run and created FailureReport",
        "next_tools = [\"query.run.status\"]",
        "next_tools.extend",
        "next_tools.append(\"healing.propose\")",
        "Failure fingerprint `",
        '"planner_kind": "failure_loop_progress"',
    ]:
        assert leaked_rule not in failure_block


def test_quality_loop_step_guidance_rules_live_in_domain_policy() -> None:
    use_case_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "use_cases.py"
    ).read_text()
    quality_steps_source = (
        ROOT / "apps" / "api" / "app" / "application" / "quality_loop" / "quality_steps.py"
    ).read_text()
    policy_source = (
        ROOT / "apps" / "api" / "app" / "domain" / "quality_loop" / "step_guidance.py"
    ).read_text()

    assert "from ...domain.quality_loop.step_guidance import" in quality_steps_source
    assert "from ...domain.quality_loop.step_guidance import" not in use_case_source
    for fragment in [
        "class QualityStepGuidance",
        "DEFAULT_QUALITY_STEP_GUIDANCE",
        "QUALITY_STEP_GUIDANCE",
        "def quality_step_guidance",
        "def quality_step_running_summary",
        "def quality_step_assistant_followup",
        "Generating scenario pack",
        "Generating test scope from system image context",
        "The quality loop is ready for human release review or governance follow-up.",
        "I will continue with the next quality-loop step.",
    ]:
        assert fragment in policy_source

    running_summary_block = quality_steps_source.split("def running_summary", 1)[1].split(
        "def assistant_followup", 1
    )[0]
    assistant_followup_block = quality_steps_source.split("def assistant_followup", 1)[1].split(
        "__all__", 1
    )[0]
    assert "return quality_step_running_summary(step)" in running_summary_block
    assert "return quality_step_assistant_followup(step)" in assistant_followup_block
    assert "return QualityStepCompletionApplicationService.running_summary(step)" in use_case_source
    assert "return QualityStepCompletionApplicationService.assistant_followup(step)" in use_case_source

    for leaked_rule in [
        "Generating scenario pack",
        "Generating structured test cases",
        "Generating automation and execution evidence",
        "Generating test scope from system image context",
        "Assessing release readiness",
        "Next I will turn the approved scenario structure into executable test cases.",
        "I will continue with the next quality-loop step.",
    ]:
        assert leaked_rule not in use_case_source


def test_governance_tool_handler_uses_application_service_for_write_side() -> None:
    handler_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "tool_handlers" / "governance.py"
    ).read_text()
    registry_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "tool_handlers" / "registry.py"
    ).read_text()
    use_case_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "governance.py"
    ).read_text()

    assert "GovernanceApplicationService" in handler_source
    assert "ToolStatusEventPort" in handler_source
    assert "ToolInvocationApplicationService" not in handler_source
    assert "ApplicationStore" not in handler_source
    assert "self.store" not in handler_source
    assert "_emit_tool_status" not in handler_source
    assert "class ToolHandlerDependencies" in registry_source
    assert "ApplicationStore" not in registry_source
    assert "GovernanceToolHandler(dependencies.governance, dependencies.tool_invocations)" in registry_source
    for method_name in [
        "request_approval",
        "decide_approval",
        "merge_resolution",
        "submit_release_decision",
        "promote_baseline",
        "query_keys_for",
        "project_id_for",
    ]:
        assert f"def {method_name}" in use_case_source
    for method_name in [
        "request_approval",
        "decide_approval",
        "merge_resolution",
        "submit_release_decision",
        "promote_baseline",
        "query_keys_for",
    ]:
        assert f"self.governance_app.{method_name}" in handler_source
    assert "self.tool_invocations.emit_tool_status" in handler_source

    for leaked_dependency in [
        "self.store",
        "self.store.projects",
        "self.store.approval_details",
        "self.store.approvals",
        "self.store.release_readiness",
        "self.store.project_repository",
        "self.store.release_decisions",
        "self.store.baselines",
        "self.store._current_release_decision",
        "ApprovalDetail",
        "BaselineRecord",
        "ReleaseDecision",
        "uuid4",
    ]:
        assert leaked_dependency not in handler_source

    for migrated_helper in [
        "_require_project",
        "_upsert_approval",
        "_decision_from_readiness",
        "_approval_title",
        "_string_list",
    ]:
        assert f"def {migrated_helper}" not in handler_source
        assert f"def {migrated_helper}" in use_case_source


def test_query_tool_handler_uses_application_service_for_read_model_queries() -> None:
    store_source = (ROOT / "apps" / "api" / "app" / "store.py").read_text()
    handler_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "tool_handlers" / "query.py"
    ).read_text()
    registry_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "tool_handlers" / "registry.py"
    ).read_text()
    use_case_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "query_tools.py"
    ).read_text()
    read_model_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "read_models.py"
    ).read_text()
    read_port_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "read_query_ports.py"
    ).read_text()
    query_adapter_source = (
        ROOT / "apps" / "api" / "app" / "infrastructure" / "platform" / "query_read_model.py"
    ).read_text()
    agent_reply_source = (
        ROOT / "apps" / "api" / "app" / "application" / "agent" / "replies.py"
    ).read_text()
    agent_reply_ports_source = (
        ROOT / "apps" / "api" / "app" / "application" / "agent" / "reply_ports.py"
    ).read_text()

    tool_invocation_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "tool_invocations.py"
    ).read_text()

    assert "QueryToolApplicationService" in handler_source
    assert "ToolStatusEventPort" in handler_source
    assert "ToolInvocationApplicationService" not in handler_source
    assert "ApplicationStore" not in handler_source
    assert "self.store" not in handler_source
    assert "_emit_tool_status" not in handler_source
    assert "class ToolHandlerDependencies" in registry_source
    assert "ApplicationStore" not in registry_source
    assert "QueryToolHandler(dependencies.queries, dependencies.tool_invocations)" in registry_source
    assert "ReadModelSummaryService" in use_case_source
    assert "AgentReplyApplicationService" in use_case_source
    assert "AgentQueryReadPort" in use_case_source
    assert "class AgentQueryReadPort(Protocol)" in read_port_source
    assert "class TopLevelContentReadPort(Protocol)" in read_port_source
    assert "class CompatibilityPlatformQueryReadModel" in query_adapter_source
    assert "class SQLAlchemyAgentQueryReadModel" in query_adapter_source
    assert "AgentQueryReadPort" in query_adapter_source
    assert "TopLevelContentReadPort" in query_adapter_source
    assert "SQLAlchemyAgentQueryReadModel(" in store_source
    assert "CompatibilityPlatformQueryReadModel(" not in store_source
    for method_name in ["plan", "answer", "persist_answer", "complete"]:
        assert f"def {method_name}" in use_case_source
        assert f"self.query_app.{method_name}" in handler_source
    assert "def emit_tool_status" in tool_invocation_source
    assert "self._events.emit_tool_status" in tool_invocation_source
    assert "self._store._emit_tool_status" not in tool_invocation_source
    assert "self.tool_invocations.emit_tool_status" in handler_source
    for port_name in [
        "AgentReplyMemoryPort",
        "AgentReplyGenerationPort",
        "AgentReplyModelSettingsPort",
        "AgentReplyMessageWriterPort",
    ]:
        assert f"class {port_name}(Protocol)" in agent_reply_ports_source
        assert port_name in agent_reply_source
    for dependency in [
        "self._memory = memory",
        "self._generation = generation",
        "self._model_settings = model_settings",
        "self._messages = messages",
        "self._model_settings.get_custom_model_api_key(\"chat\")",
        "self._messages.append_text_message",
    ]:
        assert dependency in agent_reply_source
    for forbidden_dependency in [
        "ApplicationStore",
        "self._store",
        "ModelConfigurationApplicationService(",
    ]:
        assert forbidden_dependency not in agent_reply_source
        assert forbidden_dependency not in agent_reply_ports_source
    for forbidden_dependency in ["ApplicationStore", "self._store", "self.store"]:
        assert forbidden_dependency not in use_case_source
        assert forbidden_dependency not in read_model_source
        assert forbidden_dependency not in read_port_source
    for method_name in ["generate_reply", "append_assistant_message"]:
        assert f"def {method_name}" in agent_reply_source
        assert f"self._agent_replies.{method_name}" in use_case_source

    for leaked_dependency in [
        "self.store.conversations",
        "self.store.versions",
        "self.store._build_dashboard_summary",
        "self.store._project_status_summary",
        "self.store._version_status_summary",
        "self.store._workspace_status_summary",
        "self.store._knowledge_status_summary",
        "self.store._system_image_status_summary",
        "self.store._run_status_summary",
        "self.store._governance_status_summary",
        "self.store._generate_llm_content",
        "self.store.append_message",
    ]:
        assert leaked_dependency not in handler_source

    assert "ToolResult(" not in handler_source
    assert "ToolResult(" in use_case_source
    for method_name in [
        "dashboard_summary",
        "project_status_summary",
        "version_status_summary",
        "workspace_status_summary",
        "knowledge_status_summary",
        "system_image_status_summary",
        "run_status_summary",
        "governance_status_summary",
        "conversation_summary_fallback",
    ]:
        assert f"def {method_name}" in read_model_source

    for leaked_summary_call in [
        "_build_dashboard_summary",
        "_project_status_summary",
        "_version_status_summary",
        "_workspace_status_summary",
        "_knowledge_status_summary",
        "_system_image_status_summary",
        "_run_status_summary",
        "_governance_status_summary",
    ]:
        assert f"self._store.{leaked_summary_call}" not in use_case_source
    assert "self._store._generate_llm_content" not in use_case_source
    assert "self._store.append_message" not in use_case_source
    for removed_store_facade in [
        "def _conversation_system_prompt",
        "def _conversation_context_snapshot",
        "async def _generate_llm_content",
        "def _build_dashboard_summary",
        "def _project_status_summary",
        "def _version_status_summary",
        "def _workspace_status_summary",
        "def _knowledge_status_summary",
        "def _system_image_status_summary",
        "def _recent_project_agent_memory_summary",
        "def _run_status_summary",
        "def _governance_status_summary",
        "def _read_model_summaries",
    ]:
        assert removed_store_facade not in store_source


def test_conversation_message_orchestration_lives_in_agent_application_service() -> None:
    store_source = (ROOT / "apps" / "api" / "app" / "store.py").read_text()
    agent_use_case_source = (
        ROOT / "apps" / "api" / "app" / "application" / "agent" / "use_cases.py"
    ).read_text()
    message_source = (
        ROOT / "apps" / "api" / "app" / "application" / "agent" / "messages.py"
    ).read_text()
    message_writer_source = (
        ROOT / "apps" / "api" / "app" / "application" / "agent" / "message_writer.py"
    ).read_text()

    assert "self._messages = messages" in agent_use_case_source
    for delegated_message_fragment in [
        "return await self._messages.post_message(",
        "conversation_id,",
        "payload.content,",
        "canonical_action_id=payload.canonical_action_id,",
    ]:
        assert delegated_message_fragment in agent_use_case_source

    for fragment in [
        "ConversationMessageRuntimePort",
        "async def post_message",
        "def pending_confirmation_invocation",
        "def handle_confirmation_message_if_any",
        "def handle_source_binding_message_if_any",
        "self._runtime.plan_message",
        "ToolInvocationRequest(",
        "self._runtime.start_goal_from_proposal",
        "self._runtime.is_paused_goal(goal_id)",
        "self._runtime.get_tool_invocation(invocation.id)",
        "self._runtime.list_tool_invocations(",
        "self._runtime.project_goal(active_goal)",
        "self._runtime.record_source_binding_received(",
        'tool_id="query.answer"',
        "source_binding_received",
        "waiting_confirmation",
    ]:
        assert fragment in message_source
    assert "self._store.agent_goals" not in message_source
    assert "goal_id in self._store.agent_goals" not in message_source
    assert "self._store.tool_invocations" not in message_source
    assert "self._store" not in message_source
    assert "conversation_repository" not in message_source

    for fragment in [
        "class ConversationMessageWriterApplicationService",
        "async def append_text_message",
        "ConversationMessage(",
        "MessageBlock(type=\"text\"",
        "ConversationMessageStatePort",
        "AgentConversationEventPublisherPort",
        "self._state.persist_message(conversation, message)",
        "self._state.maybe_create_summary_checkpoint(conversation)",
        "self._events.publish_message_created(conversation_id, message)",
    ]:
        assert fragment in message_writer_source
    for leaked_message_writer_dependency in [
        "ApplicationStore",
        "conversation_repository",
        "conversation_summary_checkpoints_app",
        "PlatformEventApplicationService",
        "from ...store",
    ]:
        assert leaked_message_writer_dependency not in message_writer_source

    def store_method_block(method_name: str) -> str:
        match = re.search(
            rf"\n    (?:async\s+)?def {method_name}\(.*?(?=\n    (?:async\s+)?def |\nclass InMemoryStore\b)",
            store_source,
            flags=re.DOTALL,
        )
        assert match is not None
        return match.group(0)

    handle_message_block = store_method_block("handle_message")
    assert "self.conversation_messages.post_message" in handle_message_block
    assert ".post_message(conversation_id, content)" in handle_message_block
    for leaked_orchestration in [
        "self.planner.plan",
        "_handle_source_binding_message_if_any",
        "_handle_confirmation_message_if_any",
        "ToolInvocationRequest(",
        "agent_service.start_from_proposal",
        "decision.kind",
    ]:
        assert leaked_orchestration not in handle_message_block

    for method_name, delegated_call in [
        (
            "_pending_confirmation_invocation",
            ".pending_confirmation_invocation(conversation_id, content)",
        ),
        (
            "_handle_confirmation_message_if_any",
            ".handle_confirmation_message_if_any(conversation_id, content)",
        ),
        (
            "_handle_source_binding_message_if_any",
            ".handle_source_binding_message_if_any(conversation_id, content)",
        ),
    ]:
        method_block = store_method_block(method_name)
        assert "self.conversation_messages." in method_block
        assert delegated_call in method_block
        for leaked_message_fragment in [
            "tool_[a-f0-9]+",
            "waiting_confirmation",
            "source_binding_received",
            "system_image.sources.register",
            "ConversationOrchestrator",
            "is_confirmation_message",
            "agent_service.resume_goal",
            "ToolInvocationRequest(",
        ]:
            assert leaked_message_fragment not in method_block
    assert "self.conversation_messages = ConversationMessageApplicationService(" in store_source
    assert "self.agent_application_ports.conversation_runtime" in store_source
    assert "def _conversation_message_app" not in store_source

    append_message_block = store_method_block("append_message")
    assert "self.conversation_message_writer.append_text_message(" in append_message_block
    for leaked_writer_fragment in [
        "ConversationMessage(",
        "MessageBlock(",
        "conversation_repository.append_message",
        "conversation_repository.upsert_conversation",
        "conversation.message.created",
        "_push_event(",
        "uuid4().hex",
    ]:
        assert leaked_writer_fragment not in append_message_block


def test_conversation_management_lives_in_agent_application_service() -> None:
    store_source = (ROOT / "apps" / "api" / "app" / "store.py").read_text()
    agent_use_case_source = (
        ROOT / "apps" / "api" / "app" / "application" / "agent" / "use_cases.py"
    ).read_text()
    conversation_source = (
        ROOT / "apps" / "api" / "app" / "application" / "agent" / "conversations.py"
    ).read_text()
    scope_resolution_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "scope_resolution.py"
    ).read_text()
    scope_projection_source = (
        ROOT / "apps" / "api" / "app" / "infrastructure" / "platform" / "scope_resolution.py"
    ).read_text()
    agent_package_source = (
        ROOT / "apps" / "api" / "app" / "application" / "agent" / "__init__.py"
    ).read_text()
    platform_package_source = (
        ROOT / "apps" / "api" / "app" / "application" / "platform" / "__init__.py"
    ).read_text()

    for fragment in [
        "class ConversationManagementApplicationService",
        "def resolve_conversation_scope",
        "ConversationManagementStatePort",
        "self._state.resolve_scope(",
        "def get_or_create_conversation",
        "ConversationSession(",
        "self._state.persist_conversation(conversation",
        "def list_conversations",
        "def list_conversation_messages",
        "def archive_conversation",
        "def merge_conversations",
        "ConversationLink(",
        "def search_conversations",
        "message_hits.append",
        "related_links",
    ]:
        assert fragment in conversation_source
    for leaked_cross_domain_read in [
        "self._store",
        "conversation_repository",
        "ProjectScopeResolutionApplicationService",
        "self._store.versions.items()",
        "self._store.us_items.items()",
        "self._store.versions[resolved_project_id]",
    ]:
        assert leaked_cross_domain_read not in conversation_source

    for fragment in [
        "class ProjectScopeReadPort(Protocol)",
        "class ProjectScopeResolutionApplicationService",
        "def resolve_conversation_scope",
        "self._state.project_id_for_version(space_id)",
        "self._state.project_id_for_us(resolved_us_id)",
        "self._state.first_version_id(",
    ]:
        assert fragment in scope_resolution_source
    for leaked_storage_detail in [
        "ApplicationStore",
        "self._store",
        ".versions.items()",
        ".us_items.items()",
    ]:
        assert leaked_storage_detail not in scope_resolution_source
    for fragment in [
        "class CompatibilityProjectScopeProjection",
        "class SQLAlchemyProjectScopeReadModel",
        "def project_id_for_version",
        "def project_id_for_us",
        "def first_version_id",
    ]:
        assert fragment in scope_projection_source
    assert "ApplicationStore" not in scope_projection_source
    assert "SQLAlchemyProjectScopeReadModel," in store_source
    assert "SQLAlchemyProjectScopeReadModel()" in store_source
    assert "CompatibilityProjectScopeProjection(" not in store_source
    assert "ProjectScopeResolutionApplicationService" in platform_package_source
    assert '"ProjectScopeResolutionApplicationService": ".scope_resolution"' in platform_package_source

    assert "ConversationManagementApplicationService" in agent_package_source
    assert "self._conversations = conversations" in agent_use_case_source
    for delegated_call in [
        "self._conversations.ensure_conversation(payload)",
        "self._conversations.list_conversations(",
        "self._conversations.search_conversations(q)",
        "self._conversations.get_conversation(conversation_id)",
        "self._conversations.list_conversation_messages(conversation_id, before_message_id)",
        "self._conversations.archive_conversation(conversation_id, payload)",
        "self._conversations.merge_conversations(conversation_id, payload)",
    ]:
        assert delegated_call in agent_use_case_source

    for leaked_call in [
        "self._store.get_or_create_conversation(",
        "self._store.list_conversations(",
        "self._store.search_conversations(",
        "self._store.get_conversation(conversation_id)",
        "self._store.list_conversation_messages(",
        "self._store.archive_conversation(",
        "self._store.merge_conversations(",
    ]:
        assert leaked_call not in agent_use_case_source

    compatibility_source = store_source.split("class ApplicationRuntime:", 1)[1]
    assembly_source = store_source.split("class RuntimeAssembly:", 1)[1].split(
        "class ApplicationRuntime:",
        1,
    )[0]
    assert "def get_or_create_conversation(" in assembly_source
    assert "self.conversation_management.get_or_create_conversation(" in assembly_source

    for method_name, delegated_call, next_marker in [
        ("_resolve_conversation_scope", ".resolve_conversation_scope(", "\n    def list_conversations"),
        ("list_conversations", ".list_conversations(", "\n    def get_conversation"),
        ("get_conversation", ".get_conversation(conversation_id)", "\n    def list_conversation_messages"),
        (
            "list_conversation_messages",
            ".list_conversation_messages(conversation_id, before_message_id)",
            "\n    def archive_conversation",
        ),
        ("archive_conversation", ".archive_conversation(conversation_id, payload)", "\n    def merge_conversations"),
        ("merge_conversations", ".merge_conversations(conversation_id, payload)", "\n    def search_conversations"),
        ("search_conversations", ".search_conversations(q)", "\n    async def create_tool_invocation"),
    ]:
        method_block = compatibility_source.split(f"def {method_name}", 1)[1].split(next_marker, 1)[0]
        assert "self.conversation_management." in method_block
        assert delegated_call in method_block
        for leaked_rule in [
            "ConversationSession(",
            "ConversationLink(",
            "message_hits",
            "related_links",
            "conversation_repository.upsert_conversation",
            "target.messages.extend",
            "merged_into_conversation_id",
            "uuid4().hex",
        ]:
            assert leaked_rule not in method_block
    assert "self.conversation_management = ConversationManagementApplicationService(" in store_source
    assert "self.agent_application_ports.conversation_management" in store_source
    assert "def _conversation_management_app" not in store_source


def test_conversation_summary_checkpoint_policy_lives_in_agent_application_service() -> None:
    store_source = (ROOT / "apps" / "api" / "app" / "store.py").read_text()
    service_source = (
        ROOT / "apps" / "api" / "app" / "application" / "agent" / "conversation_summary.py"
    ).read_text()
    message_writer_source = (
        ROOT / "apps" / "api" / "app" / "application" / "agent" / "message_writer.py"
    ).read_text()

    assert "class ConversationSummaryCheckpointService" in service_source
    assert "class ConversationSummaryCheckpointApplicationService" in service_source
    for fragment in [
        "def completed_text_messages",
        "def latest_checkpoint",
        "def build_checkpoint",
        "def _summary_lines",
        "ConversationSummaryCheckpoint(",
        "message_range_start=messages_to_summarize[0].id",
        "summary_token_count=len",
        "ConversationSummaryStatePort",
        "AgentConversationEventPublisherPort",
        "async def maybe_create_checkpoint",
        "self._state.persist_summary_checkpoint(conversation, checkpoint)",
        "self._events.publish_summary_updated(conversation.id, checkpoint.id)",
    ]:
        assert fragment in service_source
    for leaked_checkpoint_dependency in [
        "ApplicationStore",
        "conversation_repository",
        "PlatformEventApplicationService",
        "from ...store",
    ]:
        assert leaked_checkpoint_dependency not in service_source

    assert "self.conversation_summaries = ConversationSummaryCheckpointService()" in store_source
    assert "self.conversation_summary_checkpoints_app = ConversationSummaryCheckpointApplicationService(" in store_source
    assert "self.agent_application_ports.conversation_summaries" in store_source
    assert "self.agent_application_ports.events" in store_source
    assert "await self._state.maybe_create_summary_checkpoint(conversation)" in message_writer_source
    for leaked_store_method in [
        "def _recent_text_messages",
        "def _latest_checkpoint_for_conversation",
        "def _build_summary_checkpoint",
        "def _conversation_history_snapshot",
        "async def _maybe_create_summary_checkpoint",
    ]:
        assert leaked_store_method not in store_source


def test_agent_goal_lifecycle_lives_in_agent_application_layer() -> None:
    compatibility_source = (ROOT / "apps" / "api" / "app" / "agent_service.py").read_text()
    lifecycle_source = (
        ROOT / "apps" / "api" / "app" / "application" / "agent" / "lifecycle.py"
    ).read_text()
    agent_package_source = (
        ROOT / "apps" / "api" / "app" / "application" / "agent" / "__init__.py"
    ).read_text()
    ports_source = (
        ROOT / "apps" / "api" / "app" / "application" / "agent" / "ports.py"
    ).read_text()
    adapter_source = (
        ROOT / "apps" / "api" / "app" / "infrastructure" / "agent" / "application_ports.py"
    ).read_text()

    assert "from .application.agent.lifecycle import *" in compatibility_source
    assert "AgentService = AgentGoalLifecycleApplicationService" not in compatibility_source
    assert "class AgentService" not in compatibility_source
    store_source = (ROOT / "apps" / "api" / "app" / "store.py").read_text()
    assert "from .application.agent.lifecycle import AgentService" in store_source
    assert "from .agent_service import AgentService" not in store_source
    for migrated_fragment in [
        "class AgentGoalLifecycleApplicationService",
        "AgentService = AgentGoalLifecycleApplicationService",
        "__all__",
        "async def start_from_proposal",
        "def create_manual_goal",
        "def create_goal_record",
        "def is_paused_goal",
        "async def resume_goal",
        "async def interrupt_goal",
        "async def add_feedback",
        "def active_goal_for_conversation",
        "AgentGoal(",
        "AgentStep(id=\"step_context\"",
        "workflow_id=f\"wf_",
        "AgentGoalLifecycleStatePort",
        "self._state.create_goal(goal)",
        "self._state.record_goal_audit(",
        "self._state.persist_goal(goal)",
        "self._state.publish_interrupted(goal)",
        "self._state.publish_feedback(goal, feedback)",
        "self._state.append_assistant_message(",
        "self._state.list_goals_for_conversation(conversation_id)",
    ]:
        assert migrated_fragment in lifecycle_source
    for leaked_lifecycle_dependency in [
        "ApplicationStore",
        "self.store",
        "self._store",
        "PlatformEventApplicationService",
        "AgentGoalProjectionApplicationService",
        "conversation_repository",
        "record_agent_goal_audit_event",
    ]:
        assert leaked_lifecycle_dependency not in lifecycle_source
    assert "class AgentGoalLifecycleStatePort(Protocol)" in ports_source
    assert "class LegacyAgentGoalLifecycleStateAdapter" in adapter_source
    assert "self.goal_lifecycle = LegacyAgentGoalLifecycleStateAdapter(" in adapter_source
    lifecycle_adapter_block = adapter_source.split(
        "class LegacyAgentGoalLifecycleStateAdapter",
        1,
    )[1].split("class LegacyAgentLoopStateAdapter", 1)[0]
    assert "self._store" not in lifecycle_adapter_block
    assert "AgentGoalLifecycleAdapters" in lifecycle_adapter_block
    assert "self.agent_application_ports.goal_lifecycle" in store_source
    assert "AgentGoalLifecycleApplicationService" in agent_package_source

    create_goal_block = store_source.split("def create_agent_goal", 1)[1].split(
        "\n    def get_agent_goal",
        1,
    )[0]
    assert "return self.agent_service.create_goal_record(payload)" in create_goal_block
    for leaked_creation_fragment in [
        "AgentGoal(",
        "AgentStep(",
        "workflow_id=f\"wf_",
        "self.agent_goals[goal.id]",
        "record_agent_goal_audit_event(",
    ]:
        assert leaked_creation_fragment not in create_goal_block

    get_goal_block = store_source.split("def get_agent_goal", 1)[1].split(
        "\n    def get_agent_goal_checkpoint",
        1,
    )[0]
    assert "return self.agent_service.get_goal(goal_id)" in get_goal_block
    for leaked_read_fragment in [
        "return self.agent_goals[goal_id]",
        "self.agent_goals.get(",
    ]:
        assert leaked_read_fragment not in get_goal_block

    checkpoint_block = store_source.split("def get_agent_goal_checkpoint", 1)[1].split(
        "\n    def get_agent_goal_explanation",
        1,
    )[0]
    assert "return self.agent_service.get_checkpoint(goal_id)" in checkpoint_block
    for leaked_checkpoint_fragment in [
        "self.agent_workflow_runtime.checkpoint(goal_id)",
        "self.agent_loop_runtime.checkpoint(goal_id)",
    ]:
        assert leaked_checkpoint_fragment not in checkpoint_block


def test_agent_goal_conversation_projection_lives_in_agent_application_layer() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    projection_source = (app_root / "application" / "agent" / "goal_projection.py").read_text()
    lifecycle_source = (app_root / "application" / "agent" / "lifecycle.py").read_text()
    graph_source = (app_root / "application" / "agent" / "graph.py").read_text()
    messages_source = (app_root / "application" / "agent" / "messages.py").read_text()
    agent_package_source = (app_root / "application" / "agent" / "__init__.py").read_text()
    workflow_factory_source = (
        app_root / "infrastructure" / "workflow" / "agent_workflow_factory.py"
    ).read_text()
    workflow_worker_source = (
        app_root / "infrastructure" / "workflow" / "agent_goal_workflow_worker.py"
    ).read_text()
    workflow_activity_source = (
        app_root / "application" / "agent" / "activities.py"
    ).read_text()
    store_source = (app_root / "store.py").read_text()
    adapter_source = (
        app_root / "infrastructure" / "agent" / "application_ports.py"
    ).read_text()

    for fragment in [
        "class AgentGoalProjectionApplicationService",
        "def upsert_in_conversation",
        "AgentGoalProjectionStatePort",
        "conversation = self._state.get_conversation(goal.conversation_id)",
        "conversation.agent_goals.append(goal)",
        "conversation.agent_goals[existing_index] = goal",
        "self._state.persist_goal_projection(conversation, goal)",
    ]:
        assert fragment in projection_source
    for leaked_projection_dependency in [
        "self._store",
        "ApplicationStore",
        "conversation_repository",
    ]:
        assert leaked_projection_dependency not in projection_source

    assert "AgentGoalProjectionApplicationService" in agent_package_source
    assert '"AgentGoalProjectionApplicationService": ".goal_projection"' in agent_package_source

    assert "AgentGoalProjectionApplicationService" not in graph_source
    assert "self._state.persist_goal(goal)" in graph_source
    assert "conversation_repository.upsert_goal(goal)" not in graph_source
    assert "AgentGoalProjectionApplicationService" not in workflow_factory_source
    assert "AgentWorkflowStatePort" in workflow_factory_source
    assert "workflow_state.accept_remote_goal" in workflow_factory_source
    assert "AgentGoalProjectionApplicationService" not in workflow_worker_source
    assert "self._goal_projector.upsert_in_conversation(goal)" in workflow_activity_source
    assert "_upsert_goal_in_conversation" not in workflow_worker_source
    assert "self._state.persist_goal(goal)" in lifecycle_source
    assert "AgentGoalProjectionApplicationService" not in lifecycle_source
    assert "self._runtime.project_goal(active_goal)" in messages_source
    assert "AgentGoalProjectionApplicationService" not in messages_source
    assert "class LegacyAgentGoalProjectionStateAdapter" in adapter_source
    assert "def persist_goal_projection(" in adapter_source
    projection_adapter_block = adapter_source.split(
        "class LegacyAgentGoalProjectionStateAdapter",
        1,
    )[1].split("class LegacyAgentGoalLifecycleStateAdapter", 1)[0]
    assert "self._persistence.upsert_goal(goal)" in projection_adapter_block
    assert "self._store" not in projection_adapter_block

    store_block = store_source.split("def _upsert_goal_in_conversation", 1)[1].split(
        "\n    def _upsert_invocation_in_conversation",
        1,
    )[0]
    assert "self.agent_goal_projection.upsert_in_conversation(goal)" in store_block
    assert "AgentGoalProjectionApplicationService(self)" not in store_block
    for leaked_projection_fragment in [
        "existing_index",
        "conversation.agent_goals.append",
        "conversation.agent_goals[",
        "conversation_repository.upsert_goal(goal)",
        "conversation_repository.upsert_conversation(conversation)",
    ]:
        assert leaked_projection_fragment not in store_block


def test_agent_goal_explanation_read_model_lives_in_agent_application_layer() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    explanations_source = (app_root / "application" / "agent" / "explanations.py").read_text()
    use_cases_source = (app_root / "application" / "agent" / "use_cases.py").read_text()
    agent_package_source = (app_root / "application" / "agent" / "__init__.py").read_text()
    store_source = (app_root / "store.py").read_text()

    for fragment in [
        "class AgentGoalExplanationApplicationService",
        "def get_explanation",
        "def _step_explanation",
        "def _waiting_on",
        "def _next_action",
        "def _reasoning_summary",
        "tool_invocation_refs",
        "memory_refs",
        "audit_event_refs",
        "goal = self._queries.get_goal(goal_id)",
        "checkpoint = self._queries.get_checkpoint(goal_id)",
        "def _tool_invocation_or_none",
        "self._queries.get_tool_invocation(invocation_id)",
        'self._queries.list_agent_memory_items(source_ref=f"agent_goal:{goal_id}")',
    ]:
        assert fragment in explanations_source

    for leaked_lifecycle_read in [
        "ApplicationStore",
        "from ...store",
        "self.store",
        "agent_service",
        "agent_workflow_runtime",
    ]:
        assert leaked_lifecycle_read not in explanations_source

    for dependency_fragment in [
        "from .agent_models import AgentGoal, AgentStep",
        "from .ports import AgentGoalExplanationQueryPort",
        "from ..platform.tool_models import ToolInvocation",
    ]:
        assert dependency_fragment in explanations_source

    assert "from .explanations import AgentGoalExplanationApplicationService" in use_cases_source
    assert "self._explanations = explanations" in use_cases_source
    assert "return self._explanations.get_explanation(goal_id)" in use_cases_source
    assert "AgentGoalExplanationApplicationService" in agent_package_source
    assert '"AgentGoalExplanationApplicationService": ".explanations"' in agent_package_source

    assert "from .application.agent.explanations import AgentGoalExplanationApplicationService" in store_source
    assert "self.agent_application_ports.goal_explanations" in store_source
    method_block = store_source.split("def get_agent_goal_explanation", 1)[1].split(
        "\n    def get_agent_memory_context",
        1,
    )[0]
    assert "return self.agent_goal_explanations.get_explanation(goal_id)" in method_block
    for forbidden_fragment in [
        "checkpoint.current_step_index",
        "blocked_invocation",
        "latest_think_step",
        "tool_invocation_refs",
        "reasoning_summary",
    ]:
        assert forbidden_fragment not in method_block

    for migrated_helper in [
        "def _agent_step_explanation",
        "def _agent_goal_waiting_on",
        "def _agent_goal_next_action",
        "def _agent_goal_reasoning_summary",
    ]:
        assert migrated_helper not in store_source


def test_backend_code_architecture_documentation_defines_migration_contract() -> None:
    ddd_boundaries = (ROOT / "apps" / "api" / "app" / "DDD_BOUNDARIES.md").read_text()
    code_architecture = (ROOT / "docs" / "design" / "backend" / "code-architecture.md").read_text()
    docs_index = (ROOT / "docs" / "design" / "README.md").read_text()
    docs_root = (ROOT / "docs" / "README.md").read_text()

    for fragment in [
        "progressive DDD migration",
        "HTTP routers must call application services",
        "Routers must not",
        "Migration Exit Criteria",
        "New Code Checklist",
        "ApplicationStore",
        "App-root `models.py` is a compatibility re-export barrel only",
        "application/quality_loop/quality_models.py",
        "root `models.py` may re-export these names for API",
        "application/system_image/system_image_models.py",
        "application/platform/project_models.py",
        "application/platform/read_models.py",
        "application/platform/top_level_content.py",
        "`ApplicationStore.get_welcome`, `get_build`, `get_dashboard`, and",
        "`list_documentation` are compatibility delegates only",
        "application/platform/demo_seed.py",
        "`ApplicationStore._seed` is a compatibility delegate only",
        "Project and\n  version record creation defaults",
        "`ApplicationStore.create_project` and `ApplicationStore.create_version` are\n  compatibility delegates only",
        "ConversationManagementApplicationService`: conversation\n  lifecycle and discovery use cases",
        "Project/version/US scope lookup for conversation\n  creation must be delegated to",
        "`ApplicationStore` conversation lifecycle methods are compatibility delegates",
        "`ApplicationStore.get_agent_goal` and\n  `ApplicationStore.get_agent_goal_checkpoint` are compatibility delegates only",
        "It must obtain AgentGoal state and checkpoint projection through\n  `AgentGoalLifecycleApplicationService`",
        "Agent memory context views must obtain AgentGoal\n  state through `AgentGoalLifecycleApplicationService`",
        "System-image memory context sections and long-term system-image refs must be",
        "`SystemImageMemoryContextApplicationService`; Agent memory must",
            "Agent memory receives retrieval hits and trace refs from the asynchronous",
            "Concrete retrievers own retrieval\n  evidence persistence; Agent memory must not create",
        "`ApplicationStore.list_agent_memory_items` is also a compatibility delegate",
        "AgentGoal explanation memory refs must be read through `AgentMemoryManager`",
        "Planner quality state must be read through\n  `QualityLoopContextQueryApplicationService`",
        "Confirmation-driven\n  AgentGoal resume checks must call `AgentGoalLifecycleApplicationService`",
        "Agent application services must obtain ToolInvocation facts through\n  the platform ToolInvocation application boundary",
        "AgentGoal, ToolInvocation, and\n  AgentSwarm snapshot payload reads enter through\n  `PlatformEventEntityReaderPort`",
        "Project workspace\n  read-model assembly, current-US selection, quality-loop state projection",
        "`get_release_readiness` are compatibility delegates only",
        "`ApplicationStore.list_knowledge_objects`,\n  `get_knowledge_object`, and `get_system_image` are compatibility delegates",
    ]:
        assert fragment in ddd_boundaries

    for fragment in [
        "Target Package Structure",
        "Dependency Direction",
        "Current Transitional State",
        "Application Service Contracts",
        "Router Contract",
        "Tool-Native Write Path",
        "Migration Roadmap",
        "interface must not import the global `store`",
        "`models.py` is a compatibility re-export barrel only",
        "application/quality_loop/quality_models.py",
        "new code must import them from `application.quality_loop.quality_models`",
        "application/system_image/system_image_models.py",
        "new code must import them from\n  `application.system_image.system_image_models`",
        "application/platform/project_models.py",
        "new code must import them from\n  `application.platform.project_models`",
        "application/platform/read_models.py",
        "import them from `application.platform.read_models`",
        "TopLevelContentApplicationService",
        "must not directly assemble\n  `WelcomeResponse`, `BuildResponse`, or `DashboardResponse`",
        "DemoSeedApplicationService",
        "`ApplicationStore._seed` is a compatibility delegate only",
        "ConversationManagementApplicationService`: conversation lifecycle and",
        "Project/version/US scope lookup for conversation creation must be\n  delegated to `ProjectScopeResolutionApplicationService`",
        "`ApplicationStore` conversation lifecycle methods remain\n  compatibility delegates only",
        "`ApplicationStore.get_agent_goal` and\n  `ApplicationStore.get_agent_goal_checkpoint` are compatibility delegates only",
        "It must obtain AgentGoal state and checkpoint projection through\n  `AgentGoalLifecycleApplicationService`",
        "Agent memory context views must obtain AgentGoal\n  state through `AgentGoalLifecycleApplicationService`",
        "Memory item queries\n  used by Agent read models also belong to `AgentMemoryManager`",
        "System-image memory context sections and long-term\n  system-image refs must be delegated to",
        "`SystemImageMemoryContextApplicationService`; Agent memory must not directly",
        "System-image retrieval trace writes must be delegated to",
        "`SystemImageRetrievalTraceApplicationService`; Agent memory must not create",
        "AgentGoal explanation memory refs must be read through\n  `AgentMemoryManager`",
        "Planner quality state\n  must be read through `QualityLoopContextQueryApplicationService`",
        "Confirmation-driven AgentGoal\n  resume checks must call `AgentGoalLifecycleApplicationService`",
        "Agent application services must obtain ToolInvocation facts through\n  the platform ToolInvocation application boundary",
        "AgentGoal, ToolInvocation, and AgentSwarm\n  snapshot payload reads must go through `PlatformEventEntityReaderPort`",
        "Project and version record creation defaults",
        "`ApplicationStore.create_project` and\n  `ApplicationStore.create_version` remain compatibility delegates only",
        "Keep project and version record creation behind",
        "ProjectWorkspaceApplicationService`: project workspace aggregation",
        "read-model assembly, current-US selection, quality-loop state projection",
        "`ApplicationStore.get_project_workspace`",
        "`ApplicationStore.get_release_readiness` remain compatibility delegates only",
        "`ApplicationStore.list_knowledge_objects`, `ApplicationStore.get_knowledge_object`,",
        "`ApplicationStore.get_system_image` remain compatibility delegates only",
        "system image snapshots behind `SystemImageApplicationService` instead of the\n  project workspace BFF or inline `ApplicationStore` read aggregation",
    ]:
        assert fragment in code_architecture

    assert "./backend/code-architecture.md" in docs_index
    assert "./design/backend/code-architecture.md" in docs_root


def test_portal_architecture_documentation_defines_frontend_rules() -> None:
    portal_root = ROOT / "apps" / "portal" / "src"
    architecture_source = (portal_root / "ARCHITECTURE.md").read_text()
    domains_readme = (portal_root / "domains" / "README.md").read_text()
    routes_readme = (portal_root / "routes" / "README.md").read_text()
    shared_readme = (portal_root / "shared" / "README.md").read_text()
    shells_readme = (portal_root / "app" / "shells" / "README.md").read_text()

    for fragment in [
        "Layer Ownership",
        "Dependency Direction",
        "Route Module Pattern",
        "Domain Pattern",
        "Agent-First Rule",
        "UI Component Rules",
        "Verification Gates",
        "Do not add a button that performs a write path unavailable to the agent.",
        "Auth routes are still route modules",
        "route files must not import shared API\n  token helpers directly",
        "Domains may import shared transport/status/token helpers",
        "Agent domain owns conversation SSE event reduction",
        "Product-neutral shared infrastructure must not import `domains/*`",
        "Shared UI must stay product-neutral and must not import `domains/*`",
        "`shared/tokens` must remain product-neutral",
        "Platform settings domain code under `domains/platform/settings` owns model",
        "must not contain React panel/popover components",
        "Global settings popovers, provider/model configuration forms",
        "`app/shells/settings`",
        "Shared UI must not call `platformApi`, auth hooks, `apiAuthToken`, or raw `fetch`",
        "Top-level build/dashboard/documentation content queries belong",
        "Project overview quality asset presenters consume route-local view models",
        "projectWorkspaceSelectors.ts",
        "Project workspace section components consume route-local view models",
        "ProjectSectionViewModels.ts",
        "Build prompt post-processing",
        "Project workspace write orchestration belongs",
        "must not call",
        "`platformApi.confirmToolInvocation`",
        "Agent write",
        "tests/test_ddd_boundaries.py",
    ]:
        assert fragment in architecture_source

    for fragment in [
        "`types.ts` is a compatibility barrel",
        "Platform tool actions",
        "must not import route components",
        "Platform domain hooks own auth",
        "token lookup, token persistence, and expired-session cleanup",
        "Platform settings domain code owns settings contracts",
        "`domains/platform/settings`",
        "`app/shells/settings`",
        "Platform owns top-level build/dashboard/documentation server-state hooks",
        "Platform owns build-project resolution helpers",
        "Agent domain hooks own AgentGoal explanation polling",
        "Platform tool action executors own project workspace UI-to-tool orchestration",
        "Platform tool invocation commands own confirmation/approval command calls",
    ]:
        assert fragment in domains_readme

    for fragment in [
        "Route Responsibilities",
        "Route model hooks",
        "raw API clients",
        "useAuthActions",
        "useTopLevelContent.ts",
        "projectWorkspaceSelectors.ts",
        "ProjectSectionViewModels.ts",
        "Project workspace route files must not call `platformApi.invokeTool`",
    ]:
        assert fragment in routes_readme

    for fragment in [
        "Shared Rules",
        "event-reducer",
        "Conversation/SSE event normalization belongs in `domains/agent`",
        "shared/status",
        "shared/tokens",
        "Shared UI must not import `domains/*`",
        "ProjectGalleryItem",
        "Settings popovers, model-provider forms",
        "`app/shells/settings`",
        "Shared avatar/account presenters define local view types",
        "move that orchestration into a route model or domain hook",
        "no `platformApi`, auth hooks",
    ]:
        assert fragment in shared_readme

    for fragment in [
        "Shell Rules",
        "persistent chrome",
        "Shell containers may compose platform domain hooks",
        "`*ShellView.tsx` files must not import `domains/*`",
        "must not call product workflow mutations directly",
    ]:
        assert fragment in shells_readme


def test_auth_routes_delegate_session_storage_to_platform_domain() -> None:
    portal_root = ROOT / "apps" / "portal" / "src"
    require_auth_source = (portal_root / "routes" / "auth" / "RequireAuth.tsx").read_text()
    public_auth_source = (portal_root / "routes" / "auth" / "PublicAuthRoute.tsx").read_text()
    auth_session_source = (portal_root / "domains" / "platform" / "useAuthSession.ts").read_text()
    auth_token_storage_source = (portal_root / "domains" / "platform" / "authTokenStorage.ts").read_text()
    shared_client_source = (portal_root / "shared" / "api" / "client.ts").read_text()

    for route_source in [require_auth_source, public_auth_source]:
        assert "domains/platform/useAuthSession" in route_source
        assert "shared/api/client" not in route_source
        for forbidden in [
            "apiAuthToken",
            "setApiAuthToken",
            "clearApiAuthToken",
            "hasStoredApiAuthToken",
            "platformApi.",
        ]:
            assert forbidden not in route_source

    for fragment in [
        "platformApiAuthToken",
        "setApiAuthToken",
        "clearApiAuthToken",
        "hasStoredApiAuthToken",
        "export function hasAuthToken",
        "export function persistAuthSession",
        "export function clearAuthSession",
    ]:
        assert fragment in auth_session_source
    assert "shared/api/client" not in auth_session_source

    for fragment in [
        "const API_TOKEN_STORAGE_KEY = 'nasus_api_token'",
        "window.localStorage.getItem(API_TOKEN_STORAGE_KEY)",
        "window.localStorage.setItem(API_TOKEN_STORAGE_KEY, token)",
        "window.localStorage.removeItem(API_TOKEN_STORAGE_KEY)",
        "configureApiAuthTokenProvider(storedApiAuthToken)",
    ]:
        assert fragment in auth_token_storage_source

    for fragment in [
        "localStorage",
        "nasus_api_token",
        "setApiAuthToken",
        "clearApiAuthToken",
        "hasStoredApiAuthToken",
    ]:
        assert fragment not in shared_client_source
    assert "configureApiAuthTokenProvider" in shared_client_source
    assert "export function apiAuthToken" in shared_client_source


def test_portal_import_boundaries_follow_feature_sliced_layers() -> None:
    portal_root = ROOT / "apps" / "portal" / "src"
    import_pattern = re.compile(
        r"""(?:import|export)\s+(?:type\s+)?(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]"""
    )
    violations: list[str] = []

    def layer_for(path: Path) -> str | None:
        relative = path.relative_to(portal_root)
        return relative.parts[0] if relative.parts else None

    def resolve_import(source_path: Path, specifier: str) -> Path | None:
        if specifier.startswith("."):
            candidate = (source_path.parent / specifier).resolve()
            try:
                candidate.relative_to(portal_root)
            except ValueError:
                return None
            return candidate
        if specifier.startswith("@/"):
            return (portal_root / specifier[2:]).resolve()
        return None

    for source_path in portal_root.rglob("*"):
        if source_path.suffix not in {".ts", ".tsx"}:
            continue
        source_layer = layer_for(source_path)
        source_text = source_path.read_text()
        for specifier in import_pattern.findall(source_text):
            target_path = resolve_import(source_path, specifier)
            if target_path is None:
                continue
            target_layer = layer_for(target_path)
            relative_source = source_path.relative_to(ROOT)

            if source_layer == "shared" and target_layer in {"app", "routes", "domains"}:
                violations.append(f"{relative_source} imports {target_layer} via {specifier}")

            if source_layer == "domains" and target_layer in {"app", "routes"}:
                violations.append(f"{relative_source} imports {target_layer} via {specifier}")

            if source_layer == "domains" and "/shared/ui/" in str(target_path):
                violations.append(f"{relative_source} imports shared UI via {specifier}")

            if source_path.name.endswith("ShellView.tsx") and target_layer == "domains":
                violations.append(f"{relative_source} imports domain code via {specifier}")

    assert violations == []


def test_app_root_modules_are_only_entrypoints_or_compatibility_reexports() -> None:
    app_root = ROOT / "apps" / "api" / "app"
    implementation_entrypoints = {
        "__init__.py",
        "composition.py",
        "main.py",
        "models.py",
        "store.py",
    }
    violations: list[str] = []

    for source_path in sorted(app_root.glob("*.py")):
        if source_path.name in implementation_entrypoints:
            continue

        source = source_path.read_text()
        tree = ast.parse(source)
        non_empty_lines = [line for line in source.splitlines() if line.strip()]

        if len(non_empty_lines) > 5:
            violations.append(f"{source_path.name}: compatibility module is too large")

        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                continue
            if isinstance(node, ast.ImportFrom) and node.level >= 1 and all(alias.name == "*" for alias in node.names):
                continue
            violations.append(
                f"{source_path.name}:{getattr(node, 'lineno', 1)} must only contain relative star re-exports"
            )

        for forbidden in [
            "class ",
            "def ",
            "async def ",
            "ApplicationStore",
            "FastAPI(",
            "Request",
            "select(",
            "mapped_column",
            "os.getenv",
            "httpx",
            "boto3",
            "import temporalio",
            "from temporalio",
            "import langgraph",
            "from langgraph",
        ]:
            if forbidden in source:
                violations.append(f"{source_path.name}: contains forbidden app-root implementation fragment {forbidden!r}")

    assert violations == []


def test_portal_feature_skeleton_and_provider_are_present() -> None:
    portal_root = ROOT / "apps" / "portal" / "src"
    required_paths = [
        portal_root / "ARCHITECTURE.md",
        portal_root / "app" / "providers.tsx",
        portal_root / "app" / "routing" / "routeConfig.tsx",
        portal_root / "app" / "routing" / "routeElements.tsx",
        portal_root / "app" / "shells" / "README.md",
        portal_root / "app" / "shells" / "ProjectWorkspaceSidebar.tsx",
        portal_root / "app" / "shells" / "StudioSettingsLayer.tsx",
        portal_root / "app" / "shells" / "StudioTermsBar.tsx",
        portal_root / "app" / "shells" / "StudioShellTypes.ts",
        portal_root / "app" / "shells" / "TopLevelSidebar.tsx",
        portal_root / "app" / "shells" / "TopLevelStudioShellView.tsx",
        portal_root / "app" / "shells" / "ProjectWorkspaceShellView.tsx",
        portal_root / "app" / "shells" / "UserAccountMenuContainer.tsx",
        portal_root / "routes" / "build" / "BuildRoute.tsx",
        portal_root / "routes" / "build" / "BuildHero.tsx",
        portal_root / "routes" / "build" / "BuildHeroTypes.ts",
        portal_root / "routes" / "build" / "components" / "BuildGalleryPanel.tsx",
        portal_root / "routes" / "build" / "components" / "BuildSidebarToggle.tsx",
        portal_root / "routes" / "build" / "components" / "BuildSkillStrip.tsx",
        portal_root / "routes" / "build" / "useBuildProjects.ts",
        portal_root / "routes" / "build" / "useBuildPromptRunner.ts",
        portal_root / "routes" / "build" / "useBuildRouteModel.ts",
        portal_root / "routes" / "build" / "useBuildSkillSelection.ts",
        portal_root / "routes" / "dashboard" / "DashboardRoute.tsx",
        portal_root / "routes" / "dashboard" / "DashboardContent.tsx",
        portal_root / "routes" / "dashboard" / "useDashboardRouteModel.ts",
        portal_root / "routes" / "documentation" / "DocumentationRoute.tsx",
        portal_root / "routes" / "documentation" / "DocumentationContent.tsx",
        portal_root / "routes" / "documentation" / "useDocumentationRouteModel.ts",
        portal_root / "routes" / "project-overview" / "ProjectOverviewRoute.tsx",
        portal_root / "routes" / "project-overview" / "ProjectWorkspaceView.tsx",
        portal_root / "routes" / "project-overview" / "ProjectWorkspaceViewTypes.ts",
        portal_root / "routes" / "project-overview" / "projectWorkspaceCardActions.ts",
        portal_root / "routes" / "project-overview" / "projectWorkspaceSelectors.ts",
        portal_root / "routes" / "project-overview" / "ProjectWorkspaceTypes.ts",
        portal_root / "routes" / "project-overview" / "useProjectWorkspaceSourceBindings.ts",
        portal_root / "routes" / "project-overview" / "components" / "agentCards.ts",
        portal_root / "routes" / "project-overview" / "components" / "AgentCardGrid.tsx",
        portal_root / "routes" / "project-overview" / "components" / "AgentGoalPanel.tsx",
        portal_root / "routes" / "project-overview" / "components" / "AgentLog.tsx",
        portal_root / "routes" / "project-overview" / "components" / "AgentModeTabs.tsx",
        portal_root / "routes" / "project-overview" / "components" / "ConfirmationGates.tsx",
        portal_root / "routes" / "project-overview" / "components" / "ProjectNotFound.tsx",
        portal_root / "routes" / "project-overview" / "components" / "ProjectTaskComposer.tsx",
        portal_root / "routes" / "project-overview" / "components" / "QualityAssetPanel.tsx",
        portal_root / "routes" / "project-overview" / "components" / "quality-asset" / "LatestRunRow.tsx",
        portal_root / "routes" / "project-overview" / "components" / "quality-asset" / "QualityLaneGrid.tsx",
        portal_root / "routes" / "project-overview" / "components" / "quality-asset" / "QualityLoopStateCard.tsx",
        portal_root / "routes" / "project-overview" / "components" / "quality-asset" / "QualityPanelHeader.tsx",
        portal_root / "routes" / "project-overview" / "components" / "RunSettingsPanel.tsx",
        portal_root / "routes" / "project-overview" / "components" / "SourceBindingCard.tsx",
        portal_root / "routes" / "project-overview" / "components" / "SourceBindingPanel.tsx",
        portal_root / "routes" / "project-overview" / "components" / "sourceBindingCards.ts",
        portal_root / "routes" / "project-overview" / "components" / "sourceBindingDefaults.ts",
        portal_root / "routes" / "project-overview" / "components" / "SystemImageStrip.tsx",
        portal_root / "routes" / "project-overview" / "components" / "ToolInvocationRail.tsx",
        portal_root / "routes" / "project-overview" / "components" / "useSourceBindingDrafts.ts",
        portal_root / "routes" / "project-overview" / "components" / "WorkspaceToolbar.tsx",
        portal_root / "routes" / "project" / "ProjectRouteFrame.tsx",
        portal_root / "routes" / "project" / "ProjectSectionRegistry.tsx",
        portal_root / "routes" / "project" / "ProjectSectionView.tsx",
        portal_root / "routes" / "project" / "ProjectSectionViewModels.ts",
        portal_root / "routes" / "project" / "ProjectRouteTypes.ts",
        portal_root / "routes" / "project" / "projectRouteActionHandlers.ts",
        portal_root / "routes" / "project" / "projectRouteMessages.ts",
        portal_root / "routes" / "project" / "useProjectActionLock.ts",
        portal_root / "routes" / "project" / "useProjectConversationModel.ts",
        portal_root / "routes" / "project" / "useProjectRouteActions.ts",
        portal_root / "routes" / "project" / "useProjectRouteContext.ts",
        portal_root / "routes" / "project" / "useProjectRouteData.ts",
        portal_root / "routes" / "project" / "useProjectSectionParams.ts",
        portal_root / "routes" / "project" / "useProjectPromptRunner.ts",
        portal_root / "routes" / "project" / "useProjectToolConfirmation.ts",
        portal_root / "routes" / "project" / "ProjectSectionRoute.tsx",
        portal_root / "routes" / "project" / "sections" / "version" / "VersionCards.tsx",
        portal_root / "routes" / "project" / "sections" / "version" / "VersionCreateSection.tsx",
        portal_root / "routes" / "project" / "sections" / "version" / "VersionSpaceSection.tsx",
        portal_root / "routes" / "project" / "sections" / "WorkspaceSection.tsx",
        portal_root / "routes" / "project" / "sections" / "KnowledgeSection.tsx",
        portal_root / "routes" / "project" / "sections" / "RunsSection.tsx",
        portal_root / "routes" / "project" / "sections" / "GovernanceSection.tsx",
        portal_root / "routes" / "project" / "sections" / "ReleaseReadinessSection.tsx",
        portal_root / "routes" / "project" / "sections" / "primitives" / "AgentConversationPanel.tsx",
        portal_root / "routes" / "project" / "sections" / "primitives" / "MetricCards.tsx",
        portal_root / "routes" / "project" / "sections" / "primitives" / "ProjectSectionToolbar.tsx",
        portal_root / "domains" / "system-image",
            portal_root / "domains" / "system-image" / "api.ts",
            portal_root / "domains" / "system-image" / "sourceUploadCommands.ts",
        portal_root / "domains" / "system-image" / "types.ts",
        portal_root / "domains" / "system-image" / "types" / "baseline.ts",
        portal_root / "domains" / "system-image" / "types" / "data.ts",
        portal_root / "domains" / "system-image" / "types" / "knowledge.ts",
        portal_root / "domains" / "system-image" / "types" / "metrics.ts",
        portal_root / "domains" / "system-image" / "types" / "source.ts",
        portal_root / "domains" / "agent",
        portal_root / "domains" / "agent" / "api.ts",
        portal_root / "domains" / "agent" / "conversationEventReducer.ts",
        portal_root / "domains" / "agent" / "eventPayloadReaders.ts",
        portal_root / "domains" / "agent" / "types.ts",
        portal_root / "domains" / "agent" / "types" / "conversation.ts",
        portal_root / "domains" / "agent" / "types" / "goal.ts",
        portal_root / "domains" / "agent" / "types" / "memory.ts",
        portal_root / "domains" / "agent" / "types" / "swarm.ts",
        portal_root / "domains" / "agent" / "toolInvocationEvent.ts",
        portal_root / "domains" / "agent" / "agentGoalCommands.ts",
        portal_root / "domains" / "agent" / "useAgentGoalExplanation.ts",
        portal_root / "domains" / "agent" / "useConversation.ts",
        portal_root / "domains" / "agent" / "useConversationEvents.ts",
        portal_root / "domains" / "quality-loop",
        portal_root / "domains" / "quality-loop" / "api.ts",
        portal_root / "domains" / "quality-loop" / "types.ts",
        portal_root / "domains" / "quality-loop" / "types" / "assets.ts",
        portal_root / "domains" / "quality-loop" / "types" / "execution.ts",
        portal_root / "domains" / "quality-loop" / "types" / "governance.ts",
        portal_root / "domains" / "quality-loop" / "types" / "us.ts",
        portal_root / "domains" / "quality-loop" / "types" / "version.ts",
        portal_root / "domains" / "quality-loop" / "types" / "workspace.ts",
        portal_root / "domains" / "platform" / "api.ts",
        portal_root / "domains" / "platform" / "authTokenStorage.ts",
        portal_root / "domains" / "platform" / "buildProjectResolution.ts",
        portal_root / "domains" / "platform" / "build-skills.ts",
        portal_root / "domains" / "platform" / "homeTypes.ts",
        portal_root / "domains" / "platform" / "starterContent.ts",
        portal_root / "domains" / "platform" / "tool-actions.ts",
        portal_root / "domains" / "platform" / "tool-actions" / "projectActionExecutor.ts",
        portal_root / "domains" / "platform" / "tool-actions" / "studioActionCommand.ts",
        portal_root / "domains" / "platform" / "tool-actions" / "systemImageSourcePlan.ts",
        portal_root / "domains" / "platform" / "tool-actions" / "toolActionMap.ts",
        portal_root / "domains" / "platform" / "tool-actions" / "types.ts",
        portal_root / "domains" / "platform" / "toolInvocationCommands.ts",
        portal_root / "domains" / "platform" / "types.ts",
        portal_root / "domains" / "platform" / "types" / "content.ts",
        portal_root / "domains" / "platform" / "types" / "events.ts",
        portal_root / "domains" / "platform" / "types" / "project.ts",
        portal_root / "domains" / "platform" / "types" / "settings.ts",
        portal_root / "domains" / "platform" / "types" / "space.ts",
        portal_root / "domains" / "platform" / "types" / "tool.ts",
        portal_root / "domains" / "platform" / "useUserAvatar.ts",
        portal_root / "domains" / "platform" / "useStudioSettings.ts",
        portal_root / "domains" / "platform" / "useProjectWorkspaceData.ts",
        portal_root / "domains" / "platform" / "useTopLevelContent.ts",
        portal_root / "shared" / "api",
        portal_root / "shared" / "api" / "client.ts",
        portal_root / "shared" / "status",
        portal_root / "shared" / "status" / "backendStatus.ts",
        portal_root / "shared" / "ui" / "BuildComposer.tsx",
        portal_root / "shared" / "ui" / "build-composer" / "BuildComposerActions.tsx",
        portal_root / "shared" / "ui" / "build-composer" / "BuildComposerTypes.ts",
        portal_root / "shared" / "ui" / "build-composer" / "BuildPromptInput.tsx",
        portal_root / "shared" / "ui" / "build-composer" / "SelectedSkillGrid.tsx",
        portal_root / "shared" / "ui" / "StudioSidebarIcon.tsx",
        portal_root / "shared" / "ui" / "ProjectGallery.tsx",
        portal_root / "app" / "shells" / "settings" / "SettingsPopover.tsx",
        portal_root / "shared" / "ui" / "AvatarEditor.tsx",
        portal_root / "shared" / "ui" / "UserAccountMenu.tsx",
        portal_root / "shared" / "ui" / "UserAvatar.tsx",
        portal_root / "app" / "shells" / "settings" / "ModelConfigurationPanel.tsx",
        portal_root / "app" / "shells" / "settings" / "ModelConfigurationFields.tsx",
        portal_root / "app" / "shells" / "settings" / "ModelConfigurationList.tsx",
        portal_root / "app" / "shells" / "settings" / "ModelConfigurationBody.tsx",
        portal_root / "app" / "shells" / "settings" / "ModelConnectionResult.tsx",
        portal_root / "app" / "shells" / "settings" / "ModelRouteTabs.tsx",
        portal_root / "app" / "shells" / "settings" / "SettingsPanelRenderer.tsx",
        portal_root / "app" / "shells" / "settings" / "SettingsChoicePanel.tsx",
        portal_root / "app" / "shells" / "settings" / "SettingsChoicePanelRenderer.tsx",
        portal_root / "app" / "shells" / "settings" / "settingsChoiceConfigs.ts",
        portal_root / "app" / "shells" / "settings" / "settingsChoicePanelIds.ts",
        portal_root / "app" / "shells" / "settings" / "SettingsInfoPanels.tsx",
        portal_root / "app" / "shells" / "settings" / "SettingsMenu.tsx",
        portal_root / "app" / "shells" / "settings" / "settingsMenuModel.ts",
        portal_root / "domains" / "platform" / "settings" / "modelProfiles.ts",
        portal_root / "domains" / "platform" / "settings" / "useModelConfigurationDraft.ts",
        portal_root / "shared" / "tokens",
        portal_root / "shared" / "event-reducer",
        portal_root / "shared" / "event-reducer" / "eventUpsert.ts",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required_paths if not path.exists()]
    assert missing == []

    main_source = (portal_root / "main.tsx").read_text()
    project_workspace_view_source = (portal_root / "routes" / "project-overview" / "ProjectWorkspaceView.tsx").read_text()
    project_workspace_actions_source = (
        portal_root / "routes" / "project-overview" / "projectWorkspaceCardActions.ts"
    ).read_text()
    project_workspace_selectors_source = (
        portal_root / "routes" / "project-overview" / "projectWorkspaceSelectors.ts"
    ).read_text()
    project_workspace_source_bindings_source = (
        portal_root / "routes" / "project-overview" / "useProjectWorkspaceSourceBindings.ts"
    ).read_text()
    quality_asset_panel_source = (
        portal_root / "routes" / "project-overview" / "components" / "QualityAssetPanel.tsx"
    ).read_text()
    quality_lane_grid_source = (
        portal_root / "routes" / "project-overview" / "components" / "quality-asset" / "QualityLaneGrid.tsx"
    ).read_text()
    quality_loop_state_card_source = (
        portal_root / "routes" / "project-overview" / "components" / "quality-asset" / "QualityLoopStateCard.tsx"
    ).read_text()
    quality_panel_header_source = (
        portal_root / "routes" / "project-overview" / "components" / "quality-asset" / "QualityPanelHeader.tsx"
    ).read_text()
    latest_run_row_source = (
        portal_root / "routes" / "project-overview" / "components" / "quality-asset" / "LatestRunRow.tsx"
    ).read_text()
    source_binding_panel_source = (portal_root / "routes" / "project-overview" / "components" / "SourceBindingPanel.tsx").read_text()
    source_binding_card_source = (portal_root / "routes" / "project-overview" / "components" / "SourceBindingCard.tsx").read_text()
    source_binding_cards_source = (portal_root / "routes" / "project-overview" / "components" / "sourceBindingCards.ts").read_text()
    project_route_context_source = (portal_root / "routes" / "project" / "useProjectRouteContext.ts").read_text()
    project_route_data_source = (portal_root / "routes" / "project" / "useProjectRouteData.ts").read_text()
    project_route_actions_source = (portal_root / "routes" / "project" / "useProjectRouteActions.ts").read_text()
    project_conversation_model_source = (
        portal_root / "routes" / "project" / "useProjectConversationModel.ts"
    ).read_text()
    project_action_handlers_source = (portal_root / "routes" / "project" / "projectRouteActionHandlers.ts").read_text()
    project_prompt_runner_source = (portal_root / "routes" / "project" / "useProjectPromptRunner.ts").read_text()
    project_tool_confirmation_source = (portal_root / "routes" / "project" / "useProjectToolConfirmation.ts").read_text()
    tool_actions_source = (portal_root / "domains" / "platform" / "tool-actions.ts").read_text()
    project_workspace_data_domain_source = (
        portal_root / "domains" / "platform" / "useProjectWorkspaceData.ts"
    ).read_text()
    project_action_domain_source = (
        portal_root / "domains" / "platform" / "tool-actions" / "projectActionExecutor.ts"
    ).read_text()
    project_workspace_invalidation_source = (
        portal_root / "domains" / "platform" / "projectWorkspaceInvalidation.ts"
    ).read_text()
    tool_invocation_commands_source = (
        portal_root / "domains" / "platform" / "toolInvocationCommands.ts"
    ).read_text()
    tool_invocation_confirmation_hook_source = (
        portal_root / "domains" / "platform" / "useToolInvocationConfirmation.ts"
    ).read_text()
    agent_goal_commands_source = (portal_root / "domains" / "agent" / "agentGoalCommands.ts").read_text()
    agent_goal_explanation_hook_source = (
        portal_root / "domains" / "agent" / "useAgentGoalExplanation.ts"
    ).read_text()
    studio_action_command_source = (
        portal_root / "domains" / "platform" / "tool-actions" / "studioActionCommand.ts"
    ).read_text()
    source_action_plan_source = (
        portal_root / "domains" / "platform" / "tool-actions" / "systemImageSourcePlan.ts"
    ).read_text()
    tool_action_map_source = (portal_root / "domains" / "platform" / "tool-actions" / "toolActionMap.ts").read_text()
    agent_types_source = (portal_root / "domains" / "agent" / "types.ts").read_text()
    system_image_types_source = (portal_root / "domains" / "system-image" / "types.ts").read_text()
    quality_loop_types_source = (portal_root / "domains" / "quality-loop" / "types.ts").read_text()
    platform_types_source = (portal_root / "domains" / "platform" / "types.ts").read_text()
    assert "AppProviders" in main_source
    assert "QueryClientProvider" not in main_source
    assert len(tool_actions_source.splitlines()) < 8
    assert "buildStudioActionCommand" in tool_actions_source
    assert "buildSystemImageSourceActionPlan" in tool_actions_source
    assert "executeProjectActionCommand" in tool_actions_source
    assert "executeSystemImageSourceActionPlan" in tool_actions_source
    assert "toolIdForAction" not in tool_actions_source
    assert "source_specs" not in tool_actions_source
    assert "Build the official system image" not in tool_actions_source
    assert "Build the official system image" in studio_action_command_source
    assert "quality-loop.continue-goal" in studio_action_command_source
    assert "toolIdForAction" in studio_action_command_source
    assert "source_specs" in source_action_plan_source
    assert "system-image.register-sources" in source_action_plan_source
    assert "system_image.sources.register" in tool_action_map_source
    assert "release.assess" in tool_action_map_source
    assert len(project_workspace_view_source.splitlines()) <= 105
    assert len(source_binding_panel_source.splitlines()) < 90
    assert len(project_route_context_source.splitlines()) < 70
    assert len(project_route_actions_source.splitlines()) < 60
    assert "agentCards =" not in project_workspace_view_source
    assert "ProjectNotFound" not in project_workspace_view_source
    for fragment in [
        "tool_id",
        ".filter(",
        "useSourceBindingDrafts",
        "System Image Builder",
        "missing_source_binding",
    ]:
        assert fragment not in project_workspace_view_source
    assert "ProjectWorkspaceViewProps" in project_workspace_view_source
    assert "createProjectWorkspaceCardActions" in project_workspace_view_source
    assert "selectPendingBaselineInvocation" in project_workspace_view_source
    assert "useProjectWorkspaceSourceBindings" in project_workspace_view_source
    assert "System Image Builder" in project_workspace_actions_source
    assert "quality-loop.continue-goal" in project_workspace_actions_source
    assert "system_image.baseline.initialize" in project_workspace_selectors_source
    assert "missing_source_binding" in project_workspace_selectors_source
    assert "useSourceBindingDrafts" in project_workspace_source_bindings_source
    assert "submitSourceBindings" in project_workspace_source_bindings_source
    assert "WorkspaceToolbar" in project_workspace_view_source
    assert "AgentCardGrid" in project_workspace_view_source
    assert "ConfirmationGates" in project_workspace_view_source
    assert "SourceBindingCard" in source_binding_panel_source
    assert "sourceBindingCards.map" in source_binding_panel_source
    assert "Local path or Git URL" not in source_binding_panel_source
    assert len(quality_asset_panel_source.splitlines()) < 35
    assert "QualityPanelHeader" in quality_asset_panel_source
    assert "QualityLoopStateCard" in quality_asset_panel_source
    assert "QualityLaneGrid" in quality_asset_panel_source
    assert "LatestRunRow" in quality_asset_panel_source
    for fragment in ["quality-stage-bar", "quality-lane-card", "quality-run-row", "quality-empty-state"]:
        assert fragment not in quality_asset_panel_source
    assert "quality-lane-card" in quality_lane_grid_source
    assert "quality-empty-state" in quality_lane_grid_source
    assert "quality-stage-bar" in quality_loop_state_card_source
    assert "quality-panel-header" in quality_panel_header_source
    assert "quality-run-row" in latest_run_row_source
    assert "sourceBindingCards" in source_binding_cards_source
    assert "source-binding-card" in source_binding_card_source
    assert "useProjectRouteData" in project_route_context_source
    assert "useProjectWorkspaceData" in project_route_data_source
    assert "useQuery(" not in project_route_data_source
    for fragment in ["qualityLoopApi", "systemImageApi"]:
        assert fragment not in project_route_data_source
        assert fragment in project_workspace_data_domain_source
    assert "useProjectRouteActions" in project_route_context_source
    assert "useProjectConversationModel" in project_route_context_source
    assert "useQuery(" not in project_route_context_source
    assert "useMutation(" not in project_route_context_source
    assert "useProjectActionLock" in project_route_actions_source
    assert "useProjectPromptRunner" in project_route_actions_source
    assert "useProjectToolConfirmation" in project_route_actions_source
    assert "createProjectRouteActionHandlers" in project_route_actions_source
    for fragment in [
        "useState(",
        "useMutation(",
        "executeProjectActionCommand",
        "executeSystemImageSourceActionPlan",
        "invalidateProjectWorkspaceQueries",
        "platformApi.",
        "agentApi.",
    ]:
        assert fragment not in project_route_actions_source
    assert "platformApi.invokeTool" not in project_route_actions_source
    assert "agentApi.ensureConversation" not in project_route_actions_source
    assert not (portal_root / "routes" / "project" / "projectActionExecutor.ts").exists()
    assert "platformApi.invokeTool" in project_action_domain_source
    assert "agentApi.ensureConversation" in project_action_domain_source
    assert "agentApi.postMessage" in project_action_domain_source
    assert "executeProjectActionCommand" in project_action_handlers_source
    assert "executeSystemImageSourceActionPlan" in project_action_handlers_source
    assert "agentApi.resumeAgentGoal" not in project_action_handlers_source
    assert "resumeAgentGoal" in project_action_handlers_source
    assert "agentApi.resumeAgentGoal" in agent_goal_commands_source
    assert "invalidateProjectWorkspaceQueries" in project_action_handlers_source
    assert "projectConversation.sendMessage" in project_prompt_runner_source
    assert "invalidateProjectWorkspaceQueries" in project_prompt_runner_source
    assert "invalidateProjectWorkspaceQueries" in project_workspace_invalidation_source
    assert not (portal_root / "routes" / "project" / "projectRouteInvalidation.ts").exists()
    assert "useAgentGoalExplanation" in project_conversation_model_source
    assert "agentApi.getAgentGoalExplanation" not in project_conversation_model_source
    assert "agentApi.getAgentGoalExplanation" in agent_goal_explanation_hook_source
    assert "platformApi.confirmToolInvocation" not in project_tool_confirmation_source
    assert "usePlatformToolInvocationConfirmation" in project_tool_confirmation_source
    assert "confirmToolInvocationCommand" not in project_tool_confirmation_source
    assert "platformApi.confirmToolInvocation" in tool_invocation_commands_source
    assert "confirmToolInvocationCommand" in tool_invocation_confirmation_hook_source
    assert "useMutation(" not in project_tool_confirmation_source
    assert "useMutation(" in tool_invocation_confirmation_hook_source
    route_raw_api_refs = []
    for path in (portal_root / "routes").rglob("*.ts*"):
        source = path.read_text()
        for marker in ["platformApi.", "agentApi.", "qualityLoopApi.", "systemImageApi."]:
            if marker in source:
                route_raw_api_refs.append(
                    f"{path.relative_to(ROOT)}:{marker}{source.split(marker, 1)[1].split('(', 1)[0]}"
                )
    assert route_raw_api_refs == []
    assert len(agent_types_source.splitlines()) < 8
    for fragment in [
        "export type * from './types/conversation'",
        "export type * from './types/goal'",
        "export type * from './types/swarm'",
        "export type * from './types/memory'",
    ]:
        assert fragment in agent_types_source
    for fragment in [
        "interface ConversationSession",
        "interface AgentGoal",
        "interface AgentSwarmRun",
        "interface AgentMemoryContextView",
    ]:
        assert fragment not in agent_types_source
    assert len(system_image_types_source.splitlines()) < 10
    for fragment in [
        "export type * from './types/knowledge'",
        "export type * from './types/source'",
        "export type * from './types/baseline'",
        "export type * from './types/metrics'",
        "export type * from './types/data'",
    ]:
        assert fragment in system_image_types_source
    for fragment in [
        "interface KnowledgeObject",
        "interface RawAssetRecord",
        "interface BaselineRecord",
        "interface QualityMetricSnapshot",
        "interface SystemImageData",
    ]:
        assert fragment not in system_image_types_source
    assert len(quality_loop_types_source.splitlines()) < 12
    for fragment in [
        "export type * from './types/version'",
        "export type * from './types/us'",
        "export type * from './types/assets'",
        "export type * from './types/execution'",
        "export type * from './types/governance'",
        "export type * from './types/workspace'",
    ]:
        assert fragment in quality_loop_types_source
    for fragment in [
        "interface VersionSummary",
        "interface QualityAssetPack",
        "interface RunSummary",
        "interface ReleaseReadiness",
        "interface ProjectWorkspaceData",
    ]:
        assert fragment not in quality_loop_types_source
    assert len(platform_types_source.splitlines()) < 12
    for fragment in [
        "export type * from './types/space'",
        "export type * from './types/project'",
        "export type * from './types/tool'",
        "export type * from './types/content'",
        "export type * from './types/events'",
        "export type * from './types/settings'",
    ]:
        assert fragment in platform_types_source
    for fragment in [
        "interface ProjectCard",
        "interface ToolDefinition",
        "interface EventPayload",
        "interface StudioSettings",
    ]:
        assert fragment not in platform_types_source

    conversation_hook_source = (portal_root / "domains" / "agent" / "useConversation.ts").read_text()
    conversation_events_source = (portal_root / "domains" / "agent" / "useConversationEvents.ts").read_text()
    event_reducer_source = (portal_root / "domains" / "agent" / "conversationEventReducer.ts").read_text()
    event_payload_readers_source = (portal_root / "domains" / "agent" / "eventPayloadReaders.ts").read_text()
    tool_invocation_event_source = (portal_root / "domains" / "agent" / "toolInvocationEvent.ts").read_text()
    shared_event_upsert_source = (portal_root / "shared" / "event-reducer" / "eventUpsert.ts").read_text()
    production_sources = [path.read_text() for path in portal_root.rglob("*.ts*")]
    assert all("features/" not in source for source in production_sources)
    assert len(conversation_hook_source.splitlines()) < 55
    assert len(event_reducer_source.splitlines()) < 80
    assert "agentApi.ensureConversation" in conversation_hook_source
    assert "useConversationEvents" in conversation_hook_source
    assert "EventSource" not in conversation_hook_source
    assert "reduceConversationEvent" not in conversation_hook_source
    assert "EventSource" in conversation_events_source
    assert "reduceConversationEvent" in conversation_events_source
    assert "shared/event-reducer/conversationEventReducer" not in conversation_events_source
    assert "./conversationEventReducer" in conversation_events_source
    assert "reduceConversationEvent" in event_reducer_source
    assert "asConversationMessage" in event_reducer_source
    assert "asAgentStep" in event_reducer_source
    assert "asAgentSwarm" in event_reducer_source
    assert "upsertById" in event_reducer_source
    assert "toolInvocationFromEvent" in event_reducer_source
    assert "isRecord" not in event_reducer_source
    assert "tool_id" not in event_reducer_source
    assert "isRecord" in event_payload_readers_source
    assert "tool_id" in tool_invocation_event_source
    assert "upsertById" in shared_event_upsert_source
    shared_event_reducer_sources = [
        path.read_text() for path in (portal_root / "shared" / "event-reducer").rglob("*.ts*")
    ]
    assert all("domains/" not in source for source in shared_event_reducer_sources)
    for shared_package in ["tokens", "status", "ui"]:
        shared_sources = [
            path.read_text() for path in (portal_root / "shared" / shared_package).rglob("*.ts*")
        ]
        assert all("domains/" not in source for source in shared_sources)
    domain_sources = [path.read_text() for path in (portal_root / "domains").rglob("*.ts*")]
    assert all("shared/ui" not in source for source in domain_sources)
    settings_hook_source = (portal_root / "domains" / "platform" / "useStudioSettings.ts").read_text()
    backend_status_pill_source = (portal_root / "shared" / "ui" / "BackendStatusPill.tsx").read_text()
    theme_hook_source = (portal_root / "shared" / "tokens" / "useTheme.ts").read_text()
    assert "shared/status/backendStatus" in settings_hook_source
    assert "shared/ui/BackendStatusPill" not in settings_hook_source
    assert "import type { BackendStatus } from '../status/backendStatus'" in backend_status_pill_source
    assert "export type ThemePreference" in theme_hook_source
    assert "StudioSettings" not in theme_hook_source
    assert "useTheme(settingsQuery.data?.theme)" in settings_hook_source


def test_portal_styles_are_split_by_frontend_boundary() -> None:
    styles_root = ROOT / "apps" / "portal" / "src" / "styles"
    app_css = (styles_root / "app.css").read_text()
    required_style_files = [
        "foundations.css",
        "auth.css",
        "studio-shell.css",
        "build.css",
        "project-workspace.css",
        "settings.css",
        "theme-overrides.css",
        "responsive.css",
    ]
    missing = [filename for filename in required_style_files if not (styles_root / filename).exists()]
    assert missing == []

    app_css_lines = [line for line in app_css.splitlines() if line.strip()]
    assert len(app_css_lines) == 9
    assert all(line.startswith("@import ") for line in app_css_lines)
    for filename in required_style_files:
        assert f"@import './{filename}';" in app_css

    assert ".settings-pop" not in app_css
    assert ".auth-shell" not in app_css
    assert ".build-hero" not in app_css
    assert ".studio-sidebar" not in app_css
    assert ".agent-workspace" not in app_css
    assert ":root[data-theme='light']" not in app_css

    assert ":root {" in (styles_root / "foundations.css").read_text()
    assert ".auth-shell" in (styles_root / "auth.css").read_text()
    assert ".studio-sidebar" in (styles_root / "studio-shell.css").read_text()
    assert ".build-hero" in (styles_root / "build.css").read_text()
    assert ".agent-workspace" in (styles_root / "project-workspace.css").read_text()
    assert ".settings-pop" in (styles_root / "settings.css").read_text()
    assert ":root[data-theme='light']" in (styles_root / "theme-overrides.css").read_text()
    assert "@media (max-width: 960px)" in (styles_root / "responsive.css").read_text()


def test_top_level_routes_are_not_backed_by_nasus_studio_singleton() -> None:
    portal_root = ROOT / "apps" / "portal" / "src"
    legacy_files = [
        portal_root / "app" / "TopLevelStudio.tsx",
        portal_root / "app" / "PrototypeStudio.tsx",
        portal_root / "app" / "NasusStudio.tsx",
        portal_root / "app" / "PageFrames.tsx",
        portal_root / "app" / "inspectorRails.tsx",
        portal_root / "app" / "prototypeShared.tsx",
    ]
    existing_legacy_files = [str(path.relative_to(ROOT)) for path in legacy_files if path.exists()]
    assert existing_legacy_files == []
    assert not (portal_root / "pages").exists() or not list((portal_root / "pages").glob("*.tsx"))
    assert not (portal_root / "components").exists() or not list((portal_root / "components").glob("*.tsx"))

    router_source = (portal_root / "app" / "router.tsx").read_text()
    route_config_source = (portal_root / "app" / "routing" / "routeConfig.tsx").read_text()
    route_elements_source = (portal_root / "app" / "routing" / "routeElements.tsx").read_text()
    build_route_source = (portal_root / "routes" / "build" / "BuildRoute.tsx").read_text()
    build_hero_source = (portal_root / "routes" / "build" / "BuildHero.tsx").read_text()
    build_skill_strip_source = (portal_root / "routes" / "build" / "components" / "BuildSkillStrip.tsx").read_text()
    build_gallery_panel_source = (portal_root / "routes" / "build" / "components" / "BuildGalleryPanel.tsx").read_text()
    build_composer_source = (portal_root / "shared" / "ui" / "BuildComposer.tsx").read_text()
    build_composer_actions_source = (
        portal_root / "shared" / "ui" / "build-composer" / "BuildComposerActions.tsx"
    ).read_text()
    build_composer_types_source = (
        portal_root / "shared" / "ui" / "build-composer" / "BuildComposerTypes.ts"
    ).read_text()
    selected_skill_grid_source = (
        portal_root / "shared" / "ui" / "build-composer" / "SelectedSkillGrid.tsx"
    ).read_text()
    build_prompt_input_source = (
        portal_root / "shared" / "ui" / "build-composer" / "BuildPromptInput.tsx"
    ).read_text()
    build_route_model_source = (portal_root / "routes" / "build" / "useBuildRouteModel.ts").read_text()
    build_projects_source = (portal_root / "routes" / "build" / "useBuildProjects.ts").read_text()
    build_prompt_runner_source = (portal_root / "routes" / "build" / "useBuildPromptRunner.ts").read_text()
    build_skill_selection_source = (portal_root / "routes" / "build" / "useBuildSkillSelection.ts").read_text()
    platform_top_level_content_source = (
        portal_root / "domains" / "platform" / "useTopLevelContent.ts"
    ).read_text()
    platform_starter_content_source = (
        portal_root / "domains" / "platform" / "starterContent.ts"
    ).read_text()
    platform_build_resolution_source = (
        portal_root / "domains" / "platform" / "buildProjectResolution.ts"
    ).read_text()
    dashboard_route_source = (portal_root / "routes" / "dashboard" / "DashboardRoute.tsx").read_text()
    documentation_route_source = (portal_root / "routes" / "documentation" / "DocumentationRoute.tsx").read_text()
    project_route_source = (portal_root / "routes" / "project-overview" / "ProjectOverviewRoute.tsx").read_text()
    project_frame_source = (portal_root / "routes" / "project" / "ProjectRouteFrame.tsx").read_text()
    project_section_source = (portal_root / "routes" / "project" / "ProjectSectionRoute.tsx").read_text()
    project_section_registry_source = (portal_root / "routes" / "project" / "ProjectSectionRegistry.tsx").read_text()
    project_section_view_source = (portal_root / "routes" / "project" / "ProjectSectionView.tsx").read_text()
    project_section_params_source = (portal_root / "routes" / "project" / "useProjectSectionParams.ts").read_text()
    project_section_toolbar_source = (portal_root / "routes" / "project" / "sections" / "primitives" / "ProjectSectionToolbar.tsx").read_text()
    project_metric_cards_source = (portal_root / "routes" / "project" / "sections" / "primitives" / "MetricCards.tsx").read_text()
    project_conversation_panel_source = (portal_root / "routes" / "project" / "sections" / "primitives" / "AgentConversationPanel.tsx").read_text()

    assert len(router_source.splitlines()) < 8
    assert "createBrowserRouter(appRoutes)" in router_source
    assert "path:" not in router_source
    assert "BuildRoute" not in router_source
    assert "BuildRoute" in route_elements_source
    assert "DashboardRoute" in route_elements_source
    assert "DocumentationRoute" in route_elements_source
    assert "ProjectOverviewRoute" in route_elements_source
    assert "ProjectSectionRoute" in route_elements_source
    assert "path: '/build'" in route_config_source
    assert "path: '/dashboard'" in route_config_source
    assert "path: '/documentation'" in route_config_source
    assert "path: '/projects/:projectId'" in route_config_source
    assert "path: '/projects/:projectId/versions'" in route_config_source
    assert "path: '/projects/:projectId/runs'" in route_config_source
    assert "path: '/projects/:projectId/governance'" in route_config_source
    assert "path: '/projects/:projectId/release-readiness'" in route_config_source
    assert "path: '/prototype/:viewId?'" in route_config_source
    build_route_section = route_config_source.split("path: '/build'", 1)[1].split("},", 1)[0]
    dashboard_route_section = route_config_source.split("path: '/dashboard'", 1)[1].split("},", 1)[0]
    documentation_route_section = route_config_source.split("path: '/documentation'", 1)[1].split("},", 1)[0]
    project_route_section = route_config_source.split("path: '/projects/:projectId'", 1)[1].split("},", 1)[0]
    project_versions_section = route_config_source.split("path: '/projects/:projectId/versions'", 1)[1].split("},", 1)[0]
    project_runs_section = route_config_source.split("path: '/projects/:projectId/runs'", 1)[1].split("},", 1)[0]
    project_governance_section = route_config_source.split("path: '/projects/:projectId/governance'", 1)[1].split("},", 1)[0]
    project_release_section = route_config_source.split("path: '/projects/:projectId/release-readiness'", 1)[1].split("},", 1)[0]
    assert "buildElement" in build_route_section
    assert "dashboardElement" in dashboard_route_section
    assert "documentationElement" in documentation_route_section
    assert "projectOverviewElement" in project_route_section
    assert "projectVersionsElement" in project_versions_section
    assert "projectRunsElement" in project_runs_section
    assert "projectGovernanceElement" in project_governance_section
    assert "projectReleaseReadinessElement" in project_release_section
    assert "studioElement" not in build_route_section
    assert "studioElement" not in dashboard_route_section
    assert "studioElement" not in documentation_route_section
    assert "studioElement" not in project_route_section
    assert "studioElement" not in project_versions_section
    assert "studioElement" not in project_runs_section
    assert "studioElement" not in project_governance_section
    assert "studioElement" not in project_release_section
    assert "NasusStudio" not in build_route_source
    assert "NasusStudio" not in dashboard_route_source
    assert "NasusStudio" not in documentation_route_source
    assert "NasusStudio" not in project_route_source
    assert "NasusStudio" not in project_frame_source
    assert "NasusStudio" not in project_section_source
    assert "BuildHero" in build_route_source
    assert "useBuildRouteModel" in build_route_source
    assert len(build_route_source.splitlines()) < 60
    assert len(build_hero_source.splitlines()) < 50
    assert len(build_composer_source.splitlines()) < 35
    assert "BuildGalleryPanel" in build_hero_source
    assert "BuildSkillStrip" in build_hero_source
    assert "BuildSidebarToggle" in build_hero_source
    assert "ProjectGallery" not in build_hero_source
    assert "buildSkillCards.map" not in build_hero_source
    assert "collapse-button" not in build_hero_source
    assert "ProjectGallery" in build_gallery_panel_source
    assert "buildSkillCards.map" in build_skill_strip_source
    assert "SelectedSkillGrid" in build_composer_source
    assert "BuildPromptInput" in build_composer_source
    assert "BuildComposerActions" in build_composer_source
    assert "selectedSkills" in build_composer_source
    assert "BuildComposerSkill" in build_composer_types_source
    assert "selectedSkills={model.selectedSkills}" in build_route_source
    assert "selectedSkills={selectedSkills}" in build_hero_source
    assert "buildSkillCards.filter" in build_route_model_source
    assert "selected-skill-card" not in build_composer_source
    assert "composer-action-button" not in build_composer_source
    assert "textarea" not in build_composer_source
    assert "selected-skill-card" in selected_skill_grid_source
    assert "composer-action-button" in build_composer_actions_source
    assert "textarea" in build_prompt_input_source
    for shared_build_source in [
        build_composer_source,
        build_composer_actions_source,
        selected_skill_grid_source,
        build_prompt_input_source,
        (portal_root / "shared" / "ui" / "BuildSkillIcon.tsx").read_text(),
    ]:
        for forbidden in ["domains/platform", "buildSkillCards", "BuildSkillCard", "BuildSkillIconName"]:
            assert forbidden not in shared_build_source
    assert len(build_route_model_source.splitlines()) < 60
    assert "useBuildProjects" in build_route_model_source
    assert "useBuildPromptRunner" in build_route_model_source
    assert "useBuildSkillSelection" in build_route_model_source
    for fragment in ["useQuery(", "useState(", "platformApi.", "composeBuildPrompt", "normalizeProjectName"]:
        assert fragment not in build_route_model_source
    assert "useBuildContent" in build_projects_source
    for fragment in ["useQuery(", "platformApi.", "starterProjects", "getDashboard", "getBuild"]:
        assert fragment not in build_projects_source
    assert "platformApi.getDashboard" in platform_top_level_content_source
    assert "platformApi.getBuild" in platform_top_level_content_source
    assert "platformApi.getDocumentation" in platform_top_level_content_source
    assert "starterProjects" in platform_top_level_content_source
    assert "fallbackDocumentationEntries" in platform_top_level_content_source
    assert "Payment System" in platform_starter_content_source
    assert "System Image" in platform_starter_content_source
    assert "buildConversation.sendMessage" in build_prompt_runner_source
    assert "projectIdFromBuildResponse" in build_prompt_runner_source
    assert "waitForCreatedProjectFromPrompt" in build_prompt_runner_source
    for fragment in ["platformApi.", "normalizeProjectName", "DashboardData", "setQueryData(['dashboard']"]:
        assert fragment not in build_prompt_runner_source
    assert "normalizeProjectName" in platform_build_resolution_source
    assert "platformApi.getDashboard" in platform_build_resolution_source
    assert "queryClient.setQueryData(['dashboard'], latestDashboard)" in platform_build_resolution_source
    assert "composeBuildPrompt" in build_skill_selection_source
    assert "DashboardContent" in dashboard_route_source
    assert "useDashboardRouteModel" in dashboard_route_source
    assert len(dashboard_route_source.splitlines()) < 60
    assert "DocumentationContent" in documentation_route_source
    assert "useDocumentationRouteModel" in documentation_route_source
    assert len(documentation_route_source.splitlines()) < 60
    dashboard_route_model_source = (portal_root / "routes" / "dashboard" / "useDashboardRouteModel.ts").read_text()
    documentation_route_model_source = (
        portal_root / "routes" / "documentation" / "useDocumentationRouteModel.ts"
    ).read_text()
    assert "useDashboardContent" in dashboard_route_model_source
    assert "useDocumentationContent" in documentation_route_model_source
    for route_model_source in [dashboard_route_model_source, documentation_route_model_source]:
        for fragment in ["useQuery(", "platformApi.", "starterProjects", "fallbackDocs"]:
            assert fragment not in route_model_source
    for route_source in [build_route_source, dashboard_route_source, documentation_route_source]:
        for fragment in ["useQuery(", "useQueryClient", "api.", "useConversation("]:
            assert fragment not in route_source
    assert "ProjectRouteFrame" in project_route_source
    assert "ProjectRouteFrame" in project_section_source
    assert "ProjectSectionView" in project_section_source
    assert "useProjectSectionParams" in project_section_source
    assert "renderProjectSection" not in project_section_source
    assert "titleForProjectSection" not in project_section_source
    assert "decodeURIComponent" not in project_section_source
    assert "useProjectRouteContext" in project_frame_source
    assert "ProjectRouteTypes" in project_frame_source
    assert len(project_frame_source.splitlines()) < 80
    assert len(project_section_source.splitlines()) < 30
    assert len(project_section_view_source.splitlines()) < 40
    assert len(project_section_params_source.splitlines()) < 30
    for fragment in ["useQuery(", "useMutation", "useQueryClient", "api."]:
        assert fragment not in project_frame_source
        assert fragment not in project_section_source
    assert project_section_source.count("function ") <= 1
    assert "ProjectSectionToolbar" in project_section_view_source
    assert "sections/section-primitives" not in project_section_view_source
    assert not (portal_root / "routes" / "project" / "sections" / "section-primitives.tsx").exists()
    assert len(project_section_toolbar_source.splitlines()) < 40
    assert len(project_metric_cards_source.splitlines()) < 30
    assert len(project_conversation_panel_source.splitlines()) < 40
    assert "ProjectSectionToolbar" in project_section_toolbar_source
    assert "MetricCard" in project_metric_cards_source
    assert "MetricMini" in project_metric_cards_source
    assert "AgentConversationPanel" in project_conversation_panel_source
    assert "MetricCard" not in project_conversation_panel_source
    assert "AgentConversationPanel" not in project_metric_cards_source
    assert "renderProjectSection" in project_section_view_source
    assert "titleForProjectSection" in project_section_view_source
    assert "decodeOptionalRouteParam" in project_section_params_source
    assert "VersionSpaceSection" in project_section_registry_source
    assert "ReleaseReadinessSection" in project_section_registry_source
    assert "sections/VersionSections" not in project_section_source
    assert not (portal_root / "routes" / "project" / "sections" / "VersionSections.tsx").exists()

    version_space_source = (portal_root / "routes" / "project" / "sections" / "version" / "VersionSpaceSection.tsx").read_text()
    version_create_source = (portal_root / "routes" / "project" / "sections" / "version" / "VersionCreateSection.tsx").read_text()
    version_cards_source = (portal_root / "routes" / "project" / "sections" / "version" / "VersionCards.tsx").read_text()
    assert len(version_space_source.splitlines()) < 70
    assert len(version_create_source.splitlines()) < 70
    assert "VersionList" in version_space_source
    assert "USCard" in version_space_source
    assert "ToolInvocationRuntime" in version_create_source
    assert "react-router-dom" not in version_space_source
    assert "react-router-dom" in version_cards_source

    assert "studioElement" not in router_source
    assert "NasusStudio" not in router_source
    assert "studioElement" not in route_config_source
    assert "NasusStudio" not in route_config_source
    prototype_route_section = route_config_source.split("path: '/prototype/:viewId?'", 1)[1].split("},", 1)[0]
    assert 'Navigate to="/build"' in prototype_route_section


def test_project_overview_quality_asset_presenters_use_route_view_models() -> None:
    portal_root = ROOT / "apps" / "portal" / "src"
    quality_asset_root = portal_root / "routes" / "project-overview" / "components" / "quality-asset"
    selectors_source = (portal_root / "routes" / "project-overview" / "projectWorkspaceSelectors.ts").read_text()
    panel_source = (portal_root / "routes" / "project-overview" / "components" / "QualityAssetPanel.tsx").read_text()
    workspace_view_source = (portal_root / "routes" / "project-overview" / "ProjectWorkspaceView.tsx").read_text()

    for fragment in [
        "export type QualityAssetPanelView",
        "export type QualityLaneCardView",
        "export type QualityLatestRunView",
        "export type QualityLoopStateView",
        "export type QualityPanelHeaderView",
        "export function qualityAssetPanelModel",
        "workspace.asset_lanes.map",
        "workspace.quality_loop_state",
        "workspace.runs[0]",
        "workspace.us_items[0]",
    ]:
        assert fragment in selectors_source

    assert "qualityAssetPanelModel(workspace)" in workspace_view_source
    assert "model?: QualityAssetPanelView" in panel_source
    assert "workspace?: ProjectWorkspaceData" not in panel_source

    forbidden_fragments = [
        "domains/quality-loop",
        "ProjectWorkspaceData",
        "RunSummary",
        "USItem",
        "AssetLane",
        "asset_lanes",
        "us_items",
        "quality_loop_state",
    ]
    presenter_paths = [portal_root / "routes" / "project-overview" / "components" / "QualityAssetPanel.tsx"]
    presenter_paths.extend(quality_asset_root.glob("*.tsx"))
    for source_path in presenter_paths:
        source = source_path.read_text()
        for fragment in forbidden_fragments:
            assert fragment not in source, f"{source_path.relative_to(ROOT)} leaks quality-loop DTO {fragment}"


def test_project_section_presenters_use_route_local_view_models() -> None:
    portal_root = ROOT / "apps" / "portal" / "src"
    section_root = portal_root / "routes" / "project" / "sections"
    view_models_source = (portal_root / "routes" / "project" / "ProjectSectionViewModels.ts").read_text()

    for fragment in [
        "export type GovernanceApprovalCardView",
        "export type SystemImageKnowledgeCardView",
        "export type RunCardView",
        "export function governanceSectionModel",
        "export function knowledgeSectionModel",
        "export function runsSectionModel",
        "context.workspace?.approvals",
        "context.systemImage?.objects",
        "context.workspace?.runs",
    ]:
        assert fragment in view_models_source

    forbidden_fragments = [
        "../../../domains/quality-loop",
        "../../../domains/system-image",
        "domains/quality-loop",
        "domains/system-image",
        "ApprovalSummary",
        "KnowledgeObject",
        "RunSummary",
    ]
    for source_path in section_root.glob("*.tsx"):
        source = source_path.read_text()
        for fragment in forbidden_fragments:
            assert fragment not in source, f"{source_path.relative_to(ROOT)} leaks domain DTO {fragment}"


def test_portal_bootstrap_and_route_elements_stay_thin() -> None:
    portal_root = ROOT / "apps" / "portal" / "src"
    main_source = (portal_root / "main.tsx").read_text()
    app_source = (portal_root / "App.tsx").read_text()
    providers_source = (portal_root / "app" / "providers.tsx").read_text()
    router_source = (portal_root / "app" / "router.tsx").read_text()
    route_config_source = (portal_root / "app" / "routing" / "routeConfig.tsx").read_text()
    route_elements_source = (portal_root / "app" / "routing" / "routeElements.tsx").read_text()

    assert "createRoot(document.getElementById('root')!).render(" in main_source
    assert "<AppProviders>" in main_source
    assert "<App />" in main_source
    assert "RouterProvider" in app_source
    assert "router={router}" in app_source
    assert "QueryClientProvider" in providers_source
    assert "createBrowserRouter(appRoutes)" in router_source
    assert "RouteObject[]" in route_config_source

    for source_name, source in [
        ("main.tsx", main_source),
        ("App.tsx", app_source),
        ("app/providers.tsx", providers_source),
        ("app/router.tsx", router_source),
        ("app/routing/routeConfig.tsx", route_config_source),
    ]:
        for forbidden in [
            "NasusStudio",
            "PrototypeStudio",
            "TopLevelStudio",
            "platformApi.",
            "agentApi.",
            "qualityLoopApi.",
            "systemImageApi.",
            "useConversation(",
            "useAuthActions",
            "useStudioSettings",
            "useTopLevelContent",
            "useProjectWorkspaceData",
            "dangerouslySetInnerHTML",
        ]:
            assert forbidden not in source, f"{source_name} must stay bootstrap/routing-only"

    assert "Navigate" in route_config_source
    assert "BuildRoute" not in route_config_source
    assert "DashboardRoute" not in route_config_source
    assert "ProjectSectionRoute" not in route_config_source
    assert "BuildRoute" in route_elements_source
    assert "DashboardRoute" in route_elements_source
    assert "ProjectSectionRoute" in route_elements_source
    assert "createBrowserRouter" not in route_elements_source
    assert "path:" not in route_elements_source
    for forbidden in [
        "platformApi.",
        "agentApi.",
        "qualityLoopApi.",
        "systemImageApi.",
        "useQuery(",
        "useMutation",
        "useConversation(",
        "dangerouslySetInnerHTML",
    ]:
        assert forbidden not in route_elements_source


def test_auth_routes_delegate_session_side_effects_to_platform_domain_hook() -> None:
    portal_root = ROOT / "apps" / "portal" / "src"
    login_source = (portal_root / "routes" / "auth" / "LoginRoute.tsx").read_text()
    register_source = (portal_root / "routes" / "auth" / "RegisterRoute.tsx").read_text()
    auth_hook_source = (portal_root / "domains" / "platform" / "useAuthSession.ts").read_text()

    for source in [login_source, register_source]:
        assert "useAuthActions" in source
        assert "platformApi" not in source
        assert "setSession" not in source

    assert "async login(payload: AuthLoginPayload)" in auth_hook_source
    assert "async register(payload: AuthRegisterPayload)" in auth_hook_source
    assert "platformApi.login(payload)" in auth_hook_source
    assert "platformApi.register(payload)" in auth_hook_source
    assert "setSession(await platformApi.login(payload))" in auth_hook_source
    assert "setSession(await platformApi.register(payload))" in auth_hook_source


def test_shells_do_not_own_platform_settings_side_effects() -> None:
    portal_root = ROOT / "apps" / "portal" / "src"
    shell_container_paths = [
        portal_root / "app" / "shells" / "TopLevelStudioShell.tsx",
        portal_root / "app" / "shells" / "ProjectWorkspaceShell.tsx",
    ]
    shell_view_paths = [
        portal_root / "app" / "shells" / "TopLevelStudioShellView.tsx",
        portal_root / "app" / "shells" / "ProjectWorkspaceShellView.tsx",
    ]
    forbidden_shell_fragments = [
        "useMutation",
        "useQuery(",
        "useQueryClient",
        "api.getSettings",
        "api.updateSettings",
        "api.testSettingsConnection",
        "useTheme(",
    ]

    for shell_path in shell_container_paths:
        shell_source = shell_path.read_text()
        assert "useStudioSettings" in shell_source
        assert "StudioSettingsLayer" in shell_source
        assert "ShellView" in shell_source
        assert "../../shared/ui/SettingsPopover" not in shell_source
        assert "<SettingsPopover" not in shell_source
        assert len(shell_source.splitlines()) < 80
        for fragment in forbidden_shell_fragments:
            assert fragment not in shell_source, f"{shell_path.relative_to(ROOT)} still owns settings side effect {fragment}"

    for shell_view_path in shell_view_paths:
        shell_view_source = shell_view_path.read_text()
        assert "StudioTermsBar" in shell_view_source
        assert "useSettingsPopover" in shell_view_source
        assert "renderSettingsLayer" in shell_view_source
        assert "domains/platform" not in shell_view_source
        assert "useStudioSettings" not in shell_view_source
        assert "StudioSettingsLayer" not in shell_view_source

    settings_hook_source = (portal_root / "domains" / "platform" / "useStudioSettings.ts").read_text()
    project_sidebar_source = (portal_root / "app" / "shells" / "ProjectWorkspaceSidebar.tsx").read_text()
    settings_layer_source = (portal_root / "app" / "shells" / "StudioSettingsLayer.tsx").read_text()
    assert "platformApi.getSettings" in settings_hook_source
    assert "platformApi.updateSettings" in settings_hook_source
    assert "platformApi.testModelConfig" in settings_hook_source
    assert "useTheme(" in settings_hook_source
    assert "ProjectNav" in project_sidebar_source
    assert "SettingsPopover" in settings_layer_source
    assert "useStudioSettings(" not in settings_layer_source


def test_settings_popover_is_composed_from_focused_panels() -> None:
    portal_root = ROOT / "apps" / "portal" / "src"
    settings_root = portal_root / "app" / "shells" / "settings"
    platform_settings_root = portal_root / "domains" / "platform" / "settings"
    popover_source = (settings_root / "SettingsPopover.tsx").read_text()
    panel_renderer_source = (settings_root / "SettingsPanelRenderer.tsx").read_text()
    choice_renderer_source = (
        settings_root / "SettingsChoicePanelRenderer.tsx"
    ).read_text()
    choice_configs_source = (settings_root / "settingsChoiceConfigs.ts").read_text()
    choice_panel_ids_source = (settings_root / "settingsChoicePanelIds.ts").read_text()
    menu_model_source = (settings_root / "settingsMenuModel.ts").read_text()
    model_panel_source = (settings_root / "ModelConfigurationPanel.tsx").read_text()
    model_body_source = (settings_root / "ModelConfigurationBody.tsx").read_text()
    model_fields_source = (settings_root / "ModelConfigurationFields.tsx").read_text()
    model_draft_source = (platform_settings_root / "useModelConfigurationDraft.ts").read_text()
    settings_sources = [
        popover_source,
        panel_renderer_source,
        choice_renderer_source,
        choice_configs_source,
        choice_panel_ids_source,
        menu_model_source,
        model_panel_source,
        model_body_source,
        model_fields_source,
        model_draft_source,
        (settings_root / "SettingsInfoPanels.tsx").read_text(),
        (platform_settings_root / "modelProfiles.ts").read_text(),
        (portal_root / "shared" / "tokens" / "useTheme.ts").read_text(),
        (portal_root / "domains" / "platform" / "useStudioSettings.ts").read_text(),
    ]

    assert len(popover_source.splitlines()) < 70
    assert len(panel_renderer_source.splitlines()) < 80
    assert len(choice_renderer_source.splitlines()) < 60
    assert len(model_panel_source.splitlines()) < 90
    assert "SettingsMenu" in popover_source
    assert "SettingsPanelRenderer" in popover_source
    assert "buildSettingsMenuItems" in popover_source
    assert "SettingsChoicePanel" not in popover_source
    assert "ModelConfigurationPanel" not in popover_source
    assert "AccountStatusPanel" not in popover_source
    assert "ProviderStatusPanel" not in popover_source
    assert "modelRouteLabel" not in popover_source
    assert "SettingsChoicePanelRenderer" in panel_renderer_source
    assert "isSettingsChoicePanel" in panel_renderer_source
    assert "from './SettingsChoicePanel'" not in panel_renderer_source
    assert "themeChoices" not in panel_renderer_source
    assert "isSettingsChoicePanel" in choice_panel_ids_source
    assert "SettingsChoicePanel" in choice_renderer_source
    assert "themeChoices" in choice_renderer_source
    assert "languageChoices" in choice_renderer_source
    assert "notificationChoices" in choice_renderer_source
    assert "themeChoices" in choice_configs_source
    assert "languageChoices" in choice_configs_source
    assert "notificationChoices" in choice_configs_source
    assert "ModelConfigurationPanel" in panel_renderer_source
    assert "AccountStatusPanel" in panel_renderer_source
    assert "ProviderStatusPanel" in panel_renderer_source
    assert "modelRouteLabel" in menu_model_source
    assert "ModelConfigurationBody" in model_panel_source
    assert "ModelConfigurationFields" in model_body_source
    assert "ModelConfigurationList" in model_body_source
    assert "ModelConnectionResult" in model_body_source
    assert "ModelRouteTabs" in model_panel_source
    assert "useModelConfigurationDraft" in model_body_source
    assert "model-config-form" not in popover_source
    assert "model-config-form" not in model_panel_source
    assert "custom_provider_kind" not in popover_source
    assert "custom_provider_kind" not in model_panel_source
    assert "profileFor(" not in popover_source
    assert "profileFor(" not in model_panel_source
    assert "model-config-form" in model_fields_source
    assert "custom_provider_kind" in model_draft_source
    for source in settings_sources:
        assert "features/" not in source
    assert not (portal_root / "shared" / "ui" / "settings").exists()
    assert not (portal_root / "shared" / "ui" / "SettingsPopover.tsx").exists()
    assert not (platform_settings_root / "SettingsPopover.tsx").exists()
    assert not (platform_settings_root / "ModelConfigurationPanel.tsx").exists()


def test_shared_account_ui_is_presentational_and_platform_hooks_own_avatar_side_effects() -> None:
    portal_root = ROOT / "apps" / "portal" / "src"
    avatar_editor_source = (portal_root / "shared" / "ui" / "AvatarEditor.tsx").read_text()
    account_menu_source = (portal_root / "shared" / "ui" / "UserAccountMenu.tsx").read_text()
    user_avatar_source = (portal_root / "shared" / "ui" / "UserAvatar.tsx").read_text()
    settings_info_source = (portal_root / "app" / "shells" / "settings" / "SettingsInfoPanels.tsx").read_text()
    avatar_hook_source = (portal_root / "domains" / "platform" / "useUserAvatar.ts").read_text()
    account_container_source = (portal_root / "app" / "shells" / "UserAccountMenuContainer.tsx").read_text()
    settings_layer_source = (portal_root / "app" / "shells" / "StudioSettingsLayer.tsx").read_text()

    for source in [avatar_editor_source, account_menu_source, user_avatar_source, settings_info_source]:
        for forbidden in [
            "platformApi",
            "useAuthUser",
            "useAuthActions",
            "apiAuthToken",
            "fetch(",
            "react-router-dom",
        ]:
            assert forbidden not in source

    for source in [avatar_editor_source, account_menu_source, user_avatar_source]:
        assert "domains/" not in source
        assert "UserProfile" not in source

    assert "onUploadAvatar" in avatar_editor_source
    assert "onSelectPreset" in avatar_editor_source
    assert "avatarImageUrl" in avatar_editor_source
    assert "UserAvatarView" in user_avatar_source
    assert "UserAccountMenuView" in account_menu_source
    assert "avatarEditor" in account_menu_source
    assert "avatarEditor" in settings_info_source
    assert "platformApi.updateAvatar" in avatar_hook_source
    assert "platformApi.logout" in avatar_hook_source
    assert "platformApiAuthToken" in avatar_hook_source
    assert "fetch(" in avatar_hook_source
    assert "useNavigate" in account_container_source
    assert "useAvatarEditorModel" in account_container_source
    assert "UserAccountMenu" in account_container_source
    assert "useAvatarEditorModel" in settings_layer_source
    assert "SettingsPopover" in settings_layer_source


def test_portal_upgrade_card_glow_is_not_coupled_to_hero_composer() -> None:
    styles_root = ROOT / "apps" / "portal" / "src" / "styles"
    shell_css = (styles_root / "studio-shell.css").read_text()
    build_css = (styles_root / "build.css").read_text()
    theme_css = (styles_root / "theme-overrides.css").read_text()

    assert ".upgrade-card::after,\n.hero-composer::after" not in shell_css
    assert ".upgrade-card::after,\n.hero-composer::after" not in build_css
    assert ".upgrade-card::before,\n.hero-composer::before" not in shell_css
    assert ".upgrade-card::before,\n.hero-composer::before" not in build_css
    assert ".upgrade-card::after {" in shell_css
    assert ".hero-composer::after {" in shell_css
    assert "padding-box" in shell_css
    assert "border-box" in shell_css
    assert ".upgrade-card::after {\n  content: none;\n}" in shell_css
    assert "linear-gradient(rgb(29, 30, 32), rgb(29, 30, 32)) padding-box" in shell_css
    assert "radial-gradient(circle at 18% 4%" not in shell_css
    assert ":root[data-theme='light'] .upgrade-card::after,\n:root[data-theme='light'] .hero-composer::after" not in theme_css
    assert ":root[data-theme='light'] .upgrade-card::before,\n:root[data-theme='light'] .hero-composer::before" not in theme_css
    assert ":root[data-theme='light'] .upgrade-card::after {\n  content: none;\n}" in theme_css
    assert "linear-gradient(rgb(255, 255, 255), rgb(255, 255, 255)) padding-box" in theme_css


def test_frontend_has_no_legacy_bucket_directories() -> None:
    portal_root = ROOT / "apps" / "portal" / "src"
    forbidden_dirs = [
        portal_root / "app",
        portal_root / "routes",
        portal_root / "shared",
        portal_root / "hooks",
        portal_root / "domains",
    ]
    offenders: list[str] = []

    assert not (portal_root / "features").exists() or not list((portal_root / "features").glob("*"))
    assert not (portal_root / "hooks").exists() or not list((portal_root / "hooks").glob("*"))

    for directory in forbidden_dirs:
        for path in directory.rglob("*"):
            if path.suffix not in {".ts", ".tsx"}:
                continue
            source = path.read_text()
            if "features/" in source or "/hooks/" in source or "../hooks/" in source:
                offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_http_operational_controls_follow_platform_ddd_boundaries() -> None:
    application_source = (
        ROOT
        / "apps/api/app/application/platform/request_rate_limits.py"
    ).read_text()
    adapter_source = (
        ROOT
        / "apps/api/app/infrastructure/platform/request_rate_limiter.py"
    ).read_text()
    metrics_source = (
        ROOT
        / "apps/api/app/infrastructure/platform/http_metrics.py"
    ).read_text()
    composition_source = (ROOT / "apps/api/app/composition.py").read_text()
    runtime_config_source = (
        ROOT / "apps/api/app/infrastructure/config/runtime_config.py"
    ).read_text()
    migration = (
        ROOT / "apps/api/migrations/versions/0024_api_rate_limit_windows.py"
    )

    assert "class RequestRateLimitPort(Protocol)" in application_source
    assert "sqlalchemy" not in application_source.lower()
    assert "fastapi" not in application_source.lower()
    assert "class SQLAlchemyFixedWindowRateLimiter" in adapter_source
    assert "on_conflict_do_update" in adapter_source
    assert "sha256" in adapter_source
    assert "nasus_http_requests_total" in metrics_source
    assert "nasus_rate_limit_rejections_total" in metrics_source
    assert "resolve_request_id(request)" in composition_source
    assert "X-RateLimit-Remaining" in composition_source
    assert "NASUS_RATE_LIMIT_ENABLED must be true" in runtime_config_source
    assert migration.exists()


def test_production_governance_uses_sql_workspace_and_atomic_entity_writes() -> None:
    app_root = ROOT / "apps/api/app"
    store_source = (app_root / "store.py").read_text()
    workspace_source = (
        app_root / "infrastructure/platform/governance_workspace.py"
    ).read_text()
    repository_source = (
        app_root / "infrastructure/platform/governance_repository.py"
    ).read_text()
    application_source = (
        app_root / "application/platform/governance.py"
    ).read_text()

    assert "self.governance_workspace = SQLAlchemyGovernanceWorkspace(" in store_source
    assert "CompatibilityGovernanceWorkspace(" not in store_source
    assert "class SQLAlchemyGovernanceWorkspace" in workspace_source
    assert "class SQLAlchemyGovernanceCommandRepository" in repository_source
    assert "save_approval_and_sync_pending_counts" in repository_source
    assert "session.flush()" in repository_source
    assert "ProjectRecord.pending_approvals" not in application_source
    assert "self._workspace.save_approval(project_id, approval)" in application_source
    assert "self._workspace.replace_approvals(" not in application_source
    assert "self._workspace.replace_versions(" not in application_source
