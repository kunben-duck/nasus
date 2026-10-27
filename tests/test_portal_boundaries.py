from __future__ import annotations

import re
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PORTAL_SRC = ROOT / "apps" / "portal" / "src"
IMPORT_RE = re.compile(
    r"""(?:import|export)\s+(?:type\s+)?(?:[\s\S]*?\s+from\s+)?["']([^"']+)["']""",
    re.MULTILINE,
)
DIRECT_FETCH_RE = re.compile(r"(?<![\w$])fetch\s*\(")


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
        if "i18n" not in source_path.parts:
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


def test_analysis_result_view_does_not_import_provider_or_transport_contracts() -> None:
    view = PORTAL_SRC / "routes/project/sections/knowledge/analysis/AnalysisObservationList.tsx"
    imports = _imports_inside_portal(view)
    assert not any(item.parts[0] == "domains" or item.parts[:2] == ("shared", "api") for item in imports)
    assert any(item.name == "analysisObservationView" for item in imports)


def test_frozen_image_inspector_reads_domain_view_models_without_current_alias_lookup() -> None:
    views = PORTAL_SRC / "routes/project/sections/knowledge/revisions"
    for path in views.rglob("*.tsx"):
        source = path.read_text()
        assert "dangerouslySetInnerHTML" not in source
        assert "evidenceApi" not in source and "useSourceEvidence" not in source
        assert "imageRevisionApi" not in source
    hooks = (PORTAL_SRC / "domains/system-image/useImageRevisions.ts").read_text()
    assert "gcTime: 0" in hooks and "retry: false" in hooks
    assert "scope.sessionId" in hooks and "loadImageRevisionPage" in hooks
    page_reader = (PORTAL_SRC / "domains/system-image/imageRevisionPage.ts").read_text()
    assert "requireMatchingMembers" in page_reader and "signal.throwIfAborted()" in page_reader
    pair = (PORTAL_SRC / "domains/system-image/imageReadPair.ts").read_text()
    assert "readImagePair(" in page_reader and "!isImagePageSizeError(error)" in page_reader
    assert "error.status === 413" in pair and "error.code === 'image_page_too_large'" in pair
    assert "Promise.allSettled" in pair and "failures.find((error) => !isImagePageSizeError(error))" in pair
    assert "throw denied" in pair and "signal.throwIfAborted()" in pair
    assert "member.evidence_ids.includes(evidenceId)" in hooks
    api = (PORTAL_SRC / "domains/system-image/imageRevisionApi.ts").read_text()
    assert "cache: 'no-store'" in api and "encodeURIComponent(revisionId)" in api
    assert "/objects/${encodeURIComponent(objectId)}/evidence/" in api


def test_build_review_handoff_reauthorizes_the_original_checkpoint_without_a_write() -> None:
    domain = PORTAL_SRC / "domains/system-image"
    reader = (domain / "buildReviewHandoffApi.ts").read_text()
    hook = (domain / "useBuildReviewHandoff.ts").read_text()
    backend = ROOT / "apps/api/app/application/platform/tool_handlers/query_input.py"
    declaration = next(node for node in ast.parse(backend.read_text()).body
        if isinstance(node, ast.Assign) and node.targets[0].id == "CONTEXT_KEYS")
    context_keys = ast.literal_eval(declaration.value.args[0])
    frontend_keys = set(re.findall(r"'([^']+)'", re.search(
        r"const coordinationKeys = new Set\(\[(.*?)\]\)", reader, re.S).group(1)))
    assert frontend_keys == context_keys | {"confirmed_at", "confirmed_by_user"}
    assert "command.input_payload.agent_goal_id !== goal.id" in reader
    assert "input(step.tool_input_payload)" in reader
    assert "const current = await read<AgentGoal>(goalPath)" in reader
    assert "!same(goal, current)" in reader and "signal.throwIfAborted()" in reader
    assert "cache: 'no-store'" in reader and "method:" not in reader
    assert "platformApi" not in reader and "publication_allowed !== false" in reader
    assert "buildPlanApi.read" in reader and "imageRevisionApi.page" in reader
    assert "buildPlanApi.target" in reader and "currentTarget.target_version_id !== target.target_version_id" in reader
    for contract in ("gcTime: 0", "retry: false", "refetchOnWindowFocus: 'always'", "sessionId"):
        assert contract in hook
    view = (PORTAL_SRC / "routes/project/sections/knowledge/revisions/BuildReviewInspector.tsx").read_text()
    assert "if (query.isFetching) return" in view and "query.isError || !query.data" in view
    assert "reloadReview={() => { void query.refetch() }}" in view
    assert "baselines={[query.data.targetBaseline]}" in view
    workspace = (PORTAL_SRC / "domains/platform/useProjectWorkspaceData.ts").read_text()
    assert workspace.count("enabled: Boolean(project?.id) && !reviewingBuild") == 2
    assert "systemImage: reviewingBuild || systemImageQuery.isError ? undefined" in workspace
    knowledge = (PORTAL_SRC / "routes/project/sections/KnowledgeSection.tsx").read_text()
    assert knowledge.index("if (context.reviewingBuild") < knowledge.index("if (!context.systemImage)")


