# Formal Browser Runner v1

This bounded adapter is not RunPlan integration, execution authorization, target
acceptance, or a RealWorld acceptance claim. The public server has **no private
dispatcher** and will not launch Chromium for this protocol. Existing `/v1/jobs`
browser and HTTP protocols are unchanged.

## Public command (fixed v1 field names)

`POST /v1/browser/jobs` uses the existing service bearer token, capacity limit,
request correlation, disconnect signal, and response envelope. JSON parsing is
strict, including duplicate-key rejection. No metadata or unknown fields are
accepted. A structurally valid command without a dispatcher returns HTTP 200,
`status: "error"`, `failure_summary: "private_dispatch_required"`, no receipt,
and empty `artifacts` and `timeline`. Malformed JSON returns HTTP 400 with a
constant message. Validation errors return HTTP 200 with no receipt.

Required command fields:

```json
{
  "job_id": "job-1",
  "project_id": "project-1",
  "us_id": "case-1",
  "execution_kind": "browser",
  "receipt_protocol": "nasus.runner-browser-execution.v1",
  "base_url": "https://registered.example",
  "timeout_ms": 30000,
  "reviewed_pins": {
    "plan_digest": "sha256:<64 lowercase hex>",
    "script_digest": "sha256:<64 lowercase hex>",
    "case_digest": "sha256:<64 lowercase hex>",
    "environment_digest": "sha256:<64 lowercase hex>",
    "browser_digest": "sha256:<64 lowercase hex>"
  },
  "steps": [
    {"action": "goto", "url": "/login", "source_step_indices": [0]},
    {"action": "fill", "selector": "input[name=\"email\"]", "value": "", "source_step_indices": [1]},
    {"action": "click", "selector": "button[type=\"submit\"]", "source_step_indices": [2]},
    {"action": "assert_url", "value": "/", "source_step_indices": [3]}
  ]
}
```

`base_url` is a credential-free HTTP(S) origin without query/fragment. IDs are
1..128 ASCII letters/digits/`_.:-`, starting with a letter or digit. There are
1..100 steps, with 1..512 distinct original indices in 0..511 per step. The job
deadline is 1000..120000 ms. Optional step `timeout_ms` is 100..30000 ms; optional
`phase` is `business` (default) or `verification`. All assertions fence writes on
their first observed mismatch; verification mismatches never restore permission.

Supported operands are exactly:

| Action | Required operands | Semantics |
| --- | --- | --- |
| `goto` | `url` | Target-relative path, no authority/backslash/fragment |
| `fill` | `selector`, `value` | Empty value permitted for private credential injection |
| `click` | `selector` | One explicit action, no runner retry |
| `press` | `selector`, `key` | Enter, Tab, Escape, Space, ArrowUp, ArrowDown only |
| `assert_text` | `selector`, `value` | Nonempty literal substring in textContent |
| `assert_visible` | `selector` | Actual visibility |
| `assert_url` | `value` | Exact resolved target-relative URL, not substring |
| `wait_for` | `selector` | Visible state only |

Every step also requires `action` and `source_step_indices`. There is no legacy
`goto.path` or `assert_text.text` alias, JS, shell, regex, raw HTTP action, storage
state, headers, caller origin allowlist, or public credential reference.

Selectors are restricted to `#stable-id`, optional input/button/textarea/select
tag plus one exact `name`/`data-testid`/`data-test` attribute, exact input/textarea
`placeholder`, and enumerated input/button `type`. Values cannot contain CSS
escapes or selector composition. Examples from the fixed Vue source are
`input[name="email"]`, `textarea[name="body"]`,
`input[placeholder="Enter tags"]`, and `button[type="submit"]`. Every selector
must also match independent dispatcher evidence for its exact step, and resolve
to exactly one node. No fallback to first/nth, tags, class lists, or inferred text.

## Private dispatcher port

