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
const validation = load('domains/quality-loop/runPlanBuildValidation.ts'), recovery = load('domains/quality-loop/runPlanBuildRecovery.ts')
const plain = (v) => JSON.parse(JSON.stringify(v)), hash = 'sha256:' + 'a'.repeat(64)
// Independent production Python compiler; protocol JARs are not native builds or business gold.
const native = JSON.parse(execFileSync(path.join(repo, '.venv/bin/python'), ['-c',
  'import json; from apps.api.tests.test_run_plan_builds import binding_inputs; from apps.api.app.domain.quality_loop.run_plan_build import compile_run_plan_build; v,s,b=binding_inputs(multiple=True); print(json.dumps(dict(plan=v,selection=s.model_dump(mode="json"),builds=b,binding=compile_run_plan_build(v,s.model_dump(mode="json"),b)),ensure_ascii=False))'], { cwd: repo, encoding: 'utf8' }))
const nativeFixtures = JSON.parse(execFileSync(path.join(repo, '.venv/bin/python'), ['-c',
  'import json; from apps.api.tests.test_http_fixture_binding_scripts import fixture_build_inputs; from apps.api.app.domain.quality_loop.run_plan_build import compile_run_plan_build; v,s,b=fixture_build_inputs(); print(json.dumps(dict(plan=v,selection=s.model_dump(mode="json"),builds=b,binding=compile_run_plan_build(v,s.model_dump(mode="json"),b)),ensure_ascii=False))'], { cwd: repo, encoding: 'utf8' }))
