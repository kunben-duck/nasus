const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { createHash, webcrypto } = require('node:crypto')
const ts = require('../../apps/portal/node_modules/typescript')

const hash = 'sha256:' + 'a'.repeat(64)
const plan = () => ({ project_id: 'project', plan_id: 'plan', plan_digest: hash, proposal: {
  policy_version: 'nasus.image-investigation-plan.v3', state: 'draft', execution_ready: false, authorization_state: 'not_granted',
  intent: { project_id: 'project', source_manifest_id: 'manifest', objective: '构建系统画像', mode: 'initialize', purpose: 'structure',
    expected_head: null, expected_head_status: 'resolved',
    budget: { max_tool_calls: 80, max_model_calls: 30, max_active_seconds: 1200, max_cost_microusd: null },
    sources: [{ binding_id: 'code', source_type: 'code', source_revision_id: 'source', status: 'captured' }], scope_binding_ids: ['code'],
    target: { project_id: 'project', target_baseline_id: 'baseline', target_version_id: null, expected_head_id: null, expected_head_hash: null } },
} })
const goal = () => ({ id: 'goal', project_id: 'project', conversation_id: 'conversation', goal_template: 'system_image_build',
  target_refs: ['project:project', 'build_plan:plan', 'build_plan_digest:' + hash],
  steps: ['query.system_image.build_plans.read', 'system_image.build.authorize', 'system_image.build.structure'].map((tool, index) => ({
    phase: 'acting', selected_tool_id: tool, tool_input_payload: { project_id: 'project', plan_id: 'plan',
      ...(index ? { plan_digest: hash, target_baseline_id: 'baseline' } : {}),
      ...(index === 1 ? { budget: { max_tool_calls: 1, max_model_calls: 0, max_cost_microusd: 0, max_active_seconds: 300 } } : {}),
    },
  })),
})

function fixture({ mutate = () => {}, revoke = false, matching = true, natural = false, waited = false } = {}) {
  const calls = [], saved = plan(), active = goal()
  let command, waitCommand
  if (natural) {
    const body = Object.fromEntries(['project_id', 'source_manifest_id', 'objective', 'mode', 'purpose', 'budget', 'target']
      .map((key) => [key, saved.proposal.intent[key]]))
    const canonical = (item) => Array.isArray(item) ? `[${item.map(canonical).join(',')}]`
      : item !== null && typeof item === 'object' ? `{${Object.keys(item).sort().map((key) => `${JSON.stringify(key)}:${canonical(item[key])}`).join(',')}}`
        : JSON.stringify(item)
    const digest = 'sha256:' + createHash('sha256').update(canonical(body)).digest('hex')
    active.target_refs = ['project:project', 'source_manifest:manifest', 'build_target:baseline',
      'build_request_digest:' + digest, ...active.target_refs.slice(1)]
    active.steps.unshift({ phase: 'acting', status: 'completed', selected_tool_id: 'system_image.build.plan',
      tool_invocation_id: 'prepare', tool_input_payload: structuredClone(body) })
    command = { id: 'prepare', conversation_id: 'conversation', status: 'completed', tool_id: 'system_image.build.plan',
      input_payload: { ...structuredClone(body), agent_goal_id: 'goal' },
      result: { invocation_id: 'prepare', status: 'completed', requires_followup: true,
        followup_reason: 'build_plan_review', object_refs: ['build_plan:plan'] } }
    if (waited) {
      const waiting = Object.fromEntries(['project_id', 'objective', 'mode', 'target'].map((key) => [key, structuredClone(body[key])]))
      const waitDigest = 'sha256:' + createHash('sha256').update(canonical(waiting)).digest('hex')
      active.target_refs.splice(4, 0, 'build_source_wait_digest:' + waitDigest)
      active.steps.unshift({ phase: 'acting', status: 'completed', selected_tool_id: 'query.system_image.status',
        tool_invocation_id: 'waiting', tool_input_payload: { project_id: 'project', build_input_request: structuredClone(waiting) } })
      waitCommand = { id: 'waiting', conversation_id: 'conversation', status: 'completed', tool_id: 'query.system_image.status',
        input_payload: { project_id: 'project', build_input_request: structuredClone(waiting), agent_goal_id: 'goal' },
        result: { invocation_id: 'waiting', status: 'completed', object_refs: ['project:project'] } }
    }
  }
  mutate(active, command, saved, waitCommand)
  const conversation = { id: 'conversation', project_id: 'project', space_type: 'project', space_id: 'project',
    agent_goals: matching ? [active] : [] }
  const request = async (url, options = {}) => {
    calls.push({ url, options })
    if (url.includes('/build-plans/')) {
      if (revoke) throw new Error('Access denied')
      return saved
    }
    if (url === '/v1/agent-goals') return active
    if (url === '/v1/tool-invocations/prepare') return command
    if (url === '/v1/tool-invocations/waiting') return waitCommand
    if (url.startsWith('/v1/conversations')) return conversation
    throw new Error('Unexpected request ' + url)
  }
  const load = (name) => {
    const filename = path.resolve(__dirname, '../../apps/portal/src/domains/system-image', name + '.ts')
    const context = { exports: {}, URLSearchParams, TextEncoder, crypto: webcrypto, require: (dependency) => {
      if (dependency === '../../shared/api/client') return { request }
      if (dependency === '../platform/api') return { platformApi: {} }
      if (dependency === './buildPlanApi') return load('buildPlanApi')
      if (dependency === '../../shared/utils/canonicalDigest') return load('../../shared/utils/canonicalDigest')
      throw new Error('Unexpected dependency ' + dependency)
    } }
    vm.runInNewContext(ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
    } }).outputText, context)
    return context.exports
  }
  return { api: load('savedBuildAgentApi').savedBuildAgentApi, calls, saved, active }
}