def test_frozen_page_continuity_keeps_scope_checks_and_hides_unverified_data() -> None:
    domain = PORTAL_SRC / "domains/system-image"
    hooks = (domain / "useImageRevisions.ts").read_text()
    placeholder = (domain / "imagePageReuse.ts").read_text()
    view = (PORTAL_SRC / "routes/project/sections/knowledge/revisions/ImageRevisionData.tsx").read_text()
    assert "previousQuery?.queryKey, queryKey" in hooks and "imagePagePlaceholder" in hooks
    assert "previousKey.length !== 6" in placeholder and "currentKey.length !== 6" in placeholder
    assert "currentKey.slice(0, 5).every" in placeholder and "[1, 3, 4].every" in placeholder
    assert "!query.isError && query.data" in view and "hidden={query.isFetching}" in view
    assert "!query.isFetching && !query.isPlaceholderData" in view
    assert "gcTime: 0" in hooks and "staleTime: 0" in hooks and "retry: false" in hooks


def test_frozen_record_navigation_uses_the_verified_page_without_another_transport() -> None:
    domain = PORTAL_SRC / "domains/system-image"
    views = PORTAL_SRC / "routes/project/sections/knowledge/revisions"
    policy = (domain / "imageRecordPosition.ts").read_text()
    navigation = (views / "ImageRecordNavigation.tsx").read_text()
    page = (views / "ImageRevisionData.tsx").read_text()
    assert "Number.isSafeInteger(total)" in policy and "Number.isSafeInteger(record)" in policy
    assert "record >= 1 && record <= total" in policy
    assert "event.preventDefault()" in navigation and "next !== null && next !== offset" in navigation
    assert "disabled={next === null || next === offset}" in navigation
    assert "ImageRecordNavigation" in page and "total={query.data.total}" in page
    assert "offsets: [...paging.offsets, offset]" in page
    assert "key={`navigation:${selection.section}:${selection.offset}`}" in page
    assert "key={`records:${selection.section}:${selection.offset}`}" in page
    assert "platformApi" not in navigation and "shared/api" not in navigation


def test_analysis_reauthorization_hides_content_without_discarding_fixed_selection() -> None:
    analysis = PORTAL_SRC / "routes/project/sections/knowledge/analysis"
    for name in ("AnalysisSourceSelector.tsx", "AnalysisReportSelector.tsx"):
        view = (analysis / name).read_text()
        assert "if (query.isError) return null" in view
        assert "if (query.isPending) return" in view
        assert "hidden={query.isFetching}" in view
        assert "if (query.isPending || query.isFetching) return" not in view
        assert "!query.isFetching && chosen" in view
    hooks = (PORTAL_SRC / "domains/system-image/useCodeAnalysis.ts").read_text()
    for fragment in ("gcTime: 0", "staleTime: 0", "retry: false", "refetchOnWindowFocus: 'always'", "scope.sessionId"):
        assert fragment in hooks


