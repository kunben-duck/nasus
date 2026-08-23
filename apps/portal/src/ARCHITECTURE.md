# Portal Architecture

Nasus Portal follows a feature-sliced, agent-first frontend architecture. The goal is to keep product flows easy to extend without returning to a single studio component.

## Layer Ownership

- `app`: application bootstrap, providers, router creation, persistent shell containers, and layout chrome.
- `routes`: user-facing pages and route-local view models. Route modules compose shells, domain hooks, and shared UI.
- `domains`: product boundary models and API adapters for `system-image`, `agent`, `quality-loop`, and `platform`.
- `shared`: product-neutral infrastructure, status/type contracts, and reusable UI primitives.
- `styles`: AI Studio-aligned visual tokens and feature-scoped CSS files.

## Dependency Direction

Allowed direction:

```text
app -> routes -> domains -> shared/api + shared/status + shared/tokens
routes -> shared/ui
routes -> app/shells
app/shells/settings -> domains/platform/settings + domains/platform/types + shared/ui
domains/platform/settings -> domains/platform/types + shared/status + shared/tokens
```

Rules:

- `app/router.tsx` only creates the browser router from `app/routing/routeConfig.tsx`.
- `main.tsx`, `App.tsx`, `app/providers.tsx`, and `app/router.tsx` are
  bootstrap-only. They may wire React, providers, CSS, and the router, but must
  not import route business models, domain hooks, API clients, or legacy studio
  components.
- `app/routing/routeConfig.tsx` owns URL paths and redirects only. It imports
  route element constants from `app/routing/routeElements.tsx` instead of
  importing page components directly.
- `app/routing/routeElements.tsx` owns route element assembly only. It may
  compose auth guards and route components, but must not call hooks, APIs, or
  own business branching.
- Route pages must render real route modules, never legacy singleton studio components.
- Shell containers may compose domain hooks for settings/account chrome, but
  shell view files own layout chrome only and must not import `domains/*`.
- Product chrome such as the top-level Nasus sidebar belongs under
  `app/shells`, not `shared/ui`. Shell view components receive navigation
  callbacks through props; shell containers may use router hooks such as
  `useNavigate`.
- Domains own API payload contracts, command builders, settings hooks, and conversation controllers.
- Agent domain owns conversation SSE event reduction and message/tool/goal cache
  patching. Shared reducer code must stay product-neutral.
- Auth routes are still route modules: login, registration, logout, avatar, and session persistence side effects belong in `domains/platform` hooks.
- Auth route guards may redirect based on session state, but token lookup,
  token persistence, and expired-session cleanup must be exposed through
  `domains/platform/useAuthSession.ts`; route files must not import shared API
  token helpers directly.
- Browser token persistence belongs in `domains/platform/authTokenStorage.ts`.
  `shared/api/client.ts` may expose a configurable token provider and attach
  auth headers, but it must not read or write `localStorage` or own the concrete
  `nasus_api_token` key.
- Top-level build/dashboard/documentation content queries belong in
  `domains/platform/useTopLevelContent.ts`; route models consume those hooks and
  should not call `platformApi` directly for these pages.
- Project workspace aggregate reads belong in
  `domains/platform/useProjectWorkspaceData.ts`; route modules may pass
  URL-derived IDs into this hook but must not call `qualityLoopApi` or
  `systemImageApi` directly.
- Project overview quality asset presenters consume route-local view models
  from `projectWorkspaceSelectors.ts`; quality-loop aggregate DTOs should be
  projected before reaching `components/quality-asset`.
- Project workspace section components consume route-local view models from
  `ProjectSectionViewModels.ts`. Domain DTO imports belong in route context,
  route data hooks, or selector/view-model files, not presentational section
  components under `routes/project/sections`.
- Build skill catalog and prompt composition belong to the build route/platform
  boundary. Shared composer components must receive selected skill view models
  through props and must not import `domains/platform/build-skills`.
- Domains may import shared transport/status/token helpers, but must not import `shared/ui` components or UI-owned types.
- Shared UI must stay product-neutral and must not import `domains/*`.
  Components that need product data should define small local view types and
  receive callbacks or data from routes, shells, or domain hooks.
- Shared UI must not import `react-router-dom`, own concrete route paths, or
  render product chrome such as the Nasus sidebar. If a reusable primitive
  needs navigation, inject an `onClick` / `onNavigate` callback from a route or
  shell container.
- Platform settings domain code under `domains/platform/settings` owns model
  profile helpers, configuration payload builders, and settings draft hooks
  only. It must not contain React panel/popover components.
