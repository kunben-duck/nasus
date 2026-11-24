# 模块设计：version-delivery

## 1. 模块目标

`version-delivery` 负责把项目正式基线分叉成版本工作分支，并围绕版本组织 US、参与者和风险。

## 2. 模块边界

负责：

- `Version Space`
- `Version Create`
- US 导入、分配和版本风险初始化

不负责：

- US 级质量资产生成细节
- 执行、审批和放行细节

## 3. 前端组成

- `VersionSpacePage`
- `VersionCreatePage`
- `USBoard`
- `OwnerAssignmentPanel`
- `VersionRiskPanel`

## 4. 后端组成

### 4.1 主要对象

- `Version`
- `USWorkItem`
- `Task`
- `Baseline overlay`

### 4.2 主要工具

- `version.create`
- `version.inputs.import`
- `version.participants.assign`
- `version.risk.initialize`
- `version.progress.get`

## 5. 开发指导

- `Version Create` 是 `Version Space` 的详情态，不应脱离父导航上下文。
- `USWorkItem` 与 `Task` 明确为 `1:N`。
- 版本创建必须同时完成：分支建立、US 导入、初始风险种子和责任人分配。

## 6. 验收标准

- 版本可从项目空间创建并落成独立版本分支。
- `Version Space` 能以 board 方式展示 US、负责人、风险和当前进展。

## M1 Image-Pinned Delivery Contract

M1 creates the existing Version entity, not a second iteration entity. It pins
knowledge only; it does not create a Git branch, import requirements, implement
changes, execute tests, or authorize release. The earlier full-workflow criteria
above are not claims of M1 completion.

`POST /v1/projects/{project_id}/versions` retains the existing `VersionSummary`
response and accepts `Idempotency-Key` (1-128 characters). The body is:

```json
{
  "name": "Release 1",
  "image_binding": {
    "publication_id": "publication-id",
    "image_revision_id": "image-id",
    "image_artifact_hash": "sha256:<64 lowercase hex characters>",
    "expected_head_id": "publication-id"
  }
}
```

`image_binding` is optional only for projects that have not opted into delivery.
The first successful bound create atomically enables delivery for the project.
Every subsequent new Version requires an explicit pin. Existing unbound Versions
remain readable and usable. The pin must match the exact current official project
publication; no implicit latest-image selection or version-working publication
is accepted. All API and chat commands use the existing `version.create` runtime.
Its result retains `object_refs: ["version:<id>"]` and adds `version_delivery`.

`GET /v1/projects/{project_id}/versions/{version_id}/delivery` returns a
`VersionDeliveryReadModel` with `Cache-Control: private, no-store`:

- `project_id`, `version_id`, `name`: strings.
- `enabled`: true only for a bound Version, not retroactively for older Versions.
- `stage`: `legacy`, `image_pinned`, `requirement_review`, or `requirements_confirmed`.
- `baseline`, `iteration_image`: null for legacy Versions; otherwise identical
  `PublishedImagePin` objects containing `publication_id`, `baseline_id`,
  `image_revision_id`, `image_artifact_hash`, `manifest_id`, `manifest_hash`,
  `sequence`, `quality_generation_authorized: false`, `release_authorized: false`.
- `code_revisions`: captured `binding_id`, `source_id`, `source_revision_id`,
  `repository`, nullable `tracked_ref`, `external_revision`, nullable `commit_sha`,
  `content_hash`, and `manifest_hash`. Non-Git captures have no invented SHA.
- `blockers`: starts with `requirement_input_required` for a bound Version;
  subsequent blockers come from current requirement review facts.
- `pending_confirmations`: `[]` in M1. No M2 confirmation is manufactured.
- `available_actions`: `["view_pinned_image"]` for bound Versions, otherwise `[]`.

The application entry point is `container.version_delivery.read(project_id,
version_id)`. There is no project-level `/delivery` endpoint in M1; pre-creation
selection uses existing published-image APIs.

Creation serializes against publication/source-policy changes and locks current
membership through commit. Version, creation receipt, immutable image binding,
project opt-in, readiness draft, completed invocation result, audit and outbox
are one transaction. Creation receipts are unique on invocation ID; mismatching
idempotency payloads return 409. Bindings and opt-in records are append-only.
Historical reads and replay verify the original image and fresh source ACLs,
without requiring it to remain the current publication. Stored repository/ref
labels never follow mutable source-binding labels. Publication review policy is
unchanged.