def test_reviewed_scope_owns_commands_and_keeps_private_reads_out_of_route_views() -> None:
    domain = PORTAL_SRC / "domains/quality-loop"
    hook = (domain / "useTestDesignScope.ts").read_text()
    api = (domain / "testDesignScopeApi.ts").read_text()
    for expected in ("gcTime: 0", "retry: false", "sessionId", "query.dataUpdatedAt", "setConsent('')", "onFailure(true)"):
        assert expected in hook
    assert "cache: 'no-store'" in api and "quality.test_design_scope.review" in api
    assert "platformApi.confirmToolInvocation(pending.id)" in api
    assert "verifyScopeArchive" in api and "verifyScopeView" in api
    for name in ("testDesignScopeDraft.ts", "testDesignScopeValidation.ts"):
        assert "shared/api" not in (domain / name).read_text()
        assert "scopeContractValid" in (domain / name).read_text()
    for path in (PORTAL_SRC / "routes/project/sections/knowledge/scope").glob("*.tsx"):
        source = path.read_text()
        assert "testDesignScopeApi" not in source and "platformApi" not in source
        assert "dangerouslySetInnerHTML" not in source and "localStorage" not in source


def test_native_generation_ui_keeps_fixed_budget_and_canonical_controls_in_domain() -> None:
    domain = PORTAL_SRC / "domains/quality-loop"
    hook = (domain / "useTestDesignGeneration.ts").read_text()
    api = (domain / "testDesignGenerationApi.ts").read_text()
    validator = (domain / "testDesignGenerationValidation.ts").read_text()
    for value in ("gcTime: 0", "retry: false", "sessionId", "models.dataUpdatedAt", "const controlKey = JSON.stringify(job)", "void refreshHistory()", "setConsent('')"):
        assert value in hook
    for value in ("verifyGenerationPreview", "verifyGenerationJob", "verifyGenerationArchive", "cache: 'no-store'",
                  "platformApi.confirmToolInvocation(pending.id)", "quality.test_design.cancel", "quality.test_design.recover"):
        assert value in api
    for value in ("one_complete_input_no_truncation", "pending_independent_review", "expectedObligations", "provider_outcome_unknown"):
        assert value in validator
    for value in ("useInfiniteQuery", "historyPage(scope, pageParam, signal)", "page.has_running", "history.fetchNextPage()"):
        assert value in hook
    assert "verifyGenerationHistory" in api and "limit: 20" in api
    assert "/v1/tool-invocations?" not in api
    assert "testDesignGenerationApi.history(scope" not in hook
    assert "shared/api" not in validator and "platformApi" not in validator
    view = (PORTAL_SRC / "routes/project/sections/knowledge/scope/TestDesignGenerationPanel.tsx").read_text()
    for forbidden in ("platformApi", "testDesignGenerationApi", "dangerouslySetInnerHTML", "localStorage"):
        assert forbidden not in view


def test_mapping_review_keeps_canonical_writes_and_fail_closed_parent_in_domain() -> None:
    domain = PORTAL_SRC / "domains/quality-loop"
    hook = (domain / "useTestDesignMapping.ts").read_text()
    api = (domain / "testDesignMappingApi.ts").read_text()
    validator = (domain / "testDesignMappingValidation.ts").read_text()
    for value in ("gcTime: 0", "retry: false", "sessionId", "query.dataUpdatedAt", "submitted.current", "onFailure()"):
        assert value in hook
    for value in ("quality.test_design_mapping.review", "cache: 'no-store'", "platformApi.confirmToolInvocation(pending.id)", "verifyMappingArchive", "verifyMappingView"):
        assert value in api
    assert "shared/api" not in validator and "platformApi" not in validator
    generation = (domain / "useTestDesignGeneration.ts").read_text()
    assert "setMappingFailed(true)" in generation and "!mappingFailed && job" in generation
    for name in ("TestDesignMappingPanel.tsx", "AssertionMappingEditor.tsx"):
        source = (PORTAL_SRC / "routes/project/sections/knowledge/scope" / name).read_text()
        for forbidden in ("testDesignMappingApi", "platformApi", "dangerouslySetInnerHTML", "localStorage"):
            assert forbidden not in source


