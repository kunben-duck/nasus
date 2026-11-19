const { before, test } = require('node:test')
const assert = require('node:assert/strict')
const { createHash } = require('node:crypto')

let prepare
before(async () => { prepare = (await import('../../scripts/realworld-retained-publication.mjs')).preparePublication })
const textHash = s => 'sha256:' + createHash('sha256').update(s).digest('hex')
function digest(obj) {
  const keys = new Set()
  JSON.stringify(obj, (k, v) => { keys.add(k); return v })
  return textHash(JSON.stringify(obj, [...keys].sort()))
}

// No actual API, old sessions, credentials or run directory. Every route is
// enumerated so falling back to a list, another actor or a write fails the test.
function scenario() {
  const run = 'm3-20000101-0000', p = 'proj_new', c = 'conv_new', name = 'RealWorld M3 20000101 0000'
  const portal = 'http://localhost:5173', project = 'projects/' + p, base = project + '/system-image'
  const receipts = [
    ['create', 'project.create'], ['register', 'system_image.sources.register'], ['ingest', 'system_image.sources.ingest'],
    ['build', 'system_image.build.structure'],
  ].map(([id, tool]) => ({ id, tool, status: 'completed' }))
  const report = { project_id: p, conversation_id: c, build_url: portal + '/build?session=' + run,
    project_url: portal + '/' + project + '/knowledge', full_m3_verified: false }
  const proofs = Object.fromEntries(['create', 'sources', 'capture'].map(step => [step,
    { ...report, receipts: receipts.slice(0, step === 'capture' ? 3 : 1) }]))
  const specs = [
    { source_type: 'code', source_uri: 'https://github.com/c4ffein/realworld-django-ninja', tracked_ref: '87dd078c883a046f5ff20269df2fb004d8b5f83f' },
    { source_type: 'code', source_uri: 'https://github.com/realworld-apps/vue-realworld-example-app', tracked_ref: 'db749e3bb1a45755e0a3f4065abaf7346f004f36' },
    ...['us_doc', 'test_asset'].map(type => ({ source_type: type, source_uri: 'fixture://local/source-uploads/' + p + '/' + type + '/file' })),
  ]
  const sources = specs.map((s, i) => ({ source_type: s.source_type, status: 'captured', binding_id: 'b' + i, source_revision_id: 'r' + i }))
  const raw = specs.map((s, i) => ({ ...s, id: 's' + i, project_id: p, registered_from_invocation_id: 'register',
    ingestion_status: 'indexed', evidence_refs: ['source-revision:r' + i] }))
  const target = { project_id: p, target_baseline_id: 'official', target_version_id: null, expected_head_id: null, expected_head_hash: null }
  const intent = { project_id: p, target, sources, source_manifest_id: 'manifest', source_manifest_hash: digest(sources) }
  const plan = { project_id: p, plan_id: 'plan', plan_digest: textHash('plan'), proposal: { intent },
    structural_artifacts: [{ invocation_id: 'build', image_revision_id: 'image', target_baseline_id: 'official' }] }
  const image = { project_id: p, image_revision_id: 'image', baseline_id: 'official', status: 'candidate',
    code_member_count: 2, object_count: 2, artifact_hash: textHash('image'), manifest_id: 'manifest', manifest_hash: digest(sources) }
  const reviewTarget = { project_id: p, image_revision_id: 'image', image_artifact_hash: image.artifact_hash,
    target_baseline_id: 'official', expected_head_id: null, policy_revision: 'nasus.image-publication.v1' }
  const facts = { target: reviewTarget, source_members: sources, image,
    baseline: { project_id: p, baseline_id: 'official', kind: 'official', source_version_id: null }, head: null,
    source_scope: { acl_epoch: 2, binding_ids: sources.map(s => s.binding_id) },
    readiness: { scope: 'knowledge_snapshot_only', quality_generation_authorized: false, release_authorized: false } }
  const preview = { ...facts, review: null, can_review: true, preview_digest: digest(facts) }
  const payloads = [{ name }, { project_id: p, source_specs: specs },
    { project_id: p, idempotency_key: 'intake:test:1:system_image.sources.ingest' },
    { project_id: p, target_baseline_id: 'official', plan_id: 'plan', plan_digest: plan.plan_digest, agent_goal_id: 'goal' }]
  const commands = receipts.map((r, i) => ({ id: r.id, tool_id: r.tool, status: 'completed', conversation_id: c, input_payload: payloads[i],
    result: { invocation_id: r.id, status: 'completed', object_refs: ['project:' + p] } }))
  commands[2].result.object_refs.push(...raw.map(s => 'raw_asset:' + s.id))
  commands[2].result.evidence_refs = raw.flatMap(s => s.evidence_refs)
  commands[2].result.evidence_refs.push('source-inventory:original')
  Object.assign(commands[3].result, { object_refs: ['build_plan:plan', 'image_revision:image'], followup_reason: 'structural_candidate_review' })
  const chat = { id: c, project_id: p, initiator_id: 'operator', space_type: 'build', space_id: 'build-' + run,
    tool_invocations: structuredClone(commands),
    agent_goals: [{ id: 'goal', project_id: p, conversation_id: c, pause_reason: 'structural_candidate_review',
      steps: [{ selected_tool_id: receipts[3].tool, status: 'blocked', tool_invocation_id: 'build' }] }],
    messages: [{ role: 'assistant', metadata: { system_image_intake: { project_id: p, project_name: name, goal_id: 'goal',
      code: specs[0].source_uri, code_ref: specs[0].tracked_ref, additional_code_sources: [{ code: specs[1].source_uri, code_ref: specs[1].tracked_ref }],
      requirements: specs[2].source_uri, tests: specs[3].source_uri } } }] }
  Object.assign(chat.tool_invocations[2], { input_payload: {}, result: null })
  const who = role => ({ id: role, email: 'nasus-m3-20261118-' + role + '@example.test', role: 'tester' })
  const member = role => ({ user: { ...who(role), status: 'active' }, binding: { project_id: p, scope_ref: 'project:' + p,
    status: 'active', role: 'project_admin', user_id: role, version_id: null, session_id: null } })
  const members = [member('operator'), member('reviewer')]
  const working = { project: { id: p, name }, visibility: { mode: 'project' }, sources: raw,
    source_manifest: { project_id: p, manifest_id: 'manifest', content_hash: digest(sources) } }
  const revisions = { items: specs.slice(0, 2).map((s, i) => ({ project_id: p, binding_id: 'b' + i,
    source_id: 's' + i, source_revision_id: 'r' + i, external_revision: s.tracked_ref })), next_after_id: null }
  const paths = [], writes = [], overrides = new Map()
  const client = role => ({
    get: async route => {
      paths.push([role, route])
      if (overrides.has(role + ':' + route)) return overrides.get(role + ':' + route)()
      const read = (expected, response, only) => route === expected && (!only || only === role) ? response : undefined
      const fixed = read('auth/me', who(role)) ?? read('conversations/' + c, chat, 'operator')
        ?? read(base + '/build-plans/plan', plan, 'operator') ?? read(project + '/members', members)
        ?? read(base + '?view=working', working) ?? read(base + '/code-source-revisions?limit=100&after_id=', revisions)
        ?? read(base + '/revisions/image?section=source_members&limit=10', { revision: image, section: 'source_members',
          total: 4, next_offset: null, items: sources }, 'operator')
      if (fixed) return structuredClone(fixed)
      if (role === 'operator' && route.startsWith('tool-invocations/')) {
        const command = commands.find(t => route === 'tool-invocations/' + t.id)
        assert.ok(command, 'only original ID can be resolved')
        return structuredClone(command)
      }
      if (role === 'operator' && route === project + '/member-candidates?q=nasus-m3-20261118-reviewer%40example.test') return [who('reviewer')]
      if (route === base + '/publications/preview?image_revision_id=image&image_artifact_hash='
          + encodeURIComponent(image.artifact_hash) + '&target_baseline_id=official') return structuredClone(preview)
      if (role === 'reviewer' && route === base + '/revisions/image?section=members&limit=10&offset=0')
        return { section: 'members', revision: image, total: 2, next_offset: null, items: [0, 1].map(i => ({
          object_id: 'o' + i, object_hash: textHash('o' + i), kind: 'code_entity', source_revision_id: 'r' + i, evidence_ids: ['e' + i] })) }
      for (const i of [0, 1]) if (role === 'reviewer' && route === base + '/revisions/image/objects/o' + i + '/evidence/e' + i + '?max_lines=20')
        return { integrity: 'verified', content: 'do-not-log-source', excerpt_hash: textHash('do-not-log-source'), start_line: 1, end_line: 2,
          evidence: { evidence_id: 'e' + i, source_revision_id: 'r' + i, binding_id: 'b' + i, file_hash: textHash('file'),
            locator: { precision: 'exact', start_line: 1, end_line: 2 } } }
      assert.fail('unexpected route: ' + role + ' ' + route)
    },
  })
  const operator = client('operator')
  operator.grant = async (projectId, userId) => {
    assert.deepEqual([projectId, userId], [p, 'reviewer'])
    writes.push('grant')
    members.push(member('reviewer'))
    return members.at(-1)
  }
  return { args: { run, proofs, operator, reviewer: client('reviewer'), reserveGrant: async () => { writes.push('intent') } },
    paths, writes, members, chat, commands, overrides, preview, revisions }
}