Delivery errors use `version_delivery_conflict` (409),
`version_delivery_forbidden` (403), `version_delivery_not_found` (404),
`version_delivery_integrity_failed` (502), `version_delivery_unavailable` (503),
or `version_delivery_invalid` (400). Request-shape validation remains 422.
An already-running idempotent request may return `version_creation_pending`
(409); retry with the same key. Tool failures expose the code in `followup_reason`.

## M2 Requirement Review and Confirmation

Requirement intake now continues through live-model review, persisted clarification,
source-backed acceptance proposals and independent human confirmation. See
[the M2 contract](requirement-review.md) for the model, authority and replay details.
It does not authorize test generation, execution or release.

- `quality.requirement.revise` uses the canonical ToolInvocationRuntime. Inputs
  include explicit project, Version and exact image/hash, title, original text
  and clarification question/answer pairs. Editing also requires the original
  US ID and the latest `expected_revision_id`.
- `query.quality.requirements` reads draft references in the selected Version.
  The no-store HTTP page is `GET /v1/projects/{project_id}/versions/{version_id}/requirements`.
  With `us_id`, it returns descending revision history; without it, latest
  revisions only. `offset` and `limit` bound paging.
- Migration `0126_requirement_revisions` adds an append-only PostgreSQL table.
  Original text, earlier revisions and clarification history remain intact.
  A correction creates a new revision; it never rewrites historical answers.
- New drafts reuse USWorkItem. US projection, revision, completed command,
  audit and outbox commit together. A stale parent loses the compare-and-swap;
  an outbox failure rolls back the business writes. One command ID cannot
  create a second requirement on retry.
- Writes require a current project QA lead/administrator. Reads, writes and
  original completed receipt replay recheck access to the pinned image sources.
  Broadcast invalidations contain identifiers, not draft text or answers.
- Delivery-enabled projects cannot implicitly choose a Version. Old shortcut
  import, generation and execution commands cannot mutate image-bound Versions.
  Unbound historical Versions remain readable. An explicit matching Version can
  pass the legacy entry guard, but project-latest generation helpers still refuse
  to infer a Version in opted-in projects. This is not an alternative approval
  mechanism or a claim that historical assets satisfy the delivery gate.

The Version page supports creation, correction, clarification answers and
revision history in light/dark and narrow layouts. Lost responses retain the
original scoped idempotency key and payload in session storage; refreshing can
retry that command without guessing whether it committed. Access errors hide
the last fetched requirement content. Draft intake and the current review/approval
state are displayed separately; saving text never constitutes approval.

Migration `0127_requirement_reviews` adds append-only review events. Confirmation
adopts the source-backed candidate as the Version's working image, without moving
its initial baseline or the project's publication head. The derived working pin
has a `review_event_id` and nullable `publication_id`; it is not a new publication.
`requirements_confirmed` still exposes `formal_test_design_required`. M3 formal
Django HTTP execution, M4 defect/fix/regression and M5 Version gate/promotion are
not delivered by M2. `verify:realworld-loop --phase full` must not report success
until that full evidence chain exists.

## M3 Integration Progress (2026-11-16)

M3 is **in progress, not accepted**. The following foundation is implemented:

- A confirmed requirement exposes `test_design_context_request` from the review
  read model. The Version page uses this exact request under "Test design and
  execution"; it does not infer the project latest image. In a requirement-scoped
  conversation, `开始测试设计` prepares a separate confirmation, and
  `确认准备测试上下文` saves the original context command. Neither step invokes a
  model, approves cases, or executes tests. Unrelated questions remain ordinary
  conversation turns.
- Context policy `nasus.test-design-context.v6` pins `iteration.version_id`,
  `requirement_revision_id`, `confirmation_id` and `confirmation_hash` together
  with the exact working image. It retains all confirmed requirement criteria
  and global business rules. It verifies independent confirmation, current
  criterion approvals, current working image, immutable code revisions and
  source ACLs. Legacy context policies and historical hashes are unchanged.
- A v6 context can enter the existing scope review and budgeted generation
  path without pretending the working image is published. Model selection,
  egress consent, budget, mapping, case admission, script review and execution
  gates remain separate. Approval withdrawal makes current use stale; original
  archives stay historical rather than gaining new authority.
- Case admission and script review on this iteration path require a reviewer
  other than the model-generation author. Identity separation is rechecked
  before persistence and when reading current approval. Legacy policies retain
  their original behavior; no historical approval is silently upgraded.