def test_reviewer_discovery_does_not_depend_on_admin_generation_access() -> None:
    domain = PORTAL_SRC / "domains/quality-loop"
    api = (domain / "testDesignReviewApi.ts").read_text()
    hook = (domain / "useTestDesignReviewQueue.ts").read_text()
    validator = (domain / "testDesignReviewValidation.ts").read_text()
    for fragment in ("test-design-review-drafts", "cache: 'no-store'", "verifyScopeArchive", "verifyGenerationArchive",
                     "mappingDigest(archive.result)", "signal.throwIfAborted()"):
        assert fragment in api
    for forbidden in ("platformApi", "invokeTool", "test-design-jobs", "model-configs", "method: 'POST'"):
        assert forbidden not in api
    for fragment in ("gcTime: 0", "retry: false", "sessionId", "setBlocked(true)", "!detail.isFetching", "list.isError", "overlap"):
        assert fragment in hook
    assert "shared/api" not in validator and "platformApi" not in validator
    for name in ("TestDesignReviewQueue.tsx", "ArchivedDraftCases.tsx"):
        source = (PORTAL_SRC / "routes/project/sections/knowledge/scope" / name).read_text()
        for forbidden in ("testDesignReviewApi", "platformApi", "dangerouslySetInnerHTML", "localStorage", "useMutation"):
            assert forbidden not in source


def test_mapping_parts_use_private_pins_and_independent_canonical_confirmation() -> None:
    domain = PORTAL_SRC / "domains/quality-loop"
    api = (domain / "mappingStagingApi.ts").read_text()
    for value in ("'/v1/auth/me'", "cache: 'no-store'", "prepareMappingPlan", "verifyPartHead", "verifyStagedArchive",
                  "verifyFinalPreview", "quality.test_design_mapping.stage_part", "quality.test_design_mapping.finalize",
                  "platformApi.confirmToolInvocation(pending.id)", "done.id !== pending.id", "signal.throwIfAborted()"):
        assert value in api
    for forbidden in ("model-configs", "test-design-jobs", "localStorage", "artifact_ref"):
        assert forbidden not in api
    for name in ("mappingStagingValidation.ts", "mappingFinalPreviewValidation.ts"):
        source = (domain / name).read_text()
        assert "canonicalDigest" in source
        for forbidden in ("shared/api", "platformApi", "localStorage", "fetch("):
            assert forbidden not in source
    for name in ("useMappingStaging.ts", "useMappingPartEditor.ts", "useMappingFinalization.ts"):
        source = (domain / name).read_text()
        for value in ("gcTime: 0", "retry: false", "refetchOnWindowFocus: 'always'", "onFailure()"):
            assert value in source
    part = (domain / "useMappingPartEditor.ts").read_text()
    final = (domain / "useMappingFinalization.ts").read_text()
    for source in (part, final):
        for value in ("workspace.actorId", "query.dataUpdatedAt", "submitted.current", "setConsent('')", "write.isIdle"):
            assert value in source
    assert "partDecisionsValid(view.part, values)" in part
    assert "expected_previous_part_revision_id: view.head.head?.part_revision_id ?? null" in part
    assert "part_set_digest: view.part_set.part_set_digest" in final and "savedEpoch" in final
    for name in ("MappingStagingPanel.tsx", "MappingPartEditor.tsx", "MappingPartAssertions.tsx", "MappingFinalizationPanel.tsx"):
        source = (PORTAL_SRC / "routes/project/sections/knowledge/scope" / name).read_text()
        for forbidden in ("mappingStagingApi", "platformApi", "dangerouslySetInnerHTML", "localStorage", "useMutation", "fetch("):
            assert forbidden not in source


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
        "evidenceApi.",
        "linkCandidateApi.",
        "semanticEvaluationApi.",
        "semanticReviewApi.",
        "semanticMembershipApi.",
        "contextPackApi.",
        "dangerouslySetInnerHTML",
    ]

    for source_path in _source_files():
        if _layer_for(source_path) != "routes":
            continue
        specifiers = set(_import_specifiers(source_path))
        leaked_imports = specifiers & forbidden_imports
        assert not leaked_imports, f"{source_path.relative_to(ROOT)} imports raw domain API {leaked_imports}"
        source = source_path.read_text()
        assert not DIRECT_FETCH_RE.search(source), f"{source_path.relative_to(ROOT)} calls fetch directly"
        for fragment in forbidden_fragments:
            assert fragment not in source, f"{source_path.relative_to(ROOT)} bypasses domain command surface: {fragment}"


