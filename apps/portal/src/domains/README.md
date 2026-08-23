# Portal Domains

Frontend domain packages mirror the product boundaries:

- `system-image`: sources, ingestion, graph/object views, retrieval state.
- `agent`: conversation, goal, step, memory, and swarm view models.
- `quality-loop`: tasks, quality assets, runs, evidence, governance, and release readiness.
- `platform`: settings, auth, tool catalog, tool invocation, audit, and notifications.

Domain packages adapt API payloads into UI-ready view models. They should not own layout chrome.

## Domain Rules

- `api.ts` talks to HTTP endpoints and returns typed payloads.
- `types.ts` is a compatibility barrel; focused types live under `types/`.
- Domain hooks may own server-state orchestration for their domain.
- Domains must not import route components or app shells.
- Agent owns conversation SSE event reduction, message payload parsing, AgentGoal
  updates, and tool-invocation event patching for conversation caches.
- Agent domain hooks own AgentGoal explanation polling and other Agent read
  models; route files should not call `agentApi` for these reads directly.
- Platform domain hooks own auth, account, avatar, settings, and model configuration side effects, including token lookup, token persistence, and expired-session cleanup for route guards.
- Platform settings domain code owns settings contracts, model profile helpers,
  configuration payload builders, and draft hooks under
  `domains/platform/settings`; React popovers, provider/model panels, account
  status panels, and settings choice menus belong to `app/shells/settings`.
- Platform tool actions are the canonical bridge from UI actions to tool invocation commands.
- Platform tool action executors own project workspace UI-to-tool orchestration,
  including conversation creation, tool invocation payload construction, and
  source-ingestion command chaining.
- Platform tool invocation commands own confirmation/approval command calls;
  routes may only call those domain commands from UI locks and callbacks.
- Platform owns top-level build/dashboard/documentation server-state hooks and
  starter content fallbacks through `useTopLevelContent.ts` and
  `starterContent.ts`.
- Platform owns project workspace aggregate read hooks through
  `useProjectWorkspaceData.ts` when a route needs to combine quality-loop and
  system-image read models.
- Platform owns build-project resolution helpers that parse tool invocation
  results and reconcile newly created projects from dashboard read models.

If a new feature crosses domains, expose a use case or command builder instead of importing another domain repository-style module directly.