`executeBrowserJob(command, {wireBody?, signal?, privateDispatcher, launchBrowser?})`
calls `privateDispatcher({command, requestHash, signal})` before browser launch.
`command` is a frozen strict-wire snapshot. If wire bytes are supplied, their
decoded object must equal the command; the request hash covers the exact bytes.
`launchBrowser` is a worker/test seam, not a public option. The dispatcher must
verify original reviewed plan/script/case/locator evidence, registered environment
and current browser/build pins, actor authorization, consent, lease/fencing and
single-attempt ownership. Merely echoing command pins is **not** authorization.

The trusted dispatcher returns the following JS object, not public JSON:

```js
{
  schema: 'nasus.browser-dispatch.v1',
  request_hash: requestHash,
  reviewed_pins: {plan_digest, script_digest, case_digest, environment_digest, browser_digest},
  environment: {base_url, allowed_origins: ['https://registered.example']},
  step_permissions: [
    // Exactly one entry per command step, in order. selector/url only when relevant.
    {step_index: 0, read_only: true, url: 'https://registered.example/login',
      requests: [{method: 'GET', url: 'https://registered.example/login'}]},
    {step_index: 1, read_only: false, selector: 'input[name="email"]', requests: []},
    {step_index: 2, read_only: false, selector: 'button[type="submit"]',
      requests: [{method: 'POST', url: 'https://registered.example/api/users/login'}]},
    {step_index: 3, read_only: true, url: 'https://registered.example/', requests: []}
  ],
  credential_bindings: [{step_index: 1, credential_ref: 'private-infrastructure-reference'}],
  resolve_credential: async ({credential_ref, signal}) => 'resolved-private-value',
  evidence: {
    record: async (event, {signal}) => true,
    seal: async (receipt, {signal}) => true
  }
}
```

The two credential fields are optional. Credential bindings can only replace an
empty `fill.value`, and only through the private port. The sample strings are
illustrative; no credentials are read from the environment or public command.
Private evidence ports must acknowledge actual private storage with literal
`true`; missing ports or failed acknowledgements fail closed. `record` receives
start, network metadata, step observations, and a final screenshot Buffer. No
trace/script/body/console/error text or evidence references are publicly emitted.
`seal` receives the final candidate receipt with `private_evidence_stored: false`;
only its acknowledgement makes the public value true. Cancellation can leave it
false, and must never be promoted by a consumer to complete private evidence.

Network permissions are bounded, exact method+absolute URL pairs **per active
step**, including subresources and any secondary registered API origin. There
are no wildcard hosts/paths or caller routing overrides. Verification and
assertions require `read_only: true` and only GET/HEAD permissions. Fill/click/
press cannot claim read-only status. After a mismatch or unknown write, only
steps with `phase: "verification"` AND private `read_only: true` may execute.
GET/HEAD is not proof of business read-only semantics: that classification must
come from the independent evidence review. Requests already dispatched before a
fence cannot be rolled back. The adapter never resets the write fence.

Each execution creates and closes a fresh nonpersistent BrowserContext. Routing
is installed before page creation. Every routed request is checked, fetched with
`maxRedirects: 0, maxRetries: 0`, and fulfilled without automatic redirects.
All HTTP redirects/Refresh headers are rejected, including same-origin redirects.
Service workers, WebSockets, frames, popups, downloads and explicit worker use
are unsupported. Added CSP restricts frame/object/form/connect surfaces without
removing the application's existing CSP. There is no external-browser attachment
or reuse of cookies/storage. This is an adapter policy, not an OS/network sandbox
for a hostile compromised browser; deployment egress isolation remains required.
Cleanup has a bounded one-second grace period. Failure to close the browser is
an error, never a pass; worker supervision must reap an unresponsive child.

Writes whose transport fails, receives a 5xx, or whose action is interrupted have
unknown outcomes. They are never retried by this adapter. A private dispatcher
must additionally prevent cross-request replay: this slice has no durable job
ledger, idempotency claim, or retry authorization. Read-only verification cannot
turn an unknown write or prior assertion failure into a successful job.

## Receipt (fixed v1 fields)

