const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

const summary = (id = 'command-a') => ({ invocation_id: id, target_baseline_id: 'baseline', status: 'waiting_confirmation', idempotency_key: 'original-key' })
const page = () => ({ project_id: 'project', plan_id: 'plan', plan_digest: 'digest', items: [summary()], next_after_id: null })
function fixture(response) {
  const calls = []
  const source = fs.readFileSync(path.resolve(__dirname, '../../apps/portal/src/domains/system-image/structureCommandDiscoveryApi.ts'), 'utf8')
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  const context = { exports: {}, URLSearchParams, require: (name) => {
    assert.equal(name, '../../shared/api/client')
    return { request: async (url, options) => { calls.push({ url, options }); return response } }
  } }
  vm.runInNewContext(code, context)
  return { ...context.exports, calls }
}
test('discovery uses an abortable no-store read and returns the original identity', async () => {
  const value = fixture(page()), signal = new AbortController().signal
  const result = await value.structureCommandDiscoveryApi.list('project', 'plan', 'digest', '', signal)
  assert.equal(result.items[0].invocation_id, 'command-a')
  assert.equal(value.calls[0].options.cache, 'no-store')
  assert.equal(value.calls[0].options.signal, signal)
  assert.equal(value.calls[0].url, '/v1/projects/project/system-image/build-plans/plan/structure-commands?plan_digest=digest&after_id=&limit=20')
})
for (const corruption of ['project', 'plan', 'digest', 'empty-id', 'duplicate', 'cursor', 'order', 'status', 'target', 'key', 'limit', 'next']) {
  test(`discovery rejects ${corruption} without choosing another command`, async () => {
    const response = page()
    if (corruption === 'project') response.project_id = 'other'
    if (corruption === 'plan') response.plan_id = 'other'
    if (corruption === 'digest') response.plan_digest = 'other'
    if (corruption === 'empty-id') response.items[0].invocation_id = ''
    if (corruption === 'duplicate') response.items.push(summary())
    if (corruption === 'cursor') response.items[0].invocation_id = 'before-cursor'
    if (corruption === 'order') response.items = [summary('z'), summary('a')]
    if (corruption === 'status') response.items[0].status = 'completed'
    if (corruption === 'target') response.items[0].target_baseline_id = ''
    if (corruption === 'key') delete response.items[0].idempotency_key
    if (corruption === 'limit') response.items = Array.from({ length: 21 }, (_, i) => summary(`command-${i.toString().padStart(2, '0')}`))
    if (corruption === 'next') response.next_after_id = 'another'
    await assert.rejects(fixture(response).structureCommandDiscoveryApi.list('project', 'plan', 'digest', corruption === 'cursor' ? 'command-a' : ''), /mismatch|invalid/)
  })
}
test('bounded pagination and legacy keys retain their exact values', async () => {
  const response = page()
  response.items = Array.from({ length: 20 }, (_, i) => summary(`command-${i.toString().padStart(2, '0')}`))
  response.items[0].idempotency_key = null
  response.next_after_id = 'command-19'
  const result = await fixture(response).structureCommandDiscoveryApi.list('project', 'plan', 'digest', '')
  assert.equal(result.items[0].idempotency_key, null)
  assert.equal(result.next_after_id, 'command-19')
})
