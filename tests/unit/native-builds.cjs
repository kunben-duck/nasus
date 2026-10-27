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
const validation = load('domains/quality-loop/nativeBuildValidation.ts'), recovery = load('domains/quality-loop/nativeBuildRecovery.ts')
const plain = (v) => JSON.parse(JSON.stringify(v)), h = 'sha256:' + 'a'.repeat(64)
// Independent production receipt compiler; the tiny JAR is an explicit protocol specimen, not exweb execution.
const sample = JSON.parse(execFileSync(path.join(repo, '.venv/bin/python'), ['-c',
  'import json; from apps.api.tests.test_run_plan_builds import binding_inputs; v,s,b=binding_inputs(); print(json.dumps(b[0]))'], { cwd: repo, encoding: 'utf8' }))
async function fixture() {
  const view = structuredClone(sample), pin = view.receipt.source.pin
  Object.assign(view, { status: 'completed', historical_not_live: true, execution_authorized: false })
  const sources = { project_id: pin.project_id, image_revision_id: pin.image_revision_id, image_artifact_hash: pin.image_artifact_hash,
    manifest_id: pin.manifest_id, manifest_hash: pin.manifest_hash,
    source_members: [{ binding_id: pin.binding_id, source_type: 'code', source_revision_id: pin.source_revision_id, status: 'captured' }] }
  const selection = { project_id: pin.project_id, image_revision_id: pin.image_revision_id, image_artifact_hash: pin.image_artifact_hash,
    binding_id: pin.binding_id, source_revision_id: pin.source_revision_id, artifact_path: view.receipt.artifact.path, expected_artifact_hash: null }
  const policy = { adapter: view.receipt.adapter, image_id: view.receipt.toolchain.image_id, cache_identity_hash: h,
    timeout_seconds: 180, network: 'none', cache_access: 'read_only', cache_contents_attested: false }
  const input = { ...selection, request_digest: view.receipt.request_digest, operator_policy_digest: await digest(policy), source_scope_digest: h }
  const attempt = { projectId: pin.project_id, imageId: pin.image_revision_id, imageHash: pin.image_artifact_hash, requestKey: 'original-key', requestHash: await digest(input) }
  const command = { id: view.invocation_id, tool_id: 'quality.native_build.prepare', status: 'completed', input_payload: { ...input, idempotency_key: attempt.requestKey, confirmed_by_user: true },
    result: { invocation_id: view.invocation_id, status: 'completed', object_refs: ['native_build:' + view.metadata.build_id] } }
  const preview = { request: input, source: { pin, file_count: view.receipt.source.files.length, byte_count: view.receipt.source.files.reduce((n, f) => n + f.byte_count, 0) },
    operator_policy: policy, status: 'preview', source_execution_started: false, execution_authorized: false,
    remaining_gates: ['independent_build_confirmation', 'native_target_execution'] }
  return { view, sources, selection, input, attempt, command, preview }
}
test('native preview and original receipt preserve the exact production Python source digest', async () => {
  const v = await fixture(), before = structuredClone(v)
  assert.equal(await validation.verifyNativePreview(v.preview, v.selection, v.sources), v.preview)
  assert.equal(await validation.verifyNativeJob(v.view, v.input, v.view.invocation_id, 'completed', v.sources), v.view)
  assert.deepEqual(v, before)
})
for (const [fault, change] of Object.entries({
  project: (v) => v.preview.request.project_id = 'foreign', revision: (v) => v.preview.source.pin.source_revision_id = 'foreign',
  manifest: (v) => v.preview.source.pin.manifest_hash = h, binding: (v) => v.sources.source_members[0].binding_id = 'foreign',
  optional: (v) => v.sources.source_members[0].source_type = 'us', count: (v) => v.preview.source.file_count = false,
  bytes: (v) => v.preview.source.byte_count = 32 * 1024 * 1024 + 1, network: (v) => v.preview.operator_policy.network = 'host',
  cache: (v) => v.preview.operator_policy.cache_access = 'read_write', policy: (v) => v.preview.request.operator_policy_digest = h,
  timeout: (v) => v.preview.operator_policy.timeout_seconds = 301, started: (v) => v.preview.source_execution_started = true,
  execution: (v) => v.preview.execution_authorized = true, gates: (v) => v.preview.remaining_gates = [],
})) test(`native preview rejects changed original inputs or authority: ${fault}`, async () => {
  const v = await fixture(); change(v)
  if (['network', 'cache', 'timeout'].includes(fault)) v.preview.request.operator_policy_digest = await digest(v.preview.operator_policy)
  await assert.rejects(validation.verifyNativePreview(v.preview, v.selection, v.sources))
})
for (const [fault, change] of Object.entries({
  original: (v) => v.view.receipt.request_digest = h, image: (v) => v.view.receipt.source.pin.image_artifact_hash = h,
  path: (v) => v.view.receipt.artifact.path = 'target/foreign.jar', pom: (v) => v.view.receipt.source.files[0].path = 'elsewhere.xml',
  bytes: (v) => v.view.receipt.source.files[0].byte_count++, toolchain: (v) => v.view.receipt.toolchain.image_id = 'mutable-tag',
  expected: (v) => v.input.expected_artifact_hash = h, passed: (v) => v.view.receipt.passed_count = 1,
})) test(`native receipt rejects self-consistent but wrong original evidence: ${fault}`, async () => {
  const v = await fixture(); change(v); v.view.metadata.receipt_digest = await digest(v.view.receipt)
  v.view.metadata.artifact = v.view.receipt.artifact
  if (fault === 'original') v.view.metadata.request_digest = h
  await assert.rejects(validation.verifyNativeJob(v.view, v.input, v.view.invocation_id, 'completed', v.sources))
})
test('reserved unknown output is not promoted to success or inferred cleanup', async () => {
  const v = await fixture(), job = { project_id: v.input.project_id, invocation_id: v.view.invocation_id, status: 'failed',
    metadata: null, call_reserved: true, outcome_unknown: true, worker: 'expired', cleanup_confirmed: false, execution_authorized: false }
  assert.equal(await validation.verifyNativeJob(job, v.input, v.view.invocation_id, 'failed', v.sources), job)
  for (const change of [(p) => p.status = 'completed', (p) => p.outcome_unknown = false, (p) => p.cleanup_confirmed = true, (p) => p.call_reserved = 1]) {
    const bad = structuredClone(job); change(bad)
    await assert.rejects(validation.verifyNativeJob(bad, v.input, v.view.invocation_id, bad.status, v.sources))
  }
})
test('build paths reject traversal, aliases, controls, git internals and oversize UTF-8', () => {
  for (const value of ['target/app.jar', 'target/nested/app.jar']) assert.equal(validation.nativeArtifactPath(value), true)
  for (const value of ['target/../app.jar', 'target/./app.jar', 'target/.git/app.jar', 'target//app.jar', '/target/app.jar', 'target/a\\b.jar',
    'target/a\n.jar', 'target/' + '界'.repeat(400) + '.jar', 'target/app.zip']) assert.equal(validation.nativeArtifactPath(value), false)
})
test('recovery pointers are actor/image/hash scoped, metadata-only and cannot be rebound', async () => {
  const { attempt } = await fixture(), values = new Map(), port = { getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key) }
  const state = recovery.createNativeRecovery(() => port)
  state.save('actor', attempt)
  assert.deepEqual(plain(state.read('actor', attempt.projectId, attempt.imageId, attempt.imageHash)), attempt)
  for (const args of [['other', attempt.projectId, attempt.imageId, attempt.imageHash], ['actor', attempt.projectId, 'other', attempt.imageHash], ['actor', attempt.projectId, attempt.imageId, h]])
    assert.equal(state.read(...args), null)
  assert.throws(() => state.save('actor', attempt))
  assert.throws(() => state.acknowledge('actor', { ...attempt, requestHash: h, commandId: 'other' }))
  const fixed = { ...attempt, commandId: 'original-command' }; state.acknowledge('actor', fixed)
  assert.throws(() => state.acknowledge('actor', { ...fixed, commandId: 'replacement' }))
  assert.throws(() => recovery.verifyNativeAttempt({ ...attempt, source_text: 'private' }))
  state.clear('actor', fixed); assert.equal(values.size, 0)
  assert.throws(() => recovery.createNativeRecovery(() => ({ ...port, setItem: () => {} })).save('actor', attempt))
})
test('lost prepare acknowledgement recovery is GET-only and never confirms or invokes a build', async () => {
  const v = await fixture(), reads = [], writes = []
  const api = load('domains/quality-loop/nativeBuildApi.ts', {
    '../../shared/api/client': { request: async (url, options) => { reads.push([url, options]); return url.includes('/resolve?') ? v.command : v.view } },
    '../platform/api': { platformApi: { invokeTool: () => writes.push('invoke'), confirmToolInvocation: () => writes.push('confirm') } },
  })
  const result = await api.nativeBuildApi.recover(v.attempt, v.sources, new AbortController().signal)
  assert.equal(result.command.id, v.view.invocation_id); assert.deepEqual(writes, [])
  assert.equal(reads.length, 2); assert.ok(reads[0][0].includes('request_key=original-key'))
  for (const [url, options] of reads) { assert.equal(options.cache, 'no-store'); assert.equal(options.body, undefined); assert.equal(options.method, undefined); assert.ok(!url.includes('/confirm')) }
})
test('unconfirmed original request is inspected without native archive access or an implicit confirmation', async () => {
  const v = await fixture(); v.command.status = 'waiting_confirmation'; delete v.command.input_payload.confirmed_by_user; delete v.command.result
  let reads = 0
  const api = load('domains/quality-loop/nativeBuildApi.ts', {
    '../../shared/api/client': { request: async () => { reads++; return v.command } }, '../platform/api': { platformApi: {} },
  })
  const value = await api.nativeBuildApi.recover(v.attempt, v.sources, new AbortController().signal)
  assert.equal(value.view, null); assert.equal(reads, 1)
})
test('route disposal after creation stops automatic confirmation but preserves its original acknowledgement', async () => {
  const v = await fixture(), acknowledged = [], writes = []; let live = true
  const api = load('domains/quality-loop/nativeBuildApi.ts', {
    '../../shared/api/client': {}, '../platform/api': { platformApi: {
      invokeTool: async () => { writes.push('create'); live = false; return { ...v.command, status: 'waiting_confirmation', result: undefined } },
      confirmToolInvocation: () => writes.push('confirm'),
    } },
  })
  await assert.rejects(api.nativeBuildApi.prepare(v.input, v.attempt, v.sources, (a) => acknowledged.push(a), () => { if (!live) throw new Error('disposed scope') }))
  assert.deepEqual(writes, ['create']); assert.equal(acknowledged[0].commandId, v.command.id)
})
test('full frozen-source pagination rejects truncation, duplicate sources and changed image metadata', async () => {
  const v = await fixture(), pin = { project_id: v.sources.project_id, image_revision_id: v.sources.image_revision_id, artifact_hash: v.sources.image_artifact_hash }
  const revision = { ...pin, manifest_id: v.sources.manifest_id, manifest_hash: v.sources.manifest_hash }
  const members = Array.from({ length: 26 }, (_, i) => ({ binding_id: 'source-' + i, source_type: 'code', source_revision_id: 'revision-' + i, status: 'captured' }))
  for (const fault of ['none', 'duplicate', 'revision', 'empty', 'over-budget']) {
    const offsets = [], api = load('domains/system-image/frozenImageSources.ts', { './imageRevisionApi': { imageRevisionApi: { page: async (_p, _i, selection) => {
      offsets.push(selection.offset)
      const page = { revision: structuredClone(revision), section: 'source_members', items: members.slice(selection.offset, selection.offset + 25), total: 26,
        next_offset: selection.offset === 0 ? 25 : null }
      if (selection.offset === 25 && fault === 'duplicate') page.items[0] = members[0]
      if (selection.offset === 25 && fault === 'revision') page.revision.manifest_hash = h
      if (fault === 'empty') page.items = []
      if (fault === 'over-budget') page.total = 1001
      return page
    } } } })
    if (fault === 'none') { const result = await api.readFrozenImageSources(pin, new AbortController().signal); assert.equal(result.source_members.length, 26); assert.deepEqual(offsets, [0, 25]) }
    else await assert.rejects(api.readFrozenImageSources(pin, new AbortController().signal))
  }
})

