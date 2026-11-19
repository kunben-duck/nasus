const { test, before } = require('node:test')
const assert = require('node:assert/strict')
const { createHash } = require('node:crypto')

let check
before(async () => {
  check = (await import('../../scripts/realworld-retained-review.mjs')).preflightRetainedReview
})

const H = c => 'sha256:' + c.repeat(64)
function digest(record) {
  const keys = new Set()
  JSON.stringify(record, (k, v) => { keys.add(k); return v })
  return 'sha256:' + createHash('sha256').update(JSON.stringify(record, [...keys].sort())).digest('hex')
}

// Entirely synthetic product projections; no account/session files or services.
function fixture(action) {
  const project_id = 'proj_acceptance'
  const session = { schema: 'nasus.realworld-retained-session.v1', acceptance_id: 'test-round',
    project_id, conversation_id: 'conv_build', source_commits: ['a'.repeat(40), 'b'.repeat(40)] }
  const conversation = { id: session.conversation_id, project_id, space_type: 'build', initiator_id: 'operator' }
  const code_sources = ['django', 'vue'].map((binding_id, i) => ({ binding_id, commit_sha: session.source_commits[i] }))
  // Independent Python source_snapshots.snapshot_digest vector, ordered by binding_id.
  const manifest_hash = 'sha256:ce360e712a30d3e4903e97c76c1ddd28b7baafa25b2783b20585b4584353ae85'
  const pins = { acceptance_id: session.acceptance_id, project_id, operator_id: 'operator', reviewer_id: 'reviewer',
    image_revision_id: 'image', image_artifact_hash: H('c'), target_baseline_id: 'official',
    manifest_id: 'manifest', manifest_hash, code_sources }
  const manifest = { project_id, manifest_id: pins.manifest_id, content_hash: manifest_hash }
  const revisions = code_sources.map(s => ({ project_id, binding_id: s.binding_id, source_revision_id: 'rev_' + s.binding_id,
    external_revision: s.commit_sha }))
  const members = ['operator', 'reviewer'].map(id => ({ user: { id, status: 'active' }, binding: { user_id: id,
    project_id, scope_ref: 'project:' + project_id, status: 'active', role: 'project_admin', version_id: null, session_id: null } }))
  const target = { project_id, image_revision_id: 'image', image_artifact_hash: H('c'), target_baseline_id: 'official',
    expected_head_id: null, policy_revision: 'nasus.image-publication.v1' }
  const image = { project_id, image_revision_id: 'image', artifact_hash: H('c'), baseline_id: 'official',
    manifest_id: 'manifest', manifest_hash, code_member_count: 2, status: 'candidate' }
  const source_members = ['vue', 'spec', 'django'].map(b => ({ binding_id: b, source_revision_id: 'rev_' + b,
    source_type: b === 'spec' ? 'us_doc' : 'code', status: 'captured' }))
  const facts = { target, image, baseline: { project_id, baseline_id: 'official', kind: 'official', source_version_id: null },
    head: null, source_members, source_scope: { binding_ids: ['django', 'spec', 'vue'], acl_epoch: 1 },
    readiness: { scope: 'knowledge_snapshot_only', release_authorized: false, quality_generation_authorized: false,
      unverified_observation_count: 0, limitations: ['Knowledge only.'] } }
  const preview_digest = digest(facts)
  const review = { review_id: 'approval', actor_id: 'reviewer', invocation_id: 'invocation', decision: 'approve',
    project_id, baseline_id: 'official', image_revision_id: 'image', image_artifact_hash: H('c'), manifest_id: 'manifest',
    manifest_hash, policy_revision: target.policy_revision, preview_digest, claim_digest: digest({ target, preview_digest }),
    recorded_at: '2026-01-01T01:02:03.123456+00:00', previous_review_id: null,
    quality_generation_authorized: false, release_authorized: false }
  const command = { id: 'invocation', status: 'completed', tool_id: 'system_image.revisions.review_publication',
    input_payload: { ...target, expected_preview_digest: preview_digest, expected_review_id: null,
      confirmed_by_user: true, confirmed_actor_id: 'reviewer', decision: 'approve' },
    result: { invocation_id: 'invocation', status: 'completed', object_refs: ['publication_review:approval', 'approval:approval'] } }
  return { session, pins, conversation, action, members, revisions, manifest,
    actor: { id: action === 'review' ? 'reviewer' : 'operator' },
    preview: { ...facts, can_review: true, preview_digest, review: action === 'review' ? null : review },
    command: action === 'review' ? undefined : command, nowMs: Date.parse('2026-01-01T01:03:00Z') }
}

