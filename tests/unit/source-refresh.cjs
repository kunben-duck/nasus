const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')
const root = path.resolve(__dirname, '../../apps/portal/src')
const digest = 'sha256:' + 'a'.repeat(64)

function load(overrides = {}) {
  const exports = {}
  const recoveryExports = {}
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(root, 'domains/system-image/sourceRefreshRecovery.ts'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, { exports: recoveryExports })
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(root, 'domains/system-image/sourceRefreshApi.ts'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, { exports, URLSearchParams, require: (name) => name === './sourceRefreshRecovery' ? recoveryExports : overrides[name] })
  return exports
}
const api = load()
function snapshot() {
  return { project: { id: 'project' }, read_state: { mode: 'working_draft' }, visibility: { mode: 'project' },
    source_manifest: { project_id: 'project', manifest_id: 'manifest', content_hash: digest },
    sources: [{ id: 'code', project_id: 'project', source_type: 'code', registered_at: '2026-10-09' },
      { id: 'us', project_id: 'project', source_type: 'us_doc', registered_at: '2026-10-09' },
      { id: 'empty-test-slot', project_id: 'project', source_type: 'test_asset', registered_at: null }] }
}
const input = { project_id: 'project', source_ids: ['us', 'code'], expected_manifest_id: 'manifest', expected_manifest_hash: digest }
const attempt = { input, requestKey: 'request-key' }
function command() {
  return { id: 'command', tool_id: 'system_image.sources.ingest', status: 'completed',
    input_payload: { ...input, source_ids: [...input.source_ids], idempotency_key: attempt.requestKey },
    result: { invocation_id: 'command', status: 'completed', object_refs: ['project:project', 'raw_asset:code',
      'raw_asset:us', 'source_manifest:manifest', 'source_manifest:after'], next_recommended_tools: ['system_image.build.structure'] } }
}

