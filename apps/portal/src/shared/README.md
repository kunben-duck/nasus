# Shared Portal Infrastructure

- `api`: HTTP/SSE clients and request helpers.
- `event-reducer`: product-neutral reducer utilities shared by domain-owned event reducers.
- `status`: product-neutral UI/runtime status contracts shared by domain hooks and presentation components.
- `tokens`: AI Studio-aligned visual tokens.
- `ui`: reusable primitive components such as composer, chips, cards, avatar
  presenters, and icon buttons.

Shared code should stay product-neutral by default. Product-specific state and
event parsing belong under `domains/*`; shared UI must define local view types
instead of importing domain contracts.

## Shared Rules

- `shared/api` owns request helpers and transport defaults.
- `shared/api` is storage-agnostic. It may attach auth headers through an
  injected token provider, but it must not read or write browser storage or own
  platform session keys.
- `shared/event-reducer` owns product-neutral cache reducer utilities only.
  Conversation/SSE event normalization belongs in `domains/agent`.
- `shared/status` owns type-only or pure status contracts; it must not import React components.
- `shared/ui` owns reusable UI primitives and cross-route components.
- `shared/tokens` owns theme and visual token helpers. It may define primitive
  token types such as `ThemePreference`, but it must not import `domains/*`
  settings or product contracts.
- Shared avatar/account presenters define local view types and must not import
  platform `UserProfile`; platform hooks adapt their user objects before
  rendering shared presenters.

Shared modules should not know about a concrete route. If a shared component needs product-specific orchestration, move that orchestration into a route model or domain hook and pass plain props.

Shared UI must not import `domains/*`. If a presenter needs user or project
fields, define a minimal local view type such as `UserAvatarView` or
`ProjectGalleryItem` and let the platform/domain object satisfy it
structurally.

Shared UI must remain side-effect-light: no `platformApi`, auth hooks, `apiAuthToken`, or raw `fetch` calls. Use domain hooks or app shell containers for account, avatar, settings, and other platform orchestration.

Platform session token persistence belongs in
`domains/platform/authTokenStorage.ts`; do not add `localStorage` access to
shared transport or shared UI.

Settings popovers, model-provider forms, provider status panels, and account
status panels are shell-owned platform chrome, not shared primitives. Keep them
under `app/shells/settings` so shared UI remains reusable across product
spaces while platform side effects stay in `domains/platform` hooks.

Shared composer primitives must not import product catalogs such as
`domains/platform/build-skills`. Build routes or domain hooks should select and
compose the product-specific skills, then pass plain view-model props into
shared UI.