test('completed ingest snapshot with input_payload={} and result=null resolves the original full receipt', async () => {
  const s = scenario()
  assert.deepEqual(s.chat.tool_invocations[2], { id: 'ingest', tool_id: 'system_image.sources.ingest',
    conversation_id: 'conv_new', status: 'completed', input_payload: {}, result: null })
  assert.deepEqual(s.commands[2].input_payload, { project_id: 'proj_new', idempotency_key: 'intake:test:1:system_image.sources.ingest' })
  const result = await prepare(s.args)
  assert.deepEqual(s.paths.filter(([, path]) => path.startsWith('tool-invocations')), [['operator', 'tool-invocations/ingest']])
  assert.equal(result.reason, 'independent_human_publication_review_required')
  assert.equal(result.review_recorded, false)
  assert.equal(result.published, false)
  assert.equal(result.pins.expected_preview_digest, s.preview.preview_digest)
  assert.equal(result.evidence_samples.length, 2)
  assert.doesNotMatch(JSON.stringify(result), /do-not-log|example\.test/)
  assert.deepEqual(s.writes, [])
})

test('complete inline receipts are not re-fetched; null receipts on each original resolve by ID', async () => {
  const s = scenario()
  s.chat.tool_invocations = structuredClone(s.commands)
  await prepare(s.args)
  assert.equal(s.paths.some(([, path]) => path.startsWith('tool-invocations')), false)
  s.chat.tool_invocations.forEach(t => { t.result = null })
  await prepare(s.args)
  assert.deepEqual(s.paths.filter(([, path]) => path.startsWith('tool-invocations')),
    s.commands.map(t => ['operator', 'tool-invocations/' + t.id]))
})