test('selection pins the displayed working manifest and excludes empty slots without grouping multiple code bindings', () => {
  const image = snapshot(), selected = ['us', 'code']
  const body = api.prepareSourceRefresh('project', image, selected)
  assert.deepEqual(JSON.parse(JSON.stringify(body)), input)
  selected.pop()
  assert.equal(body.source_ids.length, 2)
  image.sources.push({ ...image.sources[0], id: 'second-code' })
  assert.equal(api.refreshableSources('project', image).length, 3)
  assert.deepEqual(JSON.parse(JSON.stringify(api.prepareSourceRefresh('project', image, ['second-code']).source_ids)), ['second-code'])
})
test('identical frozen scope survives read timestamps and order changes, while source or manifest changes invalidate it', () => {
  const image = snapshot(), original = api.sourceRefreshScope('project', image)
  image.sources.reverse()
  image.sources[0].last_ingested_at = 'later'
  assert.equal(api.sourceRefreshScope('project', image), original)
  image.source_manifest.manifest_id = 'different'
  assert.notEqual(api.sourceRefreshScope('project', image), original)
  image.source_manifest.manifest_id = 'manifest'
  image.sources.push({ ...image.sources[1], id: 'additional-source', registered_at: 'today' })
  assert.notEqual(api.sourceRefreshScope('project', image), original)
})
const badSnapshots = {
  'foreign project': (image) => { image.project.id = 'other' },
  'foreign manifest': (image) => { image.source_manifest.project_id = 'other' },
  'published view': (image) => { image.read_state.mode = 'published' },
  'legacy view': (image) => { image.read_state.mode = 'legacy_draft' },
  'restricted source view': (image) => { image.visibility.mode = 'source_filtered' },
  'missing manifest': (image) => { image.source_manifest = null },
  'invalid manifest digest': (image) => { image.source_manifest.content_hash = 'unverified' },
  'duplicate source': (image) => { image.sources.push(image.sources[0]) },
  'foreign source': (image) => { image.sources[0].project_id = 'other' },
  'unknown source kind': (image) => { image.sources[0].source_type = 'run' },
  'controlled identity': (image) => { image.sources[0].id = 'bad\x00id' },
}
for (const [name, mutate] of Object.entries(badSnapshots)) test(`reject ${name} before preparing a command`, () => {
  const image = snapshot(); mutate(image)
  assert.throws(() => api.prepareSourceRefresh('project', image, ['us']))
})
for (const selected of [null, [], ['us', 'us'], ['foreign'], ['empty-test-slot'], ['us\x7f'], Array(101).fill('us')]) {
  test(`invalid selection cannot become an all-source refresh: ${JSON.stringify(selected)}`, () => {
    assert.throws(() => api.prepareSourceRefresh('project', snapshot(), selected))
  })
}
test('complete receipt accepts the original selected set and an unchanged manifest without authorizing a build', () => {
  const value = command()
  value.result.object_refs[4] = 'source_manifest:manifest'
  assert.equal(api.requireSourceRefreshCommand(value, attempt), value)
})
const corruptions = {
  'different command tool': (value) => { value.tool_id = 'system_image.context.materialize' },
  'different request key': (value) => { value.input_payload.idempotency_key = 'other' },
  'different project': (value) => { value.input_payload.project_id = 'other' },
  'different manifest': (value) => { value.input_payload.expected_manifest_id = 'other' },
  'different hash': (value) => { value.input_payload.expected_manifest_hash = 'sha256:' + 'b'.repeat(64) },
  'different source order': (value) => { value.input_payload.source_ids.reverse() },
  'all sources fallback': (value) => { delete value.input_payload.source_ids },
  'different result command': (value) => { value.result.invocation_id = 'other' },
  'different result status': (value) => { value.result.status = 'failed' },
  'unselected source': (value) => { value.result.object_refs[1] = 'raw_asset:foreign' },
  'duplicate selected source': (value) => { value.result.object_refs[1] = 'raw_asset:us' },
  'missing before manifest': (value) => { value.result.object_refs[3] = 'source_manifest:other' },
  'missing after manifest': (value) => { value.result.object_refs.pop() },
  'invented published image': (value) => { value.result.object_refs.push('image_publication:fake') },
  'legacy automatic materialization': (value) => { value.result.next_recommended_tools = ['system_image.context.materialize'] },
}
for (const [name, mutate] of Object.entries(corruptions)) test(`reject ${name} rather than acknowledge success`, () => {
  const value = command(); mutate(value)
  assert.throws(() => api.requireSourceRefreshCommand(value, attempt))
})

