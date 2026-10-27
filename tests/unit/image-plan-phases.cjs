const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

const hash = (letter) => 'sha256:' + letter.repeat(64)
const plan = () => ({ project_id: 'project', plan_id: 'root', plan_digest: hash('a'), proposal: { intent: { budget: { max_active_seconds: 1200 } } } })
const checkpoint = () => ({ goal: { id: 'goal', project_id: 'project', conversation_id: 'conversation', status: 'paused',
  pause_reason: 'structural_candidate_review', target_refs: ['build_plan:root'], steps: [{ id: 'root-step' }] },
  phases: [], history: [{ revision_hash: hash('b'), revision: { revision_id: 'revision', project_id: 'project',
    goal_id: 'goal', root_plan_id: 'root', from_plan_id: 'root', from_plan_digest: hash('a'), plan_id: 'revised',
    plan_digest: hash('c'), source_manifest_id: 'manifest', source_manifest_hash: hash('d'), invocation_id: 'revision-command',
    revision_number: 1, parent_revision_id: null, parent_revision_hash: null, execution_authorized: false, publication_authorized: false } }] })
function phased() {
  const value = checkpoint()
  value.phases.push({ phase_hash: hash('e'), phase: { phase_id: 'phase', project_id: 'project', goal_id: 'goal', root_plan_id: 'root',
    revision_id: 'revision', revision_hash: hash('b'), plan_id: 'revised', plan_digest: hash('c'), source_manifest_id: 'manifest',
    source_manifest_hash: hash('d'), phase_number: 1, start_index: 1, parent_phase_id: null, parent_phase_hash: null,
    prefix_hash: hash('f'), policy_version: 'nasus.agent-image-plan-phase.v1' } })
  value.goal.target_refs.push('build_plan_phase:phase')
  value.goal.steps.push({ id: 'build_plan_phase:phase', status: 'completed', tool_input_payload: {
    phase_hash: hash('e'), plan_id: 'revised', source_manifest_id: 'manifest' } }, { id: 'new-step', status: 'pending' })
  return value
}
function fixture({ value = checkpoint(), failure, mutate = () => {} } = {}) {
  const calls = []
  function load(file) {
    const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText
    const context = { exports: {}, URLSearchParams, require: (name) => {
      if (name === '../../shared/api/client') return { request: async (url, options) => {
        calls.push(['read', url, options]); if (failure) throw failure; return structuredClone(value.phases)
      } }
      if (name === '../platform/api') return { platformApi: {
        invokeTool: async (body) => { calls.push(['prepare', body]); return { id: 'pending', tool_id: body.tool_id, status: 'waiting_confirmation' } },
        confirmToolInvocation: async (id) => {
          calls.push(['confirm', id]); if (failure) throw failure
          const command = { id, tool_id: 'system_image.build.plan.activate_revision', status: 'completed', result: {
            invocation_id: id, status: 'completed', object_refs: ['build_plan_phase:phase', 'build_plan:revised', 'agent_goal:goal'] } }
          mutate(command); return command
        },
      } }
      return load(path.resolve(path.dirname(file), name + '.ts'))
    } }
    vm.runInNewContext(code, context)
    return context.exports
  }
  const api = load(path.resolve(__dirname, '../../apps/portal/src/domains/system-image/buildPlanPhaseApi.ts'))
  return { ...api, calls }
}

