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
  const context = { exports: {}, URLSearchParams, crypto: webcrypto, TextEncoder, require: (name) => {
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
  const calls = [], signal = new AbortController().signal
  const review = { projectId: 'project', selection: { goalId: 'goal', invocationId: 'investigation-command' },
    goal: { id: 'goal', project_id: 'project', conversation_id: 'conversation', workflow_id: 'workflow',
      status: 'paused', pause_reason: 'build_completion_review', goal_template: 'system_image_build',
      target_refs: [], active_runtime_ms: 1240, active_started_at: null,
      summary: '核对原目标', steps: [{ id: 'investigate', phase: 'acting', status: 'completed',
        tool_invocation_id: 'investigation-command', selected_tool_id: 'system_image.build.investigate' }] },
    investigation: { revision_id: 'investigation', revision_hash: hash, request: { plan_digest: hash } },
    image: { image_revision_id: 'image', artifact_hash: hash, manifest_id: 'manifest', manifest_hash: hash } }
  const pointer = { requestKey: 'original-request', invocationId: 'completion-command' }
  const report = { schema: 'nasus.image-build-completion.v2', project_id: 'project',
    plan_digest: hash, image_revision_id: 'image', image_artifact_hash: hash,
    source_manifest_id: 'manifest', source_manifest_hash: hash,
    investigation_revision_id: 'investigation', investigation_revision_hash: hash,
    state: 'blocked', delivery_kind: 'candidate_only', candidate_ready: false, goal_completed: false,
    publication_authorized: false, execution_authorized: false,
    goal_checkpoint: { goal_id: 'goal', conversation_id: 'conversation', project_id: 'project', workflow_id: 'workflow',
      digest: await canonicalDigest({ schema: 'nasus.agent-resume-checkpoint.v2', goal: review.goal }) },
    blockers: ['code_analysis_partial', 'full_plan_budget_unverified', 'critical_conflicts_unverified', 'gap_ownership_unassigned'],
    gaps: [{ code: 'code_analysis_partial', blocks: 'candidate_delivery', reason: 'Incomplete code analysis',
      required_action: 'Inspect the original evidence', owner_actor_id: null, ownership_status: 'unassigned' }],
    source_scans: [{ source_revision_id: 'source', source_type: 'code', file_count: 4,
      file_bodies_verified: true, verified_file_count: 4, verified_byte_count: 321 }],
    code_analyses: [{ source_revision_id: 'source', analysis_id: 'analysis', report_hash: hash,
      file_count: 4, projection_status: 'partial', build_lineage_verified: true }],
    build_lineages: [{ invocation_id: 'structure', analyses: [{ source_revision_id: 'source', analysis_id: 'analysis',
      native: { generation: { generation_id: 'native-index' } }, unused_native_generations: [] }] }],
    readiness: Object.fromEntries(['structure', 'behavior', 'traceability', 'automation', 'execution'].map((key) =>
      [key, { state: 'unresolved', coverage: null, ...(key === 'structure' ? { verified_evidence_count: 12 } : {}) }])),
    budget: { goal_model_calls_used: 0, goal_thinking_tokens_used: 0, goal_steps_completed: 3,
      goal_active_runtime_ms: 1240, cost_microusd: null, full_plan_accounting_verified: false },
    critical_conflicts: { state: 'unverified', count: null } }
  const v = { review, pointer, report, calls, signal, discovered: null, current: null }
  const api = load('domains/system-image/buildCompletionApi.ts', {
    '../../shared/api/client': { request: async (url, options) => {
      calls.push({ method: 'GET', url, options })
      assert.equal(options.cache, 'no-store'); assert.equal(options.signal, signal)
      if (v.deny === url) throw new Error('403 Source access denied')
      if (url.startsWith('/v1/tool-invocations?')) return clone(v.discovered ?? [v.command])
      if (url === '/v1/projects/project/system-image/build-completions/completion-command') return clone(report)
      if (url === '/v1/agent-goals/goal') return clone(v.current ?? review.goal)
      throw new Error('Unexpected GET ' + url)
    } },
    '../platform/api': { platformApi: {
      invokeTool: async (payload) => {
        calls.push({ method: 'POST', payload })
        if (v.lostAck) throw new Error('Lost response')
        return clone(v.command)
      }, getToolInvocation: async (id, options) => {
        calls.push({ method: 'GET', id, options }); assert.equal(options.signal, signal)
        if (v.denyCommand) throw new Error('403 Command access denied')
        return clone(v.command)
      },
    } },
  })
  v.api = api
  v.input = clone(api.completionInput(review))
  v.command = { id: 'completion-command', conversation_id: 'conversation', tool_id: 'query.system_image.build_completion.read',
    status: 'completed', input_payload: { ...v.input, idempotency_key: pointer.requestKey },
    result: { invocation_id: 'completion-command', status: 'completed', object_refs: ['build_completion:completion-command'],
      build_completion: { kind: 'build_completion', project_id: 'project', investigation_revision_id: 'investigation',
        investigation_revision_hash: hash, request_hash: await canonicalDigest(v.input), report_hash: await canonicalDigest(report) } } }
  v.rehash = async () => { v.command.result.build_completion.report_hash = await canonicalDigest(report) }
  v.read = () => api.buildCompletionApi.read(review, pointer, signal)
  return v
}

test('explicit assessment uses the canonical query and the full settled original goal, not selected reports', async () => {
  const v = await fixture()
  const result = await v.api.buildCompletionApi.prepare(v.review, { ...v.pointer, invocationId: null })
  assert.equal(result.id, 'completion-command')
  assert.equal(v.calls.length, 1)
  assert.deepEqual(clone(v.calls[0].payload), { tool_id: 'query.system_image.build_completion.read', conversation_id: 'conversation',
    idempotency_key: v.pointer.requestKey, input: { ...v.input } })
  assert.deepEqual(v.input.analyses, [])
  assert.equal(v.input.analysis_policy, 'committed_build')
})

test('private GET replays actual lineage and remains blocked without changing the goal or publishing', async () => {
  const v = await fixture(), before = clone(v.review)
  const result = await v.read()
  assert.equal(result.report.state, 'blocked')
  assert.equal(result.report.budget.cost_microusd, null)
  assert.deepEqual(v.review, before)
  assert.ok(v.calls.every((call) => call.method === 'GET'))
  assert.equal(v.calls.length, 3)
})

test('lost POST acknowledgement is recovered by its exact original key using GET only', async () => {
  const v = await fixture(); v.lostAck = true
  await assert.rejects(v.api.buildCompletionApi.prepare(v.review, { ...v.pointer, invocationId: null }), /Lost response/)
  v.pointer.invocationId = null
  const value = await v.read()
  assert.equal(value.command.id, 'completion-command')
  assert.deepEqual(v.calls.map((call) => call.method), ['POST', 'GET', 'GET', 'GET', 'GET'])
  assert.ok(v.calls[1].url.includes('conversation_id=conversation'))
})

for (const kind of ['missing', 'duplicate', 'over-budget', 'unrelated']) {
  test(`${kind} discovery cannot choose the newest command or submit another assessment`, async () => {
    const v = await fixture(); v.pointer.invocationId = null
    v.discovered = kind === 'missing' ? [] : kind === 'duplicate' ? [v.command, v.command]
      : kind === 'over-budget' ? Array(257).fill(v.command) : [{ ...v.command, input_payload: { idempotency_key: 'other' } }]
    await assert.rejects(v.read())
    assert.equal(v.calls.length, 1); assert.equal(v.calls[0].method, 'GET')
  })
}

for (const status of ['pending', 'running', 'failed', 'cancelled']) {
  test(`${status} command is observed without a fabricated report or restart`, async () => {
    const v = await fixture(); v.command.status = status; v.command.result = null
    const result = await v.read()
    assert.equal(result.report, null)
    assert.equal(result.command.status, status)
    assert.deepEqual(v.calls.map((call) => call.method), ['GET', 'GET'])
  })
}

test('the failed optional native attempt is distinguished from consumed native output', async () => {
  const v = await fixture()
  const analysis = v.report.build_lineages[0].analyses[0]
  analysis.native = null; analysis.unused_native_generations = [{ generation_id: 'unused-index' }]
  await v.rehash()
  assert.equal((await v.read()).report.build_lineages[0].analyses[0].native, null)
})

const corruptions = {
  'wrong command': (v) => { v.command.id = 'other' },
  'wrong conversation': (v) => { v.command.conversation_id = 'other' },
  'wrong tool': (v) => { v.command.tool_id = 'system_image.build.structure' },
  'changed request key': (v) => { v.command.input_payload.idempotency_key = 'other' },
  'changed goal snapshot': (v) => { v.command.input_payload.expected_goal.summary = 'Other goal' },
  'caller-selected analysis': (v) => { v.command.input_payload.analyses = [{ analysis_id: 'other' }] },
  'extra publication input': (v) => { v.command.input_payload.publish = true },
  'missing receipt': (v) => { delete v.command.result.build_completion },
  'wrong request hash': (v) => { v.command.result.build_completion.request_hash = hash },
  'wrong result scope': (v) => { v.command.result.invocation_id = 'other' },
  'wrong object receipt': (v) => { v.command.result.object_refs = ['image_revision:other'] },
  'report corruption': (v) => { v.report.source_scans[0].verified_byte_count += 1 },
  'goal changed while reading': (v) => { v.current = { ...clone(v.review.goal), summary: 'Another phase' } },
}
for (const [name, corrupt] of Object.entries(corruptions)) {
  test(`${name} hides the assessment without a write`, async () => {
    const v = await fixture(); corrupt(v)
    await assert.rejects(v.read()); assert.ok(v.calls.every((call) => call.method === 'GET'))
  })
}

const scopeCorruptions = {
  'wrong image': (report) => { report.image_revision_id = 'other' },
  'wrong investigation': (report) => { report.investigation_revision_id = 'other' },
  'wrong manifest': (report) => { report.source_manifest_id = 'other' },
  'wrong checkpoint digest': (report) => { report.goal_checkpoint.digest = hash },
  'wrong plan': (report) => { report.plan_digest = 'sha256:' + 'b'.repeat(64) },
  'fake delivery': (report) => { report.candidate_ready = true },
  'fake goal completion': (report) => { report.goal_completed = true },
  'fake publication': (report) => { report.publication_authorized = true },
  'fake execution': (report) => { report.execution_authorized = true },
  'partial file verification': (report) => { report.source_scans[0].verified_file_count = 1 },
  'fake verified coverage': (report) => { report.readiness.behavior.coverage = 100 },
  'fake zero spend': (report) => { report.budget.cost_microusd = 0 },
  'fake zero conflicts': (report) => { report.critical_conflicts.count = 0 },
  'fake assigned owner': (report) => { report.gaps[0].owner_actor_id = 'other' },
}
for (const [name, corrupt] of Object.entries(scopeCorruptions)) {
  test(`${name} is not accepted even with a recomputed report digest`, async () => {
    const v = await fixture(); corrupt(v.report); await v.rehash()
    await assert.rejects(v.read()); assert.ok(v.calls.every((call) => call.method === 'GET'))
  })
}

test('source revocation and aborted reads cannot return cached protected findings', async () => {
  const v = await fixture()
  await v.read()
  v.deny = '/v1/projects/project/system-image/build-completions/completion-command'
  await assert.rejects(v.read(), /Source access denied/)
  const controller = new AbortController(); controller.abort()
  const before = v.calls.length
  await assert.rejects(v.api.buildCompletionApi.read(v.review, v.pointer, controller.signal), { name: 'AbortError' })
  assert.equal(v.calls.length, before)
})

for (const query of ['build_completion_invocation=command', 'build_completion_request=',
  'build_completion_request=a&build_completion_request=b', 'build_completion_request=a&build_completion_invocation=b&build_completion_invocation=c',
  'build_completion_request=%0Aa']) {
  test(`invalid assessment pointer ${query} is rejected`, async () => {
    const v = await fixture()
    assert.throws(() => v.api.parseCompletionPointer(new URLSearchParams(query)))
  })
}
