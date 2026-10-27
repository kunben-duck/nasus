const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

const hash = (letter) => 'sha256:' + letter.repeat(64)
const goal = () => ({ id: 'goal', project_id: 'project', conversation_id: 'conversation', status: 'paused',
  target_refs: ['build_plan:root'], pause_reason: 'structural_candidate_review' })
const plan = () => ({ project_id: 'project', plan_id: 'root', plan_digest: hash('a') })
const revision = (number) => ({ revision_hash: hash(number === 1 ? 'b' : 'd'), revision: {
  revision_id: `revision-${number}`, project_id: 'project', goal_id: 'goal', root_plan_id: 'root',
  from_plan_id: number === 1 ? 'root' : 'plan-1', from_plan_digest: hash(number === 1 ? 'a' : 'c'),
  plan_id: `plan-${number}`, plan_digest: hash(number === 1 ? 'c' : 'e'),
  source_manifest_id: `manifest-${number}`, source_manifest_hash: hash('f'), invocation_id: `command-${number}`,
  revision_number: number, parent_revision_id: number === 1 ? null : 'revision-1',
  parent_revision_hash: number === 1 ? null : hash('b'), execution_authorized: false, publication_authorized: false,
} })

function fixture({ history = [revision(1), revision(2)], current = goal(), failure, mutateConfirmation = () => {} } = {}) {
  const calls = []
  const file = path.resolve(__dirname, '../../apps/portal/src/domains/system-image/buildPlanApi.ts')
  const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const context = { exports: {}, URLSearchParams, require: (name) => {
    if (name === '../../shared/api/client') return { request: async (url, options) => {
      calls.push(['read', url, options])
      if (failure) throw failure
      return url.startsWith('/v1/agent-goals/') ? current : history
    } }
    if (name === '../platform/api') return { platformApi: {
      invokeTool: async (body) => { calls.push(['invoke', body]); return { id: 'pending', status: 'waiting_confirmation' } },
      confirmToolInvocation: async (id) => {
        calls.push(['confirm', id])
        if (failure) throw failure
        const result = { id, tool_id: 'system_image.build.plan.revise', status: 'completed',
          result: { invocation_id: id, status: 'completed', object_refs: ['build_plan_revision:revision', 'build_plan:plan'] } }
        mutateConfirmation(result)
        return result
      },
    } }
    throw new Error(`Unexpected dependency ${name}`)
  } }
  vm.runInNewContext(code, context)
  return { api: context.exports.buildPlanApi, calls }
}

test('rereads the exact goal and complete chain with no-store, without a write', async () => {
  const { api, calls } = fixture()
  const signal = new AbortController().signal
  const checkpoint = await api.revisionCheckpoint('project', 'root', 'goal', signal)
  assert.equal(checkpoint.history.length, 2)
  assert.equal(checkpoint.goal.id, 'goal')
  assert.equal(calls.length, 2)
  for (const call of calls) { assert.equal(call[2].cache, 'no-store'); assert.equal(call[2].signal, signal) }
})

for (const change of ['scope', 'first-parent', 'from-plan', 'from-digest', 'duplicate-revision', 'duplicate-plan',
  'hash', 'manifest-id', 'sequence', 'execution', 'publication', 'limit', 'malformed']) {
  test(`rejects ${change} history before confirmation controls can consume it`, async () => {
    let history = [revision(1), revision(2)]
    if (change === 'scope') history[1].revision.goal_id = 'another-goal'
    if (change === 'first-parent') history[0].revision.from_plan_id = 'another-root'
    if (change === 'from-plan') history[1].revision.from_plan_id = 'another-plan'
    if (change === 'from-digest') history[1].revision.from_plan_digest = hash('f')
    if (change === 'duplicate-revision') history[1].revision.revision_id = history[0].revision.revision_id
    if (change === 'duplicate-plan') history[1].revision.plan_id = history[0].revision.plan_id
    if (change === 'hash') history[1].revision_hash = 'unverified'
    if (change === 'manifest-id') history[1].revision.source_manifest_id = 'private\nmanifest'
    if (change === 'sequence') history[1].revision.revision_number = 3
    if (change === 'execution') history[1].revision.execution_authorized = true
    if (change === 'publication') history[1].revision.publication_authorized = true
    if (change === 'limit') history = Array.from({ length: 81 }, () => revision(1))
    if (change === 'malformed') history = null
    const { api, calls } = fixture({ history })
    await assert.rejects(api.revisionCheckpoint('project', 'root', 'goal', new AbortController().signal))
    assert.equal(calls.filter((call) => call[0] === 'invoke').length, 0)
  })
}