- Python v3 RunPlans use frozen Python AST evidence for literal Django Ninja
  mounts and HTTP decorators, including cross-file supporting locations and
  hashes. No source imports or execution are used. Unknown prefixes, conditional
  mounts, ambiguous imports and parse failures are unresolved, not successful
  route matches. The parser is bounded and not a general dynamic Django resolver.
  Static route evidence is not business correctness or execution evidence.
- The RunPlan form selects from the project-scoped operator environment registry
  via `GET /v1/projects/{project_id}/quality/target-environments`. It no longer
  accepts arbitrary environment IDs, origins or policy hashes. The no-store
  response contains no container IDs and explicitly grants neither verified
  health nor execution. Native preparation still verifies actual owned instances,
  build identity, isolation and health separately.

After confirming a requirement, open its Version review panel, expand the test
design entry, confirm and archive context, then inspect the existing scope review
panel. Saved contexts can be selected after refresh. Scope editing is currently
manual; this entry is **not** the complete promised model-assisted M3 workflow.

Remaining acceptance work includes model-assisted scope drafting, version-scoped
execution progress, authenticated controlled HTTP fixtures, denial readback after
a failed assertion, isolated account cleanup, and the complete
`verify:realworld-m3 --phase full` live replay. The M0
hand-written runtime probe and browser protocol fixtures cannot substitute for
model-generated cases detecting the injected unauthorized update through the
formal execution chain. M4/M5 are not claimed by this integration.

Focused PostgreSQL tests cover confirmed working context -> scope approval ->
generation preflight, stale approval rejection and cross-iteration denial. Static
locator tests include the fixed RealWorld checkout when present. Browser RunPlan
tests use explicitly labeled transport specimens, not live acceptance evidence.

Validation for this integration: Portal build/lint and 1,573 contract tests;
331 selected backend unit/boundary tests; eight selected PostgreSQL + MinIO
context/admission/script-review tests; four RunPlan browser scenarios; and the
isolated smoke journey passed. The selected browser scenarios cover light/dark,
narrow layouts, original-command recovery and source-access failures.

`verify:v1-release` was attempted, but its backend shards were stopped after
detecting a tool-catalog ranking regression. The regression is fixed and its
109-test suite passed separately. The full release gate has **not** completed
on this change. A separate S3-specific approval test initially ran with local
storage; rerunning it with `test-api-postgres.py --minio` passed without relaxing
the storage assertion. These results are not a live-model M3 acceptance report.

### Immutable Case Editing

The archived case panel now has an edit form. Select an existing case, edit its
title, preconditions, inputs or steps, enter a reason and explicitly confirm the
change. Any subsequent form change clears consent. The original assertion
oracles are read-only; changing a business expectation requires a new M2
requirement revision and confirmation, not a case edit.

`quality.test_design.cases.revise` accepts the exact project, parent generation
ID/hash, edited cases and reason. It records a
`nasus.test-design-case-revision.v1` archive with parent/original references,
before/after diffs and all authors. It does not fabricate a model call or rewrite
the original raw response. The current scope is rechecked under transaction locks;
only one child can supersede a parent. The child, canonical command result, audit
and outbox commit atomically. Replay and history reads reauthorize all sources.
The revision event also registers its own generation/case/coverage nodes in the
derivation index in the same transaction. It remains a human revision, not a new
model invocation; mapping review can resolve the child without borrowing the
parent's approval.

Existing case IDs, assertion row IDs, oracle digests, oracle contents and evidence
references cannot change. Assertion-to-step indices may be remapped to edited
steps; complete planned coverage is recalculated. Adding cases or fixing model
gaps still requires new generation. Chains are bounded to 64 revisions.

Superseded revisions remain readable but their mapping, case approval and script
authorization cannot be used for new work. The new child starts unreviewed. On
the iteration path, neither its original generator nor any human editor may
approve the cases. A separate reviewer must review the new mappings and admit
the new revision. Editing is not execution authorization.

### Explicit Working-Image Adoption

The Version panel lists frozen image revisions and previews the selected code
SHA changes. Nothing is auto-selected from the project latest publication.
`GET /v1/projects/{project_id}/versions/{version_id}/delivery/image-options/{image_id}`
returns a no-store preview with `adoption_authorized: false`.