test('phase history reauthorizes with no-store and does not execute or prepare work', async () => {
  const value = phased(), { buildPlanPhaseApi, calls } = fixture({ value })
  const signal = new AbortController().signal
  const read = await buildPlanPhaseApi.history(plan(), value.goal, value.history, signal)
  assert.equal(read.phases[0].phase.plan_id, 'revised')
  assert.equal(calls.length, 1); assert.equal(calls[0][2].cache, 'no-store'); assert.equal(calls[0][2].signal, signal)
})
test('prepare preserves the displayed goal and revision with its own zero-model budget', async () => {
  const value = checkpoint(), { buildPlanPhaseApi, calls } = fixture()
  await buildPlanPhaseApi.prepare(plan(), value, 600, 'request')
  const body = calls[0][1]
  assert.equal(body.tool_id, 'system_image.build.plan.activate_revision')
  assert.equal(body.input.expected_goal, value.goal)
  assert.equal(body.input.revision_id, 'revision'); assert.equal(body.input.revision_hash, hash('b'))
  assert.equal(body.input.parent_phase_id, null); assert.equal(body.input.parent_phase_hash, null)
  assert.deepEqual(JSON.parse(JSON.stringify(body.input.budget)), { max_tool_calls: 1, max_model_calls: 0, max_active_seconds: 600, max_cost_microusd: 0 })
})
test('a different root digest cannot prepare or read a phase as the displayed plan', async () => {
  const changed = plan()
  changed.plan_digest = hash('f')
  const { buildPlanPhaseApi, calls } = fixture()
  await assert.rejects(buildPlanPhaseApi.prepare(changed, checkpoint(), 600, 'key'))
  assert.equal(calls.length, 0)
  await assert.rejects(buildPlanPhaseApi.history(changed, checkpoint().goal, checkpoint().history, new AbortController().signal))
  assert.equal(calls.length, 1)
})
for (const seconds of [0, -1, 1201, 1.5, NaN]) {
  test(`invalid time budget ${seconds} cannot prepare a phase`, async () => {
    const { buildPlanPhaseApi, calls } = fixture()
    await assert.rejects(buildPlanPhaseApi.prepare(plan(), checkpoint(), seconds, 'key'))
    assert.equal(calls.length, 0)
  })
}
for (const change of ['project', 'goal', 'root', 'plan', 'revision', 'digest', 'sequence', 'parent', 'index', 'marker', 'marker-hash', 'missing', 'limit', 'active']) {
  test(`rejects ${change} phase history without writes`, async () => {
    const value = phased(), phase = value.phases[0].phase
    if (change === 'project') phase.project_id = 'other'
    if (change === 'goal') phase.goal_id = 'other'
    if (change === 'root') phase.root_plan_id = 'other'
    if (change === 'plan') phase.plan_id = 'other'
    if (change === 'revision') phase.revision_id = 'other'
    if (change === 'digest') phase.plan_digest = hash('f')
    if (change === 'sequence') phase.phase_number = 2
    if (change === 'parent') phase.parent_phase_id = 'other'
    if (change === 'index') phase.start_index = 503
    if (change === 'marker') value.goal.steps[1].id = 'other'
    if (change === 'marker-hash') value.goal.steps[1].tool_input_payload.phase_hash = hash('a')
    if (change === 'missing') value.phases = []
    if (change === 'limit') value.phases = Array.from({ length: 81 }, () => value.phases[0])
    if (change === 'active') value.goal.target_refs.push('build_plan_phase:other')
    const { buildPlanPhaseApi, calls } = fixture({ value })
    await assert.rejects(buildPlanPhaseApi.history(plan(), value.goal, value.history, new AbortController().signal))
    assert.equal(calls.length, 1)
  })
}
for (const change of ['id', 'tool', 'status', 'result-id', 'result-status', 'plan', 'goal', 'phase', 'duplicate']) {
  test(`confirmation rejects ${change} receipt without automatic retry`, async () => {
    const { buildPlanPhaseApi, calls } = fixture({ mutate: (command) => {
      if (change === 'id') command.id = 'other'
      if (change === 'tool') command.tool_id = 'other'
      if (change === 'status') command.status = 'failed'
      if (change === 'result-id') command.result.invocation_id = 'other'
      if (change === 'result-status') command.result.status = 'failed'
      if (change === 'plan') command.result.object_refs[1] = 'build_plan:other'
      if (change === 'goal') command.result.object_refs[2] = 'agent_goal:other'
      if (change === 'phase') command.result.object_refs[0] = 'build_plan_phase:'
      if (change === 'duplicate') command.result.object_refs.push('build_plan_phase:other')
    } })
    await assert.rejects(buildPlanPhaseApi.confirm('command', checkpoint()))
    assert.deepEqual(calls, [['confirm', 'command']])
  })
}
test('lost acknowledgement is propagated without retry', async () => {
  const { buildPlanPhaseApi, calls } = fixture({ failure: new Error('ack lost') })
  await assert.rejects(buildPlanPhaseApi.confirm('command', checkpoint()))
  assert.deepEqual(calls, [['confirm', 'command']])
})
