const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

const input = () => ({ project_id: 'project', plan_id: 'plan', plan_digest: 'sha256:' + 'a'.repeat(64),
  target_baseline_id: 'baseline', idempotency_key: 'same-attempt' })
const command = (status = 'running') => ({ id: 'original', tool_id: 'system_image.build.structure', status,
  input_payload: { ...input(), confirmed_at: '2026-10-07T00:00:00Z' },
  result: ['completed', 'failed', 'cancelled'].includes(status) ? { invocation_id: 'original', status, object_refs: [] } : null })
function fixture(response) {
  const calls = []
  const source = fs.readFileSync(path.resolve(__dirname, '../../apps/portal/src/domains/system-image/structureBuildApi.ts'), 'utf8')
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  const context = { exports: {}, require: (name) => {
    assert.equal(name, '../platform/api')
    return { platformApi: {
      invokeTool: async (value) => { calls.push(['prepare', value]); return response },
      confirmToolInvocation: async (id) => { calls.push(['confirm', id]); return response },
      getToolInvocation: async (id, options) => { calls.push(['read', id, options]); return response },
    } }
  } }
  vm.runInNewContext(code, context)
  return { ...context.exports, calls }
}
for (const status of ['pending', 'running', 'waiting_confirmation', 'waiting_approval', 'completed', 'failed', 'cancelled']) {
  test(`structural command validates ${status} without assuming synchronous completion`, async () => {
    const value = fixture(command(status)), signal = new AbortController().signal
    assert.equal((await value.structureBuildApi.read(input(), 'original', signal)).status, status)
    assert.equal(value.calls[0][2].signal, signal)
  })
}
for (const mismatch of ['project_id', 'plan_id', 'plan_digest', 'target_baseline_id', 'idempotency_key', 'id', 'tool', 'status', 'result_id', 'result_status', 'missing_result']) {
  test(`structural command rejects ${mismatch} rather than enabling another write`, async () => {
    const response = command('completed')
    if (mismatch in response.input_payload) response.input_payload[mismatch] = 'different'
    if (mismatch === 'id') response.id = 'different'
    if (mismatch === 'tool') response.tool_id = 'other-tool'
    if (mismatch === 'status') response.status = 'accepted'
    if (mismatch === 'result_id') response.result.invocation_id = 'different'
    if (mismatch === 'result_status') response.result.status = 'failed'
    if (mismatch === 'missing_result') response.result = null
    await assert.rejects(fixture(response).structureBuildApi.read(input(), 'original'), /scope mismatch|missing/)
  })
}
test('prepare and confirm preserve the original exact input and canonical id', async () => {
  const value = fixture(command('waiting_confirmation'))
  await value.structureBuildApi.prepare(input())
  await value.structureBuildApi.confirm(input(), 'original')
  assert.equal(value.calls[0][1].tool_id, 'system_image.build.structure')
  assert.equal(value.calls[0][1].idempotency_key, input().idempotency_key)
  assert.equal(JSON.stringify(value.calls[0][1].input), JSON.stringify(input()))
  assert.equal(value.calls[1][1], 'original')
})
test('legacy confirmation can recover by the four exact pins without inventing a request key', async () => {
  const response = command('waiting_confirmation')
  delete response.input_payload.idempotency_key
  const pin = input()
  delete pin.idempotency_key
  const value = fixture(response)
  await value.structureBuildApi.read(pin, 'original')
  await value.structureBuildApi.confirm(pin, 'original')
  assert.deepEqual(value.calls.map((item) => item[0]), ['read', 'confirm'])
  await assert.rejects(value.structureBuildApi.prepare(pin), /key is missing/)
  assert.equal(value.calls.length, 2)
})