function fixture(protocol = 'v1') {
  const v = structuredClone(protocol === 'v3' ? nativeFixtures : native)
  Object.assign(v.plan.metadata, { project_id: 'p', run_plan_id: 'plan' })
  for (const build of v.builds) Object.assign(build, { execution_authorized: false, historical_not_live: true, status: 'completed' })
  v.request = { ...v.selection, binding_digest: v.binding.binding_digest, source_scope_digest: hash }
  v.preview = { request: v.request, status: 'preview', code_source_count: v.builds.length, native_build_source_attested: true,
    target_artifact_hash: v.binding.target_artifact_hash, execution_authorized: false,
    remaining_gates: ['independent_build_binding_confirmation', ...v.binding.remaining_gates] }
  return v
}
test('frontend complete multi-source binding matches independent Python bytes and preserves the original plan', async () => {
  const v = fixture(), original = structuredClone(v)
  assert.deepEqual(plain(await validation.expectedBuildBinding(v.plan, v.selection, v.builds)), v.binding)
  assert.equal(await validation.verifyBuildPreview(v.preview, v.plan, v.selection, v.builds), v.preview)
  assert.deepEqual(v, original)
})
test('v3 build binding matches the independent Python compiler without losing its fixture-import plan pins', async () => {
  const v = fixture('v3'), original = structuredClone(v)
  assert.deepEqual(plain(await validation.expectedBuildBinding(v.plan, v.selection, v.builds)), v.binding)
  assert.equal(await validation.verifyBuildPreview(v.preview, v.plan, v.selection, v.builds), v.preview)
  assert.equal(v.plan.artifact.schema, 'nasus.run-plan-artifact.v3')
  assert.equal(v.plan.artifact.plan.proposal.http_protocol, 'nasus.runner-http-execution.v3')
  assert.equal(v.binding.execution_authorized, false)
  assert.deepEqual(v, original)
})
for (const fault of ['missing', 'extra', 'duplicate', 'revision', 'image', 'manifest', 'project', 'artifact', 'receipt', 'uncommitted',
  'boolean', 'executed', 'passed', 'false-zero', 'jar', 'pom', 'runtime', 'network', 'cache', 'target', 'plan-digest', 'plan-authority']) {
  test(`binding rejects original scope or evidence mismatch: ${fault}`, async () => {
    const v = fixture(), b = v.builds[0], r = b.receipt
    if (fault === 'missing') { v.builds.pop(); v.selection.native_builds.pop() }
    if (fault === 'extra') { v.builds.push(structuredClone(b)); v.selection.native_builds.push(structuredClone(v.selection.native_builds[0])) }
    if (fault === 'duplicate') v.builds[1].receipt.source.pin = structuredClone(r.source.pin)
    if (fault === 'revision') r.source.pin.source_revision_id = 'foreign'
    if (fault === 'image') r.source.pin.image_revision_id = 'foreign'
    if (fault === 'manifest') r.source.pin.manifest_hash = hash
    if (fault === 'project') r.source.pin.project_id = 'foreign'
    if (fault === 'artifact') v.selection.native_builds[0].artifact_hash = hash
    if (fault === 'receipt') v.selection.native_builds[0].receipt_digest = hash
    if (fault === 'uncommitted') b.metadata = null
    if (fault === 'boolean') r.native_build_verified = 'true'
    if (fault === 'executed') r.execution_authorized = true
    if (fault === 'passed') r.passed_count = 1
    if (fault === 'false-zero') r.passed_count = false
    if (fault === 'jar') r.artifact.content_hash = hash
    if (fault === 'pom') r.source.files = []
    if (fault === 'runtime') r.toolchain.java = '17'
    if (fault === 'network') r.toolchain.network = 'host'
    if (fault === 'cache') r.toolchain.dependency_cache = 'mutable'
    if (fault === 'target') v.selection.target_build_invocation_id = 'foreign'
    if (fault === 'plan-digest') v.plan.artifact.plan.plan_digest = hash
    if (fault === 'plan-authority') v.plan.artifact.plan.execution_authorized = true
    // Self-consistent response hashes cannot repair wrong original source pins or authority.
    if (b.metadata && !['artifact', 'receipt'].includes(fault)) {
      b.metadata.receipt_digest = await digest(r)
      v.selection.native_builds[0].receipt_digest = b.metadata.receipt_digest
    }
    if (fault.startsWith('plan-')) {
      v.plan.metadata.artifact_hash = await digest(v.plan.artifact); v.selection.run_plan_artifact_hash = v.plan.metadata.artifact_hash
    }
    await assert.rejects(validation.expectedBuildBinding(v.plan, v.selection, v.builds))
  })
}
async function archive(v) {
  const artifact = { schema: 'nasus.run-plan-build-artifact.v1', project_id: 'p', binding_id: 'binding', invocation_id: 'command',
    actor_id: 'reviewer', recorded_at: '2026-10-10T00:00:00Z', request: v.request, binding: v.binding }
  return { artifact, metadata: { ...Object.fromEntries(['project_id', 'binding_id', 'invocation_id', 'actor_id', 'recorded_at'].map((k) => [k, artifact[k]])),
    ...Object.fromEntries(['run_plan_id', 'run_plan_artifact_hash', 'plan_digest', 'binding_digest', 'target_artifact_hash'].map((k) => [k, v.binding[k]])),
    image_revision_id: v.binding.source_pin.image_revision_id, manifest_id: v.binding.source_pin.manifest_id,
    artifact_hash: await digest(artifact), request_hash: await digest(v.request) }, historical_not_live: true,
    current_use: { inputs_current: true, native_build_source_attested: true, environment_verified: false, fixtures_verified: false, execution_authorized: false } }
}
test('saved binding validates full original members and never promotes environment or execution', async () => {
  const v = fixture(), a = await archive(v)
  assert.equal(await validation.verifyBuildArchive(a, v.request, 'command', v.plan, v.builds), a)
  for (const change of [(p) => p.artifact.binding.builds.pop(), (p) => p.artifact.binding.passed_count = 1,
    (p) => p.current_use.environment_verified = true, (p) => p.current_use.fixtures_verified = true,
    (p) => p.metadata.invocation_id = 'foreign', (p) => p.artifact.request.reason = 'changed']) {
    const bad = structuredClone(a); change(bad); bad.metadata.artifact_hash = await digest(bad.artifact)
    await assert.rejects(validation.verifyBuildArchive(bad, v.request, 'command', v.plan, v.builds))
  }
  v.plan.current_use.inputs_current = false; a.current_use.inputs_current = false
  assert.equal(await validation.verifyBuildArchive(a, v.request, 'command', v.plan, v.builds), a)
})
test('build preview rejects changed requests, missing gates, fake counts and source scope', async () => {
  const v = fixture()
  for (const change of [(p) => p.request.reason = 'changed', (p) => p.remaining_gates.pop(), (p) => p.code_source_count--,
    (p) => p.execution_authorized = true, (p) => p.request.source_scope_digest = 'invalid']) {
    const bad = structuredClone(v.preview); change(bad); await assert.rejects(validation.verifyBuildPreview(bad, v.plan, v.selection, v.builds))
  }
})
test('build acknowledgement recovery stores only actor-scoped IDs and hashes', async () => {
  const v = fixture(), values = new Map(), storage = { getItem: (k) => values.get(k) ?? null, setItem: (k, v) => values.set(k, v), removeItem: (k) => values.delete(k) }
  const r = recovery.createBuildRecovery(() => storage), attempt = { projectId: 'p', planId: 'plan', planHash: v.selection.run_plan_artifact_hash, requestKey: 'key', requestHash: await digest(v.request) }
  r.save('owner', attempt); assert.deepEqual(plain(r.read('owner', 'p', 'plan', attempt.planHash)), attempt)
  assert.equal(r.read('other', 'p', 'plan', attempt.planHash), null); assert.throws(() => r.read('owner', 'p', 'plan', hash))
  assert.throws(() => r.save('owner', attempt)); assert.throws(() => recovery.verifyBuildAttempt({ ...attempt, native_builds: v.builds }))
  const ack = { ...attempt, commandId: 'command' }; r.acknowledge('owner', ack)
  assert.throws(() => r.acknowledge('owner', { ...ack, commandId: 'foreign' })); assert.throws(() => r.clear('owner', attempt))
  assert.doesNotMatch([...values.values()][0], /reason|target|receipt|code-source|native_builds/)
  r.clear('owner', ack); assert.equal(values.size, 0)
})
test('lost write acknowledgement has no automatic resubmit; recovery rechecks original builds with GET only', async () => {
  const v = fixture(), calls = [], seen = [], attempt = { projectId: 'p', planId: 'plan', planHash: v.selection.run_plan_artifact_hash, requestKey: 'key', requestHash: await digest(v.request) }
  const command = { id: 'command', tool_id: 'quality.run_plan.bind_native_build', status: 'waiting_confirmation', input_payload: { ...v.request, idempotency_key: 'key' } }
  const { runPlanBuildApi: api } = load('domains/quality-loop/runPlanBuildApi.ts', { '../platform/api': { platformApi: {
    invokeTool: async (input) => { calls.push(input); return command }, confirmToolInvocation: async (id) => { calls.push(id); throw new Error('Lost acknowledgement') },
  } }, '../../shared/api/client': { request: async (url, options) => {
    calls.push({ url, options }); return url.includes('/resolve?') ? command : v.builds.find((b) => url.endsWith(b.invocation_id))
  } } })
  await assert.rejects(api.bind(v.request, attempt, (a) => seen.push(plain(a))))
  assert.equal(calls.length, 2); assert.equal(seen[0].commandId, 'command')
  const original = await api.recover(attempt, v.plan, new AbortController().signal)
  assert.equal(original.command.status, 'waiting_confirmation'); assert.equal(calls.length, 5)
  for (const c of calls.slice(2)) { assert.equal(c.options.method, undefined); assert.equal(c.options.cache, 'no-store') }
  await assert.rejects(api.recover(attempt, v.plan, AbortSignal.abort()), { name: 'AbortError' }); assert.equal(calls.length, 5)
})