`quality.iteration_image.adopt` requires the selected image/hash, expected current
image/hash, complete binding-to-commit SHA map and a reason. Confirmation appends
an adoption event using a compare-and-set head. The original M1 baseline is never
changed. Requirement projections and code adoptions form one parent-linked
working-image history; they are not ordered by timestamps or chosen by latest
project image. A changed image invalidates old requirement confirmation and its
test-design entry until re-review and confirmation.

Current scope retains the same code binding IDs. It supports new captured commits
on an already selected tracked branch; replacing fixed-SHA source bindings or
adding/removing repositories is not yet supported. Such changes are rejected,
not silently mapped by repository name. The live replay uses an isolated local
tracked branch, verifies the original SHA before M1, then explicitly advances it
to the labelled injected-defect SHA; both captured images remain immutable.

Migrations `0128_iteration_image_adoptions` and `0129_test_design_case_edits` are
incremental PostgreSQL migrations with append-only history. Existing data and
legacy model-result schemas remain readable. Downgrade does not discard populated
history.

### Live M3 Design Replay and Limits

With the documented RealWorld repositories, PostgreSQL, MinIO and Temporal ready:

```bash
npm run verify:realworld-m3 -- --phase design
```

The current harness supports an active, tested official DeepSeek Flash profile
and pins the official tokenizer data plus an explicit USD budget. Another model
requires a reviewed tokenizer/pricing profile; it cannot silently fall back to a
mock. It reads the development model selection but saves acceptance data in a
disposable PostgreSQL database and private MinIO bucket. It does not change
development business records or modify the original validation repository.

The replay checks original/defect/fix commit provenance, creates and publishes M1,
adopts the defect image, performs live M2 review and independent confirmation,
reviews a complete scope copied from confirmed AC, invokes real Temporal model
generation, then edits and independently reviews the generated cases. Missing
coverage or model-reported gaps fail the replay; no returned gap is erased to
manufacture success. Scope drafting and review decisions in this harness are
explicit acceptance inputs, not autonomous AI review or production approvals.

The single-call generation prompt is now version `v2`. It distinguishes missing
design information from the expected "not yet executed" state, while still
requiring actual design gaps and conflicting evidence to be reported. Exact
prompt bytes remain part of the confirmation plan digest, so an old unexecuted
preview cannot authorize a changed prompt. Archived results remain readable and
their gaps are not rewritten. Existing batch-v1 prompt bytes are unchanged to
preserve historical batch receipt verification.

Reports are written under `output/realworld/m3-<UTC timestamp>/`. `design_verified`
means only the design/edit/review subset passed. `full_m3_verified` remains false.
The live replay completed on 2026-11-16: eight model-generated cases, no design
gaps, an immutable human revision, complete mapping review and an independent
case approval. The generator/editor's self-approval was rejected. Evidence:
`output/realworld/m3-20261116T013818Z/report.json` and its `junit.xml` (one live
integration test passed in 2,389.49 seconds). This elapsed time includes M1/M2,
source verification, real model calls and approval replay; it is not model-only
latency. The run did **not** generate executable scripts or dispatch cases to the
defect target, and does not establish full M3 acceptance.

Default `--phase full` returns exit code 2 and writes a blocked report before any
model call or target mutation. HTTP v4 now supports reviewed readback after a
failed assertion, but the live chain still lacks model scope drafting, controlled
role credentials/fixture manifest v2, durable environment leases/batch reset and
version-level execution/cleanup progress. Legacy v1-v3 stop-on-failure semantics
remain unchanged. These are capability gaps, not permission checks to disable.
The verifier does not substitute M0 probes, protocol fixtures or handwritten cases
for the formal live execution chain. A blocked report records both execution and
cleanup as `not_started`, never completed or passed.

Focused validation of the new edits/adoption: 17 PostgreSQL + MinIO tests,
two migration round-trip tests, 1,610 Portal contract tests, Portal build/lint/i18n,
three case-review browser scenarios and the Web/API smoke journey passed. Two
additional browser scenarios verify working-image adoption in light and dark
themes, including explicit selection, old/new SHA preview, consent invalidation,
immutable baseline and refresh recovery. Both existing tracked-branch browser
scenarios also passed after extracting their shared isolated Git fixture.
The 17 include ten case-revision tests, six image-adoption tests and one bound-
iteration edit/mapping/independent-approval integration test. The integration
fixture is deterministic, not live-model acceptance evidence. A further 113
derivation and automation-provenance regression tests passed.
The live replay and full release gate must also pass before M3 can be marked
delivered; those results are not implied by these focused checks.