test('a captured-input continuation reuses its waiting goal after both original commands are verified', async () => {
  const { api, calls, saved, active } = fixture({ natural: true, waited: true })
  const signal = new AbortController().signal
  assert.equal(await api.recover(saved, 'conversation', signal), active)
  assert.equal(calls.length, 4)
  assert.ok(calls.every((call) => call.options.method === undefined && call.options.signal === signal && call.options.cache === 'no-store'))
  assert.equal(calls[2].url, '/v1/tool-invocations/waiting')
  assert.equal(calls[3].url, '/v1/tool-invocations/prepare')
})

for (const change of ['wait-digest', 'wait-objective', 'wait-target', 'wait-extra-field', 'wait-tool', 'wait-status',
  'wait-duplicate', 'command-goal', 'command-conversation', 'command-objective', 'command-result', 'command-project']) {
  test(`a waited ${change} mismatch cannot substitute a new build or retry its POST`, async () => {
    const { api, calls, saved } = fixture({ natural: true, waited: true, mutate: (value, command, saved, wait) => {
      const step = value.steps[0]
      if (change === 'wait-digest') value.target_refs[4] = 'build_source_wait_digest:' + hash
      if (change === 'wait-objective') step.tool_input_payload.build_input_request.objective = 'Changed'
      if (change === 'wait-target') step.tool_input_payload.build_input_request.target.target_baseline_id = 'other'
      if (change === 'wait-extra-field') step.tool_input_payload.build_input_request.publish = true
      if (change === 'wait-tool') step.selected_tool_id = 'query.project.status'
      if (change === 'wait-status') step.status = 'pending'
      if (change === 'wait-duplicate') value.steps.unshift(structuredClone(step))
      if (change === 'command-goal') wait.input_payload.agent_goal_id = 'other'
      if (change === 'command-conversation') wait.conversation_id = 'other'
      if (change === 'command-objective') wait.input_payload.build_input_request.objective = 'Other'
      if (change === 'command-result') wait.result.invocation_id = 'other'
      if (change === 'command-project') wait.result.object_refs = ['project:other']
    } })
    await assert.rejects(api.start(saved, 'conversation'))
    assert.equal(calls.filter((call) => call.options.method === 'POST').length, 1)
  })
}

