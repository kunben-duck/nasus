const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

function fixture(sessions) {
  const calls = [], signal = new AbortController().signal
  const file = path.resolve(__dirname, '../../apps/portal/src/domains/agent/api.ts')
  const context = { exports: {}, URLSearchParams, require: () => ({ request: async (url, options) => {
    calls.push({ url, options }); return sessions
  } }) }
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, context)
  return { calls, signal, read: () => context.exports.agentApi.readProjectConversation('project', signal) }
}

test('review navigation discovers only the exact existing project conversation by private GET', async () => {
  const v = fixture([{ id: 'original', project_id: 'project', space_id: 'project', space_type: 'project' },
    { id: 'other', project_id: 'other', space_id: 'other', space_type: 'project' },
    { id: 'version', project_id: 'project', space_id: 'version', space_type: 'version' }])
  assert.equal((await v.read()).id, 'original')
  assert.equal(v.calls.length, 1)
  assert.equal(v.calls[0].url, '/v1/conversations?project_id=project&space_type=project')
  assert.equal(v.calls[0].options.cache, 'no-store')
  assert.equal(v.calls[0].options.signal, v.signal)
  assert.equal(v.calls[0].options.method, undefined)
})

test('a missing review conversation never triggers creation', async () => {
  const v = fixture([])
  assert.equal(await v.read(), null)
  assert.equal(v.calls.length, 1)
})

test('multiple project conversations are not resolved by arbitrary list order', async () => {
  const v = fixture(['one', 'two'].map((id) => ({ id, project_id: 'project', space_id: 'project', space_type: 'project' })))
  await assert.rejects(v.read(), /ambiguous/)
  assert.equal(v.calls.length, 1)
})

function scopeFixture() {
  const calls = [], controller = new AbortController(), signal = controller.signal
  const file = path.resolve(__dirname, '../../apps/portal/src/domains/agent/conversationScopeQuery.ts')
  const scope = { exports: {} }
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.resolve(__dirname, '../../apps/portal/src/shared/api/queryScope.ts'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, scope)
  const context = { exports: {}, require: (name) => name === '../../shared/api/queryScope' ? scope.exports : ({ agentApi: {
    ensureConversation: (...args) => { calls.push(['ensure', ...args]); return 'created' },
    readProjectConversation: (...args) => { calls.push(['read', ...args]); return 'existing' },
  } }) }
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, context)
  return { calls, signal, controller, read: context.exports.readConversationScope }
}

test('the review scope query preserves its abort signal and never ensures a conversation', async () => {
  const v = scopeFixture()
  assert.equal(await v.read('project', 'project', 'Project', true, v.signal), 'existing')
  assert.deepEqual(v.calls, [['read', 'project', v.signal]])
})

test('read-only discovery rejects other space types before any API call', async () => {
  for (const scope of ['top_level', 'version', 'us']) {
    const v = scopeFixture()
    await assert.rejects(v.read(scope, 'scope', 'Title', true, v.signal), /project scope/)
    assert.deepEqual(v.calls, [])
  }
})

test('ordinary conversation entry still uses the existing canonical ensure contract', async () => {
  const v = scopeFixture()
  assert.equal(await v.read('project', 'project', 'Project', false, v.signal), 'created')
  assert.deepEqual(v.calls, [['ensure', 'project', 'project', 'Project', v.signal]])
})

test('a stale workspace observer cannot POST a conversation from the review route', async () => {
  const v = scopeFixture()
  await assert.rejects(v.read('project', 'project', 'Project', false, v.signal, () => false), /no longer active/)
  assert.deepEqual(v.calls, [])
  assert.equal(await v.read('project', 'project', 'Project', true, v.signal, () => false), 'existing')
  assert.deepEqual(v.calls, [['read', 'project', v.signal]])
})

test('late ensure results are discarded when the workspace lifetime ends', async () => {
  const v = scopeFixture()
  let current = true
  const reading = v.read('project', 'project', 'Project', false, v.signal, () => current)
  current = false
  await assert.rejects(reading, /no longer active/)
  assert.deepEqual(v.calls, [['ensure', 'project', 'project', 'Project', v.signal]])
})

test('an aborted ordinary conversation query cannot issue its ensure request', async () => {
  const v = scopeFixture(); v.controller.abort()
  await assert.rejects(v.read('project', 'project', 'Project', false, v.signal), { name: 'AbortError' })
  assert.deepEqual(v.calls, [])
})
