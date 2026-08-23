from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PORTAL_SRC = ROOT / "apps" / "portal" / "src"
IMPORT_RE = re.compile(
    r"""(?:import|export)\s+(?:type\s+)?(?:[\s\S]*?\s+from\s+)?["']([^"']+)["']""",
    re.MULTILINE,
)


def _source_files() -> list[Path]:
    return sorted(
        path
        for path in PORTAL_SRC.rglob("*")
        if path.suffix in {".ts", ".tsx"} and "dist" not in path.parts
    )


def _layer_for(path: Path) -> str:
    relative = path.relative_to(PORTAL_SRC)
    return relative.parts[0]


def _resolve_import(source_path: Path, specifier: str) -> Path | None:
    if specifier.startswith("."):
        resolved = (source_path.parent / specifier).resolve()
        try:
            return resolved.relative_to(PORTAL_SRC.resolve())
        except ValueError:
            return None
    if specifier.startswith("@/"):
        return Path(specifier[2:])
    return None


def _import_specifiers(source_path: Path) -> list[str]:
    return [match.group(1) for match in IMPORT_RE.finditer(source_path.read_text())]


def _imports_inside_portal(source_path: Path) -> list[Path]:
    imports: list[Path] = []
    for specifier in _import_specifiers(source_path):
        resolved = _resolve_import(source_path, specifier)
        if resolved is not None:
            imports.append(resolved)
    return imports


def test_portal_has_feature_sliced_entrypoints_without_legacy_studios() -> None:
    assert (PORTAL_SRC / "app" / "routing" / "routeConfig.tsx").exists()
    assert (PORTAL_SRC / "app" / "routing" / "routeElements.tsx").exists()
    assert (PORTAL_SRC / "app" / "shells" / "TopLevelStudioShell.tsx").exists()
    assert (PORTAL_SRC / "domains" / "agent").is_dir()
    assert (PORTAL_SRC / "domains" / "platform").is_dir()
    assert (PORTAL_SRC / "domains" / "quality-loop").is_dir()
    assert (PORTAL_SRC / "domains" / "system-image").is_dir()
    assert (PORTAL_SRC / "shared" / "ui").is_dir()

    for legacy_file in [
        "app/NasusStudio.tsx",
        "app/PrototypeStudio.tsx",
        "app/TopLevelStudio.tsx",
        "app/prototypeShared.tsx",
    ]:
        assert not (PORTAL_SRC / legacy_file).exists(), legacy_file

    route_config = (PORTAL_SRC / "app" / "routing" / "routeConfig.tsx").read_text()
    route_elements = (PORTAL_SRC / "app" / "routing" / "routeElements.tsx").read_text()
    router = (PORTAL_SRC / "app" / "router.tsx").read_text()
    assert "createBrowserRouter(appRoutes)" in router
    assert "NasusStudio" not in route_config + route_elements + router
    assert "PrototypeStudio" not in route_config + route_elements + router
    assert "TopLevelStudio" not in route_config + route_elements + router


def test_shared_layer_is_product_neutral() -> None:
    for source_path in _source_files():
        if _layer_for(source_path) != "shared":
            continue
        source = source_path.read_text()
        assert "react-router-dom" not in source, f"{source_path.relative_to(ROOT)} imports router APIs"
        assert "Nasus Studio" not in source, f"{source_path.relative_to(ROOT)} owns product chrome"
        assert "studio-sidebar" not in source, f"{source_path.relative_to(ROOT)} owns shell chrome"
        for imported in _imports_inside_portal(source_path):
            imported_layer = imported.parts[0]
            assert imported_layer in {"shared", "styles"}, (
                f"{source_path.relative_to(ROOT)} imports product layer {imported}"
            )


def test_domain_layer_does_not_import_routes_app_or_shared_ui() -> None:
    for source_path in _source_files():
        if _layer_for(source_path) != "domains":
            continue
        for imported in _imports_inside_portal(source_path):
            assert imported.parts[0] not in {"app", "routes"}, (
                f"{source_path.relative_to(ROOT)} imports UI layer {imported}"
            )
            assert imported.parts[:2] != ("shared", "ui"), (
                f"{source_path.relative_to(ROOT)} imports shared UI {imported}"
            )


def test_shared_api_transport_does_not_own_platform_token_storage() -> None:
    shared_client_source = (PORTAL_SRC / "shared" / "api" / "client.ts").read_text()
    platform_token_source = (PORTAL_SRC / "domains" / "platform" / "authTokenStorage.ts").read_text()
    auth_session_source = (PORTAL_SRC / "domains" / "platform" / "useAuthSession.ts").read_text()

    for forbidden in [
        "localStorage",
        "nasus_api_token",
        "setApiAuthToken",
        "clearApiAuthToken",
        "hasStoredApiAuthToken",
    ]:
        assert forbidden not in shared_client_source

    assert "configureApiAuthTokenProvider" in shared_client_source
    assert "apiAuthToken" in shared_client_source
    assert "window.localStorage" in platform_token_source
    assert "configureApiAuthTokenProvider(storedApiAuthToken)" in platform_token_source
    assert "platformApiAuthToken" in auth_session_source
    assert "shared/api/client" not in auth_session_source