The response uses the existing Runner envelope. `execution_receipt.schema` is
`nasus.runner-browser-execution.v1`. Existing receipt fields are retained:
`runner_job_id`, `project_id`, `us_id`, `request_hash`, `execution_status`,
`step_count`, `steps`, `assertion_count`, `observed_assertion_count`,
`passed_assertion_count`, `failed_assertion_count`, `target_build_verified: false`,
`business_coverage_verified: false`. Each receipt step contains only
`step_index`, `action`, `kind`, and `status`; skipped steps remain `not_executed`,
unknown/interrupted actions are `interrupted`. Additional fields:

- `reviewed_pins`: the five public command digests, not an acceptance assertion.
- `first_failed_assertion_index`: first observed mismatch index or null.
- `write_fence`: open, assertion_failed, unknown_write, policy_rejected, interrupted.
- `unknown_write_step_indices`: sorted distinct zero-based action indices.
- `private_evidence_stored`: true only after acknowledged private sealing.

If an action was provisionally passed before a late unknown-write observation,
the final receipt downgrades it to `interrupted` and the job to `error` (or keeps
`timed_out`). Original failed assertions and their counts remain intact, even
when subsequent evidence recording or verification is interrupted. A passed
action is only an action/transport observation, never a successful business
submit or oracle. Receipt serialization reconciles unknown writes after closing
the context and before private sealing.

No raw values, credential references, resolved secrets, locators, URLs, exception
messages, screenshot bytes, traces, or script artifacts occur in public outputs.
Public IDs/digests must already be nonsecret infrastructure identities. Outcome
status is passed/failed/error/timed_out. `failure_summary` is a fixed machine code,
not a browser exception. Missing dispatcher/invalid input yields no receipt.

## Remaining integration

Parent infrastructure owns durable authorization, registered environment lookup,
pin/evidence verification, private credential/evidence adapters, leases, replay
prevention, RunPlan receipts and acceptance. Source intake alone grants none of
those capabilities. Tests of this slice use browser doubles, not a running UI or
retained acceptance data.

### Pinned Vue UI gaps (not v1 capabilities)

Read-only source inspection at Vue commit
`db749e3bb1a45755e0a3f4065abaf7346f004f36` identifies the following minimum gaps.
Current v1 cannot completely verify the article detail view, error presentation,
or current form values; source inspection and Runner tests are not target UI
acceptance evidence.

- Detail title/body: `src/views/Article.vue:5` renders an unannotated `h1`;
  line 12 renders Markdown in an unannotated `div`. Neither has a v1 locator.
  Future source-reviewed, read-only locator candidates are
  `div.article-page > div.banner > div.container > h1` and
  `div.article-page > div.container.page > div.row.article-content > div.col-xs-12 > div`.
  Do not substitute the whole article-content container: its tag text can falsely
  satisfy a body oracle. Rendered Markdown text is not the raw source body.
- Error presentation: `src/components/ListErrors.vue:2` renders
  `ul.error-messages`, mounted by `src/views/ArticleEdit.vue:6`. A future scoped
  candidate is
  `div.editor-page > div.container.page > div.row > div.col-md-10.offset-md-1.col-xs-12 > ul.error-messages`.
  Root text matching cannot associate a field with its message across dynamic
  rows. The root also exists when empty. Field-message association and zero-error
  checks require separately reviewed read-only assertions, not positional fallback.
- Input readback: the editor's title/description/body `name` locators already
  support filling, but v1 has no current-input-value assertion. `textContent`
  cannot verify `v-model` values, correct prefill, or retained input after failure.
  Description is not rendered in the article detail template either.
- Oracle strength: substring/visibility/URL checks cannot replace required exact
  values, empty collections, HTTP 401/403/404 observations, or persisted-state
  unchanged checks. An error message alone does not prove a rejected write left
  the original resource unchanged. Keep these gaps explicit in the original roster.

The locator strings above are review candidates, not additions to the v1
allowlist. Any future extension must bind exact source commit/blob, template
node, page scope, original step and permitted read-only action through reviewed
evidence; require a unique runtime match and fail closed on source drift. Do not
enable arbitrary CSS, nth/first fallback, or automatic locator repair. Version
the capability explicitly and update Python/Runner validation together after
review. Do not weaken or drop original assertions, or modify the target source
to manufacture locators or make acceptance pass. This documentation adds no
execution authorization or v1 capability.