for (const [key, mutate] of Object.entries({
  'wrong ID': t => { t.id = 'other' }, 'wrong tool': t => { t.tool_id = 'project.create' },
  'wrong conversation': t => { t.conversation_id = 'conv_other' }, 'not completed': t => { t.status = 'running' },
  'missing receipt': t => { delete t.result },
  'wrong receipt ID': t => { t.result.invocation_id = 'other' }, 'failed receipt': t => { t.result.status = 'failed' },
})) test('canonical read must not substitute an original: ' + key, async () => {
  const s = scenario()
  s.overrides.set('operator:tool-invocations/ingest', () => {
    const t = structuredClone(s.commands[2]); mutate(t); return t
  })
  await assert.rejects(prepare(s.args), /original_command_scope_mismatch/)
  assert.deepEqual(s.paths.at(-1), ['operator', 'tool-invocations/ingest'])
  assert.deepEqual(s.writes, [])
})

test('a partially projected input must match every present field; unprojected keys may be filled in', async () => {
  const s = scenario()
  s.chat.tool_invocations[2].input_payload = { idempotency_key: s.commands[2].input_payload.idempotency_key }
  assert.equal((await prepare(s.args)).reason, 'independent_human_publication_review_required')
  for (const known of [{ project_id: 'proj_other' }, { idempotency_key: 'other-request' },
    { source_ids: [] }, { expected_head_id: null }]) {
    s.chat.tool_invocations[2].input_payload = known
    await assert.rejects(prepare(s.args), /original_command_scope_mismatch/)
  }
  assert.deepEqual(s.writes, [])
})