def test_direct_fetch_guard_distinguishes_query_refetch_from_network_calls() -> None:
    for source in ("fetch(url)", "fetch (url)", "window.fetch(url)", "globalThis.fetch(url)"):
        assert DIRECT_FETCH_RE.search(source)
    for source in ("query.refetch()", "refetch()", "usePrefetch(query)"):
        assert not DIRECT_FETCH_RE.search(source)


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


def test_conversation_replay_refreshes_are_coalesced_without_cancelling_snapshots() -> None:
    event_hook = (PORTAL_SRC / "domains/agent/useConversationEvents.ts").read_text()
    refresh = (PORTAL_SRC / "domains/agent/conversationQueryRefresh.ts").read_text()
    assert "createConversationQueryRefresh(queryClient," in event_hook
    assert "key[0] === 'conversation' || (!existingOnly && canReadWorkspace?.() !== false)" in event_hook
    assert "refreshes.schedule(['conversation', conversationId])" in event_hook
    assert "refreshes.schedule(key)" in event_hook and "refreshes.close()" in event_hook
    assert "queryClient.invalidateQueries" not in event_hook
    assert "cancelRefetch: false" in refresh and "active.has(key)" in refresh
    assert "if (unfinished.size && !closed && canRefresh(queryKey))" in refresh
    assert "findAll({ queryKey, fetchStatus: 'fetching' })" in refresh
    assert "query.promise === promise" in refresh and "unfinished.has(query)" in refresh
    assert "query.state.status !== 'error'" in refresh
    assert "if (closed || !canRefresh(queryKey)) return" in refresh
    assert "setTimeout(flush, 200)" in refresh and "pending.clear()" in refresh


def test_project_query_lifetime_is_checked_before_dispatch_and_after_transport() -> None:
    guard = (PORTAL_SRC / "routes/project/useProjectRouteData.ts").read_text()
    assert "window.location" in guard and "isCurrentProjectWorkspace(projectId," in guard
    assert "location.pathname === path || location.pathname.startsWith(`${path}/`)" in guard
    assert "!params.has('build_review_goal') && !params.has('build_review_invocation')" in guard
    assert "useProjectWorkspaceData(projectId, { ...options, canReadWorkspace })" in guard
    scope = (PORTAL_SRC / "shared/api/queryScope.ts").read_text()
    assert "signal?.throwIfAborted()" in scope and "canRead?.() === false" in scope
    context = (PORTAL_SRC / "routes/project/useProjectRouteContext.ts").read_text()
    assert "canReadWorkspace: routeData.canReadWorkspace" in context
    consumers = {
        "domains/platform/useProjectWorkspaceData.ts": 4,
        "domains/agent/conversationScopeQuery.ts": 2,
        "domains/agent/useAgentGoalExplanation.ts": 2,
        "domains/agent/useAgentRuntimeDetails.ts": 4,
    }
    for name, checks in consumers.items():
        source = (PORTAL_SRC / name).read_text()
        assert source.count("requireActiveQueryScope(") == checks, name
    reader = (PORTAL_SRC / "domains/agent/conversationScopeQuery.ts").read_text()
    assert reader.index("requireActiveQueryScope(") < reader.index("agentApi.ensureConversation(")
    assert "agentApi.ensureConversation(spaceType, spaceId, title, signal)" in reader


def test_context_invalidation_events_refresh_project_scoped_sensitive_consumers() -> None:
    event_hook = (PORTAL_SRC / "domains" / "agent" / "useConversationEvents.ts").read_text()
    assert "source.addEventListener('system_image.context.invalidated', typedHandler)" in event_hook
    assert "source.addEventListener('quality.test_design_mapping.reviewed', typedHandler)" in event_hook
    expected = {
        "useTestDesignGeneration.ts": "['generation-jobs', scope.revision.project_id, sessionId",
        "useTestDesignMapping.ts": "['test-design-mapping', m.project_id, sessionId",
        "useTestDesignReviewQueue.ts": "['test-design-review-drafts', projectId, sessionId",
        "useMappingStaging.ts": "['mapping-staging', draft.metadata.project_id, sessionId",
        "useMappingPartEditor.ts": "['mapping-part-editor', pin.project_id, workspace.actorId",
        "useMappingFinalization.ts": "['mapping-final-preview', workspace.plan.generation_pin.project_id, workspace.actorId",
        "useAutomationInput.ts": "['automation-input', draft.metadata.project_id, sessionId",
    }
    for name, prefix in expected.items():
        assert prefix in (PORTAL_SRC / "domains" / "quality-loop" / name).read_text()