async function cancelFixture() {
  const v = await fixture(), input = { project_id: v.input.project_id, invocation_id: v.view.invocation_id }
  const attempt = { ...v.attempt, requestKey: 'original-cancellation', requestHash: await digest(input) }
  const command = { id: 'cancel-command', tool_id: 'quality.native_build.cancel', status: 'completed',
    input_payload: { ...input, idempotency_key: attempt.requestKey, confirmed_by_user: true },
    result: { invocation_id: 'cancel-command', status: 'completed', object_refs: [], native_build_job: {
      ...input, status: 'cancelled', cancellation_requested: true, cleanup_confirmed: false, execution_authorized: false } } }
  return { ...v, input, attempt, command, target: input.invocation_id }
}
test('canonical cancellation preserves the exact target and never claims cleanup or execution', async () => {
  const v = await cancelFixture(), api = load('domains/quality-loop/nativeBuildCancellationApi.ts', { '../../shared/api/client': {}, '../platform/api': {} })
  const original = structuredClone(v.command), result = await api.verifyNativeCancellation(v.command, v.attempt, v.target)
  assert.equal(result.receipt.cancellation_requested, true); assert.equal(result.receipt.cleanup_confirmed, false)
  assert.deepEqual(v.command, original)
  v.command.result.native_build_job.status = 'completed'; v.command.result.native_build_job.cancellation_requested = false
  assert.equal((await api.verifyNativeCancellation(v.command, v.attempt, v.target)).receipt.cancellation_requested, false)
})
for (const [fault, change] of Object.entries({
  target: (v) => v.command.input_payload.invocation_id = 'other-build', project: (v) => v.command.input_payload.project_id = 'other-project',
  self: (v) => v.command.id = v.target, tool: (v) => v.command.tool_id = 'quality.native_build.prepare',
  key: (v) => v.command.input_payload.idempotency_key = 'other-key', hash: (v) => v.attempt.requestHash = h,
  result: (v) => v.command.result.invocation_id = 'other-cancel', confirmed: (v) => delete v.command.input_payload.confirmed_by_user,
  cleanup: (v) => v.command.result.native_build_job.cleanup_confirmed = true,
  execution: (v) => v.command.result.native_build_job.execution_authorized = true,
  cancelled: (v) => v.command.result.native_build_job.cancellation_requested = 1,
  active: (v) => v.command.result.native_build_job.status = 'running',
})) test(`cancellation rejects changed target, authority or lifecycle: ${fault}`, async () => {
  const v = await cancelFixture(); change(v)
  const api = load('domains/quality-loop/nativeBuildCancellationApi.ts', { '../../shared/api/client': {}, '../platform/api': {} })
  await assert.rejects(api.verifyNativeCancellation(v.command, v.attempt, v.target))
})
test('lost cancellation acknowledgement recovery reads only its original control command', async () => {
  const v = await cancelFixture(), reads = [], writes = [], api = load('domains/quality-loop/nativeBuildCancellationApi.ts', {
    '../../shared/api/client': { request: async (url, options) => { reads.push([url, options]); return v.command } },
    '../platform/api': { platformApi: { invokeTool: () => writes.push('create'), confirmToolInvocation: () => writes.push('confirm') } },
  })
  const result = await api.nativeBuildCancellationApi.recover(v.attempt, v.target, new AbortController().signal)
  assert.equal(result.command.id, v.command.id); assert.deepEqual(writes, [])
  assert.equal(reads.length, 1); assert.ok(reads[0][0].includes('tool_id=quality.native_build.cancel'))
  assert.equal(reads[0][1].cache, 'no-store'); assert.equal(reads[0][1].method, undefined)
  await assert.rejects(api.nativeBuildCancellationApi.create(v.attempt, 'different-build', () => {}, () => {}))
  assert.deepEqual(writes, [])
})
test('cancellation disposal preserves the original control ACK without confirming it', async () => {
  const v = await cancelFixture(), writes = [], acknowledged = []; let live = true
  const pending = { ...v.command, status: 'waiting_confirmation', result: undefined, input_payload: { ...v.command.input_payload, confirmed_by_user: undefined } }
  const api = load('domains/quality-loop/nativeBuildCancellationApi.ts', { '../../shared/api/client': {}, '../platform/api': { platformApi: {
    invokeTool: async () => { writes.push('create'); live = false; return pending }, confirmToolInvocation: () => writes.push('confirm'),
  } } })
  await assert.rejects(api.nativeBuildCancellationApi.create(v.attempt, v.target, (a) => acknowledged.push(a), () => { if (!live) throw new Error('disposed') }))
  assert.deepEqual(writes, ['create']); assert.equal(acknowledged[0].commandId, v.command.id)
})
test('explicit cancellation re-reads its original control before confirming exactly once', async () => {
  const v = await cancelFixture(), actions = []
  const pending = { ...v.command, status: 'waiting_confirmation', result: undefined, input_payload: { ...v.command.input_payload, confirmed_by_user: undefined } }
  const api = load('domains/quality-loop/nativeBuildCancellationApi.ts', { '../../shared/api/client': {}, '../platform/api': { platformApi: {
    getToolInvocation: async (id) => { actions.push(['read', id]); return pending },
    confirmToolInvocation: async (id) => { actions.push(['confirm', id]); return v.command },
  } } })
  const result = await api.nativeBuildCancellationApi.confirm({ ...v.attempt, commandId: v.command.id }, v.target, () => {})
  assert.equal(result.receipt.cleanup_confirmed, false)
  assert.deepEqual(actions, [['read', v.command.id], ['confirm', v.command.id]])
})
test('original build and each target cancellation use isolated metadata recovery namespaces', async () => {
  const v = await cancelFixture(), map = new Map(), port = { getItem: (k) => map.get(k) ?? null, setItem: (k, value) => map.set(k, value), removeItem: (k) => map.delete(k) }
  const build = recovery.createNativeRecovery(() => port), cancel = recovery.createNativeRecovery(() => port, 'nasus.native-build-cancel.v1:' + v.target)
  build.save('actor', v.attempt); cancel.save('actor', v.attempt)
  assert.equal(map.size, 2)
  assert.equal(recovery.createNativeRecovery(() => port, 'nasus.native-build-cancel.v1:another-build').read('actor', v.attempt.projectId, v.attempt.imageId, v.attempt.imageHash), null)
  cancel.acknowledge('actor', { ...v.attempt, commandId: v.command.id })
  assert.equal(build.read('actor', v.attempt.projectId, v.attempt.imageId, v.attempt.imageHash).commandId, undefined)
})
for (const status of ['failed', 'cancelled']) test(`a known ${status} cancellation is recovered without retrying or inventing cleanup`, async () => {
  const v = await cancelFixture(), actions = []
  v.command.status = status; v.command.result = { invocation_id: v.command.id, status, object_refs: [] }
  const api = load('domains/quality-loop/nativeBuildCancellationApi.ts', { '../../shared/api/client': {}, '../platform/api': { platformApi: {
    getToolInvocation: async (id) => { actions.push(['read', id]); return v.command },
    invokeTool: () => actions.push(['create']), confirmToolInvocation: () => actions.push(['confirm']),
  } } })
  const result = await api.nativeBuildCancellationApi.recover({ ...v.attempt, commandId: v.command.id }, v.target, new AbortController().signal)
  assert.deepEqual(actions, [['read', v.command.id]]); assert.equal(result.command.status, status); assert.equal(result.receipt, undefined)
})
test('clearing an exact cancellation pointer preserves the original build and allows a distinct fresh request key', async () => {
  const v = await cancelFixture(), map = new Map(), port = { getItem: (k) => map.get(k) ?? null, setItem: (k, value) => map.set(k, value), removeItem: (k) => map.delete(k) }
  const build = recovery.createNativeRecovery(() => port), cancel = recovery.createNativeRecovery(() => port, 'nasus.native-build-cancel.v1:' + v.target)
  build.save('actor', v.attempt); cancel.save('actor', v.attempt)
  const original = { ...v.attempt, commandId: v.command.id }; cancel.acknowledge('actor', original)
  assert.throws(() => cancel.clear('actor', { ...original, commandId: 'unverified-control' }))
  assert.equal(map.size, 2); cancel.clear('actor', original)
  cancel.save('actor', { ...v.attempt, requestKey: 'new-independently-confirmed-cancellation' })
  assert.deepEqual(plain(build.read('actor', v.attempt.projectId, v.attempt.imageId, v.attempt.imageHash)), v.attempt)
  assert.equal(cancel.read('actor', v.attempt.projectId, v.attempt.imageId, v.attempt.imageHash).requestKey, 'new-independently-confirmed-cancellation')
})
