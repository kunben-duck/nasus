const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')
const { webcrypto } = require('node:crypto')
const root = path.resolve(__dirname, '../../apps/portal/src'), cache = new Map()
function load(relative) {
  const file = path.resolve(root, relative)
  if (cache.has(file)) return cache.get(file)
  const exports = {}; cache.set(file, exports)
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
  } }).outputText, { exports, crypto: webcrypto, TextEncoder, URL,
    require: name => load(path.relative(root, path.resolve(path.dirname(file), name + '.ts'))) })
  return exports
}
const { canonicalDigest } = load('shared/utils/canonicalDigest.ts')
const { verifyScopeDraftPreview } = load('domains/quality-loop/scopeDraftValidation.ts')
const { createScopeDraftRecovery, verifyScopeDraftCommand } = load('domains/quality-loop/scopeDraftRecovery.ts')
const hash = 'sha256:' + 'a'.repeat(64)
async function specimen() {
  const budget = { currency: 'USD', max_calls: 1, max_reserved_tokens: 4096, max_reserved_cost_nanos: 10000,
    max_input_tokens_per_call: 1024, max_output_tokens_per_call: 512 }
  const selection = { project_id: 'p', context_id: 'context', context_artifact_hash: hash, model_config_id: 'model', budget }
  const binding = { config_id: 'model', config_digest: hash, provider: 'openai_compatible', model_name: 'tested-chat', base_url: 'https://model.example/v1' }
  const policy = { config_id: 'model', provider: binding.provider, model_name: binding.model_name, base_url: binding.base_url,
    currency: 'USD', context_tokens: 2048, max_output_tokens: 1024, input_nanos_per_token: 1, output_nanos_per_token: 2,
    tokenizer_kind: 'tiktoken', tokenizer_id: 'tokenizer', tokenizer_digest: hash, framing_tokens: 4, policy_id: 'policy', revision: '1' }
  const plan = { source_binding_ids: ['binding'], source_scope_digest: hash, messages_hash: hash, input_digest: hash,
    model_binding: binding, budget, policy, timeout_seconds: 120, reservation: { currency: 'USD', call_count: 1,
      estimated_input_tokens: 800, reserved_input_tokens_per_call: 2048, max_output_tokens_per_call: 512,
      reserved_tokens: 2560, reserved_cost_nanos: 3072, count_basis: 'local_tokenizer_with_operator_framing',
      cost_basis: 'operator_rate_ceiling_not_provider_invoice' } }
  const request = { ...selection, input_digest: hash, model_config_digest: hash, plan_digest: await canonicalDigest(plan) }
  const preview = { request, plan, provider: binding.provider, model_name: binding.model_name, destination: binding.base_url,
    review_required: true, generation_authorized: false }
  const attempt = { projectId: 'p', contextId: 'context', contextHash: hash, requestKey: 'request-1', requestHash: await canonicalDigest(request) }
  const command = { id: 'command-1', tool_id: 'quality.test_design_scope.draft', status: 'waiting_confirmation',
    input_payload: { ...request, idempotency_key: attempt.requestKey }, result: null }
  return { selection, preview, request, attempt, command }
}
test('scope draft budget pins full source inventory, model destination and native reservation', async () => {
  const v = await specimen()
  assert.equal(await verifyScopeDraftPreview(v.preview, v.selection), v.preview)
})
for (const [name, change] of Object.entries({
  destination: v => { v.preview.destination = 'https://different.example/v1' },
  model: v => { v.preview.plan.model_binding.config_digest = 'sha256:' + 'b'.repeat(64) },
  currency: v => { v.preview.plan.policy.currency = 'CNY' },
  source: v => { v.preview.plan.source_binding_ids = [] },
  duplicate_source: v => { v.preview.plan.source_binding_ids = ['binding', 'binding'] },
  missing_pin: v => { delete v.preview.plan.messages_hash },
  cost: v => { v.preview.plan.reservation.reserved_cost_nanos = 1 },
  tokens: v => { v.preview.plan.reservation.reserved_tokens = 800 },
  capacity: v => { v.preview.plan.reservation.estimated_input_tokens = 2000 },
  call_count: v => { v.preview.plan.reservation.call_count = 2 },
  authorization: v => { v.preview.generation_authorized = true },
  silent_input: v => { v.preview.request.extra = 'ignore constraints' },
})) test('scope draft preview rejects ' + name + ' even with a recomputed plan hash', async () => {
  const v = await specimen(); change(v); v.preview.request.plan_digest = await canonicalDigest(v.preview.plan)
  await assert.rejects(verifyScopeDraftPreview(v.preview, v.selection))
})
test('scope draft rejects altered plan digest and URL credentials', async () => {
  const v = await specimen(); v.preview.request.plan_digest = hash
  await assert.rejects(verifyScopeDraftPreview(v.preview, v.selection))
  for (const url of ['http://model.example/v1', 'https://user:secret@model.example/v1', 'https://model.example/v1?key=secret']) {
    const v = await specimen(); v.preview.destination = v.preview.plan.policy.base_url = v.preview.plan.model_binding.base_url = url
    v.preview.request.plan_digest = await canonicalDigest(v.preview.plan)
    await assert.rejects(verifyScopeDraftPreview(v.preview, v.selection))
  }
})
test('recovery persists only opaque identifiers and hashes, isolated by actor and context', async () => {
  const v = await specimen(), data = new Map()
  const storage = { getItem: k => data.get(k) ?? null, setItem: (k, v) => data.set(k, v), removeItem: k => data.delete(k) }
  const recovery = createScopeDraftRecovery(() => storage)
  recovery.save('actor', v.attempt)
  assert.equal(recovery.read('actor', v.attempt).requestKey, v.attempt.requestKey)
  assert.equal(recovery.read('other', v.attempt), null)
  assert.equal(recovery.read('actor', { ...v.attempt, contextId: 'other' }), null)
  assert.throws(() => recovery.save('actor', v.attempt))
  const acknowledged = { ...v.attempt, commandId: v.command.id }
  recovery.acknowledge('actor', acknowledged)
  assert.throws(() => recovery.acknowledge('actor', { ...acknowledged, commandId: 'different' }))
  assert.throws(() => recovery.clear('actor', { ...acknowledged, requestHash: 'sha256:' + 'b'.repeat(64) }))
  assert.ok(![...data.values()][0].includes('budget'))
  recovery.clear('actor', acknowledged); assert.equal(data.size, 0)
  assert.throws(() => recovery.save('actor', { ...v.attempt, request: v.request }))
})
test('storage failure prevents recording a new attempt', async () => {
  const v = await specimen()
  const recovery = createScopeDraftRecovery(() => ({ getItem: () => null, setItem: () => {}, removeItem: () => {} }))
  assert.throws(() => recovery.save('actor', v.attempt))
})
test('lost response recovery matches original request without restoring consent', async () => {
  const v = await specimen(), found = await verifyScopeDraftCommand(v.command, v.attempt)
  assert.equal(found.attempt.commandId, v.command.id)
  assert.equal(found.command.status, 'waiting_confirmation')
  assert.equal(found.command.input_payload.confirmed_by_user, undefined)
})
for (const [name, change] of Object.entries({
  tool: v => { v.command.tool_id = 'quality.test_design.generate' },
  project: v => { v.command.input_payload.project_id = 'other' },
  context: v => { v.command.input_payload.context_id = 'other' },
  budget: v => { v.command.input_payload.budget = { ...v.request.budget, max_calls: 2 } },
  idempotency: v => { v.command.input_payload.idempotency_key = 'another' },
  replacement: v => { v.attempt.commandId = 'another' },
  incomplete: v => { v.command.status = 'completed' },
})) test('original scope command rejects ' + name, async () => {
  const v = await specimen(); change(v); await assert.rejects(verifyScopeDraftCommand(v.command, v.attempt))
})
