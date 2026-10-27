const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

const directory = path.resolve(__dirname, '../../apps/portal/src/domains/system-image')
function load(file, dependencies = {}) {
  const code = ts.transpileModule(fs.readFileSync(path.join(directory, file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const context = { URLSearchParams, exports: {}, require: (name) => {
    assert.ok(Object.hasOwn(dependencies, name), `Unexpected dependency ${name}`)
    return dependencies[name]
  } }
  vm.runInNewContext(code, context)
  return context.exports
}
const validation = load('contextAuthorityRegistrationValidation.ts')
const verify = validation.verifyContextAuthorityBackfillPage
const item = (id) => ({ registration_request: { project_id: 'project', context_id: id,
  artifact_hash: 'sha256:' + 'a'.repeat(64), policy_revision: 'nasus.context-authority-dependencies.v1' },
  image_revision_id: 'image', image_artifact_hash: 'sha256:' + 'b'.repeat(64), status: 'requires_independent_confirmation' })
const page = () => ({ items: [item('a'), item('b'), item('c')], next_after_id: 'c', generation_authorized: false })

test('verifies a bounded ordered page and an empty terminal page', () => {
  const v = page()
  assert.equal(verify(v, 'project', ''), v)
  assert.equal(verify({ items: [], next_after_id: null, generation_authorized: false }, 'project', '').items.length, 0)
})
for (const change of ['project', 'order', 'duplicate', 'extra-body', 'missing-hash', 'policy', 'authority', 'cursor', 'limit']) {
  test(`rejects ${change} before protected selections can render`, () => {
    const v = page()
    if (change === 'project') v.items[0].registration_request.project_id = 'foreign'
    if (change === 'order') v.items.reverse()
    if (change === 'duplicate') v.items[1] = v.items[0]
    if (change === 'extra-body') v.items[0].oracle = 'Private body'
    if (change === 'missing-hash') delete v.items[0].registration_request.artifact_hash
    if (change === 'policy') v.items[0].registration_request.policy_revision = 'unverified'
    if (change === 'authority') v.generation_authorized = true
    if (change === 'cursor') v.next_after_id = 'foreign'
    if (change === 'limit') v.items.push(item('d'))
    assert.throws(() => verify(v, 'project', ''))
  })
}
test('rejects control characters, malformed bodies and before-cursor IDs', () => {
  for (const invalid of [null, {}, { items: [null], next_after_id: null, generation_authorized: false }]) assert.throws(() => verify(invalid, 'project', ''))
  assert.throws(() => verify(page(), 'project', 'a'))
  assert.equal(validation.contextRegistrationId('\n'), false)
  assert.equal(validation.contextRegistrationId('x\u0000y'), false)
})

function api(fresh = page(), mutate = () => {}) {
  const calls = []
  const registration = item('a').registration_request
  const pending = { id: 'command', tool_id: 'system_image.context.register_authorities', status: 'waiting_confirmation', input_payload: registration }
  const done = { ...pending, status: 'completed', result: { invocation_id: 'command', status: 'completed', object_refs: ['context_pack:a'] } }
  mutate(pending, done)
  const loaded = load('contextAuthorityRegistrationApi.ts', {
    './contextAuthorityRegistrationValidation': validation,
    '../../shared/api/client': { request: async (url, options) => { calls.push(['read', url, options]); return fresh } },
    '../platform/api': { platformApi: {
      invokeTool: async (request) => { calls.push(['invoke', request]); return pending },
      confirmToolInvocation: async (id) => { calls.push(['confirm', id]); return done },
    } },
  })
  return { application: loaded.contextAuthorityRegistrationApi, calls }
}
test('registration rereads a no-store page before separate canonical confirmation', async () => {
  const { application, calls } = api()
  assert.equal(await application.register(item('a'), '', 'attempt'), 'a')
  assert.deepEqual(calls.map((call) => call[0]), ['read', 'invoke', 'confirm'])
  assert.equal(calls[0][2].cache, 'no-store')
  assert.equal(calls[1][1].idempotency_key, 'attempt')
})
test('a registered or changed selection cannot issue another write', async () => {
  for (const fresh of [{ items: [], next_after_id: null, generation_authorized: false }, page()]) {
    if (fresh.items.length) fresh.items[0].image_artifact_hash = 'sha256:' + 'c'.repeat(64)
    const { application, calls } = api(fresh)
    await assert.rejects(application.register(item('a'), '', 'attempt'))
    assert.deepEqual(calls.map((call) => call[0]), ['read'])
  }
})
for (const boundary of ['pending-tool', 'pending-hash', 'unconfirmed', 'failed', 'wrong-ref', 'wrong-command']) {
  test(`rejects ${boundary} without automatic retry`, async () => {
    const { application, calls } = api(page(), (pending, done) => {
      if (boundary === 'pending-tool') pending.tool_id = 'other'
      if (boundary === 'pending-hash') pending.input_payload = { ...pending.input_payload, artifact_hash: 'sha256:' + 'c'.repeat(64) }
      if (boundary === 'unconfirmed') pending.status = 'completed'
      if (boundary === 'failed') done.status = 'failed'
      if (boundary === 'wrong-ref') done.result.object_refs = ['context_pack:foreign']
      if (boundary === 'wrong-command') done.id = 'other'
    })
    await assert.rejects(application.register(item('a'), '', 'attempt'))
    assert.equal(calls.filter((call) => call[0] === 'invoke').length, 1)
    assert.ok(calls.filter((call) => call[0] === 'confirm').length <= 1)
  })
}
