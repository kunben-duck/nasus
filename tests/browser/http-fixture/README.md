# Fixture Component Browser Contract

This surface mounts the production `HttpFixtureOperationPanel`, real React Query,
StrictMode, i18n and existing Portal CSS. It does not replace production-route E2E.
Python production-domain compilers and explicit inspector doubles construct the
wire specimens. No PostgreSQL, Temporal, Docker, provider or target is contacted.
There is no API proxy; unconfigured API requests fail, and browser egress outside
the owned loopback origin is blocked and asserted empty.

From the repository root, start a separate, unused test port:

```sh
apps/portal/node_modules/.bin/vite --config tests/browser/http-fixture/vite.config.mjs --port 4197
```

In another terminal, run the existing Playwright engine:

```sh
node tests/browser/http-fixture/verify.cjs
```

Do not reuse or restart the development services. Stop only the Vite process you
started when the check ends. A different unused port can be supplied through
`NASUS_BROWSER_CONTRACT_ORIGIN=http://127.0.0.1:PORT` and Vite's `--port PORT`.
No additional npm dependencies or browsers are installed by these commands.

The verifier checks separate grant/execution/cancellation consent, full original
build-member reads, changed-field invalidation, lost invoke/confirm ACK recovery,
double-click protection, refresh without writes, binding-before-observation,
completed-but-failed observations, same-attempt cleanup, unknown outcomes and
revocation/corruption hiding. Light/English desktop and dark/light Chinese narrow
viewports are covered. Artifacts go to `output/playwright/`; failure filenames
have a unique run tag (`NASUS_BROWSER_CONTRACT_RUN` may set it explicitly).

The isolated component surface does not prove the full production route, real
RBAC/ACL enforcement, database transactions, RPC lifecycle, target stop/cleanup,
business coverage, release readiness, accessibility or capacity/performance.
