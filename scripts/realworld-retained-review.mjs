// Offline handoff for the *first* official M1 knowledge publication. No transports,
// account setup, credential lookups, grants, confirmations or publication writes.
import { createHash } from 'node:crypto'

const policy = 'nasus.image-publication.v1'
const reviewTool = 'system_image.revisions.review_publication'
const blocked = reason => ({ status: 'blocked', reason })
const id = value => typeof value === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(value)
const hash = value => typeof value === 'string' && /^sha256:[0-9a-f]{64}$/.test(value)
const commit = value => typeof value === 'string' && /^[0-9a-f]{40}$/.test(value)
const unique = list => new Set(list).size === list.length
const knowledgeOnly = record => record?.quality_generation_authorized === false && record.release_authorized === false

// Python source_snapshots.snapshot_digest: these native DTOs have ASCII keys,
// and only strings, integers, booleans, arrays, objects and null as values.
function digest(value) {
  const json = JSON.stringify(value, (_, v) => v && typeof v === 'object' && !Array.isArray(v)
    ? Object.fromEntries(Object.keys(v).sort().map(k => [k, v[k]])) : v)
  return 'sha256:' + createHash('sha256').update(json).digest('hex')
}

function projectAdmin(members, project, user) {
  if (!Array.isArray(members)) return false
  const rows = members.filter(m => m?.user?.id === user || m?.binding?.user_id === user)
  if (rows.length !== 1) return false
  const { user: account, binding } = rows[0]
  return account?.id === user && account.status === 'active' && binding?.user_id === user
    && binding.project_id === project && binding.scope_ref === 'project:' + project
    && binding.version_id === null && binding.session_id === null
    && binding.status === 'active' && binding.role === 'project_admin'
}

function checkSources(session, pins, manifest, preview, revisions) {
  const commits = session.source_commits
  const code = pins.code_sources
  if (!Array.isArray(commits) || commits.length !== 2 || !unique(commits) || !commits.every(commit)
      || !Array.isArray(code) || code.length !== commits.length
      || !code.every(s => id(s?.binding_id) && commits.includes(s.commit_sha))
      || !unique(code.map(s => s.binding_id)) || !unique(code.map(s => s.commit_sha))) return 'retained_code_pins_invalid'
  if (!id(pins.manifest_id) || !hash(pins.manifest_hash) || manifest?.project_id !== pins.project_id
      || manifest.manifest_id !== pins.manifest_id || manifest.content_hash !== pins.manifest_hash
      || preview.image.manifest_id !== pins.manifest_id || preview.image.manifest_hash !== pins.manifest_hash)
    return 'source_manifest_changed'

  const sources = preview.source_members
  const scope = preview.source_scope
  if (!Array.isArray(sources) || !sources.every(s => id(s?.binding_id) && id(s.source_revision_id)
      && ['code', 'us_doc', 'test_asset'].includes(s.source_type) && s.status === 'captured')
      || !unique(sources.map(s => s.binding_id)) || !unique(sources.map(s => s.source_revision_id))
      || sources.filter(s => s.source_type === 'code').length !== code.length) return 'source_members_incomplete'
  if (!Array.isArray(scope?.binding_ids) || !Number.isSafeInteger(scope.acl_epoch) || scope.acl_epoch < 0
      || !sources.every(s => scope.binding_ids.includes(s.binding_id))) return 'source_access_incomplete'
  const ordered = [...sources].sort((a, b) => a.binding_id < b.binding_id ? -1 : 1)
  if (digest(ordered) !== pins.manifest_hash) return 'source_members_hash_mismatch'

  if (!Array.isArray(revisions)) return 'code_revision_evidence_missing'
  for (const { binding_id, commit_sha } of code) {
    const frozen = sources.find(s => s.source_type === 'code' && s.binding_id === binding_id)
    if (!frozen) return 'code_source_binding_changed'
    const matches = revisions.filter(r => r?.source_revision_id === frozen.source_revision_id)
    if (matches.length !== 1 || matches[0].project_id !== pins.project_id
        || matches[0].binding_id !== binding_id || matches[0].external_revision !== commit_sha)
      return 'code_source_revision_mismatch'
  }
  return null
}

