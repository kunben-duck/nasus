# Pinned Image Publication

Implemented contract: `nasus.image-publication.v1`, migration `0053_image_publication`.
This is knowledge snapshot publication, not business acceptance or release approval.
The complete P0-P6 scope remains defined in [delivery-and-evaluation](./delivery-and-evaluation.md).

## Authority And Storage

- An immutable candidate remains unchanged in PostgreSQL and MinIO. Its original status and historical readiness fields are not rewritten.
- `image_publication_reviews` records append-only decisions for an exact candidate, artifact hash, source manifest, target baseline, expected previous head, preview digest and policy revision.
- `image_publications` records immutable publications; `image_publication_heads` is the compare-and-swap pointer for each project/baseline. Both foreign keys and application checks enforce project scope.
- A review requires a currently active registered project/platform administrator and canonical user confirmation. An approved review is valid for 30 minutes, only for its pinned claim and only while it is the latest review of that claim.
- A generic `Approval` mirror supports the existing runtime gate. It cannot replace the immutable review, authorize another tool, authorize an unpinned promotion, or be edited with generic approval commands.
- Publication, head movement, audit and Outbox append share one PG transaction. Failure rolls back all four. Retrying a committed invocation returns the original publication without moving a newer head backward.
- Both review and publication repeat source authorization and verify the captured source manifest, candidate membership and archived original evidence. Source/head/ACL changes require a fresh preview and review.

## Canonical Command Surface

1. `query.system_image.publication.head` resolves the authorized current head for `project_id` and `target_baseline_id`; an empty head is explicit null.
2. `query.system_image.publication` takes that head plus `image_revision_id` and `image_artifact_hash`. Its metadata-only receipt pins the preview digest and current review ID.
3. `system_image.revisions.review_publication` additionally takes `expected_preview_digest`, `expected_review_id`, `decision` and `reason`; `ToolInvocationRuntime` requires user confirmation.
4. `baseline.promote` publishes the same pins with the approved review's `approval_id`; the existing approval-required runtime remains authoritative.

Agent discovery includes all four contracts for publication intent. Receipt expansion rechecks current authority and current head/review, refusing a stale observation rather than silently presenting it as current.

HTTP read routes are `GET /v1/projects/{project_id}/system-image/publications` (bounded history) and its `/preview` endpoint. They use private/no-store responses. There is no alternate HTTP write endpoint that bypasses the tool runtime.

## Portal

The existing image revision dialog exposes an explicit target-baseline selector. Review and publish use separate consent checkboxes bound to the rendered preview and review. Changing input or reloading clears consent. There is no automatic write retry. Concurrent reviews require reload; read authorization/integrity failures hide previously displayed image content. Light/dark/mobile reuse the existing shared visual language.

## Evidence Verification Cost

Publication verifies up to 512 evidence pins per batch. PG loads the selected evidence and its source/binding metadata in a bounded join. The service validates exact project/revision membership before storage reads. Each file and full evidence snippet is hash-checked; only metadata is returned. Authorization is checked before, after and every 16 items, and the enclosing frozen-image scope must still be current before return/commit.

Hash-verified source manifests may be reused only within one context-local verification session, capped at four manifests. The key includes project, source, manifest reference/hash, source hash and read limits. Raw source bytes and authorization decisions are not cached. Individual user-visible evidence reads retain their before/after authorization and 64 KiB page bound.

## Compatibility And Remaining Work

Legacy projection refresh now updates baseline identities in place and preserves publication review mirrors; it must not delete referenced baselines. Projects with pinned heads cannot use the unversioned legacy promotion path.

### Published Consumers

Once a project has any publication head, the default system-image and knowledge queries resolve its unique Official target. Agent image context and memory retrieval resolve the Official target for project conversations, or the exact version's working target for version conversations. A missing target/head returns an explicit `unpublished` view. Multiple matching targets fail as a conflict; a version never silently inherits a moving Official head.

The read service verifies the immutable publication, image artifact/hash, captured manifest and source membership. It reconstructs objects, relationships and source metadata from these pins, not the current compatibility projection. The response includes publication/image/hash/manifest/sequence pins. Sources do not expose archive or credential references. A head change during assembly or reranking requires a new read; revocation, missing artifacts and integrity failures never fall back to a draft. Only project identity and explicitly labeled operational summaries remain live data.

`GET /v1/projects/{project_id}/system-image?view=working` is the explicit draft query for further construction. Portal plan/revision inspectors use this query; the knowledge page displays the published pin and treats unpinned metrics/chunks as unavailable rather than zero. Background reauthorization hides mounted details without losing pagination/publication state; a rejected read removes old content.

Before any publication head exists, the legacy source-authorized view remains explicitly labeled `legacy_draft`. This compatibility period is not a claim that the old projection is an approved image.

Published retrieval currently ranks frozen members lexically and reranks them through the configured route. It emits image-qualified references and reports `published_lexical_rerank_unversioned_index_withheld`. It does not reuse mutable-alias embeddings, unproven long-term memories or unpinned legacy traces. **Versioned hybrid/vector index construction and immutable retrieval traces remain required**, not replaced by this transitional read protection. Independently governed semantic assertion consumers and historical conversation provenance also remain incomplete.

ContextPack v4 now explicitly pins an immutable publication and verifies its baseline head before/after preview and inside the canonical compilation transaction. Every subpack and derivation keeps the same pin. Historical replay uses the original publication; a later head marks current use stale without changing old bytes. See [context-packs](./context-packs.md). ContextPack v1-v3 remain unchanged historical/draft contracts. Legacy generators still require migration; publication does not remove generation blockers or rewrite historical readiness. Delta DAGs, dependency invalidation, branch overlays/tombstones, three-way image merge, rollback and reconciliation remain required P4 work. Complete AC/rule authoring, CoverageMatrix, RunPlan and target execution/release evidence remain required P3/P5 work.

## Validation Scope

API tests exercise real ToolRuntime confirmation, CAS competition, expired/rejected reviews, source/ACL changes, corruption, rollback, replay and approval-purpose isolation in disposable PostgreSQL. Browser tests cover review/publish/reload, separate consent, concurrent rejection, authorization failure and mobile layouts.

The exweb probe pins commit `fe5827f6b76f77ef34918d8b452ee823142332dc`, including 546 code members. The PG/MinIO adapter probe also uses explicitly labeled companion requirement/test fixtures. Its reviewer is a test identity, not the exweb maintainer or an independent business acceptance authority. The repository's code is not executed and no external semantic model is called. Current run results are recorded in [implementation-progress](./implementation-progress.md), not inferred from this contract.
