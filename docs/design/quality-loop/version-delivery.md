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
- `stage`: exactly `legacy` or `image_pinned` in M1.
- `baseline`, `iteration_image`: null for legacy Versions; otherwise identical
  `PublishedImagePin` objects containing `publication_id`, `baseline_id`,
  `image_revision_id`, `image_artifact_hash`, `manifest_id`, `manifest_hash`,
  `sequence`, `quality_generation_authorized: false`, `release_authorized: false`.
- `code_revisions`: captured `binding_id`, `source_id`, `source_revision_id`,
  `repository`, nullable `tracked_ref`, `external_revision`, nullable `commit_sha`,
  `content_hash`, and `manifest_hash`. Non-Git captures have no invented SHA.
- `blockers`: `["delivery_m2_not_implemented"]` for bound Versions, otherwise `[]`.
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

## M2 Requirement Intake Increment (Not M2 Completion)

The implemented increment is immutable requirement intake in an image-bound
Version. It does **not** evaluate requirements with a model, project them into a
new working image, approve acceptance criteria, or authorize test generation.
The M1 delivery blocker remains until those downstream contracts are delivered.

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
the last fetched requirement content. The UI labels all these records drafts,
not approved requirements or completed reviews.

Still required before the M2 exit condition: durable live-model evaluation with
fixed inputs, a verifiable source projection and append-only working-image
adoption, exact-revision human confirmation, and conversational clarification
that consumes the same persisted facts. M3 formal Django HTTP execution, M4
defect/fix/regression and M5 Version gate/promotion are not delivered by this
increment. `verify:realworld-loop --phase full` must not report success until
the full live-model/real-target evidence chain exists.

## Preflight Reliability Corrections

Explicit confirmation is timestamped by PostgreSQL in the locked execution
claim transaction, before preparation journaling. Confirmation freshness and
the journal thus share one clock; host/container skew cannot produce a negative
confirmation age. Pending commands and replay do not receive new confirmation
authority, and existing TTL/cancellation assertions are unchanged.

The administration DTO projects the retained legacy account status `disabled`
as `suspended`. It does not change the database status, reactivate the account,
or change either authentication mode's rejection of inactive users.
