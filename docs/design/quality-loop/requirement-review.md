# M2 Requirement Review

## Scope

M2 connects immutable requirement intake to live semantic review, conversational
clarification and independent human confirmation. It uses the existing Version,
source evidence, acceptance specifications, ToolInvocationRuntime, LangGraph
conversation turns and PostgreSQL. It does not introduce a second approval engine.

The initial delivery baseline never changes. Confirmation advances only the
iteration's working image. Test design, execution, defects and release remain
downstream M3-M5 work, not side effects of confirming a requirement.

## Interaction

In an image-bound iteration, or the Build conversation that created that iteration:

1. Send `需求：支持修改文章`, or create/select the requirement in the Version page.
2. Inspect the selected model/evidence and explicitly confirm model review.
   The chat command is `确认评审需求`; this authorizes one model call, not approval.
3. The model checks roles, preconditions, inputs/outputs, errors, verifiability
   and conflicts. Blocking questions prevent acceptance confirmation.
4. Send `回答：...` to answer the current question, or fill the displayed questions
   in the Version page. Answers create a new immutable revision. Earlier answers
   remain available and are included in the next review.
5. Repeat review until the questions are resolved. `查看需求评审` reads current
   facts; `重新评审需求` prepares a new explicit review attempt. Ordinary questions
   do not consume a pending clarification or mutate the requirement.
6. A project administrator other than both the requirement author and review
   initiator inspects the exact proposed criteria and enters a confirmation reason.
   The explicit page action invokes existing AC approvals, followed by requirement
   confirmation. Partial approval never becomes an implicit requirement approval.
7. Refreshing chat or the Version page reads the persisted revision/approval state.

The initial guided chat syntax is intentionally explicit to avoid treating arbitrary
questions, quoted source text or ordinary conversation as approval commands. The
page is the final independent confirmation surface; chat does not approve on the
reviewer's behalf or grant authorization through a model response.

## Model and Evidence

`RequirementReviewModelPort` is implemented by the existing LLM gateway. One call
pins the active chat profile, credential digest and prompt version. It records the
purpose, provider, model, usage and call ID. The review has a bounded HTTP timeout
and overall deadline; ordinary chat timeouts remain unchanged. Fallback/mock output,
empty responses, invalid JSON or invented references are failures, not reviews.
For the official DeepSeek V4/Flash compatible endpoint, this bounded review uses
the documented [non-thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/)
to avoid exhausting the response budget before JSON is emitted. This per-call
option is pinned in the preview/audit; it does not change global chat settings or
send DeepSeek-specific options to arbitrary compatible providers.

Input is the exact requirement revision, prior answers and bounded evidence from
its frozen image. Code is labelled implementation evidence, not the correct oracle.
Specifications and user answers supply intended behavior. The model cannot execute
instructions found in those records. Every check/question/criterion cites a provided
reference; duplicate dimensions and empty review content are rejected.

Retrieval currently selects at most 16 objects and 60 lines per object within a
40 KB evidence budget (48 KB total input ceiling). Document evidence uses its
verified whole-record locator, never the first UUID-sorted field. Truncation and
omitted objects are explicit. This is bounded retrieval, not a claim that the whole
repository was semantically understood. All source bytes are verified and access
is rechecked before/after the model call and before committing.

An unblocked assessment creates an immutable, clearly unapproved requirement/AC
source document, archived source revision and frozen image candidate. Original
members and code pins are retained; the new source is restricted to administrators.
The project source head is not advanced. Existing source-backed AC review machinery
validates each proposed oracle and its exact image/hash. Model suggestions cannot
acquire authority by being written into a source document.

## Persistence and Commands

`requirement_review_events` stores append-only `reserved`, `evaluated`, `failed`
and `confirmed` events with revision, actor, invocation, payload hash and timestamp.
Reservation occurs before egress. A retry never silently issues a second model call;
an interrupted reservation requires inspecting/retrying through a new explicit
review. Late responses cannot supersede a newer reservation.