test('guided entry sends one proposal with original pins and no caller-provided tools or confirmation', async () => {
  const { api, calls, saved, active } = fixture()
  assert.equal(await api.start(saved, 'conversation'), active)
  assert.equal(calls.length, 1)
  const payload = JSON.parse(calls[0].options.body)
  assert.deepEqual(payload.target_refs, active.target_refs)
  assert.equal(payload.goal_template, 'system_image_build')
  assert.equal(payload.steps, undefined)
  assert.equal(payload.confirmed_by_user, undefined)
  assert.equal(payload.max_runtime_seconds, 1200)
})

for (const change of ['project', 'conversation', 'digest', 'target', 'tool', 'model', 'cost', 'time', 'tool-budget', 'extra-ref', 'duplicate-ref']) {
  test(`a ${change} acknowledgement fails without retrying the POST`, async () => {
    const { api, calls, saved } = fixture({ mutate: (value) => {
      if (change === 'project') value.project_id = 'other'
      if (change === 'conversation') value.conversation_id = 'other'
      if (change === 'digest') value.steps[2].tool_input_payload.plan_digest = 'sha256:' + 'b'.repeat(64)
      if (change === 'target') value.steps[2].tool_input_payload.target_baseline_id = 'other'
      if (change === 'tool') value.steps[2].selected_tool_id = 'system_image.context.materialize'
      if (change === 'model') value.steps[1].tool_input_payload.budget.max_model_calls = 1
      if (change === 'cost') value.steps[1].tool_input_payload.budget.max_cost_microusd = 1
      if (change === 'time') value.steps[1].tool_input_payload.budget.max_active_seconds = 1201
      if (change === 'tool-budget') value.steps[1].tool_input_payload.budget.max_tool_calls = 2
      if (change === 'extra-ref') value.target_refs.push('project:other')
      if (change === 'duplicate-ref') value.target_refs.push(value.target_refs[0])
    } })
    await assert.rejects(api.start(saved, 'conversation'))
    assert.equal(calls.length, 1)
    assert.equal(calls[0].options.method, 'POST')
  })
}

test('a continued original goal may append steps but cannot expand the original target refs', async () => {
  const { api, saved, active } = fixture({ mutate: (value) => value.steps.push({ phase: 'acting',
    selected_tool_id: 'system_image.build.investigate', tool_input_payload: { project_id: 'project' } }) })
  assert.equal(await api.start(saved, 'conversation'), active)
})

test('unknown acknowledgement recovery reauthorizes the original plan then only reads the existing conversation', async () => {
  const { api, calls, saved, active } = fixture(), signal = new AbortController().signal
  assert.equal(await api.recover(saved, 'conversation', signal), active)
  assert.equal(calls.length, 2)
  assert.ok(calls[0].url.endsWith('/build-plans/plan'))
  assert.equal(calls[1].url, '/v1/conversations/conversation')
  for (const call of calls) {
    assert.equal(call.options.cache, 'no-store')
    assert.equal(call.options.signal, signal)
    assert.equal(call.options.method, undefined)
  }
})

test('revoked original plan blocks recovery before reading a private goal', async () => {
  const { api, calls, saved } = fixture({ revoke: true })
  await assert.rejects(api.recover(saved, 'conversation', new AbortController().signal))
  assert.equal(calls.length, 1)
})

test('an empty conversation does not authorize a second POST after a lost acknowledgement', async () => {
  const { api, calls, saved } = fixture({ matching: false })
  await assert.rejects(api.recover(saved, 'conversation', new AbortController().signal), /still unknown/)
  assert.equal(calls.length, 2)
  assert.ok(calls.every((call) => !call.options.method))
})

