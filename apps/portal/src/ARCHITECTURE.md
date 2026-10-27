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
- Route query lifetimes must be checked at dispatch, not only through React
  Query's render-time `enabled` flag. Browser history may change before old
  observers unmount. The route layer supplies an opaque `canReadWorkspace`
  callback; domain hooks check it before transport and before returning private
  data, and pass the observer's abort signal to transport. Domains must not
  import router state or encode concrete URL paths themselves.
- Exact saved-build review is read-only discovery, not conversation ensure or
  whole-workspace refresh. Its SSE may update the original conversation, but
  must not invalidate unrelated domain queries. Pending and follow-up refreshes
  recheck the current lifetime, even when the first read started on the previous
  page. Preserve immediate token reduction and the existing single-flight queue.
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
- Fixed test-design context previews, history and validation belong to
  `domains/system-image/contextPackApi.ts` and `useContextPacks.ts`. Knowledge
  route panels render these contracts and reuse the authorized evidence reader;
  they must not call HTTP or ToolInvocation directly. Context archives are
  historical investigation drafts, never implicit generation authorization.
- Reviewed test-design scopes belong to `domains/quality-loop`: fixed context
  pins, complete AC/rule denominators, draft validation, private history and
  confirmed ToolInvocation writes. The knowledge route's `scope` components
  render structured assessments and examples, not raw JSON command editors.
  Explicit gaps remain blockers; approval is never generation permission.
  Source-read or response-pin failures hide private content; edits and fresh
  reads invalidate consent. Do not restore consent from browser storage.
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

## Source Analysis Inspector

- `domains/system-image/codeAnalysisApi.ts` and `useCodeAnalysis.ts` own the
  authenticated revision/report reads, pagination keys, cancellation and
  no-persistent-cache policy. They do not render UI or perform materialization.
- The knowledge route composes source and report selectors explicitly. Opening
  the inspector, changing project, or reloading it never selects a historical
  report as the current approved image. A failed read hides previous report
  content and requires an explicit reload before another selection.
- `analysisObservationView.ts` adapts report DTOs for the result list. The list
  renders text, not repository-provided HTML. Source locations and hashes are
  observations pinned to the selected revision, not runtime acceptance or
  approved business oracles.
- The inspector shares the evidence dialog's theme tokens, keyboard/focus
  behavior and scroll-without-scrollbar styling. Capture/materialization writes
  continue to use the existing governed ToolInvocation surface.

## Frozen Image Inspection

- `domains/system-image/imageRevisionApi.ts` and `useImageRevisions.ts` own
  candidate history, paginated archive reads and revision-scoped evidence
  expansion. UI components consume typed view models, not mutable workspace
  aliases. Object and membership pages must have the same artifact hash, count
  and ordered IDs before evidence controls become available.
- `routes/project/sections/knowledge/revisions` contains the read-only dialog,
  revision selector, section pages, provenance and archived excerpts. It never
  picks a revision automatically or publishes a candidate. Legacy branch and
  confidence fields are not presented as approval or semantic validation.
- Each opening/reload uses a separate query scope, `gcTime: 0`, abort signals
  and `no-store`. Fetching hides the previous page; a failed read latches the
  whole inspector closed to sensitive content until explicit reload. Project
  changes and loss of the parent image dismiss the inspector.
- Evidence is read through the image/object/evidence endpoint, which verifies
  frozen membership and all input sources before and after archive access. Do
  not replace this with the current alias-to-evidence listing API. Scrolling,
  focus restoration, text-only rendering and theme tokens reuse the existing
  knowledge inspectors.

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

## Internationalization

- Simplified Chinese (`zh-CN`) is the primary and default product language;
  English (`en`) is the secondary language available from Settings.
- User-visible static copy must be registered in `shared/i18n/messages.ts` and
  rendered through `useI18n().t`. Do not add inline language branches such as
  `tr(en, zh)` or duplicate localized JSX trees.
- User-visible dynamic labels and statuses returned by APIs must be rendered
  through `useI18n().tx`. Backend contracts should still return stable enum
  values rather than localized identifiers.
- Product names, tool IDs, model names, code, paths, JSON keys, API fields, and
  other machine-readable identifiers must not be translated.
- Language changes update the UI immediately, persist through `/v1/settings`,
  mirror to the `nasus.locale` browser cache, and set the document language to
  `zh-CN` or `en`. The browser cache is only the startup fallback; backend
  settings remain authoritative after authentication.
- Agent commands generated by buttons and skills must follow the selected
  language. The LLM gateway must apply the same language preference while
  preserving technical identifiers verbatim.
- `shared/i18n` is the controlled cross-cutting resource catalog. It may contain
  product copy, but it must not import routes, domains, application shells, or
  transport adapters.

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
npm run test:i18n
npm run lint:portal
npm run build:portal
npm run test:e2e
npm run test:smoke
```

The E2E suite owns Chinese-default, language-switch, and reload-persistence
coverage. The smoke suite explicitly selects English so its long-running
system-image assertions remain focused on the canonical business path.

`tests/test_portal_boundaries.py` is the frontend architectural tripwire.
`tests/test_ddd_boundaries.py` remains the backend DDD tripwire and keeps a few
cross-stack compatibility assertions. Update the matching test whenever a
boundary is intentionally changed.