test('an empty summary cannot excuse a different canonical project, capture action or source receipts', async () => {
  for (const [mutate, reason] of [
    [t => { t.input_payload.project_id = 'proj_other' }, /capture_incomplete/],
    [t => { delete t.input_payload.project_id }, /capture_incomplete/],
    [t => { t.input_payload.source_ids = ['s0'] }, /capture_action_changed/],
    [t => { t.result.object_refs[0] = 'project:proj_other' }, /capture_incomplete/],
    [t => { t.result.object_refs.pop() }, /source_capture_changed/],
    [t => { t.result.object_refs.push('project:proj_other') }, /source_capture_changed/],
    [t => { t.result.object_refs.push('raw_asset:other') }, /source_capture_changed/],
    [t => { t.result.evidence_refs.push('source-revision:other') }, /captured_revision_changed/],
    [t => { t.result.evidence_refs[0] = 'source-revision:other' }, /captured_revision_changed/],
  ]) {
    const s = scenario()
    mutate(s.commands[2])
    await assert.rejects(prepare({ ...s.args, grantReviewer: true }), reason)
    assert.deepEqual(s.writes, [])
  }
})

test('denied lookup is terminal, with no reviewer retry, search or dispatch', async () => {
  const s = scenario()
  s.overrides.set('operator:tool-invocations/ingest', () => { throw Error('product_get_http_403') })
  await assert.rejects(prepare(s.args), /product_get_http_403/)
  assert.deepEqual(s.paths.at(-1), ['operator', 'tool-invocations/ingest'])
  assert.deepEqual(s.writes, [])
})

for (const [name, mutate] of [
  ['foreign snapshot', t => { t.conversation_id = 'conv_other' }],
  ['malformed inline receipt', t => { t.result = {} }],
  ['inline failure', t => { t.result = { invocation_id: 'ingest', status: 'failed' } }],
  ['not completed', t => { t.status = 'failed' }],
]) test('no repair read for ' + name, async () => {
  const s = scenario()
  mutate(s.chat.tool_invocations[2])
  await assert.rejects(prepare(s.args), /original_command_scope_mismatch/)
  assert.equal(s.paths.some(([, path]) => path.startsWith('tool-invocations')), false)
})

test('verified files cannot select a different round or project; no transport access', async () => {
  for (const change of [s => { s.args.run = 'proj_other' }, s => { s.args.proofs.sources.project_id = 'proj_other' },
    s => { delete s.args.proofs.capture }]) {
    const s = scenario(); change(s)
    await assert.rejects(prepare(s.args))
    assert.deepEqual(s.paths, [])
  }
})

test('a recovered receipt still must contain the project and captured source revision references', async () => {
  const s = scenario()
  s.commands[2].result.evidence_refs.shift()
  await assert.rejects(prepare({ ...s.args, grantReviewer: true }), /captured_revision_changed/)
  assert.deepEqual(s.writes, [])
})

test('grant is opt-in, project-only and not repeated after a verified grant', async () => {
  const s = scenario()
  s.members.pop()
  await assert.rejects(prepare(s.args), /reviewer_requires_explicit_project_grant/)
  assert.deepEqual(s.writes, [])
  s.args.grantReviewer = true
  await prepare(s.args)
  await prepare(s.args)
  assert.deepEqual(s.writes, ['intent', 'grant'])
})

test('stale commits, broken evidence and rescoping the authenticated reviewer cannot produce a handoff', async () => {
  for (const [mutate, code] of [
    [s => { s.revisions.items[0].external_revision = '0'.repeat(40) }, /repository_commit_mismatch/],
    [s => { s.overrides.set('reviewer:projects/proj_new/system-image/revisions/image/objects/o0/evidence/e0?max_lines=20', () => ({})) },
      /evidence_excerpt_mismatch/],
    [s => { s.overrides.set('reviewer:auth/me', () => ({ id: 'operator', email: 'different@example.test' })) }, /unexpected_reviewer_identity/],
  ]) {
    const s = scenario(); mutate(s)
    await assert.rejects(prepare(s.args), code)
    assert.deepEqual(s.writes, [])
  }
})