- Global settings popovers, provider/model configuration forms, account status
  panels, and choice menus live under `app/shells/settings`, because they are
  persistent application chrome. They may consume platform contracts and
  settings hooks through shell containers, but product side effects still belong
  to `domains/platform` hooks.
- Shared composer primitives may render injected skills, but must not own
  product catalogs, prompt builders, or route-specific skill selection.
- Product-neutral shared infrastructure must not import `domains/*`; move
  product event parsing or cache patching into the owning domain.
- `shared/tokens` must remain product-neutral. It may expose primitive visual
  token types such as `ThemePreference`, but it must not import platform
  settings or other `domains/*` contracts.
- Product writes must be triggered through conversation or tool invocation paths, not ad-hoc route-local API calls.
- Project workspace write orchestration belongs in
  `domains/platform/tool-actions/projectActionExecutor.ts`,
  `domains/platform/toolInvocationCommands.ts`, or the owning Agent command
  module. Route hooks may lock UI and call domain-provided invalidation helpers,
  but project workspace cache refresh policy belongs in
  `domains/platform/projectWorkspaceInvalidation.ts`.
- Tool invocation confirmation is a platform domain mutation hook. Route code
  must call `domains/platform/useToolInvocationConfirmation.ts` instead of
  owning `useMutation` or calling `platformApi.confirmToolInvocation`.
- Route-local project invalidation helpers such as `projectRouteInvalidation.ts`
  are not allowed; keep server-state refresh keys near the platform BFF/read
  model boundary.
- Route modules must not call `platformApi.invokeTool`,
  `platformApi.confirmToolInvocation`, or Agent write APIs directly.
- Route packages must not add thin proxy files that re-export command
  executors. Import domain commands directly from `domains/*` so the command
  surface has one canonical owner.
- `tests/test_portal_boundaries.py` scans TS/TSX import specifiers as the
  dedicated portal architecture gate: `shared` must not import `app`,
  `routes`, or `domains`; `domains` must not import `app`, `routes`, or
  `shared/ui`; shell view files must not import domain code; route modules must
  not bypass domain command surfaces with raw API calls.

## Route Module Pattern

Each top-level route should use this shape:

```text
routes/<space>/
  <Space>Route.tsx          # shell composition only
  <Space>Content.tsx        # visual content when needed
  use<Space>RouteModel.ts   # route view model composition
  components/               # route-local UI
```

Route files should stay thin. Data fetching, mutations, and event handling belong in route model hooks or domain hooks.

## Domain Pattern

Each domain should expose:

```text
domains/<domain>/
  api.ts                    # HTTP adapter only
  types.ts                  # compatibility barrel
  types/*                   # focused domain types
  use*.ts                   # domain-specific controller hooks
```

`types.ts` files are compatibility barrels. New types should go into focused files under `types/`.

## Agent-First Rule

All user-visible write actions must map back to the same command surface used by chat:

- Chat input uses conversation and agent goal APIs.
- UI buttons use tool action command builders or domain use cases.
- Project workspace UI actions call domain command executors; route files must
  not construct `ToolInvocation` payloads or resume Agent goals through raw API
  clients.
- Build prompt post-processing, including project ID extraction from tool
  results and dashboard read-back after project creation, belongs in
  `domains/platform/buildProjectResolution.ts`.
- Tool invocation IDs must remain traceable through the UI.
- High-risk actions must keep confirmation or approval gates visible.

Do not add a button that performs a write path unavailable to the agent.

## UI Component Rules

- Avoid `dangerouslySetInnerHTML` for app UI.
- Do not build UI with string templates.
- Keep route shell components thin; split repeated cards, panels, and action rows into subcomponents.
- Shared UI must not call `platformApi`, auth hooks, `apiAuthToken`, or raw `fetch`; inject data and callbacks from domain hooks or shell containers.
- Shared transport must stay storage-agnostic. Keep login/session token
  persistence in the platform domain and inject the token reader into
  `shared/api/client.ts`.
- Keep CSS in the existing style files and preserve AI Studio visual fidelity.
- Component files should export components only when Fast Refresh rules require it; helpers belong in sibling utility files.

## Verification Gates

Before merging frontend architecture changes, run:

```bash
./.venv/bin/python -m pytest tests/test_ddd_boundaries.py -q
npm run test:portal-boundaries
npm run lint:portal
npm run build:portal
npm run test:e2e
npm run test:smoke
```

`tests/test_portal_boundaries.py` is the frontend architectural tripwire.
`tests/test_ddd_boundaries.py` remains the backend DDD tripwire and keeps a few
cross-stack compatibility assertions. Update the matching test whenever a
boundary is intentionally changed.