The 2026-11-16 release attempt collected 9,466 backend tests but was stopped
after failures; it is **not** a passing full-suite result. Two tool-context
selection regressions were corrected without enlarging the prompt budget.
A cancellation test now synchronizes on the held indexing phase before cancelling,
rather than expiring during unrelated startup; its cancellation, durable pin and
no-artifact assertions are unchanged, including an explicit delayed-start case.
The browser phase-revision test exceeded its default overall 30-second deadline
after completing the two builds and approval gates. Only that long scenario's
overall deadline was extended; both themes passed a focused rerun, with every
assertion retained. All release stages still require a fresh complete run.

### HTTP v4 Readback Slice (2026-11-17)

The script-generation panel offers v4 explicitly. Selecting a different protocol
invalidates the old model-call preview; it never upgrades historical artifacts
or reuses their consent. Script proposals, independent action/oracle reviews,
RunPlans, private dispatch and response verification pin the same protocol.
Existing v1-v3 artifact bytes and hashes retain their original meanings.

Each v4 request declares `phase=exercise|readback`. A readback must be GET or
HEAD. `capture_snapshot` captures a JSON field from a successful GET before any
mutation; `assert_unchanged` compares it with a later successful readback GET.
These comparison actions require reviewed oracle mappings; a snapshot is an
observation, not a new business expectation or authorization. Ordinary resource
bindings remain separate from snapshots. Credentials are still rejected, rather
than placed in model-generated headers or public evidence.

After a business assertion fails, the original failure remains recorded. Only
explicitly reviewed readback and assertions over completed requests may proceed;
later writes and ordinary exercise requests are recorded as `not_executed`.
A failed readback or interrupted transport cannot be reported as a completed
passing comparison. A lost write response remains an interrupted request and is
not resent by the HTTP executor. This does not yet implement the promised
batch-level unknown-result recovery, cancellation quiescence or reset lifecycle.

The API verifies the ordered receipt, exact before/after response bytes, response
status, strict JSON field values and artifact hashes. A forged passed comparison,
omitted readback or claimed execution of a skipped mutation is rejected. The
Portal also matches every displayed action/oracle state and count to the original
Runner job receipt; recomputing the outer observation hash does not permit a
contradictory passed/failed/interrupted display. The
public Runner `/v1/jobs` endpoint rejects v4; original fixture proof and private
dispatch remain necessary for fixture-bound case execution.

An AES-GCM envelope codec is available for private execution data, binding project,
iteration, batch, case, environment epoch, inventory, record and expiry through
authenticated data. **It is not yet wired into credential preparation, key
management, persistence or artifact publication.** Codec tests do not establish
that authenticated target execution or private-evidence storage is delivered.

Focused validation includes the native Node HTTP executor against a local server,
backend verification of the original bytes, cross-language RunPlan/fixture
handoff contracts, v4 script-generation browser scenarios and v4 RunPlan browser
scenarios (light/Chinese and dark/English, including mobile, budget consent, lost
acknowledgements and independent review). The RunPlan scenarios also cover original
command recovery, source locators, build binding, fixture definitions and revoked
access. Actual PostgreSQL/MinIO persistence caught two protocol allowlists that
in-memory adapters had hidden; RunPlan artifact storage and build binding now
accept v4 without changing historical artifact bytes.
These use protocol specimens, not the RealWorld target or live-model acceptance.
The M3 completion flag remains false until the whole live chain and cleanup pass.

### Validation of This Slice

Observed on 2026-11-17; counts below are separate runs, not an additive total:

- Confirmation/cancellation and command-fence PostgreSQL/MinIO regression: 52 passed.
- New readback, private-envelope and preflight tests: 77 passed.
- RunPlan artifact/build and existing binding tests: 84 passed.
- Fixed-source v4 script/review/RunPlan API with real PostgreSQL and MinIO:
  1 passed, 1 deselected (the v3 parameter was not part of this final v4-only run).
- Runner: 168 passed. Portal contracts: 1629 passed.
- Full browser regression: 285 passed, 5 existing opt-in exweb scenarios skipped.
  The two subsequently added v4 RunPlan browser scenarios passed separately.
- Portal build/lint, smoke, focused DDD checks and release hygiene passed.

