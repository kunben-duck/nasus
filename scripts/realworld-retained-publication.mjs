// Usage: node scripts/realworld-retained-publication.mjs m3-YYYYMMDD-HHMM [--grant-reviewer]
// Read-only decision handoff; neither review nor publication is submitted here.
import { createHash } from 'node:crypto'
import { constants } from 'node:fs'
import { open, realpath, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { isDeepStrictEqual as equal } from 'node:util'
import { preflightRetainedReview } from './realworld-retained-review.mjs'

const portal = 'http://localhost:5173'
const api = 'http://127.0.0.1:8000/v1/'
const oldRun = 'm3-20261118'
const root = fileURLToPath(new URL('../output/realworld', import.meta.url))
const repos = [
  ['https://github.com/c4ffein/realworld-django-ninja', '87dd078c883a046f5ff20269df2fb004d8b5f83f'],
  ['https://github.com/realworld-apps/vue-realworld-example-app', 'db749e3bb1a45755e0a3f4065abaf7346f004f36'],
]
const id = v => typeof v === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(v)
const hash = v => typeof v === 'string' && /^sha256:[0-9a-f]{64}$/.test(v)
const record = v => v !== null && typeof v === 'object' && !Array.isArray(v)
const email = role => 'nasus-' + oldRun + '-' + role + '@example.test'
class Blocked extends Error {}
function need(ok, reason) { if (!ok) throw new Blocked(reason) }
function one(rows, predicate, reason) {
  const matches = Array.isArray(rows) ? rows.filter(predicate) : []
  need(matches.length === 1, reason)
  return matches[0]
}
function runId(value) {
  need(typeof value === 'string' && /^m3-\d{8}-\d{4}$/.test(value), 'expected_new_acceptance_id')
  return value
}

// The producer's verified files do NOT contain step or acceptance_id fields.
// The fixed filenames, Build URL and original live receipt IDs bind them.
function bindRun(run, { create, sources, capture }) {
  runId(run)
  const p = create?.project_id, c = create?.conversation_id
  need(id(p) && p.startsWith('proj_') && id(c) && c.startsWith('conv_'), 'invalid_create_proof')
  for (const proof of [create, sources, capture]) {
    need(proof?.project_id === p && proof.conversation_id === c && proof.full_m3_verified === false
      && proof.build_url === portal + '/build?session=' + run && proof.project_url === portal + '/projects/' + p + '/knowledge'
      && Array.isArray(proof.receipts), 'verified_run_scope_mismatch')
  }
  const receipt = (proof, tool) => {
    const row = one(proof.receipts, r => r?.tool === tool && r.status === 'completed', 'missing_or_ambiguous_verified_receipt')
    need(id(row.id), 'invalid_verified_receipt')
    return row.id
  }
  const created = receipt(create, 'project.create')
  need([sources, capture].every(s => receipt(s, 'project.create') === created), 'project_creation_receipt_changed')
  return { project_id: p, conversation_id: c, created, registered: receipt(capture, 'system_image.sources.register'),
    ingested: receipt(capture, 'system_image.sources.ingest'), name: 'RealWorld M3 ' + run.slice(3).replace('-', ' ') }
}

async function liveRun(run, scope, chat, operator) {
  const { project_id: p, conversation_id: c } = scope
  need(chat?.project_id === p && chat.id === c && chat.initiator_id === operator.id
    && chat.space_type === 'build' && chat.space_id === 'build-' + run, 'original_build_mismatch')
  const intake = chat.messages?.findLast(m => m.role === 'assistant' && m.metadata?.system_image_intake)?.metadata.system_image_intake
  need(intake?.project_id === p && intake.project_name === scope.name && intake.code === repos[0][0]
    && intake.code_ref === repos[0][1] && intake.additional_code_sources?.length === 1
    && intake.additional_code_sources[0].code === repos[1][0] && intake.additional_code_sources[0].code_ref === repos[1][1],
  'original_source_selection_changed')
  const completed = async (tool, invocationId) => {
    need(id(invocationId), 'invalid_verified_receipt')
    const snapshot = one(chat.tool_invocations, r => r?.id === invocationId, tool === 'system_image.build.structure'
      ? 'original_structural_candidate_unavailable' : 'original_command_unavailable')
    const sameCommand = t => t?.id === invocationId && t.tool_id === tool && t.conversation_id === c && t.status === 'completed'
    need(sameCommand(snapshot), 'original_command_scope_mismatch')
    // Lightweight conversations can omit result. Resolve only a proven original,
    // never search by tool/project or retry a failed/mismatched inline receipt.
    const t = snapshot.result == null ? await operator.get('tool-invocations/' + invocationId) : snapshot
    // The summary projects top-level input fields (sometimes none). A present
    // field, including its entire nested value, remains an exact constraint.
    need(sameCommand(t) && record(t.input_payload) && record(snapshot.input_payload)
      && Object.entries(snapshot.input_payload).every(([k, v]) => Object.hasOwn(t.input_payload, k) && equal(t.input_payload[k], v))
      && t.result?.status === 'completed' && t.result.invocation_id === invocationId,
      'original_command_scope_mismatch')
    return t
  }
  const created = await completed('project.create', scope.created)
  need(created.input_payload?.name === scope.name && equal(created.result.object_refs, ['project:' + p]), 'project_create_mismatch')
  const registered = await completed('system_image.sources.register', scope.registered)
  const ingested = await completed('system_image.sources.ingest', scope.ingested)
  for (const t of [registered, ingested]) need(t.input_payload?.project_id === p && !t.result.requires_followup
    && Array.isArray(t.result.object_refs) && t.result.object_refs.includes('project:' + p), 'capture_incomplete')
  // Build intake ingests all registered sources. A later selective refresh
  // uses the same tool ID but is not the original capture action.
  need(Object.keys(ingested.input_payload).every(k => k === 'project_id' || k === 'idempotency_key'), 'capture_action_changed')
  need(Array.isArray(ingested.result.evidence_refs) && ingested.result.evidence_refs.every(r => typeof r === 'string'),
    'captured_revision_changed')
  const specs = registered.input_payload.source_specs
  need(specs?.length === 4 && repos.every(([url, sha]) => specs.some(s =>
    s.source_type === 'code' && s.source_uri === url && s.tracked_ref === sha))
    && [['us_doc', 'requirements'], ['test_asset', 'tests']].every(([type, key]) =>
      specs.some(s => s.source_type === type && s.source_uri === intake[key]
        && s.source_uri.includes('/source-uploads/' + p + '/' + type + '/'))), 'registered_sources_changed')
  const goal = one(chat.agent_goals, g => g.id === intake.goal_id && g.project_id === p && g.conversation_id === c
    && g.pause_reason === 'structural_candidate_review', 'original_structural_candidate_unavailable')
  const step = one(goal.steps, s => s.selected_tool_id === 'system_image.build.structure' && s.status === 'blocked',
    'original_structural_checkpoint_unavailable')
  need(id(step.tool_invocation_id), 'original_structural_checkpoint_unavailable')
  const build = await completed('system_image.build.structure', step.tool_invocation_id)
  const input = build.input_payload
  const ref = one(build.result.object_refs, r => typeof r === 'string' && r.startsWith('image_revision:'), 'candidate_receipt_missing')
  const imageId = ref.slice('image_revision:'.length)
  need(input?.project_id === p && input.agent_goal_id === goal.id && id(input.plan_id) && hash(input.plan_digest) && id(imageId) && id(input.target_baseline_id)
    && build.result.followup_reason === 'structural_candidate_review' && build.result.object_refs.length === 2
    && build.result.object_refs.includes('build_plan:' + input.plan_id), 'structural_receipt_changed')
  return { input, buildId: build.id, imageId, specs, ingested: ingested.result }
}

async function codeRevisions(get, base) {
  const rows = [], seen = new Set()
  let after = ''
  for (let i = 0; i < 100; i++) {
    const page = await get(base + '/code-source-revisions?' + new URLSearchParams({ limit: '100', after_id: after }))
    need(Array.isArray(page?.items) && page.items.length <= 100, 'invalid_code_revision_page')
    rows.push(...page.items)
    if (page.next_after_id === null) return rows
    after = page.next_after_id
    need(id(after) && !seen.has(after) && page.items.at(-1)?.source_revision_id === after, 'invalid_code_revision_cursor')
    seen.add(after)
  }
  throw new Blocked('code_revision_page_limit')
}

async function originalPins(run, scope, original, operator, reviewer, base) {
  const { input, buildId, imageId, specs, ingested } = original, p = scope.project_id
  const plan = await operator.get(base + '/build-plans/' + input.plan_id)
  const intent = plan?.proposal?.intent, target = intent?.target
  need(plan?.project_id === p && plan.plan_id === input.plan_id && plan.plan_digest === input.plan_digest
    && intent?.project_id === p && target?.project_id === p && target.target_baseline_id === input.target_baseline_id
    && target.target_version_id === null && target.expected_head_id === null && target.expected_head_hash === null
    && plan.structural_artifacts?.some(a => a.invocation_id === buildId && a.image_revision_id === imageId
      && a.target_baseline_id === target.target_baseline_id), 'original_plan_candidate_mismatch')
  const working = await operator.get(base + '?view=working')
  const manifest = working?.source_manifest
  need(working?.project?.id === p && working.project.name === scope.name && working.visibility?.mode === 'project'
    && manifest?.project_id === p && id(manifest.manifest_id) && manifest.manifest_id === intent.source_manifest_id
    && hash(manifest.content_hash) && manifest.content_hash === intent.source_manifest_hash, 'working_manifest_changed')
  const imagePage = await operator.get(base + '/revisions/' + imageId + '?section=source_members&limit=10')
  const image = imagePage?.revision
  need(image?.project_id === p && image.image_revision_id === imageId && image.baseline_id === target.target_baseline_id
    && image.status === 'candidate' && hash(image.artifact_hash) && image.manifest_id === manifest.manifest_id
    && image.manifest_hash === manifest.content_hash && imagePage.section === 'source_members' && imagePage.total === 4
    && imagePage.next_offset === null && imagePage.items?.length === 4 && equal(imagePage.items, intent.sources),
  'frozen_candidate_changed')
  const revisions = await codeRevisions(operator.get, base)
  const code_sources = []
  const capturedRefs = ['project:' + p]
  for (const spec of specs) {
    const raw = one(working.sources, s => s.project_id === p && s.source_type === spec.source_type && s.source_uri === spec.source_uri,
      'registered_source_missing')
    need(id(raw.id) && raw.registered_from_invocation_id === scope.registered && raw.ingestion_status === 'indexed'
      && ingested.object_refs.includes('raw_asset:' + raw.id), 'source_capture_changed')
    capturedRefs.push('raw_asset:' + raw.id)
    const source = one(intent.sources, s => s.source_type === spec.source_type && s.status === 'captured' && id(s.binding_id)
      && id(s.source_revision_id) && raw.evidence_refs?.includes('source-revision:' + s.source_revision_id)
      && ingested.evidence_refs?.includes('source-revision:' + s.source_revision_id), 'captured_revision_changed')
    if (spec.source_type === 'code') {
      const row = one(revisions, r => r.source_revision_id === source.source_revision_id, 'original_code_revision_missing')
      need(row.project_id === p && row.source_id === raw.id && row.binding_id === source.binding_id
        && row.external_revision === spec.tracked_ref && raw.tracked_ref === spec.tracked_ref, 'repository_commit_mismatch')
      code_sources.push({ binding_id: row.binding_id, commit_sha: row.external_revision })
    }
  }
  need(equal([...ingested.object_refs].sort(), capturedRefs.sort()), 'source_capture_changed')
  need(equal(ingested.evidence_refs.filter(r => r.startsWith('source-revision:')).sort(),
    intent.sources.map(s => 'source-revision:' + s.source_revision_id).sort()), 'captured_revision_changed')
  const pins = { acceptance_id: run, project_id: p, operator_id: operator.id, reviewer_id: reviewer.id, code_sources,
    manifest_id: manifest.manifest_id, manifest_hash: manifest.content_hash, target_baseline_id: target.target_baseline_id,
    image_revision_id: imageId, image_artifact_hash: image.artifact_hash }
  return { pins, image, sources: intent.sources }
}

function membership(list, actor, project) {
  need(Array.isArray(list), 'members_unavailable')
  const matches = list.filter(m => m?.binding?.user_id === actor.id || m?.user?.id === actor.id)
  if (!matches.length) return null
  const { binding: b, user } = matches[0]
  need(matches.length === 1 && user?.id === actor.id && user.email === actor.email && user.status === 'active'
    && b?.user_id === actor.id && b.project_id === project && b.scope_ref === 'project:' + project && b.status === 'active'
    && b.session_id === null && b.version_id === null && ['tester', 'viewer', 'qa_lead', 'project_admin'].includes(b.role),
  'ambiguous_or_inactive_project_member')
  return b.role
}

// Only sample original bytes for the handoff. The product preview independently
// verifies *all* archived evidence. Do not print source, URLs from DTOs or emails.
async function sampleEvidence(get, base, preview) {
  const root = base + '/revisions/' + preview.image.image_revision_id
  const missing = new Map(preview.source_members.filter(s => s.source_type === 'code').map(s => [s.source_revision_id, s.binding_id]))
  const samples = []
  for (let offset = 0; offset < 100000 && missing.size;) {
    const page = await get(root + '?section=members&limit=10&offset=' + offset)
    need(page.section === 'members' && equal(page.revision, preview.image) && Array.isArray(page.items)
      && Number.isSafeInteger(page.total) && page.total === preview.image.object_count
      && page.items.length === Math.min(10, page.total - offset), 'frozen_members_changed')
    for (const m of page.items) {
      if (m.kind !== 'code_entity' || !missing.has(m.source_revision_id) || !m.evidence_ids?.length) continue
      const eid = m.evidence_ids[0], binding = missing.get(m.source_revision_id)
      need(id(m.object_id) && id(eid) && hash(m.object_hash), 'invalid_evidence_member')
      const route = root + '/objects/' + m.object_id + '/evidence/' + eid + '?max_lines=20'
      const excerpt = await get(route), e = excerpt?.evidence
      need(excerpt?.integrity === 'verified' && e?.binding_id === binding && e.evidence_id === eid
        && e.source_revision_id === m.source_revision_id && e.locator?.precision === 'exact' && hash(e.file_hash)
        && Number.isSafeInteger(excerpt.start_line) && excerpt.start_line > 0 && excerpt.start_line === e.locator.start_line
        && Number.isSafeInteger(excerpt.end_line) && excerpt.end_line === Math.min(excerpt.start_line + 19, e.locator.end_line)
        && excerpt.end_line >= excerpt.start_line && typeof excerpt.content === 'string' && excerpt.content.length > 0
        && excerpt.excerpt_hash === 'sha256:' + createHash('sha256').update(excerpt.content).digest('hex'), 'evidence_excerpt_mismatch')
      samples.push({ binding_id: binding, source_revision_id: m.source_revision_id, object_id: m.object_id, object_hash: m.object_hash,
        evidence_id: eid, file_hash: e.file_hash, excerpt_hash: excerpt.excerpt_hash, start_line: excerpt.start_line,
        end_line: excerpt.end_line, authenticated_url: api + route })
      missing.delete(m.source_revision_id)
    }
    offset += page.items.length
    need(page.next_offset === (offset < page.total ? offset : null), 'invalid_member_page')
    if (page.next_offset === null) break
  }
  need(!missing.size, 'code_source_evidence_missing')
  return samples
}

// Injected clients are for in-memory tests. The CLI supplies only fixed local
// transports; neither a project ID, arbitrary file nor an origin is a CLI input.
export async function preparePublication({ run, proofs, operator, reviewer, grantReviewer = false, reserveGrant }) {
  const scope = bindRun(run, proofs), p = scope.project_id
  const project = 'projects/' + p, base = project + '/system-image'
  async function identity(client, role) {
    const me = await client.get('auth/me')
    need(id(me?.id) && me.email === email(role) && ['viewer', 'tester', 'qa_lead'].includes(me.role), 'unexpected_' + role + '_identity')
    return { ...client, id: me.id, email: me.email }
  }
  operator = await identity(operator, 'operator')
  reviewer = await identity(reviewer, 'reviewer')
  need(operator.id !== reviewer.id, 'independent_reviewer_required')
  const conversation = await operator.get('conversations/' + scope.conversation_id)
  const original = await liveRun(run, scope, conversation, operator)
  const { pins, image, sources } = await originalPins(run, scope, original, operator, reviewer, base)
  const previewPath = base + '/publications/preview?' + new URLSearchParams({ image_revision_id: pins.image_revision_id,
    image_artifact_hash: pins.image_artifact_hash, target_baseline_id: pins.target_baseline_id })
  const before = await operator.get(previewPath)
  need(before.head === null && (before.review === null || record(before.review)) && before.can_review === true && hash(before.preview_digest)
    && before.target?.project_id === p && before.target.image_revision_id === pins.image_revision_id
    && before.target.image_artifact_hash === pins.image_artifact_hash && before.target.target_baseline_id === pins.target_baseline_id
    && before.target.expected_head_id === null && before.target.policy_revision === 'nasus.image-publication.v1'
    && before.baseline?.project_id === p && before.baseline.baseline_id === pins.target_baseline_id
    && before.baseline.kind === 'official' && before.baseline.source_version_id === null
    && equal(before.image, image) && equal(before.source_members, sources), 'initial_publication_unavailable')

  let members = await operator.get(project + '/members')
  need(membership(members, operator, p) === 'project_admin', 'operator_project_admin_required')
  const role = membership(members, reviewer, p)
  if (role !== 'project_admin') {
    need(before.review === null, 'reviewer_project_admin_required')
    if (role === null) {
      const found = await operator.get(project + '/member-candidates?' + new URLSearchParams({ q: reviewer.email }))
      one(found, m => m?.id === reviewer.id && m.email === reviewer.email, 'registered_reviewer_not_a_grant_candidate')
    }
    need(grantReviewer === true, 'reviewer_requires_explicit_project_grant')
    await reserveGrant({ project_id: p, user_id: reviewer.id, role: 'project_admin' })
    const result = await operator.grant(p, reviewer.id)
    need(membership([result], reviewer, p) === 'project_admin', 'project_grant_unverified')
    members = await operator.get(project + '/members')
    need(membership(members, reviewer, p) === 'project_admin', 'project_grant_unverified')
  }

  const session = { schema: 'nasus.realworld-retained-session.v1', acceptance_id: run, project_id: p,
    conversation_id: scope.conversation_id, source_commits: repos.map(r => r[1]) }
  if (before.review !== null) {
    const review = before.review
    need(review.actor_id === reviewer.id && id(review.invocation_id), 'approval_not_by_independent_reviewer')
    need(review.decision === 'approve', 'approval_not_approved')
    const reviewerView = await reviewer.get(previewPath)
    need(equal(reviewerView, before), 'review_changed_during_receipt_read')
    // The reviewer reads their own original receipt; the operator independently
    // checks the current publication target and access, not the reviewer's chat.
    const command = await reviewer.get('tool-invocations/' + review.invocation_id)
    const manifest = (await operator.get(base + '?view=working')).source_manifest
    const revisions = await codeRevisions(operator.get, base)
    members = await operator.get(project + '/members')
    const preview = await operator.get(previewPath)
    need(equal(preview, before), 'review_changed_during_receipt_read')
    const handoff = preflightRetainedReview({ action: 'publish', session, pins, conversation, actor: operator,
      members, manifest, revisions, preview, command, nowMs: Date.now() })
    need(handoff.status === 'awaiting_operator_publication', handoff.reason)
    return { status: handoff.status, acceptance_id: run, pins: { ...pins, ...handoff.pins },
      review_invocation_id: command.id, knowledge_url: portal + '/' + project + '/knowledge',
      review_recorded: true, published: false, full_m3_verified: false }
  }
  const manifest = (await reviewer.get(base + '?view=working')).source_manifest
  const revisions = await codeRevisions(reviewer.get, base)
  const inspect = async () => {
    const preview = await reviewer.get(previewPath)
    const handoff = preflightRetainedReview({ action: 'review', session, pins, conversation, actor: reviewer,
      members: await reviewer.get(project + '/members'), manifest, revisions, preview })
    need(handoff.status === 'awaiting_reviewer_decision', handoff.reason)
    return { preview, handoff }
  }
  const { preview, handoff } = await inspect()
  const samples = await sampleEvidence(reviewer.get, base, preview)
  need((await inspect()).preview.preview_digest === preview.preview_digest, 'preview_changed_during_evidence_read')
  return { status: 'blocked', reason: 'independent_human_publication_review_required', acceptance_id: run,
    pins: { ...pins, ...handoff.pins }, source_members: preview.source_members.map(s => ({
      binding_id: s.binding_id, source_revision_id: s.source_revision_id, source_type: s.source_type })),
    evidence_samples: samples, knowledge_url: portal + '/' + project + '/knowledge', authenticated_preview_url: api + previewPath,
    review_recorded: false, published: false, full_m3_verified: false }
}

async function privateJson(dir, name) {
  need(await realpath(dir) === dir, 'unsafe_run_directory')
  const f = await open(join(dir, name), constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK)
  try {
    const s = await f.stat()
    need(s.isFile() && !(s.mode & 0o077) && s.uid === process.getuid() && s.nlink === 1 && s.size <= 8_388_608, 'unsafe_run_file')
    return JSON.parse(await f.readFile('utf8'))
  } finally { await f.close() }
}

async function localClient(role) {
  const state = await privateJson(join(root, oldRun), role + '-state.private.json')
  const origin = one(state.origins, o => o.origin === portal, 'existing_login_missing')
  const token = one(origin.localStorage, e => e.name === 'nasus_api_token', 'existing_login_missing').value
  need(typeof token === 'string' && token.length > 0 && !/\s/.test(token), 'existing_login_missing')
  async function request(route, method = 'GET') {
    const response = await fetch(api + route, { method, redirect: 'error', cache: 'no-store', signal: AbortSignal.timeout(120_000),
      headers: { Authorization: 'Bearer ' + token, ...(method === 'PUT' && { 'Content-Type': 'application/json' }) },
      ...(method === 'PUT' && { body: JSON.stringify({ role: 'project_admin' }) }) })
    need(response.status === 200, 'product_' + method.toLowerCase() + '_http_' + response.status)
    return response.json()
  }
  return { get: route => request(route), ...(role === 'operator' && { grant: (p, u) => request('projects/' + p + '/members/' + u, 'PUT') }) }
}

async function main(args) {
  need(args.length === 1 || (args.length === 2 && args[1] === '--grant-reviewer'), 'invalid_arguments')
  const run = runId(args[0]), dir = join(root, run), proofs = {}
  for (const step of ['create', 'sources', 'capture']) {
    try { proofs[step] = await privateJson(dir, step + '.verified.json') }
    catch { throw new Blocked(step + '_verification_file_unavailable') }
  }
  bindRun(run, proofs)
  const reserveGrant = async pins => {
    try { await writeFile(join(dir, 'publication-grant.intent.json'), JSON.stringify(pins), { mode: 0o600, flag: 'wx' }) }
    catch { throw new Blocked('grant_intent_unavailable_reconcile_membership') }
  }
  return preparePublication({ run, proofs, operator: await localClient('operator'), reviewer: await localClient('reviewer'),
    grantReviewer: args[1] === '--grant-reviewer', reserveGrant })
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try { console.log(JSON.stringify(await main(process.argv.slice(2)), null, 2)) }
  catch (e) { console.log(JSON.stringify({ status: 'blocked', reason: e instanceof Blocked ? e.message : 'local_session_or_product_read_failed' })) }
  process.exitCode = 2
}