for (const change of ['project', 'id', 'status', 'reason', 'root', 'missing-refs']) {
  test(`rejects a changed ${change} goal before loading private revision history`, async () => {
    const current = goal()
    if (change === 'project') current.project_id = 'another-project'
    if (change === 'id') current.id = 'another-goal'
    if (change === 'status') current.status = 'running'
    if (change === 'reason') current.pause_reason = 'waiting_confirmation'
    if (change === 'root') current.target_refs = ['build_plan:other']
    if (change === 'missing-refs') delete current.target_refs
    const { api, calls } = fixture({ current })
    await assert.rejects(api.revisionCheckpoint('project', 'root', 'goal', new AbortController().signal))
    assert.equal(calls.length, 1)
  })
}

test('prepares only the displayed parent and original checkpoint through the canonical tool', async () => {
  const { api, calls } = fixture()
  const checkpoint = await api.revisionCheckpoint('project', 'root', 'goal', new AbortController().signal)
  await api.prepareRevision(plan(), 'new-manifest', checkpoint, 'request-key')
  const write = calls.at(-1)[1]
  assert.equal(write.tool_id, 'system_image.build.plan.revise')
  assert.equal(write.conversation_id, checkpoint.goal.conversation_id)
  assert.equal(write.idempotency_key, 'request-key')
  assert.equal(write.input.expected_goal, checkpoint.goal)
  assert.equal(write.input.from_plan_id, 'plan-2')
  assert.equal(write.input.parent_revision_id, 'revision-2')
  assert.equal(write.input.parent_revision_hash, hash('d'))
  assert.equal(write.input.source_manifest_id, 'new-manifest')
})

test('rejects a rebound displayed root digest before any canonical write', async () => {
  const { api, calls } = fixture()
  const checkpoint = await api.revisionCheckpoint('project', 'root', 'goal', new AbortController().signal)
  await assert.rejects(api.prepareRevision({ ...plan(), plan_digest: hash('f') }, 'new-manifest', checkpoint, 'key'))
  assert.equal(calls.filter((call) => call[0] === 'invoke').length, 0)
})

test('an access failure is propagated without retries or writes', async () => {
  const denied = new Error('Access revoked'), { api, calls } = fixture({ failure: denied })
  await assert.rejects(api.revisionCheckpoint('project', 'root', 'goal', new AbortController().signal), denied)
  assert.equal(calls.length, 1)
})

test('separate confirmation uses the domain command surface and verifies its exact receipt', async () => {
  const { api, calls } = fixture()
  assert.equal((await api.confirmRevision('command')).id, 'command')
  assert.deepEqual(calls, [['confirm', 'command']])
})

for (const change of ['id', 'tool', 'status', 'result-id', 'result-status', 'missing-result', 'duplicate-ref', 'empty-ref']) {
  test(`rejects a ${change} confirmation receipt without automatic retry`, async () => {
    const { api, calls } = fixture({ mutateConfirmation: (command) => {
      if (change === 'id') command.id = 'other'
      if (change === 'tool') command.tool_id = 'another-tool'
      if (change === 'status') command.status = 'failed'
      if (change === 'result-id') command.result.invocation_id = 'other'
      if (change === 'result-status') command.result.status = 'failed'
      if (change === 'missing-result') command.result = null
      if (change === 'duplicate-ref') command.result.object_refs = ['build_plan:plan', 'build_plan:plan']
      if (change === 'empty-ref') command.result.object_refs = ['build_plan_revision:', 'build_plan:plan']
    } })
    await assert.rejects(api.confirmRevision('command'))
    assert.deepEqual(calls, [['confirm', 'command']])
  })
}

test('lost confirmation acknowledgement is propagated without another write', async () => {
  const lost = new Error('Acknowledgement lost'), { api, calls } = fixture({ failure: lost })
  await assert.rejects(api.confirmRevision('command'), lost)
  assert.deepEqual(calls, [['confirm', 'command']])
})
