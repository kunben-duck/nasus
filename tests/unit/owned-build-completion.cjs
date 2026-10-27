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

async function fixture() {
  const review = { projectId: 'project', selection: { goalId: 'goal', invocationId: 'investigate' },
    investigation: { revision_id: 'investigation', revision_hash: hash },
    goal: { id: 'goal', project_id: 'project', conversation_id: 'conversation', goal_template: 'system_image_build',
      status: 'paused', pause_reason: 'build_completion_review', active_started_at: null, target_refs: [],
      steps: [{ id: 'investigate', phase: 'acting', status: 'completed', tool_invocation_id: 'investigate',
        selected_tool_id: 'system_image.build.investigate' }] } }
  const definition = { code: 'full_plan_budget_unverified', blocks: 'candidate_delivery', reason: 'Unknown full spend',
    required_action: 'Verify all approvals and retries' }
  const report = { schema: 'nasus.image-build-completion.v2', project_id: 'project', delivery_kind: 'candidate_only', state: 'blocked',
    candidate_ready: false, goal_completed: false, execution_authorized: false, publication_authorized: false,
    gaps: [{ ...definition, owner_actor_id: null, ownership_status: 'unassigned' },
      { code: 'gap_ownership_unassigned', blocks: 'candidate_delivery', reason: 'Owners missing', required_action: 'Assign owners',
        owner_actor_id: null, ownership_status: 'unassigned' }],
    blockers: ['full_plan_budget_unverified', 'critical_conflicts_unverified', 'gap_ownership_unassigned'],
    budget: { cost_microusd: null, full_plan_accounting_verified: false }, critical_conflicts: { state: 'unverified', count: null },
    readiness: { structure: { coverage: null } }, source_scans: [], build_lineages: [], goal_checkpoint: { goal_id: 'goal' } }
  const originalHash = await canonicalDigest(report)
  const completion = { command: { id: 'original', result: { build_completion: { report_hash: originalHash } } }, report }
  const gapId = 'gap_' + (await canonicalDigest(definition)).slice(7)
  const assignments = [{ gap_id: gapId, owner_actor_id: 'owner', reason: 'Investigate original spend' }]
  const view = { schema: 'nasus.image-build-gap-ownership.v1', project_id: 'project', completion_invocation_id: 'original',
    completion_report_hash: originalHash, revision_id: 'revision1', revision_hash: null, revision_number: 1, is_current_revision: true,
    gaps: [{ ...definition, gap_id: gapId, owner_actor_id: 'owner', ownership_status: 'confirmed', resolution_status: 'unresolved' }],
    history: [], goal_completed: false, execution_authorized: false, publication_authorized: false }
  const assignmentInput = { project_id: 'project', completion_invocation_id: 'original', completion_report_hash: originalHash,
    expected_goal: review.goal, parent_revision_id: null, parent_revision_hash: null, assignments }
  const revision = { revision_id: 'revision1', revision_hash: null, revision_number: 1, invocation_id: 'assignment1',
    confirmed_by: 'reviewer', created_at: '2026-10-08T00:00:00+00:00', assignments }
  revision.revision_hash = await canonicalDigest({ schema: view.schema, request: assignmentInput, revision_number: 1,
    confirmed_by: revision.confirmed_by, created_at: revision.created_at })
  view.history.push(revision); view.revision_hash = revision.revision_hash
  const v = { review, completion, view, calls: [], pointer: { requestKey: 'owned-request', invocationId: 'owned-command' } }
  const api = load('domains/system-image/ownedBuildCompletionApi.ts', {
    '../../shared/api/client': { request: async (url, options) => {
      v.calls.push({ method: 'GET', url }); assert.equal(options.cache, 'no-store')
      if (v.deny) throw new Error('403 source revoked')
      if (url.endsWith('/gap-ownership')) return clone(v.view)
      if (url.endsWith('/build-completions/owned-command')) return clone(v.ownedReport)
      if (url === '/v1/agent-goals/goal') return clone(v.currentGoal ?? review.goal)
      if (url.startsWith('/v1/tool-invocations?')) return clone(v.commands ?? [v.command])
      throw new Error('Unexpected GET ' + url)
    } },
    '../platform/api': { platformApi: {
      getToolInvocation: async () => { v.calls.push({ method: 'GET', url: '/command' }); return clone(v.command) },
      invokeTool: async (payload) => {
        v.calls.push({ method: 'POST', url: '/prepare', payload })
        if (v.lostAck) throw new Error('Acknowledgement lost after submit')
        return clone(v.command)
      },
    } },
  })
  v.api = api
  v.input = clone(await api.ownedCompletionInput(review, completion, view))
  v.ownedReport = clone(await api.deriveOwnedCompletionReport(completion, view, v.input.ownership_pin))
  v.command = { id: 'owned-command', conversation_id: 'conversation', tool_id: 'query.system_image.build_completion.read', status: 'completed',
    input_payload: { ...v.input, idempotency_key: v.pointer.requestKey }, result: { invocation_id: 'owned-command', status: 'completed',
      object_refs: ['build_completion:owned-command'], build_completion: { kind: 'build_completion', project_id: 'project',
        investigation_revision_id: 'investigation', investigation_revision_hash: hash,
        request_hash: await canonicalDigest(v.input), report_hash: await canonicalDigest(v.ownedReport) } } }
  v.rehash = async () => { v.command.result.build_completion.report_hash = await canonicalDigest(v.ownedReport) }
  v.read = (pointer = v.pointer) => api.ownedBuildCompletionApi.read(review, completion, pointer, new AbortController().signal)
  v.prepare = () => api.ownedBuildCompletionApi.prepare(review, completion, view, { ...v.pointer, invocationId: null })
  return v
}