The full `verify:v1-release` command has **not** been rerun successfully after
these changes. The preceding release failure is not superseded by focused green
tests. `verify:realworld-m3 -- --phase full` still exits 2 at capability preflight,
with no live target execution or cleanup. Its report remains
`full_m3_verified=false`. Missing model scope drafts, fixture manifest v2 and
private role credentials, durable environment lease/reset, version delivery
execution progress and the live RealWorld replay remain implementation work,
not optional skipped acceptance tests. No completion commit or push is justified
by this slice alone.

## Preflight Reliability Corrections

The entries above are dated slice reports, not a current completion certificate.
See the retained acceptance update below for the latest model-scope and browser
observation status.

Explicit confirmation is timestamped by PostgreSQL in the locked execution
claim transaction, before preparation journaling. Confirmation freshness and
the journal thus share one clock; host/container skew cannot produce a negative
confirmation age. Pending commands and replay do not receive new confirmation
authority, and existing TTL/cancellation assertions are unchanged.

The isolated PostgreSQL/MinIO test launcher checks server clock skew before
running suites (30-second maximum, accounting for the request time window).
MinIO `RequestTimeTooSkewed` fails preflight with a VM-clock diagnostic; it does
not extend signed-request validity or retry a model/execution command. Only a
successfully created test bucket is cleaned up. Correct the host/container clock
and rerun; do not work around this by increasing confirmation TTLs or using the
development database as a test database.

The administration DTO projects the retained legacy account status `disabled`
as `suspended`. It does not change the database status, reactivate the account,
or change either authentication mode's rejection of inactive users.

## Retained Acceptance and Model Scope Drafts (2026-11-18)

**M3 remains incomplete.** This update adds a model-assisted scope slice and
starts a retained real-Portal session. It is not evidence of HTTP/browser target
execution, snapshot restoration, or a passing full release gate.

### Model Scope Slice

- A current published or confirmed iteration Context with approved AC/rule
  oracles is the input. `quality.test_design_scope.draft` fixes the tested chat
  configuration, full source inventory, prompt, tokenizer/pricing policy and
  user-selected budget. Preview performs no model egress; the canonical tool
  requires explicit confirmation before its single native call.
- Migration `0130_scope_model_drafts` retains append-only reservation, reply,
  draft/failure events, native LLM call provenance and a private MinIO reply.
  Unknown outcomes retain the reservation and are not automatically retried.
  Reads revalidate hashes, provider usage and current source permissions.
- Model output is a suggestion, never an approval. Every approved constraint
  remains accounted for, with unchanged positive oracles. An independent
  reviewer can load the suggestion into the existing scope review form; the
  model author cannot approve their own draft. Case generation remains gated.
- The Context panel provides tested-model selection, explicit budget preview,
  confirmation, history and a read-only draft. Token-free actor/context-scoped
  request IDs and hashes survive refresh. Recovery reads the original command;
  it does not restore consent or send another model call. An unconfirmed original
  needs a fresh matching preview and an explicit checkbox/button action.
- More than 100 native attempts fails the current history view closed instead
  of silently omitting older unknown calls. Pagination and a dedicated durable
  Temporal scope-generation activity remain follow-up work; the current model
  call is awaited by the tool handler and must not be described as that activity.

### Retained Portal Session

The local acceptance ID is `m3-20261118`. Project
`proj_realworld-m3-acceptance-20261118_eb67ffcef3` and conversation
`conv_ab8c3de715` were created through the running Build page. Two distinct
operator/reviewer accounts were registered through the real Portal. No reviewer
membership or approval has been granted implicitly.

The Build source review contains the fixed Django commit
`87dd078c883a046f5ff20269df2fb004d8b5f83f` and Vue commit
`db749e3bb1a45755e0a3f4065abaf7346f004f36`. A draft US-001 plus the pinned OpenAPI
file, official Hurl examples and an official UI test were uploaded through the
Portal to MinIO. They are sources, **not generated or approved acceptance tests**.
The bounded `nasus.openapi-document.v1` adapter extracts supporting route/schema
evidence from YAML/JSON without executing YAML tags or fetching references.
Archived v1/v2 explicit-document projections keep their stored versions and
hashes; unknown extractor versions are rejected. Read-only extraction of the
fixed RealWorld spec yielded 19 operations across 12 paths, with verified source
line/hash references. It does not grant AC/oracle approval; omitted fields and
unexpanded references remain explicit gaps. Hurl and TypeScript still need
dedicated adapters. Raw upload does not imply supported execution or complete
coverage.