def test_automation_inputs_are_read_only_fixed_and_not_execution_authority() -> None:
    domain = PORTAL_SRC / "domains/quality-loop"
    api = (domain / "automationInputApi.ts").read_text()
    validator = (domain / "automationInputValidation.ts").read_text()
    hook = (domain / "useAutomationInput.ts").read_text()
    view = (PORTAL_SRC / "routes/project/sections/knowledge/scope/AutomationInputPanel.tsx").read_text()
    invalidations = (ROOT / "apps/api/app/application/system_image/context_invalidations.py").read_text()
    assert '"automation-input"' in invalidations
    for fragment in ("cache: 'no-store'", "signal.throwIfAborted()", "query.append('case_ids', id)", "mapping.revision.artifact_hash"):
        assert fragment in api
    assert "method:" not in api and "platformApi" not in api
    for fragment in ("gcTime: 0", "staleTime: 0", "retry: false", "refetchOnWindowFocus: 'always'", "!query.isFetching && !query.isError"):
        assert fragment in hook
    for fragment in ("canonicalDigest(row.oracle)", "v.execution_authorized === false", "v.passed_count === 0", "reviewed.gap_ids.length === 0"):
        assert fragment in validator
    for forbidden in ("shared/api", "platformApi", "dangerouslySetInnerHTML", "localStorage"):
        assert forbidden not in view


def test_portal_i18n_is_chinese_first_and_settings_persisted() -> None:
    provider_source = (PORTAL_SRC / "shared" / "i18n" / "I18nProvider.tsx").read_text()
    messages_source = (PORTAL_SRC / "shared" / "i18n" / "messages.ts").read_text()
    app_providers_source = (PORTAL_SRC / "app" / "providers.tsx").read_text()
    settings_source = (PORTAL_SRC / "domains" / "platform" / "useStudioSettings.ts").read_text()

    assert "const DEFAULT_LOCALE: Locale = 'zh'" in provider_source
    assert "nasus.locale" in provider_source
    assert "document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en'" in provider_source
    assert "<I18nProvider>" in app_providers_source
    assert "setLocale(settingsQuery.data.language)" not in settings_source
    assert "language: locale" in settings_source
    assert "setLocale(language)" in settings_source
    assert "updateSettings.mutate({ language })" in settings_source
    assert "'Build quality projects with Nasus': '用 Nasus 构建质量项目'" in messages_source

    core_surfaces = [
        PORTAL_SRC / "routes" / "auth" / "WelcomeRoute.tsx",
        PORTAL_SRC / "routes" / "auth" / "LoginRoute.tsx",
        PORTAL_SRC / "routes" / "build" / "BuildHero.tsx",
        PORTAL_SRC / "routes" / "dashboard" / "DashboardContent.tsx",
        PORTAL_SRC / "routes" / "documentation" / "DocumentationContent.tsx",
        PORTAL_SRC / "app" / "shells" / "TopLevelSidebar.tsx",
        PORTAL_SRC / "app" / "shells" / "ProjectWorkspaceSidebar.tsx",
        PORTAL_SRC / "app" / "shells" / "settings" / "SettingsPopover.tsx",
        PORTAL_SRC / "routes" / "project-overview" / "ProjectWorkspaceView.tsx",
    ]
    for source_path in core_surfaces:
        source = source_path.read_text()
        if source_path.name == "ProjectWorkspaceView.tsx":
            assert "SourceBindingPanel" in source and "AgentGoalPanel" in source
        else:
            assert "useI18n" in source, source_path.relative_to(ROOT)

    assert not any("tr(en" in path.read_text() for path in _source_files())