test('owned completion pins the full original goal and exact confirmed revision, preserving unresolved blockers', async () => {
  const v = await fixture(), original = clone(v.completion)
  const command = await v.prepare()
  assert.equal(command.id, 'owned-command')
  assert.equal(v.calls.filter((call) => call.method === 'POST').length, 1)
  assert.deepEqual(clone(v.calls.at(-1).payload.input), v.input)
  const result = await v.read()
  assert.equal(result.report.ownership.revision_id, 'revision1')
  assert.deepEqual(clone(result.report.blockers), ['full_plan_budget_unverified', 'critical_conflicts_unverified'])
  assert.equal(result.report.gaps[0].resolution_status, 'unresolved')
  assert.deepEqual(v.completion, original)
})

for (const mutate of [
  (v) => v.ownedReport.candidate_ready = true, (v) => v.ownedReport.goal_completed = true,
  (v) => v.ownedReport.execution_authorized = true, (v) => v.ownedReport.publication_authorized = true,
  (v) => v.ownedReport.gaps[0].owner_actor_id = 'other', (v) => v.ownedReport.gaps[0].resolution_status = 'resolved',
  (v) => v.ownedReport.blockers = [], (v) => v.ownedReport.budget.cost_microusd = 0,
  (v) => v.ownedReport.critical_conflicts.count = 0, (v) => v.ownedReport.readiness.structure.coverage = 100,
  (v) => v.ownedReport.ownership.revision_hash = hash, (v) => v.ownedReport.ownership.assignment_count = 0,
  (v) => v.ownedReport.gaps.pop(), (v) => v.ownedReport.extra_authority = true,
]) test(`owned completion rejects fabricated facts even with a recomputed response hash: ${mutate}`, async () => {
  const v = await fixture(); mutate(v); await v.rehash()
  await assert.rejects(v.read())
  assert.ok(v.calls.every((call) => call.method === 'GET'))
})

test('lost acknowledgement is recovered only by the original key, without retrying POST', async () => {
  const v = await fixture(); v.lostAck = true
  await assert.rejects(v.prepare())
  assert.equal(v.calls.filter((call) => call.method === 'POST').length, 1)
  const recovered = await v.read({ ...v.pointer, invocationId: null })
  assert.equal(recovered.command.id, 'owned-command')
  assert.equal(v.calls.filter((call) => call.method === 'POST').length, 1)
  v.commands = [v.command, v.command]
  await assert.rejects(v.read({ ...v.pointer, invocationId: null }))
})

test('source revocation and checkpoint changes cannot reuse a prior report or issue a new query', async () => {
  const v = await fixture(); await v.read(); v.calls.length = 0; v.deny = true
  await assert.rejects(v.read()); assert.ok(v.calls.every((call) => call.method === 'GET'))
  v.deny = false; v.currentGoal = { ...v.review.goal, summary: 'later checkpoint' }
  await assert.rejects(v.read()); await assert.rejects(v.prepare())
  assert.ok(v.calls.every((call) => call.method === 'GET'))
})

test('historical owned report stays pinned to an earlier assignment after reassignment', async () => {
  const v = await fixture()
  const first = v.view.history[0]
  const assignments = first.assignments.map((item) => ({ ...item, owner_actor_id: 'new-owner' }))
  const next = { ...first, revision_id: 'revision2', invocation_id: 'assignment2', revision_number: 2, assignments }
  const input = { project_id: 'project', completion_invocation_id: 'original', completion_report_hash: v.view.completion_report_hash,
    expected_goal: v.review.goal, parent_revision_id: first.revision_id, parent_revision_hash: first.revision_hash, assignments }
  next.revision_hash = await canonicalDigest({ schema: v.view.schema, request: input, revision_number: 2,
    confirmed_by: next.confirmed_by, created_at: next.created_at })
  Object.assign(v.view, { revision_id: next.revision_id, revision_hash: next.revision_hash, revision_number: 2 })
  v.view.history.push(next); v.view.gaps[0].owner_actor_id = 'new-owner'
  const observed = await v.read()
  assert.equal(observed.report.ownership.revision_id, first.revision_id)
  assert.equal(observed.report.gaps[0].owner_actor_id, 'owner')
})

test('an unavailable owner blocks a new query without rewriting the immutable report', async () => {
  const v = await fixture(); v.view.gaps[0].ownership_status = 'owner_unavailable'
  await assert.rejects(v.prepare())
  assert.ok(v.calls.every((call) => call.method === 'GET'))
  assert.equal((await v.read()).report.gaps[0].ownership_status, 'confirmed')
})

test('missing explicit pin is never replaced with the latest revision during replay', async () => {
  const v = await fixture(); delete v.command.input_payload.ownership_pin
  await assert.rejects(v.read()); assert.ok(v.calls.every((call) => call.method === 'GET'))
})

test('owned assessment rejects malformed or repeated URL pointers', () => {
  const api = load('domains/system-image/ownedBuildCompletionApi.ts', { '../../shared/api/client': {}, '../platform/api': {} })
  for (const query of ['build_owned_completion_invocation=id', 'build_owned_completion_request=a&build_owned_completion_request=b',
    'build_owned_completion_request=a&build_owned_completion_invocation=b&build_owned_completion_invocation=c']) {
    assert.throws(() => api.parseOwnedCompletionPointer(new URLSearchParams(query)))
  }
})