test('review handoff contains exact target pins, never a decision, reason or confirmation', () => {
  const e = fixture('review')
  e.revisions.unshift({ ...e.revisions[0], source_revision_id: 'historical', external_revision: 'f'.repeat(40) })
  const before = structuredClone(e)
  assert.deepEqual(check(e), { status: 'awaiting_reviewer_decision', tool_id: 'system_image.revisions.review_publication',
    pins: { ...e.preview.target, expected_preview_digest: e.preview.preview_digest, expected_review_id: null } })
  assert.deepEqual(e, before)
})

test('fresh operator preview and original independent receipt give only a manual publication handoff', () => {
  const e = fixture('publish')
  assert.deepEqual(check(e), { status: 'awaiting_operator_publication', tool_id: 'baseline.promote',
    pins: { ...e.preview.target, expected_preview_digest: e.preview.preview_digest, approval_id: 'approval' } })
})

const cases = [
  ['delegate', () => {}, 'delegated_confirmation_not_supported'],
  ['review', e => { e.pins.acceptance_id = 'prior-round' }, 'retained_project_mismatch'],
  ['review', e => { e.session.project_id = 'proj_other' }, 'retained_project_mismatch'],
  ['review', e => { e.conversation.initiator_id = 'reviewer' }, 'build_operator_mismatch'],
  ['review', e => { e.pins.reviewer_id = 'operator' }, 'independent_reviewer_required'],
  ['review', e => { e.actor.id = 'operator' }, 'wrong_authenticated_actor'],
  ['publish', e => { e.actor.id = 'reviewer' }, 'wrong_authenticated_actor'],
  ['review', e => { e.members.pop() }, 'reviewer_project_admin_required'],
  ['review', e => { e.members[1].user.status = 'suspended' }, 'reviewer_project_admin_required'],
  ['review', e => { e.members[1].binding.role = 'qa_lead' }, 'reviewer_project_admin_required'],
  ['review', e => { e.members[1].binding.project_id = 'proj_other' }, 'reviewer_project_admin_required'],
  ['publish', e => { e.members[1].binding.status = 'revoked' }, 'reviewer_project_admin_required'],
  ['publish', e => { e.members[0].binding.version_id = 'other-version' }, 'operator_project_admin_required'],
  ['review', e => { e.preview = null }, 'candidate_preview_missing'],
  ['review', e => { e.preview.can_review = false }, 'product_review_not_permitted'],
  ['publish', e => { e.preview.target.expected_head_id = 'new-head' }, 'initial_publication_head_required'],
  ['review', e => { e.preview.head = { publication_id: 'existing' } }, 'initial_publication_head_required'],
  ['review', e => { e.preview.baseline.kind = 'version_working' }, 'official_baseline_mismatch'],
  ['review', e => { e.preview.image.artifact_hash = H('d') }, 'candidate_pin_mismatch'],
  ['review', e => { e.preview.image.project_id = 'proj_other' }, 'candidate_pin_mismatch'],
  ['review', e => { e.preview.target.rollback_publication_id = 'foreign' }, 'publication_target_mismatch'],
  ['review', e => { e.preview.readiness.release_authorized = true }, 'publication_target_mismatch'],
  ['review', e => { e.session.source_commits.pop() }, 'retained_code_pins_invalid'],
  ['review', e => { e.pins.code_sources[0].commit_sha = e.session.source_commits[1] }, 'retained_code_pins_invalid'],
  ['review', e => { e.manifest.content_hash = H('e') }, 'source_manifest_changed'],
  ['review', e => { e.preview.image.manifest_id = 'another-manifest' }, 'source_manifest_changed'],
  ['review', e => { e.preview.source_members[1].status = 'failed' }, 'source_members_incomplete'],
  ['review', e => { e.preview.source_members.pop() }, 'source_members_incomplete'],
  ['review', e => { e.preview.source_scope.binding_ids.splice(1, 1) }, 'source_access_incomplete'],
  ['review', e => { e.preview.source_members.splice(1, 1) }, 'source_members_hash_mismatch'],
  ['review', e => { e.pins.code_sources[0].binding_id = 'different-repository' }, 'code_source_binding_changed'],
  ['review', e => { e.revisions[0].external_revision = e.session.source_commits[1] }, 'code_source_revision_mismatch'],
  ['review', e => { e.revisions[0].project_id = 'proj_other' }, 'code_source_revision_mismatch'],
  ['review', e => { e.revisions.push(e.revisions[0]) }, 'code_source_revision_mismatch'],
  ['review', e => { e.preview.source_scope.acl_epoch++ }, 'preview_digest_mismatch'],
  ['review', e => { delete e.preview.review }, 'existing_or_unknown_review_requires_inspection'],
  ['publish', e => { e.preview.review = null }, 'independent_approval_missing'],
  ['publish', e => { e.preview.review.actor_id = 'operator' }, 'approval_not_by_independent_reviewer'],
  ['publish', e => { e.preview.review.decision = 'reject' }, 'approval_not_approved'],
  ['publish', e => { e.preview.review.image_artifact_hash = H('d') }, 'approval_pins_changed'],
  ['publish', e => { e.preview.review.claim_digest = H('d') }, 'approval_pins_changed'],
  ['publish', e => { e.preview.review.preview_digest = H('d') }, 'approval_pins_changed'],
  ['publish', e => { e.command.id = 'another-invocation' }, 'confirmed_review_command_mismatch'],
  ['publish', e => { e.command.status = 'waiting_confirmation' }, 'confirmed_review_command_mismatch'],
  ['publish', e => { e.command.input_payload.confirmed_actor_id = 'operator' }, 'confirmed_review_command_mismatch'],
  ['publish', e => { e.command.input_payload.project_id = 'proj_other' }, 'confirmed_review_command_mismatch'],
  ['publish', e => { e.command.input_payload.expected_review_id = 'another-review' }, 'confirmed_review_command_mismatch'],
  ['publish', e => { e.command.result.object_refs[1] = 'approval:other' }, 'confirmed_review_command_mismatch'],
  ['publish', e => { e.preview.review.recorded_at = '2026-02-31T12:00:00Z' }, 'approval_clock_invalid'],
  ['publish', e => { delete e.nowMs }, 'approval_clock_invalid'],
  ['publish', e => { e.nowMs = Date.parse(e.preview.review.recorded_at) }, 'approval_in_future'],
  ['publish', e => { e.nowMs += 31 * 60 * 1000 }, 'approval_expired'],
]
for (const [i, [action, change, reason]] of cases.entries()) {
  test(`fail closed ${i + 1}: ${reason}`, () => {
    const e = fixture(action)
    change(e)
    assert.deepEqual(check(e), { status: 'blocked', reason })
  })
}