test('submit sends one canonical request with the original precondition, never a suggested follow-up', async () => {
  const calls = []
  const v = load({ '../platform/api': { platformApi: { invokeTool: async (payload) => { calls.push(payload); return command() } } } })
  await v.sourceRefreshApi.submit(attempt)
  assert.equal(calls.length, 1)
  assert.equal(calls[0].tool_id, 'system_image.sources.ingest')
  assert.deepEqual(JSON.parse(JSON.stringify(calls[0].input)), input)
})
test('lost acknowledgement recovery only reads the exact original command', async () => {
  const calls = [], controller = new AbortController()
  const v = load({ '../../shared/api/client': { request: async (url, options) => {
    calls.push(url); assert.equal(options.signal, controller.signal); assert.equal(options.cache, 'no-store')
    const parsed = new URL(url, 'http://test.local')
    assert.equal(parsed.pathname, '/v1/tool-invocations/resolve')
    assert.deepEqual(Object.fromEntries(parsed.searchParams), { project_id: input.project_id,
      tool_id: 'system_image.sources.ingest', request_key: attempt.requestKey })
    return command()
  } }, '../platform/api': { platformApi: { getToolInvocation: async (id, options) => {
    calls.push(id); assert.equal(options.signal, controller.signal); return command()
  }, invokeTool: () => assert.fail('recovery must not POST') } } })
  assert.equal((await v.sourceRefreshApi.recover(attempt, controller.signal)).id, 'command')
  assert.equal(calls.length, 2)
})
for (const variant of ['empty', 'array', 'foreign', 'changed-on-read', 'different-id-on-read']) {
  test(`recovery rejects ${variant} without resubmitting`, async () => {
    let calls = 0
    const v = load({ '../../shared/api/client': { request: async () => {
      calls++
      if (variant === 'empty') return null
      if (variant === 'array') return [command()]
      if (variant === 'foreign') return { ...command(), input_payload: { ...input, project_id: 'other', idempotency_key: attempt.requestKey } }
      return command()
    } }, '../platform/api': { platformApi: { getToolInvocation: async () => {
      calls++; const value = command()
      if (variant === 'different-id-on-read') { value.id = 'substituted'; value.result.invocation_id = value.id }
      else value.input_payload.expected_manifest_id = 'changed'
      return value
    }, invokeTool: () => assert.fail('recovery must not POST') } } })
    await assert.rejects(v.sourceRefreshApi.recover(attempt, new AbortController().signal))
    assert.equal(calls, ['changed-on-read', 'different-id-on-read'].includes(variant) ? 2 : 1)
  })
}
test('aborted or malformed recovery sends no read or write', async () => {
  const v = load({ '../../shared/api/client': { request: () => assert.fail('must not read') } })
  const controller = new AbortController(); controller.abort()
  await assert.rejects(v.sourceRefreshApi.recover(attempt, controller.signal))
  await assert.rejects(v.sourceRefreshApi.recover({ ...attempt, input: { ...input, source_ids: [] } }, new AbortController().signal))
})
test('cancellation after discovery does not start the original command detail read', async () => {
  const controller = new AbortController()
  const v = load({ '../../shared/api/client': { request: async () => {
    controller.abort()
    return command()
  } }, '../platform/api': { platformApi: {
    getToolInvocation: () => assert.fail('cancelled recovery must not start another read'),
    invokeTool: () => assert.fail('recovery must not POST'),
  } } })
  await assert.rejects(v.sourceRefreshApi.recover(attempt, controller.signal), { name: 'AbortError' })
})

test('an acknowledged marker reads its exact command ID without discovery or another POST', async () => {
  let reads = 0
  const v = load({ '../../shared/api/client': { request: () => assert.fail('known command must not rediscover latest') },
    '../platform/api': { platformApi: { getToolInvocation: async (id) => {
      reads++; assert.equal(id, 'command'); return command()
    }, invokeTool: () => assert.fail('must not POST') } } })
  const known = { ...attempt, commandId: 'command' }
  assert.equal((await v.sourceRefreshApi.recover(known, new AbortController().signal)).id, 'command')
  await assert.rejects(v.sourceRefreshApi.submit(known))
  assert.equal(reads, 1)
})
test('known command lookup still rejects substituted command IDs and post-read cancellation', async () => {
  const known = { ...attempt, commandId: 'command' }
  assert.throws(() => api.requireSourceRefreshCommand({ ...command(), id: 'other' }, known))
  const controller = new AbortController()
  const v = load({ '../platform/api': { platformApi: { getToolInvocation: async () => {
    controller.abort(); return command()
  } } } })
  await assert.rejects(v.sourceRefreshApi.recover(known, controller.signal), { name: 'AbortError' })
})

for (const commandId of ['../settings', 'command/subpath', 'command?latest=1', 'command#fragment', 'command%2fsubpath', 'command space']) {
  test(`invalid command path ${commandId} cannot cause recovery reads`, async () => {
    const value = command(); value.id = commandId; value.result.invocation_id = commandId
    assert.throws(() => api.requireSourceRefreshCommand(value, attempt))
    const v = load({ '../../shared/api/client': { request: () => assert.fail('invalid path must not discover') },
      '../platform/api': { platformApi: { getToolInvocation: () => assert.fail('invalid path must not be read') } } })
    await assert.rejects(v.sourceRefreshApi.recover({ ...attempt, commandId }, new AbortController().signal))
  })
}
