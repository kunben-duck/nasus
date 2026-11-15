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

Remaining acceptance work includes explicit defect-commit working-image adoption
and reapproval, model-assisted scope drafting, immutable case editing with
downstream invalidation, version-scoped execution progress, and the complete
`verify:realworld-m3` live replay. That verifier is not yet delivered. The M0
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

## Preflight Reliability Corrections

Explicit confirmation is timestamped by PostgreSQL in the locked execution
claim transaction, before preparation journaling. Confirmation freshness and
the journal thus share one clock; host/container skew cannot produce a negative
confirmation age. Pending commands and replay do not receive new confirmation
authority, and existing TTL/cancellation assertions are unchanged.

The administration DTO projects the retained legacy account status `disabled`
as `suspended`. It does not change the database status, reactivate the account,
or change either authentication mode's rejection of inactive users.