function checkApproval(pins, preview, command, nowMs) {
  const { review, target, preview_digest } = preview
  if (!review) return 'independent_approval_missing'
  if (review.actor_id !== pins.reviewer_id) return 'approval_not_by_independent_reviewer'
  if (review.decision !== 'approve') return 'approval_not_approved'
  if (!id(review.review_id) || review.project_id !== target.project_id || review.baseline_id !== target.target_baseline_id
      || review.image_revision_id !== target.image_revision_id || review.image_artifact_hash !== target.image_artifact_hash
      || review.manifest_id !== pins.manifest_id || review.manifest_hash !== pins.manifest_hash
      || review.policy_revision !== policy || review.preview_digest !== preview_digest || !knowledgeOnly(review)
      || review.claim_digest !== digest({ target, preview_digest })) return 'approval_pins_changed'
  const input = command?.input_payload
  const result = command?.result
  if (!id(command?.id) || review.invocation_id !== command.id || command.tool_id !== reviewTool
      || command.status !== 'completed' || result?.status !== 'completed' || result.invocation_id !== command.id
      || input?.confirmed_by_user !== true || input.confirmed_actor_id !== review.actor_id || input.decision !== 'approve'
      || (review.previous_review_id !== null && !id(review.previous_review_id))
      || input.expected_review_id !== review.previous_review_id
      || !Object.entries(target).every(([k, v]) => input[k] === v) || input.expected_preview_digest !== preview_digest
      || !Array.isArray(result.object_refs) || result.object_refs.length !== 2
      || !result.object_refs.includes('publication_review:' + review.review_id)
      || !result.object_refs.includes('approval:' + review.review_id)) return 'confirmed_review_command_mismatch'
  // The product emits UTC ISO timestamps (up to six fractional digits). Do not
  // silently drop sub-millisecond precision when checking for a future review.
  const stamp = typeof review.recorded_at === 'string'
    && /^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,6}))?(?:Z|\+00:00)$/.exec(review.recorded_at)
  const seconds = stamp ? Date.parse(stamp[1] + 'Z') : NaN
  if (!Number.isSafeInteger(nowMs) || !Number.isFinite(seconds)
      || new Date(seconds).toISOString().slice(0, 19) !== stamp[1]) return 'approval_clock_invalid'
  const ageUs = (nowMs - seconds) * 1000 - Number((stamp[2] || '').padEnd(6, '0'))
  return ageUs < 0 ? 'approval_in_future' : ageUs > 1800_000_000 ? 'approval_expired' : null
}

/**
 * Pass JSON projections from authorized product reads, never auth/session state.
 * session: public acceptance.json binding; conversation: operator's Build id,
 * project_id, space_type, initiator_id only (do not share the private chat).
 * pins: acceptance_id, project_id, operator_id, reviewer_id, image_revision_id,
 * image_artifact_hash, target_baseline_id, manifest_id/hash and code_sources
 * [{binding_id, commit_sha}] independently fixed at intake/build selection,
 * NOT derived from the preview being checked.
 * actor: /v1/auth/me id of the reader of preview; members: current project
 * /members rows (user id/status and project binding only). Registered test
 * accounts are ordinary principals; this helper requires explicit membership.
 * manifest: /system-image?view=working source_manifest; revisions: items from
 * /system-image/code-source-revisions (follow next_after_id); preview: unmodified
 * /system-image/publications/preview with the exact pins and empty initial head.
 * For publish, supply the original completed review invocation as command, a
 * fresh operator preview and nowMs (UTC epoch ms). Never synthesize receipts.
 * Optional productError: {status, code} on failed reads or terminal tool failure.
 *
 * Integration (paths below are under /v1/projects/{project_id}):
 * - Actual admin: /member-candidates?q=... then PUT /members/{user_id}
 *   {role:"project_admin"} for the authorized active test principal; re-read
 *   /members. A candidate search hit is not a grant or a delegation.
 * - Pin the original build's candidate via /system-image/revisions/{id}
 *   (section=source_members); inspect its frozen object/evidence pages. Hash
 *   agreement only identifies the evidence; it does not review its meaning.
 * - Reviewer's own project UI/session: check action=review, inspect the preview,
 *   choose approve/reject and a reason, then confirm the original invocation.
 *   Portal uses POST /v1/tool-invocations then POST /v1/tool-invocations/{id}/confirm.
 * - For action=publish refresh authorized reads as the operator; use the original
 *   confirmed command. On a handoff, use only the pinned baseline.promote UI.
 *   A caller verifying completion must re-read /system-image/publications
 *   for the same baseline and match the published head/pins/approval/actor.
 * No handoff is consent, proof of a distinct human, or a successful publication.
 */
