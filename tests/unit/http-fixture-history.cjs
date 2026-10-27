const assert = require('node:assert/strict'), test = require('node:test')
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm')
const { execFileSync } = require('node:child_process')
const ts = require('../../apps/portal/node_modules/typescript')
const root = path.resolve(__dirname, '../../apps/portal/src'), repo = path.resolve(root, '../../..')
function load(relative, overrides = {}, modules = new Map()) {
  const file = path.resolve(root, relative)
  if (modules.has(file)) return modules.get(file)
  const context = { exports: {}, URLSearchParams, require: (name) => {
    if (Object.hasOwn(overrides, name)) return overrides[name]
    return load(path.relative(root, path.resolve(path.dirname(file), `${name}.ts`)), overrides, modules)
  } }
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, context)
  modules.set(file, context.exports); return context.exports
}
// Python production compilers with explicitly doubled ports: no PG, native target, or business gold.
const native = JSON.parse(execFileSync(path.join(repo, '.venv/bin/python'), ['-c', `
import json,pytest
from apps.api.tests.test_http_fixture_history import history_specimen
from apps.api.tests.test_http_fixture_native_grants import native_grant
from apps.api.tests.test_owned_target_environment import spec
v=history_specimen.__wrapped__(native_grant.__wrapped__(spec.__wrapped__()),pytest.MonkeyPatch())
print(json.dumps(v.history.list(v.query.model_copy(update={'limit':3})).model_dump(mode='json')))
`], { cwd: repo }).toString())
const plain = (value) => JSON.parse(JSON.stringify(value))
const validation = load('domains/quality-loop/httpFixtureHistoryValidation.ts')
test('production Python metadata preserves all stages, current project and false authorities', () => {
  const page = structuredClone(native)
  assert.equal(validation.verifyFixtureHistoryPage(page, page.request), page)
  assert.deepEqual(plain(validation.verifyFixtureHistoryPages([page])), page.items)
  assert.deepEqual(page.items.map((item) => item.stage), ['grant', 'execute', 'cancel'])
  assert.equal(page.items[0].status, 'waiting_confirmation')
  assert.equal(page.items[2].original_execution_id, page.items[1].invocation_id)
})
const pageFaults = {
  schema: (p) => p.schema = 'invented', project: (p) => p.request.project_id = 'another',
  count: (p) => p.total = 0, booleanCount: (p) => p.total = true, scope: (p) => p.source_scope_digest = 'bad',
  extra: (p) => p.input_payload = { base_url: 'private' }, observation: (p) => p.observation = 'target_passed',
  duplicate: (p) => p.items[1] = structuredClone(p.items[0]), order: (p) => p.items.reverse(),
  cursor: (p) => p.next_after_id = 'not-last', missing: (p) => delete p.business_coverage_verified,
}
for (const [name, mutate] of Object.entries(pageFaults)) test(`history page rejects changed protocol: ${name}`, () => {
  const p = structuredClone(native), input = structuredClone(p.request); mutate(p)
  assert.throws(() => validation.verifyFixtureHistoryPage(p, input))
})
const itemFaults = {
  project: (v) => v.project_id = 'another', tool: (v) => v.tool_id = 'run.start', stage: (v) => v.stage = 'grant',
  digest: (v) => v.request_digest = 'bad', recipe: (v) => v.recipe_artifact_hash = 'bad', plan: (v) => v.run_plan_artifact_hash = 'bad',
  original: (v) => v.original_execution_id = 'another', grant: (v) => v.grant_id = null, status: (v) => v.status = 'passed',
  extra: (v) => v.artifact_ref = 'private', missing: (v) => delete v.original_execution_id, attempt: (v) => v.attempt_id = '',
}
for (const [name, mutate] of Object.entries(itemFaults)) test(`original metadata rejects changed ancestry: ${name}`, () => {
  const item = structuredClone(native.items[1]); mutate(item)
  assert.throws(() => validation.verifyFixtureHistoryItem(item, native.request.project_id))
})
for (const key of ['execution_authorized', 'canonical_execution_committed', 'business_coverage_verified', 'baseline_restored']) {
  for (const value of [true, 0, 1, 'false', null]) test(`history cannot convey coerced authority: ${key}=${value}`, () => {
    const p = structuredClone(native); p[key] = value
    assert.throws(() => validation.verifyFixtureHistoryPage(p, p.request))
    const item = structuredClone(native.items[1]); item[key] = value
    assert.throws(() => validation.verifyFixtureHistoryItem(item, native.request.project_id))
  })
}
function pages() {
  return native.items.map((item, index) => ({ ...structuredClone(native), request: { ...native.request, limit: 1,
    after_id: index ? native.items[index - 1].invocation_id : '' }, items: [structuredClone(item)],
    next_after_id: index < 2 ? item.invocation_id : null }))
}
test('complete multi-page inventory keeps its full count, source scope and exact cursor', () => {
  assert.deepEqual(plain(validation.verifyFixtureHistoryPages(pages())), native.items)
  assert.throws(() => validation.verifyFixtureHistoryPages(pages(), 'another-project'))
})
for (const change of ['scope', 'count', 'overlap', 'cursor', 'truncated']) test(`history reload is required when pagination changes: ${change}`, () => {
  const p = pages()
  if (change === 'scope') p[1].source_scope_digest = 'sha256:' + 'a'.repeat(64)
  else if (change === 'count') p[1].total++
  else if (change === 'overlap') p[1].items[0] = structuredClone(p[0].items[0])
  else if (change === 'cursor') p[1].request.after_id = ''
  else p.splice(1, 1)
  assert.throws(() => validation.verifyFixtureHistoryPages(p))
})
test('history transport uses GET only, no-store and original IDs; changed status requires reload', async () => {
  const calls = [], signal = new AbortController().signal
  let response = structuredClone(native)
  const api = load('domains/quality-loop/httpFixtureHistoryApi.ts', { '../../shared/api/client': {
    request: async (url, options) => { calls.push([url, options]); return structuredClone(response) },
  } }).fixtureHistoryApi
  const page = await api.page(native.request.project_id, '', signal)
  assert.deepEqual(plain(page), native)
  response = structuredClone(native.items[1])
  assert.deepEqual(plain(await api.read(native.request.project_id, response, signal)), response)
  response.status = 'cancelled'
  await assert.rejects(api.read(native.request.project_id, native.items[1], signal))
  assert(calls.every(([, options]) => options.cache === 'no-store' && options.signal === signal && !options.method && !options.body))
  assert(calls[1][0].endsWith('/002-execute'))
  const stop = new AbortController(); stop.abort()
  await assert.rejects(api.read(native.request.project_id, native.items[1], stop.signal))
})

