const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { execFileSync } = require('node:child_process')
const { webcrypto, createHash } = require('node:crypto')
const ts = require('../../apps/portal/node_modules/typescript')
const repo = path.resolve(__dirname, '../..'), root = path.join(repo, 'apps/portal/src')
function load(relative, overrides = {}, modules = new Map()) {
  const file = path.resolve(root, relative)
  if (modules.has(file)) return modules.get(file)
  const context = { exports: {}, crypto: webcrypto, TextEncoder, TextDecoder, URLSearchParams, atob, btoa, require: (name) => {
    if (Object.hasOwn(overrides, name)) return overrides[name]
    return load(path.relative(root, path.resolve(path.dirname(file), `${name}.ts`)), overrides, modules)
  } }
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, context)
  modules.set(file, context.exports); return context.exports
}
const validation = load('domains/quality-loop/environmentHealthValidation.ts')
const original = load('domains/quality-loop/environmentRecordValidation.ts')
const recovery = load('domains/quality-loop/environmentHealthRecovery.ts')
const { canonicalDigest: digest } = load('shared/utils/canonicalDigest.ts')
const { strictJson } = load('shared/utils/strictJson.ts')
const plain = (v) => JSON.parse(JSON.stringify(v)), hash = 'sha256:' + 'a'.repeat(64)
// Actual Python domain/application code with explicit probe protocol specimens, not exweb execution.
const native = JSON.parse(execFileSync(path.join(repo, '.venv/bin/python'), ['-c', `
import json
from apps.api.tests.test_environment_health_records import service, save
from apps.api.tests.test_owned_target_environment import spec
from apps.api.tests.test_run_plan_environments import state
s=state.__wrapped__(spec.__wrapped__()); h=service.__wrapped__(s); m=save(h)
print(json.dumps(dict(plan=s.plan,binding=s.binding,view=h.application.read('p',m['record_id']))))
`], { cwd: repo, encoding: 'utf8' }))
function fixture() {
  const v = structuredClone(native), input = plain(original.environmentRequest(v.plan, v.binding))
  v.attempt = { projectId: input.project_id, planId: input.run_plan_id, planHash: input.run_plan_artifact_hash,
    bindingId: input.build_binding_id, bindingHash: input.build_binding_artifact_hash, requestKey: 'health-key', requestHash: v.view.metadata.request_hash }
  v.command = { id: v.view.metadata.invocation_id, tool_id: 'quality.run_plan.record_health', status: 'completed',
    input_payload: { ...input, idempotency_key: v.attempt.requestKey, confirmed_by_user: true },
    result: { status: 'completed', invocation_id: v.view.metadata.invocation_id, object_refs: ['run_plan_health:' + v.view.metadata.record_id],
      run_plan_health_record: { metadata: v.view.metadata, historical_not_live: true } } }
  return v
}
async function response(check, body) {
  const bytes = Buffer.from(body)
  check.response_base64 = bytes.toString('base64'); check.response_hash = 'sha256:' + createHash('sha256').update(bytes).digest('hex'); check.byte_count = bytes.length
}
test('three complete original health checks agree with independently derived Python metadata; old inventory stays unpromoted', async () => {
  const v = fixture(), before = structuredClone(v)
  assert.equal(await validation.healthRecordIdentity(v.command.id), v.view.metadata.record_id)
  assert.notEqual(await original.environmentRecordIdentity(v.command.id), v.view.metadata.record_id)
  assert.deepEqual(plain(await validation.expectedHealthMetadata(v.view.archive)), v.view.metadata)
  assert.equal(await validation.verifyHealthRecord(v.view, v.plan, v.binding, v.command.id, v.view.metadata.record_id), v.view)
  v.plan.current_use.inputs_current = false; v.binding.current_use.inputs_current = false
  assert.equal(await validation.verifyHealthRecord(v.view, v.plan, v.binding, v.command.id, v.view.metadata.record_id), v.view)
  before.plan.current_use.inputs_current = false; before.binding.current_use.inputs_current = false
  assert.deepEqual(v, before)
  assert.equal(v.view.archive.observation.inventory.dependency_health_verified, false)
})
test('real DOWN bytes are displayed as unhealthy, never a failed archive or execution grant', async () => {
  const v = fixture()
  await response(v.view.archive.observation.checks[2], '{"status":"DOWN"}\n503')
  v.view.metadata = plain(await validation.expectedHealthMetadata(v.view.archive))
  await validation.verifyHealthRecord(v.view, v.plan, v.binding, v.command.id, v.view.metadata.record_id)
  assert.equal(v.view.metadata.target_health_verified, false); assert.equal(v.view.metadata.dependency_health_verified, true)
  assert.equal(v.view.metadata.execution_authorized, false); assert.equal(v.view.metadata.passed_count, 0)
})
for (const fault of ['request', 'command', 'record', 'actor', 'time', 'image', 'jar', 'policy', 'inventory-project', 'inventory-extra', 'network',
  'extra', 'schema', 'probe-schema', 'order', 'missing', 'check-extra', 'role', 'probe', 'container', 'epoch', 'probe-image', 'body', 'base64', 'byte-count',
  'too-large', 'target-json', 'duplicate-key', 'unicode-duplicate', 'invalid-utf8', 'target-status', 'summary', 'health-hash', 'authority', 'zero-bool', 'live']) {
  test(`complete health provenance rejects altered scope or bytes: ${fault}`, async () => {
    const v = fixture(), a = v.view.archive, o = a.observation, c = o.checks[2]
    if (fault === 'request') a.request.build_binding_id = 'foreign'
    if (fault === 'command') a.invocation_id = 'foreign'
    if (fault === 'record') a.record_id = 'foreign'
    if (fault === 'actor') a.actor_id = ''
    if (fault === 'time') a.recorded_at = '2026-10-11T00:00:00+08:00'
    if (fault === 'image') a.parents.image_revision_id = 'foreign'
    if (fault === 'jar') { a.parents.target_artifact_hash = hash; o.inventory.artifact_hash = hash }
    if (fault === 'policy') { a.parents.operator_policy_digest = hash; o.inventory.operator_policy_digest = hash }
    if (fault === 'inventory-project') o.inventory.project_id = 'foreign'
    if (fault === 'inventory-extra') o.inventory.execution_authorized = true
    if (fault === 'network') o.inventory.network_id = o.inventory.target.container_id
    if (fault === 'extra') o.live = true
    if (fault === 'schema') a.schema = 'imported-health'
    if (fault === 'probe-schema') o.schema = 'another-probe'
    if (fault === 'order') o.checks.reverse()
    if (fault === 'missing') o.checks.pop()
    if (fault === 'check-extra') c.healthy = true
    if (fault === 'role') c.role = 'pg'
    if (fault === 'probe') c.probe = 'postgres_select_one'
    if (fault === 'container') c.container_id = 'f'.repeat(64)
    if (fault === 'epoch') c.started_at = '2026-10-11T00:00:00Z'
    if (fault === 'probe-image') c.image_id = hash
    if (fault === 'body') c.response_hash = hash
    if (fault === 'base64') c.response_base64 += '\n'
    if (fault === 'byte-count') c.byte_count = true
    if (fault === 'too-large') await response(c, 'x'.repeat(16385))
    if (fault === 'target-json') await response(c, '["UP"]\n200')
    if (fault === 'duplicate-key') await response(c, '{"status":"DOWN","status":"UP"}\n200')
    if (fault === 'unicode-duplicate') await response(c, '{"status":"DOWN","sta\\u0074us":"UP"}\n200')
    if (fault === 'invalid-utf8') await response(c, Buffer.from([0xff, 10, 50, 48, 48]))
    if (fault === 'target-status') await response(c, '{"status":"UP"}\n600')
    o.inventory_hash = await digest(o.inventory)
    v.view.metadata.artifact_hash = await digest(a); v.view.metadata.inventory_hash = o.inventory_hash; v.view.metadata.health_hash = await digest(o)
    if (fault === 'summary') v.view.metadata.health_checks[2].healthy = false
    if (fault === 'health-hash') v.view.metadata.health_hash = hash
    if (fault === 'authority') v.view.metadata.execution_authorized = true
    if (fault === 'zero-bool') v.view.metadata.passed_count = false
    if (fault === 'live') v.view.historical_not_live = false
    await assert.rejects(validation.verifyHealthRecord(v.view, v.plan, v.binding, v.command.id, native.view.metadata.record_id))
  })
}
test('health recovery is independent from environment consent, actor and every original parent hash', () => {
  const v = fixture(), values = new Map(), storage = () => ({ getItem: (k) => values.get(k) ?? null, setItem: (k, v) => values.set(k, v), removeItem: (k) => values.delete(k) })
  const r = recovery.createHealthRecovery(storage), env = load('domains/quality-loop/environmentRecordRecovery.ts').createEnvironmentRecovery(storage)
  const read = (owner, recovery = r) => recovery.read(owner, v.attempt.projectId, v.attempt.planId, v.attempt.planHash, v.attempt.bindingId, v.attempt.bindingHash)
  r.save('owner', v.attempt); env.save('owner', { ...v.attempt, requestKey: 'environment-key' })
  assert.equal(read('owner').requestKey, 'health-key'); assert.equal(read('owner', env).requestKey, 'environment-key'); assert.equal(read('other'), null)
  assert.doesNotMatch([...values.values()].join(''), /inventory|container|response_base64|health_checks|password|127\.0/)
  const ack = { ...v.attempt, commandId: v.command.id }; r.acknowledge('owner', ack)
  r.clear('owner', ack); assert.equal(read('owner'), null); assert.equal(read('owner', env).requestKey, 'environment-key')
})
test('health recovery of a lost acknowledgement is GET only, pinned to its own tool and receipt', async () => {
  const v = fixture(), calls = [], acknowledgements = [], pending = { ...v.command, status: 'waiting_confirmation', result: null }
  const api = load('domains/quality-loop/environmentHealthApi.ts', {
    '../platform/api': { platformApi: { invokeTool: async (body) => { calls.push(body); return pending },
      confirmToolInvocation: async (id) => { calls.push({ confirm: id }); throw new Error('Explicit lost acknowledgement') } } },
    '../../shared/api/client': { request: async (url, options) => { calls.push({ url, options }); return pending } },
  }).environmentHealthApi
  await assert.rejects(api.register(original.environmentRequest(v.plan, v.binding), v.attempt, (v) => acknowledgements.push(v)))
  assert.equal(calls[0].tool_id, 'quality.run_plan.record_health'); assert.equal(acknowledgements[0].commandId, v.command.id)
  await api.recover(v.attempt, v.plan, v.binding, new AbortController().signal)
  assert.equal(calls.length, 3); assert.match(calls[2].url, /tool_id=quality.run_plan.record_health/)
  assert.equal(calls[2].options.method, undefined); assert.equal(calls[2].options.cache, 'no-store')
  await assert.rejects(api.recover(v.attempt, v.plan, v.binding, AbortSignal.abort())); assert.equal(calls.length, 3)
})
test('completed health commands and private archives reject environment receipts, rewritten summaries and unauthorized scope', async () => {
  const v = fixture(), calls = [], api = load('domains/quality-loop/environmentHealthApi.ts', {
    '../platform/api': { platformApi: {} }, '../../shared/api/client': { request: async (url, options) => { calls.push({ url, options }); return v.view } },
  }).environmentHealthApi
  assert.equal((await api.requireCommand(v.command, v.attempt)).command.id, v.command.id)
  assert.equal(await api.read(v.command, v.plan, v.binding, new AbortController().signal), v.view)
  for (const mutate of [(v) => v.tool_id = 'quality.run_plan.record_environment', (v) => v.result.object_refs = ['run_plan_environment:' + native.view.metadata.record_id],
    (v) => v.input_payload.confirmed_by_user = 1, (v) => v.input_payload.build_binding_id = 'other', (v) => v.result.invocation_id = 'other']) {
    const bad = structuredClone(v.command); mutate(bad); await assert.rejects(api.requireCommand(bad, v.attempt))
  }
  const bad = structuredClone(v.command); bad.result.run_plan_health_record.metadata.target_health_verified = false
  await assert.rejects(api.read(bad, v.plan, v.binding, new AbortController().signal))
  const before = calls.length
  for (const mutate of [(v) => v.tool_id = 'quality.run_plan.record_environment', (v) => v.input_payload.run_plan_id = 'other',
    (v) => v.input_payload.confirmed_by_user = false, (v) => v.result.object_refs = ['run_plan_environment:' + native.view.metadata.record_id]]) {
    const foreign = structuredClone(v.command); mutate(foreign)
    await assert.rejects(api.read(foreign, v.plan, v.binding, new AbortController().signal))
  }
  assert.equal(calls.length, before)
  assert.ok(calls.every((v) => v.url.includes('/quality/run-plan-health/') && v.options.cache === 'no-store' && !v.options.method))
})
for (const source of ['{"status":"UP","status":"DOWN"}', '{"status":"UP","sta\\u0074us":"DOWN"}', '{"a":{"x":1,"x":2}}',
  '{"a":1,}', '[true,]', '{} false', 'NaN', '1e999', '"unterminated', '{"a":Infinity}', '{"__proto__":1,"__proto__":2}']) {
  test(`strict health JSON refuses invalid or duplicate input: ${source}`, () => assert.throws(() => strictJson(source)))
}
test('strict JSON accepts nested arrays, escapes and whitespace without changing observations', () => {
  const source = ' {"status":"UP","details":[{"text":"a\\\"b\\\\c"},null,false,1.5e2]} \n'
  assert.deepEqual(plain(strictJson(source)), JSON.parse(source))
})
