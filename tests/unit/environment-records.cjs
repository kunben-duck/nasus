const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { execFileSync } = require('node:child_process')
const { webcrypto } = require('node:crypto')
const ts = require('../../apps/portal/node_modules/typescript')
const repo = path.resolve(__dirname, '../..'), root = path.join(repo, 'apps/portal/src')
function load(relative, overrides = {}, modules = new Map()) {
  const file = path.resolve(root, relative)
  if (modules.has(file)) return modules.get(file)
  const context = { exports: {}, crypto: webcrypto, TextEncoder, URLSearchParams, require: (name) => {
    if (Object.hasOwn(overrides, name)) return overrides[name]
    return load(path.relative(root, path.resolve(path.dirname(file), `${name}.ts`)), overrides, modules)
  } }
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, context)
  modules.set(file, context.exports); return context.exports
}
const { canonicalDigest: digest } = load('shared/utils/canonicalDigest.ts')
const validation = load('domains/quality-loop/environmentRecordValidation.ts'), recovery = load('domains/quality-loop/environmentRecordRecovery.ts')
const plain = (v) => JSON.parse(JSON.stringify(v)), hash = 'sha256:' + 'a'.repeat(64)
// Independent Python application/inspector port specimens, not a native deployment or business gold.
const native = JSON.parse(execFileSync(path.join(repo, '.venv/bin/python'), ['-c', `
import json
from types import SimpleNamespace
from apps.api.tests.test_owned_target_environment import spec
from apps.api.tests.test_run_plan_environments import state
from apps.api.tests.test_environment_observation_records import Artifacts, Repository, save
from apps.api.app.application.quality_loop.environment_observation_records import EnvironmentObservationRecordApplicationService
s = state.__wrapped__(spec.__wrapped__())
service = SimpleNamespace(application=EnvironmentObservationRecordApplicationService(s.service, Artifacts(), Repository()), state=s)
metadata = save(service)
print(json.dumps(dict(plan=s.plan,binding=s.binding,view=service.application.read('p',metadata['record_id']))))
`], { cwd: repo, encoding: 'utf8' }))
function fixture() {
  const v = structuredClone(native), input = plain(validation.environmentRequest(v.plan, v.binding))
  v.attempt = { projectId: input.project_id, planId: input.run_plan_id, planHash: input.run_plan_artifact_hash,
    bindingId: input.build_binding_id, bindingHash: input.build_binding_artifact_hash, requestKey: 'original-key', requestHash: v.view.metadata.request_hash }
  v.command = { id: v.view.metadata.invocation_id, tool_id: 'quality.run_plan.record_environment', status: 'completed',
    input_payload: { ...input, idempotency_key: v.attempt.requestKey, confirmed_by_user: true },
    result: { status: 'completed', invocation_id: v.view.metadata.invocation_id, object_refs: ['run_plan_environment:' + v.view.metadata.record_id],
      run_plan_environment_record: { metadata: v.view.metadata, historical_not_live: true } } }
  return v
}
test('complete original inventory and metadata agree with independent Python; inputs stay unchanged', async () => {
  const v = fixture(), before = structuredClone(v)
  assert.equal(await validation.environmentRecordIdentity(v.command.id), v.view.metadata.record_id)
  assert.deepEqual(plain(await validation.expectedEnvironmentMetadata(v.view.archive)), v.view.metadata)
  assert.equal(await validation.verifyEnvironmentRecord(v.view, v.plan, v.binding, v.command.id, v.view.metadata.record_id), v.view)
  v.plan.current_use.inputs_current = false; v.binding.current_use.inputs_current = false
  assert.equal(await validation.verifyEnvironmentRecord(v.view, v.plan, v.binding, v.command.id, v.view.metadata.record_id), v.view)
  before.plan.current_use.inputs_current = false; before.binding.current_use.inputs_current = false
  assert.deepEqual(v, before)
})
for (const fault of ['request', 'record', 'command', 'project', 'actor', 'time', 'observation-time', 'parent', 'jar', 'inventory-project',
  'policy', 'namespace', 'schema', 'archive-extra', 'parent-extra', 'inventory-extra', 'target-extra', 'dependencies',
  'roles', 'duplicate-containers', 'network-container', 'root', 'uid', 'false-zero', 'true-one', 'count-bool', 'ports', 'health',
  'execution', 'coverage', 'metadata', 'live', 'hash', 'bytes']) {
  test(`environment record rejects self-consistent but invalid evidence: ${fault}`, async () => {
    const v = fixture(), a = v.view.archive, i = a.observation.inventory
    if (fault === 'request') a.request.build_binding_id = 'foreign'
    if (fault === 'record') a.record_id = 'foreign'
    if (fault === 'command') a.invocation_id = 'foreign'
    if (fault === 'project') a.project_id = 'foreign'
    if (fault === 'actor') a.actor_id = ''
    if (fault === 'time') a.recorded_at = '2026-10-10T00:00:00'
    if (fault === 'observation-time') a.observation.observed_at = '2026-10-10T00:00:00+08:00'
    if (fault === 'parent') a.parents.image_revision_id = 'foreign'
    if (fault === 'jar') { a.parents.target_artifact_hash = hash; i.artifact_hash = hash }
    if (fault === 'inventory-project') i.project_id = 'foreign'
    if (fault === 'policy') { a.parents.operator_policy_digest = hash; i.operator_policy_digest = hash }
    if (fault === 'namespace') i.namespace_origin = 'http://host.docker.internal:8000'
    if (fault === 'schema') a.schema = 'imported-report'
    if (fault === 'archive-extra') a.execution_authorized = true
    if (fault === 'parent-extra') a.parents.execution_authorized = true
    if (fault === 'inventory-extra') i.claimed_verified = true
    if (fault === 'target-extra') i.target.role = 'pg'
    if (fault === 'dependencies') i.dependency_instances.pop()
    if (fault === 'roles') i.dependency_instances[1].role = 'pg'
    if (fault === 'duplicate-containers') i.dependency_instances[0].container_id = i.target.container_id
    if (fault === 'network-container') i.network_id = i.target.container_id
    if (fault === 'root') i.target.user = '0:0'
    if (fault === 'uid') i.dependency_instances[0].user = '65536:999'
    if (fault === 'false-zero') i.execution_authorized = 0
    if (fault === 'true-one') i.native_artifact_attested = 1
    if (fault === 'count-bool') i.passed_count = false
    if (fault === 'ports') i.host_ports_exposed = true
    if (fault === 'health') i.dependency_health_verified = true
    if (fault === 'execution') i.execution_authorized = true
    if (fault === 'coverage') i.business_coverage_verified = true
    if (fault === 'bytes') i.target.started_at = 'x'.repeat(140000)
    a.observation.inventory_hash = await digest(i)
    v.view.metadata = plain(await validation.expectedEnvironmentMetadata(a))
    if (fault === 'metadata') v.view.metadata.environment_fully_verified = true
    if (fault === 'live') v.view.historical_not_live = false
    if (fault === 'hash') v.view.metadata.artifact_hash = hash
    await assert.rejects(validation.verifyEnvironmentRecord(v.view, v.plan, v.binding, v.command.id, native.view.metadata.record_id))
  })
}
test('original parent selection rejects foreign projects, plan pins and bindings', () => {
  for (const field of ['project_id', 'run_plan_id', 'run_plan_artifact_hash', 'plan_digest', 'image_revision_id', 'manifest_id']) {
    const v = fixture(); v.binding.metadata[field] = 'foreign'
    assert.throws(() => validation.environmentRequest(v.plan, v.binding))
  }
})
test('actor scoped recovery stores only exact identifiers and hashes, never inventory', async () => {
  const v = fixture(), values = new Map(), r = recovery.createEnvironmentRecovery(() => ({
    getItem: (k) => values.get(k) ?? null, setItem: (k, v) => values.set(k, v), removeItem: (k) => values.delete(k),
  }))
  const read = (actor, binding = v.attempt.bindingId, bindingHash = v.attempt.bindingHash) => r.read(actor, v.attempt.projectId,
    v.attempt.planId, v.attempt.planHash, binding, bindingHash)
  r.save('owner', v.attempt); assert.deepEqual(plain(read('owner')), v.attempt)
  assert.equal(read('other'), null); assert.equal(read('owner', 'other-binding'), null); assert.throws(() => read('owner', v.attempt.bindingId, hash))
  assert.throws(() => r.save('owner', v.attempt)); assert.throws(() => recovery.verifyEnvironmentAttempt({ ...v.attempt, inventory: v.view.archive.observation.inventory }))
  const ack = { ...v.attempt, commandId: v.command.id }; r.acknowledge('owner', ack)
  assert.throws(() => r.acknowledge('owner', { ...ack, commandId: 'foreign' })); assert.throws(() => r.clear('owner', v.attempt))
  assert.doesNotMatch([...values.values()][0], /inventory|container|namespace|password|receipt|localhost|127\.0/)
  r.clear('owner', ack); assert.equal(values.size, 0)
})
test('lost acknowledgement is recovered with original GET only; abort never sends a write', async () => {
  const v = fixture(), calls = [], seen = [], pending = { ...v.command, status: 'waiting_confirmation', result: null }
  const { environmentRecordApi: api } = load('domains/quality-loop/environmentRecordApi.ts', {
    '../platform/api': { platformApi: {
      invokeTool: async (body) => { calls.push({ body }); return pending },
      confirmToolInvocation: async (id) => { calls.push({ confirm: id }); throw new Error('Lost confirmation acknowledgement') },
    } }, '../../shared/api/client': { request: async (url, options) => { calls.push({ url, options }); return pending } },
  })
  await assert.rejects(api.register(validation.environmentRequest(v.plan, v.binding), v.attempt, (a) => seen.push(plain(a))))
  assert.equal(calls.length, 2); assert.equal(seen[0].commandId, v.command.id)
  const original = await api.recover(v.attempt, v.plan, v.binding, new AbortController().signal)
  assert.equal(original.command.status, 'waiting_confirmation'); assert.equal(calls.length, 3)
  assert.equal(calls[2].options.method, undefined); assert.equal(calls[2].options.cache, 'no-store')
  await assert.rejects(api.recover(v.attempt, v.plan, v.binding, AbortSignal.abort()), { name: 'AbortError' }); assert.equal(calls.length, 3)
})
test('private archive read rechecks the original metadata receipt instead of trusting command JSON', async () => {
  const v = fixture(), calls = []
  const { environmentRecordApi: api, requireEnvironmentCommand } = load('domains/quality-loop/environmentRecordApi.ts', {
    '../platform/api': { platformApi: {} }, '../../shared/api/client': { request: async (url, options) => { calls.push({ url, options }); return v.view } },
  })
  assert.equal((await requireEnvironmentCommand(v.command, v.attempt)).command.id, v.command.id)
  assert.equal(await api.read(v.command, v.plan, v.binding, new AbortController().signal), v.view)
  for (const change of [(c) => c.result.object_refs = ['run_plan_environment:foreign'], (c) => c.input_payload.confirmed_by_user = 1,
    (c) => c.input_payload.build_binding_id = 'foreign', (c) => c.result.invocation_id = 'foreign']) {
    const bad = structuredClone(v.command); change(bad); await assert.rejects(requireEnvironmentCommand(bad, v.attempt))
  }
  const bad = structuredClone(v.command); bad.result.run_plan_environment_record.metadata.execution_authorized = true
  await assert.rejects(api.read(bad, v.plan, v.binding, new AbortController().signal))
  assert.equal(calls.length, 2); assert.ok(calls.every((c) => c.options.cache === 'no-store' && !c.options.method))
})