This exposed and fixed two UI/intake problems: a genuinely empty working image
was rejected for lacking a source manifest, and a multi-repository request kept
only the first repository. Explicit repository/ref pairs are now preserved and
shown separately; ambiguous pairings are stopped for clarification.

After the user explicitly reviewed and approved source intake, **Confirm sources
and build** was clicked through the real Portal. Nasus reported source capture
complete and saved a fixed build plan. The session is now stopped at **Authorize
Fixed Build Plan**, invocation `tool_2bee3de044`: one structural build, 1,200
seconds, zero model calls and zero model cost. This requires a separate human
confirmation, which has been requested but not supplied. Image publication,
iteration creation, M2 confirmation, live scope/case/script generation, target
execution and snapshot restore have **not** been performed in this retained
project. No existing business data was removed.

```bash
# Observation of an existing retained session, not a fixture-based replay.
npm run verify:realworld-m3 -- --mode retained --phase full \
  --acceptance-id m3-20261118
```

This reads `output/realworld/<id>/acceptance.json` and the private operator
browser state, opens the real project, refreshes Build and checks the restored
source review. Each observation gets a separate JSON report and screenshots.
It distinguishes source confirmation from structural-budget confirmation using
the visible formal card; it does not infer approval from saved report metadata.
It does not migrate, insert fixture rows, confirm tools, reset targets or remove
data. It returns exit code **2**, with `full_m3_verified=false`, even when these
observations pass. The retained mode is currently an observation/resumption
checkpoint, **not yet the promised complete execution driver**.

`scripts/realworld-retained-session.mjs --acceptance-id <id> --role operator`
(or `reviewer`) sets up or logs into an acceptance account through Portal forms.
It waits for the actual login response, not a fixed delay. Credentials and
browser state remain in mode-0600 files inside a mode-0700 ignored directory;
do not commit, print or share those files. Report metadata and screenshots are
also local artifacts. Reusing an ID keeps the same credentials and observations.

The existing default `--mode isolated --phase design` remains a disposable-store
design regression. It must not be mistaken for retained product acceptance.

### Retained Build Steps (2026-11-19)

`verify:realworld-m3 -- --mode retained` is still observation-only. The separate
`npm run verify:realworld-retained-step -- m3-YYYYMMDD-HHMM <step>` drives the
running local Portal, reusing the existing RealWorld operator login. Choose a
new ID only for a genuinely new project. Keep the same ID on recovery. The
operator browser state and the original US-001 source file are prerequisites;
the four official historical test files and the OpenAPI document are read
from the pinned Git specification, not from the working tree.

Run `create`, `sources`, `requirements`, `tests`, `capture`, then `structure`.
Each step checks the project-specific Build session, and writes an exclusive
intent **before** submitting a change. Repeating a completed step checks the
same receipt. If the outcome of a submitted action is unknown, use `inspect`;
do not delete intent files or send a second command. `reopen` starts a clean
browser, signs the same operator in, opens the retained project and captures
its page. No step cleans up business data. Pins, results and sanitized
observations are stored under `output/realworld/<id>/`.

The image is not published by a successful structure command. The publication
handoff must validate the same source revisions and the independent review
account's present access. Once the exact initial publication is recorded,
`propose`, `iteration` and `requirement-draft` are guarded follow-on steps.
The last step does not confirm a live model evaluation. None of these commands
claims generated tests, model approval, a target run, or full M3 acceptance.

To resume at the initial review, run
`node scripts/realworld-retained-publication.mjs <acceptance-id>` without
`--grant-reviewer`. An unsigned candidate returns
`independent_human_publication_review_required`. After a real approval and
before promotion, the same command reads the reviewer's original command and
rechecks the operator's current preview, membership, source pins and expiry.
`awaiting_operator_publication` means the review receipt was verified, **not**
that the baseline was promoted. Both handoffs exit 2 without submitting a
decision. After promotion, use the original Build session's `propose` step,
which verifies the published head before proposing an iteration.

### Remaining Exit Criteria

The following foundations now exist, but are not yet a connected target runtime:

- Fixture manifest v2 separates author/other/anonymous roles, resource bindings
  and opaque credential references. Private PostgreSQL adapters persist only
  authenticated ciphertext and immutable setup/cleanup claims and outcomes.
  A claimed operation without an outcome cannot be automatically dispatched again.
- Environment lifecycle persists exclusive leases, monotonically increasing
  generations, immutable before/after snapshots and separate independent-copy
  restore records. Private MinIO archives support encrypted readback. An expired
  lease or failed preservation step quarantines the environment rather than
  resetting or reassigning it.
