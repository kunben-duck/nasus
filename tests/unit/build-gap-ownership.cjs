const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { webcrypto } = require('node:crypto')
const ts = require('../../apps/portal/node_modules/typescript')
const root = path.resolve(__dirname, '../../apps/portal/src')
const clone = (value) => JSON.parse(JSON.stringify(value))
function load(relative, overrides = {}) {
  const file = path.resolve(root, relative)
  const context = { exports: {}, URLSearchParams, crypto: webcrypto, TextEncoder, AbortController, require: (name) => {
    if (Object.hasOwn(overrides, name)) return overrides[name]
    return load(path.relative(root, path.resolve(path.dirname(file), `${name}.ts`)), overrides)
  } }
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, context)
  return context.exports
}
const { canonicalDigest } = load('shared/utils/canonicalDigest.ts')
const hash = 'sha256:' + 'a'.repeat(64)
async function fixture(saved = false) {
  const calls = [], review = { projectId: 'project', goal: { id: 'goal', project_id: 'project', conversation_id: 'conversation' } }
  const definition = { code: 'unknown', blocks: 'candidate', reason: 'No verified budget', required_action: 'Verify all usage' }
  const gapId = 'gap_' + (await canonicalDigest(definition)).slice(7)
  const completion = { command: { id: 'completion', result: { build_completion: { report_hash: hash } } }, report: {
    gaps: [{ ...definition }, { ...definition }, { code: 'gap_ownership_unassigned' }] } }
  const assignments = [{ gap_id: gapId, owner_actor_id: 'owner', reason: 'Review the original usage ledger' }]
  const view = { schema: 'nasus.image-build-gap-ownership.v1', project_id: 'project', completion_invocation_id: 'completion',
    completion_report_hash: hash, revision_id: null, revision_hash: null, revision_number: 0, is_current_revision: true,
    gaps: [{ gap_id: gapId, ...definition, owner_actor_id: null, ownership_status: 'unassigned', resolution_status: 'unresolved' }],
    history: [], goal_completed: false, publication_authorized: false, execution_authorized: false }
  const input = { project_id: 'project', completion_invocation_id: 'completion', completion_report_hash: hash,
    expected_goal: review.goal, parent_revision_id: null, parent_revision_hash: null, assignments }
  const pointer = { requestKey: 'request', invocationId: 'command' }
  const command = { id: 'command', conversation_id: 'conversation', tool_id: 'system_image.build.gaps.assign',
    status: saved ? 'completed' : 'waiting_confirmation', input_payload: { ...input, idempotency_key: 'request' } }
  if (saved) {
    const revision = { revision_id: 'revision', revision_number: 1, invocation_id: 'command', confirmed_by: 'reviewer',
      created_at: '2026-10-08T00:00:00+00:00', assignments }
    revision.revision_hash = await canonicalDigest({ schema: view.schema, request: input, revision_number: 1,
      confirmed_by: revision.confirmed_by, created_at: revision.created_at })
    Object.assign(view, { revision_id: revision.revision_id, revision_hash: revision.revision_hash, revision_number: 1, history: [revision] })
    Object.assign(view.gaps[0], { owner_actor_id: 'owner', ownership_status: 'confirmed' })
    command.result = { build_gap_ownership: { kind: 'build_gap_ownership', project_id: 'project', completion_invocation_id: 'completion',
      completion_report_hash: hash, revision_id: revision.revision_id, revision_hash: revision.revision_hash } }
  }
  const v = { review, completion, pointer, command, input, view, calls, owners: [{ actor_id: 'owner', display_name: 'Owner' }] }
  const api = load('domains/system-image/buildGapOwnershipApi.ts', {
    '../../shared/api/client': { request: async (url, options) => {
      calls.push({ method: 'GET', url }); assert.equal(options.cache, 'no-store')
      if (v.deny) throw new Error('403 revoked')
      if (url.endsWith('/gap-ownership')) return clone(view)
      if (url.endsWith('/gap-owners')) return clone(v.owners)
      if (url === '/v1/agent-goals/goal') return clone(v.currentGoal ?? review.goal)
      if (url.startsWith('/v1/tool-invocations?')) return clone(v.commands ?? [command])
      throw new Error('Unexpected read ' + url)
    } },
    '../platform/api': { platformApi: {
      getToolInvocation: async () => { calls.push({ method: 'GET', url: '/command' }); return clone(command) },
      invokeTool: async () => { calls.push({ method: 'POST', url: '/prepare' }); return clone(command) },
      confirmToolInvocation: async () => {
        calls.push({ method: 'POST', url: '/confirm' })
        if (v.confirmed) { Object.assign(view, clone(v.confirmed.view)); Object.assign(command, clone(v.confirmed.command)) }
        return clone(command)
      },
    } },
  })
  return { ...v, state: v, ...api }
}
for (const saved of [false, true]) test(`verified complete gap history remains unresolved, saved=${saved}`, async () => {
  const v = await fixture(saved)
  assert.deepEqual(JSON.parse(JSON.stringify(await v.validateGapOwnership(v.view, v.review, v.completion))), v.view)
  const command = await v.buildGapOwnershipApi.command(v.review, v.completion, v.pointer, new AbortController().signal)
  assert.equal(command.id, v.command.id)
  assert.ok(v.calls.every((item) => item.method === 'GET'))
})
for (const mutate of [
  (v) => v.view.gaps.pop(), (v) => v.view.gaps[0].required_action = 'Invented',
  (v) => v.view.gaps[0].resolution_status = 'resolved', (v) => v.view.goal_completed = true,
  (v) => v.view.execution_authorized = true, (v) => v.view.publication_authorized = true,
  (v) => v.view.completion_report_hash = 'sha256:' + '0'.repeat(64),
  (v) => v.view.history[0].assignments[0].owner_actor_id = 'other',
  (v) => v.view.history[0].confirmed_by = 'other', (v) => v.view.history[0].created_at = '2026-10-09',
  (v) => v.view.revision_hash = hash, (v) => v.view.gaps[0].owner_actor_id = 'other',
]) test(`gap view rejects altered authority or immutable provenance ${mutate}`, async () => {
  const v = await fixture(true); mutate(v)
  await assert.rejects(v.validateGapOwnership(v.view, v.review, v.completion))
})
test('lost prepare acknowledgement discovers only the original key with GET', async () => {
  const v = await fixture()
  const recovered = await v.buildGapOwnershipApi.command(v.review, v.completion, { ...v.pointer, invocationId: null }, new AbortController().signal)
  assert.equal(recovered.id, 'command'); assert.ok(v.calls.every((item) => item.method === 'GET'))
  v.state.commands = [v.command, v.command]
  await assert.rejects(v.buildGapOwnershipApi.command(v.review, v.completion, { ...v.pointer, invocationId: null }, new AbortController().signal))
})
test('preparation never confirms and incomplete inventories never submit', async () => {
  const v = await fixture()
  const observed = await v.buildGapOwnershipApi.prepare(v.review, v.completion, v.input, { requestKey: 'request', invocationId: null })
  assert.equal(observed.command.id, 'command')
  assert.equal(v.calls.filter((item) => item.url.endsWith('/gap-ownership')).length, 1)
  assert.equal(v.calls.filter((item) => item.url === '/command').length, 0)
  assert.deepEqual(v.calls.filter((item) => item.method === 'POST'), [{ method: 'POST', url: '/prepare' }])
  v.calls.length = 0
  await assert.rejects(v.buildGapOwnershipApi.prepare(v.review, v.completion, { ...v.input, assignments: [] }, { requestKey: 'request', invocationId: null }))
  assert.ok(v.calls.every((item) => item.method === 'GET'))
})
test('the view and command share one fully validated private history per observation', async () => {
  const v = await fixture(true)
  const observed = await v.buildGapOwnershipApi.observe(v.review, v.completion, v.pointer, new AbortController().signal)
  assert.equal(observed.command.id, 'command')
  assert.equal(observed.view.revision_id, 'revision')
  assert.equal(v.calls.filter((item) => item.url.endsWith('/gap-ownership')).length, 1)
  assert.ok(v.calls.every((item) => item.method === 'GET'))
  v.view.history[0].assignments[0].reason = 'Changed'
  await assert.rejects(v.buildGapOwnershipApi.observe(v.review, v.completion, v.pointer, new AbortController().signal))
})
test('successful confirmation verifies the committed receipt with one before and one after history read', async () => {
  const v = await fixture(), saved = await fixture(true)
  v.state.confirmed = { view: saved.view, command: saved.command }
  const observed = await v.buildGapOwnershipApi.confirm(v.review, v.completion, v.pointer)
  assert.equal(observed.command.status, 'completed')
  assert.equal(observed.view.revision_id, 'revision')
  assert.equal(v.calls.filter((item) => item.url.endsWith('/gap-ownership')).length, 2)
  assert.equal(v.calls.filter((item) => item.url === '/command').length, 1)
  assert.deepEqual(v.calls.filter((item) => item.method === 'POST'), [{ method: 'POST', url: '/confirm' }])
})
for (const mutate of [
  (v) => v.command.tool_id = 'different.tool', (v) => v.command.input_payload.idempotency_key = 'different',
  (v) => v.command.input_payload.expected_goal = { id: 'different' },
  (v) => v.command.input_payload.resolve_all = true, (v) => v.command.status = 'invented',
]) test(`an altered prepare acknowledgement is rejected without replaying the POST ${mutate}`, async () => {
  const v = await fixture(); mutate(v)
  await assert.rejects(v.buildGapOwnershipApi.prepare(v.review, v.completion, v.input, { requestKey: 'request', invocationId: null }))
  assert.deepEqual(v.calls.filter((item) => item.method === 'POST'), [{ method: 'POST', url: '/prepare' }])
})
test('each new observation rereads authorization instead of treating the previous view as a grant', async () => {
  const v = await fixture(true)
  await v.buildGapOwnershipApi.observe(v.review, v.completion, v.pointer, new AbortController().signal)
  v.state.deny = true
  await assert.rejects(v.buildGapOwnershipApi.observe(v.review, v.completion, v.pointer, new AbortController().signal))
  assert.equal(v.calls.filter((item) => item.url.endsWith('/gap-ownership')).length, 2)
  assert.ok(v.calls.every((item) => item.method === 'GET'))
})
test('confirmation rechecks the exact goal before any POST', async () => {
  const v = await fixture(); v.state.currentGoal = { ...v.review.goal, summary: 'changed' }
  await assert.rejects(v.buildGapOwnershipApi.confirm(v.review, v.completion, v.pointer))
  assert.ok(v.calls.every((item) => item.method === 'GET'))
})
test('revocation hides history and prevents confirmation', async () => {
  const v = await fixture(); v.state.deny = true
  await assert.rejects(v.buildGapOwnershipApi.read(v.review, v.completion, new AbortController().signal))
  await assert.rejects(v.buildGapOwnershipApi.confirm(v.review, v.completion, v.pointer))
  assert.ok(v.calls.every((item) => item.method === 'GET'))
})
for (const query of ['build_gap_assignment_invocation=orphan', 'build_gap_assignment_request=a&build_gap_assignment_request=b',
  'build_gap_assignment_request=a&build_gap_assignment_invocation=']) test(`invalid pointers reject ${query}`, async () => {
  const v = await fixture(); assert.throws(() => v.parseGapAssignmentPointer(new URLSearchParams(query)))
})