Writes use the canonical tool runtime:

- `quality.requirement.revise`: new immutable text/answer revision.
- `quality.requirement.evaluate`: exact revision + evidence/model preview digests.
- `quality.acceptance_specification.review`: existing exact-image independent AC approval.
- `quality.requirement.confirm`: exact evaluation ID/digest + human reason.
- `query.quality.requirement_review`: fresh authorized review/status receipt.

Read/preview: `GET /v1/projects/{project_id}/versions/{version_id}/requirements/{revision_id}/review`
with optional `preview=true`. Responses are private/no-store. A preview does not
invoke a model. Receipt replay, conversation history and source reads recheck
permissions; SSE invalidations contain identifiers rather than model/source text.

Model review and confirmation require a current project administrator. Confirmation
checks all approved AC revisions, reviewer identity, current requirement, exact
working image and evaluation digest under the publication/source lock. Completed
command receipt, audit and outbox are committed with the review event. Missing,
revoked or stale authority is rejected; client buttons cannot bypass it.
Projection source records, source ACL, document/evidence records, frozen image and
the successful evaluation are also one PostgreSQL transaction. A failure rolls
back their business records; uploaded immutable blobs can remain unreferenced,
but cannot become a readable or approved requirement without the committed records.

The delivery read model derives the current working image from confirmed events.
The initial binding is immutable, and the new image is not a published baseline.
Changing inputs or withdrawing AC approval prevents `requirements_confirmed`.
Old records remain historical evidence, never current approval for new inputs.

## Validation and Boundaries

`npm run verify:realworld-m2` uses disposable PostgreSQL/MinIO and the development
system's selected **live** chat model. It reads model configuration only, not
development project data. Credentials stay in subprocess environment, not reports.
It requires these locally checked-out repositories:

- `.nasus/validation/realworld-django-ninja`, commit `87dd078c883a046f5ff20269df2fb004d8b5f83f`.
- `.nasus/validation/realworld-spec`, commit `25588846c314b15a5e427ffe816e6b4af7be68c7`.

The replay creates/publishes a real-source image and bound iteration, reviews vague
US-001, supplies predeclared operator clarification, then exercises separate operator
and reviewer accounts through canonical APIs. Reports under `output/realworld/m2-*`
retain source commits, input/evidence, live model calls, revisions, approvals and
confirmation. It is an acceptance replay, not a production human's approval.
`full_loop_verified` remains false: M2 does not run the target HTTP regression suite.

Contract/API and browser tests explicitly substitute a local model fixture to
exercise failure, concurrency, source revocation and UI states reproducibly. They
are not substitutes for the separate live model replay.

Current limit: the projection adapter accepts a structural image with no semantic
assertion overlays. It rejects an overlay-bearing base rather than dropping existing
assertions. Merging such overlays and authorizing M3 test generation are separate work.

## Verified Replay (2026-11-13, UTC+08)

`verify:realworld-m2` passed using the pinned RealWorld commits above, isolated
PostgreSQL/MinIO and live `deepseek-v4-flash` with the v3 review prompt. Two live
reviews produced clarification followed by eight source-referenced criteria.
A distinct reviewer account approved all eight through the existing AC commands,
then confirmed the requirement. The final stage was `requirements_confirmed`;
the original baseline/code pins were unchanged and the working image advanced.
The next blocker remains `formal_test_design_required`.

Local evidence: `output/realworld/m2-20261112T180908Z/report.json` and `junit.xml`.
This is an automated independent-account acceptance replay, not a production
human sign-off. It makes no claim about actual HTTP regression, defects or release.

Related verification: 31 PostgreSQL API tests, 196 unit/boundary/stack-contract
tests, 1556 Portal contracts, seven relevant E2E cases (including light/dark M2),
Portal build/lint/i18n and smoke passed. The latest atomic M2 browser path was
also rerun independently in both themes. Full `verify:v1-release` was not run
for this increment; existing bundle-size/deprecation warnings remain.