function hookSpecimen() {
  const state = [], observed = [], calls = []
  let cursor = 0, result
  const list = { data: { pages: [structuredClone(native)] }, isError: false, isFetching: false, hasNextPage: false,
    refetch: () => calls.push('read'), fetchNextPage: () => calls.push('page') }
  const detail = { data: structuredClone(native.items[1]), isError: false, isFetching: false }
  const hook = load('domains/quality-loop/useHttpFixtureHistory.ts', {
    react: { useState: (initial) => { const key = cursor++; if (!(key in state)) state[key] = initial
      return [state[key], (value) => state[key] = value] } },
    '@tanstack/react-query': { useInfiniteQuery: (options) => { observed.push(['list', options]); return list },
      useQuery: (options) => { const journal = options.queryKey[0] === 'fixture-original-observation'
        observed.push([journal ? 'journal' : 'detail', options]); return journal ? { isError: false, isFetching: false } : detail } },
    './httpFixtureHistoryApi': { fixtureHistoryApi: { page: () => {}, read: () => {} } },
    './httpFixtureObservationApi': { fixtureObservationApi: { read: () => {} } },
  }).useHttpFixtureHistory
  return { list, detail, observed, calls, get result() { return result },
    render: (project = native.request.project_id, actor = 'original-actor') => { cursor = 0; result = hook(project, actor); return result } }
}
test('history is folded and read-only until opened, and never depends on sessionStorage', () => {
  const h = hookSpecimen(), folded = h.render()
  assert.equal(folded.open, false); assert.equal(folded.rows, undefined)
  assert(h.observed.every(([, options]) => options.enabled === false && options.retry === false && options.gcTime === 0))
  folded.toggle(); h.render()
  assert.equal(h.result.open, true); assert.equal(h.result.rows.length, 3)
  assert.equal(h.result.metadata, undefined)
  h.result.choose(native.items[1].invocation_id); h.render()
  assert.equal(h.result.metadata.invocation_id, native.items[1].invocation_id)
  h.result.reload(); h.render()
  assert.deepEqual(h.calls, ['read']); assert.equal(h.result.metadata, undefined)
})
for (const fault of ['list-fetch', 'detail-fetch', 'list-error', 'detail-error', 'scope-change', 'project-change', 'signed-out']) {
  test(`sensitive history and metadata are hidden during ${fault}`, () => {
    const h = hookSpecimen(); h.render().toggle(); h.render().choose(native.items[1].invocation_id); h.render()
    if (fault === 'list-fetch') h.list.isFetching = true
    else if (fault === 'detail-fetch') h.detail.isFetching = true
    else if (fault === 'list-error') h.list.isError = true
    else if (fault === 'detail-error') h.detail.isError = true
    else if (fault === 'scope-change') { const p = pages(); p[1].source_scope_digest = 'sha256:' + 'b'.repeat(64); h.list.data.pages = p }
    const value = h.render(fault === 'project-change' ? 'another-project' : native.request.project_id, fault === 'signed-out' ? '' : 'original-actor')
    assert.equal(value.metadata, undefined)
    if (fault !== 'detail-fetch') assert.equal(value.rows, undefined)
    if (fault.endsWith('error') || fault === 'scope-change' || fault === 'project-change') assert.equal(value.failed, true)
    assert.deepEqual(h.calls, [])
  })
}
