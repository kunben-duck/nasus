# Route Pages

Each route package should expose a real page module for one user-facing space.

Route pages may compose:

- `app/shells` for persistent layout.
- `domains/*` hooks and view models.
- `shared/ui` primitives and tokens.
- `domains/agent` for conversation and SSE state.

Route pages must not call `dangerouslySetInnerHTML` for application UI. Markdown rendering must be isolated in a controlled renderer.

`app/routing/routeElements.tsx` is the only place that should assemble route
elements from route components and auth guards. It must stay declarative: no
hooks, no API calls, no route-specific branching, and no legacy singleton studio
components.

## Route Responsibilities

- Route components compose shells and route models.
- Route model hooks compose domain hooks, navigation, and query invalidation.
- Route-local `components/` own UI that is not reusable outside that space.
- Route files should not directly import legacy singleton studio files.
- Route files should not own raw API clients when a domain hook or command
  helper exists. For top-level build/dashboard/documentation content, consume
  `domains/platform/useTopLevelContent.ts` instead of importing `platformApi`.
- For project workspace aggregate reads, consume
  `domains/platform/useProjectWorkspaceData.ts`; routes must not import
  `qualityLoopApi` or `systemImageApi` directly.
- Project overview quality asset presenters consume route-local view models
  from `projectWorkspaceSelectors.ts`. Keep `ProjectWorkspaceData`,
  `RunSummary`, `USItem`, and `AssetLane` out of `components/quality-asset`.
- Project workspace section components consume route-local view models from
  `routes/project/ProjectSectionViewModels.ts`. Keep direct domain DTO imports
  in route context/data/model files, not in presentational section components.
- Project workspace route files must not call `platformApi.invokeTool`,
  `platformApi.confirmToolInvocation`, `agentApi.postMessage`, or
  `agentApi.resumeAgentGoal` directly. Use domain command executors and keep
  route code limited to UI locking, params, navigation, and query invalidation.
- Do not add route-local action executor proxy files. Project workspace action
  handlers should import command executors directly from
  `domains/platform/tool-actions` or `domains/agent/*Commands`.
- Auth route files should call `useAuthActions` for login and registration
  instead of importing `platformApi` directly. Route guards should use
  `domains/platform/useAuthSession.ts` for token/session checks and must not
  import token helpers from `shared/api/client` or
  `domains/platform/authTokenStorage.ts` directly.

Use route subfolders for complex spaces such as project overview or version workspace. Keep the top-level route file boring.
