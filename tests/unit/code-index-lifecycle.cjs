const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

const hash = (letter) => 'sha256:' + letter.repeat(64)
const pin = (id = 'cgen-1') => ({ generation_id: id, project_id: 'project', binding_id: 'binding', source_revision_id: 'revision',
  invocation_id: 'original', content_hash: hash('a'), source_manifest_hash: hash('b'), snapshot_hash: hash('c'), provider_fingerprint: hash('d') })
const status = () => ({ pin: pin(), state: 'idle', epoch: 1, worker_state: 'none', invocation_status: 'running',
  observed_at: '2026-10-07T00:00:00Z', protocol: null, projection_hash: null, provider_version: null,
  entity_count: null, relationship_count: null, scope: 'durable_projection_metadata_not_native_cache_or_business_authority' })
const view = () => ({ request: { project_id: 'project', generation_id: 'cgen-1' }, status: status(), can_cancel: true })
const page = () => ({ request: { project_id: 'project', binding_id: 'binding', after_id: '', limit: 10 }, items: [pin()],
  next_after_id: null, scope: 'source_authorized_generation_discovery_not_execution_authorization' })
function api(response, mutate = () => {}) {
  const calls = []
  const code = ts.transpileModule(fs.readFileSync(path.resolve(__dirname, '../../apps/portal/src/domains/system-image/codeIndexApi.ts'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const context = { URLSearchParams, Date, exports: {}, require: (name) => {
    if (name === '../../shared/api/client') return { request: async (url, options) => { calls.push(['read', url, options]); return response } }
    assert.equal(name, '../platform/api')
    const completed = (input) => ({ id: 'cancel', tool_id: 'system_image.code_indexes.cancel', input_payload: { ...input }, status: 'completed',
      result: { invocation_id: 'cancel', status: 'completed', code_index: { request: { ...input }, outcome: 'cancelled', status: { ...status(), state: 'cancelled' } } } })
    return { platformApi: {
      invokeTool: async (input) => {
        calls.push(['invoke', input])
        const value = { ...completed(input.input), status: 'waiting_confirmation', result: null }
        mutate(value, 'invoke', input)
        return value
      },
      confirmToolInvocation: async (id) => {
        calls.push(['confirm', id])
        const value = completed(calls.find((item) => item[0] === 'invoke')[1].input)
        mutate(value, 'confirm')
        return value
      },
    } }
  } }
  vm.runInNewContext(code, context)
  return { api: context.exports.codeIndexApi, calls }
}
test('discovery verifies exact source and ordered cursor pages without caching', async () => {
  const fixture = api(page()), signal = new AbortController().signal
  assert.equal((await fixture.api.list('project', 'binding', '', signal)).items[0].generation_id, 'cgen-1')
  assert.equal(fixture.calls[0][2].cache, 'no-store')
  assert.equal(fixture.calls[0][2].signal, signal)
  assert.equal(fixture.calls[0][1], '/v1/projects/project/system-image/code-indexes?binding_id=binding&after_id=&limit=10')
  const empty = api({ ...page(), items: [] })
  assert.equal((await empty.api.list('project', 'binding', '', signal)).items.length, 0)
})
for (const change of ['project', 'binding', 'revision', 'hash', 'order', 'duplicate', 'cursor', 'scope', 'limit']) {
  test(`discovery rejects ${change}`, async () => {
    const value = page()
    if (change === 'project') value.items[0].project_id = 'foreign'
    if (change === 'binding') value.request.binding_id = 'foreign'
    if (change === 'revision') value.items[0].source_revision_id = ''
    if (change === 'hash') value.items[0].snapshot_hash = 'unverified'
    if (change === 'order') value.items = [pin('cgen-2'), pin('cgen-1')]
    if (change === 'duplicate') value.items.push(pin())
    if (change === 'cursor') value.next_after_id = 'elsewhere'
    if (change === 'scope') value.scope = 'execution_authorized'
    if (change === 'limit') value.items = Array.from({ length: 11 }, (_, i) => pin(`cgen-${i}`))
    await assert.rejects(api(value).api.list('project', 'binding', '', new AbortController().signal))
  })
}
test('status retains unknown counts rather than inventing zeros', async () => {
  const fixture = api(view()), signal = new AbortController().signal
  const result = await fixture.api.status(pin(), signal)
  assert.equal(result.status.entity_count, null)
  assert.equal(fixture.calls[0][2].cache, 'no-store')
  assert.equal(fixture.calls[0][2].signal, signal)
})
const sdkReceipt = () => ({ provider: 'codegraph', package_name: '@colbymchenry/codegraph', package_version: '1.6.2',
  entry_point: 'package_public_entry', contract_hash: hash('a'), runtime_hash: hash('b'),
  public_operations: ['CodeGraph.init', 'graph.indexAll', 'graph.close'], gaps: ['os_sandbox_not_verified'],
  schema: 'nasus.code-provider-sdk-contract.v1', scope: 'exercised_public_sdk_projection_not_language_or_runtime_completeness' })
test('status accepts a genuine SDK contract discriminator without pretending it is MCP', async () => {
  const value = view()
  value.status = { ...value.status, state: 'degraded', worker_state: 'active', protocol: sdkReceipt(),
    projection_hash: hash('a'), provider_version: '1.6.2', entity_count: 526, relationship_count: 580 }
  const actual = await api(value).api.status(pin())
  assert.equal(actual.status.protocol.entry_point, 'package_public_entry')
  assert.equal(Object.hasOwn(actual.status.protocol, 'protocol_version'), false)
})
for (const change of ['schema', 'scope', 'entry', 'runtime', 'contract', 'package', 'operations', 'duplicate', 'gap']) {
  test(`SDK status rejects ${change}`, async () => {
    const value = view(), receipt = sdkReceipt()
    value.status.protocol = receipt
    if (change === 'schema') receipt.schema = 'native-latest'
    if (change === 'scope') receipt.scope = 'complete'
    if (change === 'entry') receipt.entry_point = 'lib/dist/index.js'
    if (change === 'runtime') receipt.runtime_hash = 'mutable'
    if (change === 'contract') receipt.contract_hash = 'advertised'
    if (change === 'package') receipt.package_name = '../private'
    if (change === 'operations') receipt.public_operations = []
    if (change === 'duplicate') receipt.public_operations.push('graph.close')
    if (change === 'gap') receipt.gaps.push('os_sandbox_not_verified')
    await assert.rejects(api(value).api.status(pin()))
  })
}
for (const change of ['project', 'pin', 'source', 'fingerprint', 'worker', 'state', 'epoch', 'time', 'count', 'protocol', 'terminal-consent', 'scope']) {
  test(`status rejects ${change}`, async () => {
    const value = view()
    if (change === 'project') value.request.project_id = 'foreign'
    if (change === 'pin') value.status.pin.content_hash = hash('e')
    if (change === 'source') value.status.pin.source_revision_id = 'other'
    if (change === 'fingerprint') value.status.pin.provider_fingerprint = hash('e')
    if (change === 'worker') value.status.worker_state = 'active'
    if (change === 'state') value.status.state = 'complete'
    if (change === 'epoch') value.status.epoch = true
    if (change === 'time') value.status.observed_at = 'invalid'
    if (change === 'count') value.status.entity_count = 0
    if (change === 'protocol') value.status.protocol = { schema: 'fabricated' }
    if (change === 'terminal-consent') value.status.invocation_status = 'completed'
    if (change === 'scope') value.status.scope = 'business_authority'
    await assert.rejects(api(value).api.status(pin()))
  })
}
test('cancellation rechecks status and confirms one exact canonical command', async () => {
  const fixture = api(view())
  const result = await fixture.api.cancel(view(), 'unique-attempt')
  assert.equal(result.outcome, 'cancelled')
  assert.equal(fixture.calls.map((item) => item[0]).join(','), 'read,invoke,confirm')
  const command = fixture.calls[1][1]
  assert.equal(command.tool_id, 'system_image.code_indexes.cancel')
  assert.equal(command.idempotency_key, 'unique-attempt')
  assert.equal(command.input.expected_generation_hash, pin().content_hash)
  assert.equal(Object.hasOwn(command.input, 'confirmed_by_user'), false)
})
for (const outcome of ['already_committed', 'already_terminal']) {
  test(`cancellation retains a verified ${outcome} race outcome without retry`, async () => {
    const fixture = api(view(), (value, phase) => {
      if (phase === 'confirm') {
        value.result.code_index.outcome = outcome
        value.result.code_index.status.state = 'idle'
        value.result.code_index.status.invocation_status = 'completed'
      }
    })
    assert.equal((await fixture.api.cancel(view(), 'attempt')).outcome, outcome)
    assert.equal(fixture.calls.length, 3)
  })
}
for (const change of ['epoch', 'permission', 'terminal']) {
  test(`changed ${change} blocks cancellation before invoking a tool`, async () => {
    const value = view()
    if (change === 'epoch') value.status.epoch = 2
    if (change === 'permission') value.can_cancel = false
    if (change === 'terminal') { value.can_cancel = false; value.status.invocation_status = 'completed' }
    const fixture = api(value)
    await assert.rejects(fixture.api.cancel(view(), 'attempt'))
    assert.equal(fixture.calls.length, 1)
  })
}
for (const change of ['pending-tool', 'pending-state', 'pending-hash', 'confirmed-id', 'confirmed-input', 'receipt-pin', 'receipt-state', 'receipt-invocation']) {
  test(`cancellation rejects ${change}`, async () => {
    const fixture = api(view(), (value, phase) => {
      if (change === 'pending-tool' && phase === 'invoke') value.tool_id = 'other'
      if (change === 'pending-state' && phase === 'invoke') value.status = 'pending'
      if (change === 'pending-hash' && phase === 'invoke') value.input_payload.expected_generation_hash = hash('f')
      if (change === 'confirmed-id' && phase === 'confirm') value.id = 'other'
      if (change === 'confirmed-input' && phase === 'confirm') value.input_payload.project_id = 'foreign'
      if (change === 'receipt-pin' && phase === 'confirm') value.result.code_index.status.pin.source_revision_id = 'foreign'
      if (change === 'receipt-state' && phase === 'confirm') value.result.code_index.status.state = 'idle'
      if (change === 'receipt-invocation' && phase === 'confirm') value.result.invocation_id = 'other'
    })
    await assert.rejects(fixture.api.cancel(view(), 'attempt'))
    if (change.startsWith('pending-')) assert.equal(fixture.calls.length, 2)
  })
}