- Browser v1 converts reviewed plan actions into an exact versioned command and
  verifies receipt ordering and original oracle mappings. The Runner requires a
  private dispatcher and evidence sink; the public endpoint alone cannot launch
  Chromium. A receipt does not itself grant execution or business coverage.

The production composition still needs the transaction-bound authority guards,
registered RealWorld role/target adapters, actual independent snapshot restore,
browser private dispatch/evidence integration, version execution progress and
the complete HTTP/UI live replay. The Vue source also exposes locator and
read-only assertion gaps in the browser v1 contract; see
[`browser-protocol.md`](../../../apps/runner/src/browser-protocol.md). Do not
weaken approved assertions or modify the target merely to fit that contract.

No original, defect or fix target has been exercised through this retained UI
session. Synthetic restore/target proofs in adapter tests are not actual target
restore evidence. Successful unit, PG/MinIO, Runner and Portal regressions do
not waive these requirements. No M3 completion commit or remote push has been
made for this unfinished slice.

### Slice Verification

Observed after the scope/recovery changes (separate suites, not a combined count):

- Scope native draft PostgreSQL/MinIO API regressions: 4 passed, including
  actor-scoped acknowledgement lookup, immutable history, independent review,
  expired consent, corrupted native provenance and source permission changes.
- Scope/intake, DDD/Portal boundaries and retained-mode preflight: 231 passed.
- Portal contracts: 1,654 passed; Runner: 168 passed.
- Browser regressions: 3 passed (lost acknowledgement/refresh, scope review in
  light and dark themes). The provider protocol in these regressions is a
  specimen, not a live RealWorld result.
- Portal build/lint/i18n, smoke and `git diff --check` passed. The build still
  reports the existing large-chunk warning.
- Actual retained Portal observation after host-service restart verified that
  the project and source review survived refresh. The observation remains
  `awaiting_human_confirmation`, `full_m3_verified=false`.

Later foundation checks, also separate suites rather than an additive total:

- Environment lifecycle and encrypted snapshot PostgreSQL/MinIO checks: 129 passed.
- Private role-state PostgreSQL concurrency, rollback and migration checks: 51 passed.
- Browser/role/OpenAPI contracts, boundaries and retained preflight: 433 passed.
- Current Runner suite: 196 passed; Portal contracts: 1,654 passed.
- Scope model draft, immutable case edit, working-image adoption and Build
  delivery PostgreSQL/MinIO API replay: 15 passed in 480.97 seconds. A fresh
  scope-draft lost-acknowledgement/refresh browser regression also passed.
- OpenAPI/stored-version unit checks: 152 passed; document and component API
  replay against isolated PostgreSQL/MinIO: 11 passed.
- Portal build, lint, internationalization and `git diff --check` passed. The
  existing large-chunk warning remains.

The host services were restarted after applying additive migrations through
`0132_http_role_private_state`. Portal, API and Runner returned HTTP 200 and
`dev:status` reported the schema current. A new retained observation,
`77e2063f-e858-492d-b618-0ace633ea921`, confirmed that the project and conversation
survived restart and refresh, with structural-budget confirmation still pending.
No source confirmation or execution confirmation was replayed by the observer.

The full release-gate run did not pass. It was interrupted while the backend
suite was taking unexpectedly long and predates later integration changes.
Focused profiling did not implicate the history SQL itself: its construction
and compilation took about 0.047 seconds and an independent PostgreSQL history
test passed in 0.75 seconds. The fixture's preceding verification chain issued
about 48,936 SQL reads and constructed 433 S3 clients in an 80-second sample.
This is a repeated-read performance problem, not a proven database deadlock;
it must not be worked around by caching permissions or weakening ancestry
checks. Keep the release gate incomplete until a new full run finishes. No
complete HTTP/UI target acceptance, actual target snapshot restore or completion
push is asserted here.

A small measured fix now opens the existing artifact read transport for the
duration of one `ContextPack.read()`. In alternating isolated PG/MinIO checks,
the result, 625 SQL statements and 51 object GETs were unchanged while client
construction fell from three to one; median duration across three pairs fell
from 0.791 to 0.662 seconds. Scope/transport unit checks (95) and PG/MinIO checks
(4) passed. This is not a cross-request permission/content cache, and does not
resolve the whole repeated-ancestry performance problem or make the interrupted
release run successful.