export function preflightRetainedReview(evidence = {}) {
  const { action, session, pins, conversation, actor, members, manifest, revisions, preview,
    command, nowMs, productError } = evidence ?? {}
  if (action === 'delegate') return blocked('delegated_confirmation_not_supported')
  if (action !== 'review' && action !== 'publish') return blocked('unknown_action')
  if (productError !== undefined) {
    const known = ['project_access_denied', 'project_admin_required', 'authorization_denied', 'tool_confirmation_access_denied', 'source_access_denied',
      'source_access_changed', 'publication_inputs_changed', 'publication_integrity_failed', 'publication_verification_failed']
    return blocked(known.includes(productError?.code) ? productError.code
      : ({ 401: 'authentication_required', 403: 'product_access_denied', 404: 'product_record_unavailable',
        409: 'product_inputs_changed' })[Number(productError?.status)] ?? 'product_request_failed')
  }
  if (session?.schema !== 'nasus.realworld-retained-session.v1' || !id(session.acceptance_id)
      || !id(session.project_id) || !id(session.conversation_id) || pins?.acceptance_id !== session.acceptance_id
      || pins.project_id !== session.project_id) return blocked('retained_project_mismatch')
  if (!id(pins.operator_id) || !id(pins.reviewer_id) || pins.operator_id === pins.reviewer_id)
    return blocked('independent_reviewer_required')
  if (conversation?.id !== session.conversation_id || conversation.project_id !== pins.project_id
      || conversation.space_type !== 'build' || conversation.initiator_id !== pins.operator_id)
    return blocked('build_operator_mismatch')
  if (actor?.id !== (action === 'review' ? pins.reviewer_id : pins.operator_id))
    return blocked('wrong_authenticated_actor')
  if (!projectAdmin(members, pins.project_id, pins.operator_id)) return blocked('operator_project_admin_required')
  if (!projectAdmin(members, pins.project_id, pins.reviewer_id)) return blocked('reviewer_project_admin_required')

  const image = preview?.image
  if (!image) return blocked('candidate_preview_missing')
  if (preview.can_review !== true) return blocked('product_review_not_permitted')
  const { project_id, image_revision_id, image_artifact_hash, target_baseline_id } = pins
  const target = { project_id, image_revision_id, image_artifact_hash, target_baseline_id,
    expected_head_id: null, policy_revision: policy }
  if (!id(image_revision_id) || !id(target_baseline_id) || !hash(image_artifact_hash)
      || image.project_id !== project_id || image.image_revision_id !== image_revision_id || image.artifact_hash !== image_artifact_hash
      || image.baseline_id !== target_baseline_id || image.status !== 'candidate'
      || !Number.isSafeInteger(image.code_member_count) || image.code_member_count < 1) return blocked('candidate_pin_mismatch')
  if (preview.baseline?.project_id !== project_id || preview.baseline.baseline_id !== target_baseline_id
      || preview.baseline.kind !== 'official' || preview.baseline.source_version_id !== null) return blocked('official_baseline_mismatch')
  if (preview.head !== null || preview.target?.expected_head_id !== null) return blocked('initial_publication_head_required')
  if (digest(preview.target) !== digest(target) || preview.readiness?.scope !== 'knowledge_snapshot_only'
      || !knowledgeOnly(preview.readiness)) return blocked('publication_target_mismatch')
  const failure = checkSources(session, pins, manifest, preview, revisions)
  if (failure) return blocked(failure)
  const { preview_digest, review, can_review, ...facts } = preview
  if (digest(facts) !== preview_digest) return blocked('preview_digest_mismatch')

  const pin = { ...target, expected_preview_digest: preview_digest }
  if (action === 'review') {
    if (review !== null) return blocked('existing_or_unknown_review_requires_inspection')
    // Deliberately omit decision, reason and confirmation: these are the reviewer's.
    return { status: 'awaiting_reviewer_decision', tool_id: reviewTool, pins: { ...pin, expected_review_id: null } }
  }
  const approvalFailure = checkApproval(pins, preview, command, nowMs)
  return approvalFailure ? blocked(approvalFailure) : { status: 'awaiting_operator_publication',
    tool_id: 'baseline.promote', pins: { ...pin, approval_id: review.review_id } }
}

if (import.meta.main) {
  console.log(JSON.stringify(blocked('offline_module_requires_authorized_product_reads')))
  process.exitCode = 2
}