def test_shell_views_are_layout_only_and_shell_containers_own_chrome_hooks() -> None:
    shell_root = PORTAL_SRC / "app" / "shells"
    top_level_sidebar_source = (shell_root / "TopLevelSidebar.tsx").read_text()
    top_level_shell_source = (shell_root / "TopLevelStudioShell.tsx").read_text()
    top_level_shell_view_source = (shell_root / "TopLevelStudioShellView.tsx").read_text()

    for source_path in shell_root.glob("*ShellView.tsx"):
        source = source_path.read_text()
        assert "domains/" not in source
        assert "useStudioSettings" not in source
        assert "platformApi" not in source
        assert "useNavigate" not in source

    for source_path in [
        shell_root / "TopLevelStudioShell.tsx",
        shell_root / "ProjectWorkspaceShell.tsx",
    ]:
        source = source_path.read_text()
        assert "useStudioSettings" in source
        assert "ShellView" in source
        assert "useMutation" not in source
        assert "platformApi." not in source

    assert "Nasus Studio" in top_level_sidebar_source
    assert "studio-sidebar" in top_level_sidebar_source
    assert "react-router-dom" not in top_level_sidebar_source
    assert "onNavigate: (path: string) => void" in top_level_sidebar_source
    assert "useNavigate" in top_level_shell_source
    assert "onNavigate={(path) => navigate(path)}" in top_level_shell_source
    assert "onNavigate={onNavigate}" in top_level_shell_view_source


def test_routes_do_not_bypass_domain_command_surfaces() -> None:
    forbidden_imports = {
        "../../domains/platform/api",
        "../../domains/agent/api",
        "../../domains/quality-loop/api",
        "../../domains/system-image/api",
        "../../../domains/platform/api",
        "../../../domains/agent/api",
        "../../../domains/quality-loop/api",
        "../../../domains/system-image/api",
    }
    forbidden_fragments = [
        "platformApi.invokeTool",
        "platformApi.confirmToolInvocation",
        "agentApi.createAgentGoal",
        "agentApi.resumeAgentGoal",
        "qualityLoopApi.",
        "systemImageApi.",
        "fetch(",
        "dangerouslySetInnerHTML",
    ]

    for source_path in _source_files():
        if _layer_for(source_path) != "routes":
            continue
        specifiers = set(_import_specifiers(source_path))
        leaked_imports = specifiers & forbidden_imports
        assert not leaked_imports, f"{source_path.relative_to(ROOT)} imports raw domain API {leaked_imports}"
        source = source_path.read_text()
        for fragment in forbidden_fragments:
            assert fragment not in source, f"{source_path.relative_to(ROOT)} bypasses domain command surface: {fragment}"


def test_app_bootstrap_and_route_config_stay_thin() -> None:
    checked_files = [
        PORTAL_SRC / "main.tsx",
        PORTAL_SRC / "App.tsx",
        PORTAL_SRC / "app" / "providers.tsx",
        PORTAL_SRC / "app" / "router.tsx",
        PORTAL_SRC / "app" / "routing" / "routeConfig.tsx",
    ]
    forbidden_fragments = [
        "useQuery(",
        "useMutation",
        "platformApi.",
        "agentApi.",
        "qualityLoopApi.",
        "systemImageApi.",
        "useConversation(",
        "useStudioSettings",
        "dangerouslySetInnerHTML",
    ]
    for source_path in checked_files:
        source = source_path.read_text()
        for fragment in forbidden_fragments:
            assert fragment not in source, f"{source_path.relative_to(ROOT)} owns runtime logic {fragment}"

    route_config = (PORTAL_SRC / "app" / "routing" / "routeConfig.tsx").read_text()
    route_elements = (PORTAL_SRC / "app" / "routing" / "routeElements.tsx").read_text()
    assert "path:" in route_config
    assert "BuildRoute" not in route_config
    assert "BuildRoute" in route_elements
    assert "path:" not in route_elements


def test_agent_event_reducer_uses_canonical_runtime_contract() -> None:
    event_hook = (PORTAL_SRC / "domains" / "agent" / "useConversationEvents.ts").read_text()
    reducer = (PORTAL_SRC / "domains" / "agent" / "conversationEventReducer.ts").read_text()
    workspace_view = (
        PORTAL_SRC / "routes" / "project-overview" / "ProjectWorkspaceView.tsx"
    ).read_text()

    for event_type in [
        "agent.step.updated",
        "agent.step.thinking.delta",
        "agent.step.observation.delta",
        "agent.step.decision.delta",
        "agent.swarm.updated",
    ]:
        assert event_type in event_hook

    assert "event.event_type.startsWith('agent.step.')" in reducer
    assert "event.entity_type === 'agent_swarm'" in reducer
    assert "<AgentRuntimeDetails" in workspace_view