test('legacy or malformed plans cannot start a saved-intent goal', async () => {
  for (const change of ['legacy', 'scope', 'duplicate', 'status']) {
    const { api, calls, saved } = fixture()
    if (change === 'legacy') saved.proposal.policy_version = 'nasus.image-investigation-plan.v2'
    if (change === 'scope') saved.proposal.intent.scope_binding_ids = ['other']
    if (change === 'duplicate') saved.proposal.intent.sources.push(saved.proposal.intent.sources[0])
    if (change === 'status') saved.proposal.intent.sources[0].status = 'failed'
    await assert.rejects(api.start(saved, 'conversation'))
    assert.equal(calls.length, 0)
  }
})

test('a saved entry reuses a naturally prepared goal only after reading its original canonical command', async () => {
  const { api, calls, saved, active } = fixture({ natural: true })
  assert.equal(await api.start(saved, 'conversation'), active)
  assert.equal(calls.length, 2)
  assert.equal(calls[1].url, '/v1/tool-invocations/prepare')
  assert.equal(calls[1].options.cache, 'no-store')
  assert.equal(calls[1].options.method, undefined)
  assert.equal(JSON.parse(calls[0].options.body).target_refs.length, 3)
})

test('unavailable optional documents remain explicit gaps and do not prevent a captured-code entry', async () => {
  const { api, saved, active } = fixture()
  saved.proposal.intent.sources.push({ binding_id: 'us', source_type: 'us_doc', source_revision_id: null, status: 'failed' })
  saved.proposal.intent.scope_binding_ids.push('us')
  assert.equal(await api.start(saved, 'conversation'), active)
})

for (const invalid of ['missing-code', 'unknown-kind', 'unknown-state', 'uncaptured-revision']) {
  test(`an invalid ${invalid} source scope is rejected before any write`, async () => {
    const { api, saved, calls } = fixture()
    const source = saved.proposal.intent.sources[0]
    if (invalid === 'missing-code') source.source_type = 'us_doc'
    if (invalid === 'unknown-kind') source.source_type = 'other'
    if (invalid === 'unknown-state') source.status = 'approved'
    if (invalid === 'uncaptured-revision') {
      saved.proposal.intent.sources.push({ binding_id: 'us', source_type: 'us_doc', source_revision_id: 'unexpected-revision', status: 'failed' })
      saved.proposal.intent.scope_binding_ids.push('us')
    }
    await assert.rejects(api.start(saved, 'conversation'))
    assert.equal(calls.length, 0)
  })
}

test('natural-goal recovery remains read-only and forwards cancellation to original command verification', async () => {
  const { api, calls, saved, active } = fixture({ natural: true }), signal = new AbortController().signal
  assert.equal(await api.recover(saved, 'conversation', signal), active)
  assert.equal(calls.length, 3)
  assert.ok(calls.every((call) => call.options.method === undefined && call.options.signal === signal && call.options.cache === 'no-store'))
})

for (const change of ['extra-ref', 'request-digest', 'manifest', 'objective', 'second-plan-step', 'pending-step',
  'command-goal', 'command-conversation', 'command-payload', 'command-result']) {
  test(`a naturally prepared ${change} mismatch fails without another write`, async () => {
    const { api, calls, saved } = fixture({ natural: true, mutate: (value, command) => {
      if (change === 'extra-ref') value.target_refs.push('project:other')
      if (change === 'request-digest') value.target_refs[3] = 'build_request_digest:' + hash
      if (change === 'manifest') value.target_refs[1] = 'source_manifest:other'
      if (change === 'objective') value.steps[0].tool_input_payload.objective = 'Changed'
      if (change === 'second-plan-step') value.steps.push(structuredClone(value.steps[0]))
      if (change === 'pending-step') value.steps[0].status = 'pending'
      if (change === 'command-goal') command.input_payload.agent_goal_id = 'other'
      if (change === 'command-conversation') command.conversation_id = 'other'
      if (change === 'command-payload') command.input_payload.source_manifest_id = 'other'
      if (change === 'command-result') command.result.object_refs = ['build_plan:other']
    } })
    await assert.rejects(api.start(saved, 'conversation'))
    assert.equal(calls.filter((call) => call.options.method === 'POST').length, 1)
  })
}
