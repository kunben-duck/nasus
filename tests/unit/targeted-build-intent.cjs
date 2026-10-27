const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

const target = () => ({ project_id: 'project', target_baseline_id: 'baseline', target_version_id: null,
  expected_head_id: null, expected_head_hash: null })
const plan = () => ({ project_id: 'project', plan_id: 'plan', proposal: {
  policy_version: 'nasus.image-investigation-plan.v3', state: 'draft', execution_ready: false, authorization_state: 'not_granted',
  intent: { project_id: 'project', target: target(), expected_head: null, expected_head_status: 'resolved',
    sources: [{ binding_id: 'code' }], scope_binding_ids: ['code'] },
} })

function fixture({ read = target(), mutate = () => {} } = {}) {
  const calls = []
  const source = fs.readFileSync(path.resolve(__dirname, '../../apps/portal/src/domains/system-image/buildPlanApi.ts'), 'utf8')
  const context = { exports: {}, URLSearchParams, require: (name) => {
    if (name === '../../shared/api/client') return { request: async (url, options) => { calls.push(['read', url, options]); return read } }
    if (name === '../platform/api') return { platformApi: { invokeTool: async (input) => {
      calls.push(['write', input])
      const value = { id: 'command', tool_id: 'system_image.build.plan', status: 'completed', input_payload: input.input,
        result: { invocation_id: 'command', object_refs: ['build_plan:plan'] } }
      mutate(value)
      return value
    } } }
    throw new Error(`Unexpected dependency ${name}`)
  } }
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, context)
  return { api: context.exports.buildPlanApi, calls }
}

test('reads the explicit target with no-store and the caller abort signal', async () => {
  const { api, calls } = fixture(), signal = new AbortController().signal
  assert.deepEqual(await api.target('project', 'baseline', signal), target())
  assert.equal(calls.length, 1)
  assert.equal(calls[0][1], '/v1/projects/project/system-image/build-targets/baseline')
  assert.equal(calls[0][2].cache, 'no-store')
  assert.equal(calls[0][2].signal, signal)
})

for (const change of ['project', 'baseline', 'version', 'head', 'hash', 'missing-null', 'control']) {
  test(`rejects ${change} target pins without issuing a command`, async () => {
    const read = target()
    if (change === 'project') read.project_id = 'other'
    if (change === 'baseline') read.target_baseline_id = 'other'
    if (change === 'version') read.target_version_id = ''
    if (change === 'head') read.expected_head_id = 'head'
    if (change === 'hash') read.expected_head_hash = 'sha256:' + 'a'.repeat(64)
    if (change === 'missing-null') delete read.expected_head_id
    if (change === 'control') read.target_version_id = 'version\nprivate'
    const { api, calls } = fixture({ read })
    await assert.rejects(api.target('project', 'baseline', new AbortController().signal))
    assert.equal(calls.length, 1)
  })
}

test('reads a fixed v3 intent without replacing its target', async () => {
  const read = plan(), { api } = fixture({ read })
  assert.equal(await api.read('project', 'plan', new AbortController().signal), read)
})

for (const change of ['scope', 'duplicate', 'status', 'head', 'policy', 'target-project']) {
  test(`rejects a ${change} plan before its target is used`, async () => {
    const read = plan()
    if (change === 'scope') read.proposal.intent.scope_binding_ids = ['outside']
    if (change === 'duplicate') { read.proposal.intent.sources.push({ binding_id: 'code' }); read.proposal.intent.scope_binding_ids.push('code') }
    if (change === 'status') read.proposal.intent.expected_head_status = 'unresolved'
    if (change === 'head') read.proposal.intent.expected_head = 'different'
    if (change === 'policy') read.proposal.policy_version = 'nasus.image-investigation-plan.v2'
    if (change === 'target-project') read.proposal.intent.target.project_id = 'other'
    const { api, calls } = fixture({ read })
    await assert.rejects(api.read('project', 'plan', new AbortController().signal))
    assert.equal(calls.length, 1)
  })
}

test('submits the displayed target once through the canonical command', async () => {
  const input = { project_id: 'project', target: target() }, { api, calls } = fixture()
  assert.equal(await api.propose(input, 'original-key'), 'plan')
  assert.equal(calls.length, 1)
  assert.equal(calls[0][1].tool_id, 'system_image.build.plan')
  assert.equal(calls[0][1].input.target, input.target)
})

for (const change of ['tool', 'invocation', 'rebound-target']) {
  test(`rejects a ${change} write acknowledgement without retry or repinning`, async () => {
    const { api, calls } = fixture({ mutate: (value) => {
      if (change === 'tool') value.tool_id = 'another'
      if (change === 'invocation') value.result.invocation_id = 'another'
      if (change === 'rebound-target') value.input_payload = { target: { ...target(), target_baseline_id: 'another' } }
    } })
    await assert.rejects(api.propose({ project_id: 'project', target: target() }, 'original-key'))
    assert.equal(calls.length, 1)
  })
}
