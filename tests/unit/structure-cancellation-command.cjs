const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

const pin = () => ({ project_id: 'project', original_invocation_id: 'original', plan_id: 'plan',
  plan_digest: 'sha256:' + 'a'.repeat(64), target_baseline_id: 'baseline' })
const status = () => ({ request: pin(), original_status: 'running', can_cancel: true,
  cancellation_requested: false, candidate_committed: false })
const command = (state = 'completed', outcome = 'cancelled', originalStatus = 'cancelled') => ({
  id: 'stop', tool_id: 'system_image.build.structure.cancel', status: state,
  input_payload: { ...pin(), idempotency_key: 'stop-attempt' },
  result: state === 'completed' ? { invocation_id: 'stop', status: 'completed',
    structure_cancel: { request: pin(), outcome, original_status: originalStatus } } : null,
})
function fixture({ read = status(), prepared = command('waiting_confirmation'), confirmed = command() } = {}) {
  const calls = []
  const source = fs.readFileSync(path.resolve(__dirname,
    '../../apps/portal/src/domains/system-image/structureCancellationApi.ts'), 'utf8')
  const code = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
  } }).outputText
  const context = { exports: {}, URLSearchParams, require: (name) => {
    if (name === '../../shared/api/client') return { request: async (url, options) => {
      calls.push(['read', url, options]); return read
    } }
    assert.equal(name, '../platform/api')
    return { platformApi: {
      invokeTool: async (value) => { calls.push(['prepare', value]); return prepared },
      confirmToolInvocation: async (id) => { calls.push(['confirm', id]); return confirmed },
    } }
  } }
  vm.runInNewContext(code, context)
  return { ...context.exports, calls }
}

test('stop status is a private abortable read without dispatch or original-key invention', async () => {
  const value = fixture(), signal = new AbortController().signal
  await value.structureCancellationApi.status(pin(), signal)
  assert.equal(value.calls.length, 1)
  assert.match(value.calls[0][1], /structure-commands\/original\/status\?/)
  assert.equal(value.calls[0][2].signal, signal)
  assert.equal(value.calls[0][2].cache, 'no-store')
})
for (const field of Object.keys(pin())) {
  test(`stop rejects another ${field} before preparing a write`, async () => {
    const read = status(); read.request[field] = 'other'
    const value = fixture({ read })
    await assert.rejects(value.structureCancellationApi.cancel(status(), 'stop-attempt'), /status mismatch/)
    assert.equal(value.calls.length, 1)
  })
}
for (const change of [{ can_cancel: false }, { original_status: 'waiting_confirmation' },
  { candidate_committed: true }, { cancellation_requested: true }, { can_cancel: 'true' }]) {
  test(`changed stop authority ${JSON.stringify(change)} cannot consume confirmation`, async () => {
    const value = fixture({ read: { ...status(), ...change } })
    await assert.rejects(value.structureCancellationApi.cancel(status(), 'stop-attempt'), /changed|mismatch/)
    assert.deepEqual(value.calls.map((call) => call[0]), ['read'])
  })
}
test('stop uses independent consent and key while retaining the exact original command', async () => {
  const value = fixture()
  await value.structureCancellationApi.cancel(status(), 'stop-attempt')
  assert.deepEqual(value.calls.map((call) => call[0]), ['read', 'prepare', 'confirm'])
  assert.equal(value.calls[1][1].tool_id, 'system_image.build.structure.cancel')
  assert.equal(value.calls[1][1].idempotency_key, 'stop-attempt')
  assert.equal(JSON.stringify(value.calls[1][1].input), JSON.stringify(pin()))
  assert.equal(value.calls[2][1], 'stop')
  assert.equal('confirmed_by_user' in value.calls[1][1].input, false)
})
for (const mismatch of ['id', 'tool', 'request', 'result', 'key', 'original_id']) {
  test(`a ${mismatch} mismatch cannot confirm an unrelated stop`, async () => {
    const prepared = command('waiting_confirmation')
    if (mismatch === 'id') prepared.id = ''
    if (mismatch === 'tool') prepared.tool_id = 'system_image.build.structure'
    if (mismatch === 'request') prepared.input_payload.plan_id = 'other'
    if (mismatch === 'result') prepared.result = command().result
    if (mismatch === 'key') prepared.input_payload.idempotency_key = 'other'
    if (mismatch === 'original_id') prepared.id = 'original'
    const value = fixture({ prepared })
    await assert.rejects(value.structureCancellationApi.cancel(status(), 'stop-attempt'), /mismatch/)
    assert.equal(value.calls.some((call) => call[0] === 'confirm'), false)
  })
}
for (const [outcome, originalStatus] of [['cancelled', 'cancelled'], ['cancel_requested', 'running'],
  ['already_requested', 'running'], ['already_committed', 'running'], ['already_terminal', 'failed']]) {
  test(`${outcome} is validated without pretending every stop has already exited`, async () => {
    const value = fixture({ confirmed: command('completed', outcome, originalStatus) })
    const receipt = await value.structureCancellationApi.cancel(status(), 'stop-attempt')
    assert.equal(receipt.result.structure_cancel.original_status, originalStatus)
  })
}
for (const mismatch of ['pending', 'id', 'result_id', 'result_status', 'request', 'outcome', 'state', 'key']) {
  test(`unverified ${mismatch} acknowledgement does not pretend stop succeeded`, async () => {
    const confirmed = command()
    if (mismatch === 'pending') Object.assign(confirmed, command('waiting_confirmation'))
    if (mismatch === 'id') confirmed.id = 'other'
    if (mismatch === 'result_id') confirmed.result.invocation_id = 'other'
    if (mismatch === 'result_status') confirmed.result.status = 'failed'
    if (mismatch === 'request') confirmed.result.structure_cancel.request.original_invocation_id = 'other'
    if (mismatch === 'outcome') confirmed.result.structure_cancel.outcome = 'accepted'
    if (mismatch === 'state') confirmed.result.structure_cancel.original_status = 'running'
    if (mismatch === 'key') confirmed.input_payload.idempotency_key = 'other'
    await assert.rejects(fixture({ confirmed }).structureCancellationApi.cancel(status(), 'stop-attempt'), /mismatch|acknowledged/)
  })
}