test('approval expiry matches the inclusive 1800-second product window', () => {
  const e = fixture('publish')
  e.preview.review.recorded_at = '2026-01-01T01:02:03.123000+00:00'
  e.nowMs = Date.parse(e.preview.review.recorded_at) + 1800_000
  assert.equal(check(e).status, 'awaiting_operator_publication')
  assert.equal(check({ ...e, nowMs: e.nowMs + 1 }).reason, 'approval_expired')
})

test('a newly hashed preview with changed access cannot reuse the old approval', () => {
  const e = fixture('publish')
  const { can_review, preview_digest, review, ...facts } = e.preview
  facts.source_scope.acl_epoch++
  e.preview = { ...facts, can_review, review, preview_digest: digest(facts) }
  assert.notEqual(e.preview.preview_digest, preview_digest)
  assert.deepEqual(check(e), { status: 'blocked', reason: 'approval_pins_changed' })
})

test('product failures take precedence over snapshots; do not echo free-text errors', () => {
  const e = fixture('publish')
  for (const [productError, reason] of [
    [{ status: 403 }, 'product_access_denied'], [{ code: 'publication_inputs_changed' }, 'publication_inputs_changed'],
    [{ status: 502, code: 'private-response-content' }, 'product_request_failed'],
  ]) assert.deepEqual(check({ ...e, productError }), { status: 'blocked', reason })
})
