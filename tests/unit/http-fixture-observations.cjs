const assert = require('node:assert/strict'), test = require('node:test')
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm')
const { execFileSync } = require('node:child_process'), crypto = require('node:crypto').webcrypto
const ts = require('../../apps/portal/node_modules/typescript')
const root = path.resolve(__dirname, '../../apps/portal/src'), repo = path.resolve(root, '../../..')
function load(relative, overrides = {}, modules = new Map()) {
  const file = path.resolve(root, relative)
  if (modules.has(file)) return modules.get(file)
  const context = { exports: {}, URLSearchParams, TextEncoder, crypto, require: (name) => {
    if (Object.hasOwn(overrides, name)) return overrides[name]
    return load(path.relative(root, path.resolve(path.dirname(file), `${name}.ts`)), overrides, modules)
  } }
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, context)
  modules.set(file, context.exports); return context.exports
}
// Actual production DTO/domain compilers, explicitly doubled archive ports. Not PG/target evidence.
const native = JSON.parse(execFileSync(path.join(repo, '.venv/bin/python'), ['-c', `
import json,pytest
from apps.api.tests.test_http_fixture_observations import observation_specimen, observed_phase
from apps.api.tests.test_http_fixture_history import history_specimen
from apps.api.tests.test_http_fixture_native_grants import native_grant
from apps.api.tests.test_owned_target_environment import spec
from apps.api.app.application.quality_loop.http_fixture_history import HttpFixtureHistoryTarget
m=pytest.MonkeyPatch()
v=observation_specimen.__wrapped__(history_specimen.__wrapped__(native_grant.__wrapped__(spec.__wrapped__()),m),m)
values=[v.observations.read(v.target).model_dump(mode='json')]
observed_phase(v)
values.append(v.observations.read(v.target).model_dump(mode='json'))
observed_phase(v,'observed','failed')
values.append(v.observations.read(v.target).model_dump(mode='json'))
values.append(v.observations.read(HttpFixtureHistoryTarget(project_id=v.target.project_id,invocation_id='001-grant')).model_dump(mode='json'))
print(json.dumps({'values':values,'page':v.history.list(v.query.model_copy(update={'limit':3})).model_dump(mode='json')}))
`], { cwd: repo }).toString())
const plain = (value) => JSON.parse(JSON.stringify(value))
const validation = load('domains/quality-loop/httpFixtureObservationValidation.ts').verifyFixtureOriginalObservation
for (const value of native.values) test(`production original journal retains ${value.state} without authority`, async () => {
  assert.deepEqual(plain(await validation(structuredClone(value), value.selected, value.source_scope_digest)), value)
  assert.equal(value.business_coverage_verified, false)
})
const faults = {
  schema: (v) => v.schema = 'invented', selected: (v) => v.selected.request_digest = 'sha256:' + 'a'.repeat(64),
  execution: (v) => v.execution.invocation_id = 'other-command', scope: (v) => v.source_scope_digest = 'sha256:' + 'a'.repeat(64),
  classification: (v) => v.state = 'observed', observation: (v) => v.observation = 'live_target_passed',
  noPins: (v) => v.expected_phases = [], duplicatePins: (v) => v.expected_phases.push(structuredClone(v.expected_phases[0])),
  pinPhase: (v) => v.expected_phases[0].phase = 'cleanup:other', pinClaim: (v) => v.expected_phases[0].claim_id = 'fixture_' + 'a'.repeat(64),
  missingJob: (v) => v.job = null, jobSchema: (v) => v.job.schema = 'invented', project: (v) => v.job.project_id = 'other',
  request: (v) => v.job.request_digest = 'sha256:' + 'a'.repeat(64), selection: (v) => v.job.selection.operation = 'cleanup',
  jobStatus: (v) => v.job.status = 'completed', intent: (v) => v.job.intent_digest = null,
  missingPhase: (v) => v.job.phases = [], extraPhase: (v) => v.job.phases.push(structuredClone(v.job.phases[0])),
  claim: (v) => v.job.phases[0].claim_id = 'fixture_' + 'a'.repeat(64), phase: (v) => v.job.phases[0].phase = 'another',
  inventedResult: (v) => v.job.phases[0].result_digest = 'sha256:' + 'a'.repeat(64),
  missingDispatch: (v) => delete v.job.phases[0].dispatch_digest, observedWithoutResult: (v) => v.job.phases[0].state = 'observed',
  cancelCoercion: (v) => v.job.cancellation_requested = 0, cancelWithoutRequest: (v) => v.job.cancellation_delivered = true,
  jobAuthority: (v) => v.job.execution_authorized = true, secret: (v) => v.job.idempotency_key = 'private',
  extra: (v) => v.input_payload = {}, missing: (v) => delete v.baseline_restored,
}
for (const [name, mutate] of Object.entries(faults)) test(`original observation rejects altered journal: ${name}`, async () => {
  const v = structuredClone(native.values[1]); mutate(v)
  await assert.rejects(validation(v, native.values[1].selected, native.values[1].source_scope_digest))
})
for (const key of ['execution_authorized', 'canonical_execution_committed', 'business_coverage_verified', 'baseline_restored']) {
  for (const value of [true, 0, 1, 'false', null]) test(`original journal rejects coerced authority ${key}=${value}`, async () => {
    const v = structuredClone(native.values[1]); v[key] = value
    await assert.rejects(validation(v, native.values[1].selected, native.values[1].source_scope_digest))
  })
}
test('cross-browser original observation transport is GET-only, abortable and does not use recovery keys', async () => {
  const value = native.values[1], signal = new AbortController().signal, calls = []
  let response = structuredClone(value)
  const api = load('domains/quality-loop/httpFixtureObservationApi.ts', { '../../shared/api/client': {
    request: async (url, options) => { calls.push([url, options]); return structuredClone(response) },
  } }).fixtureObservationApi
  assert.deepEqual(plain(await api.read(value.selected, value.source_scope_digest, signal)), value)
  assert(calls[0][0].endsWith('/002-execute/observation'))
  assert(calls.every(([, options]) => options.cache === 'no-store' && options.signal === signal && !options.method && !options.body))
  response.execution.status = 'failed'
  await assert.rejects(api.read(value.selected, value.source_scope_digest, signal))
  const count = calls.length, stop = new AbortController(); stop.abort()
  await assert.rejects(api.read(value.selected, value.source_scope_digest, stop.signal))
  await assert.rejects(api.read({ ...value.selected, tool_id: 'run.start' }, value.source_scope_digest, signal))
  assert.equal(calls.length, count)
})

function hookSpecimen() {
  const state = [], observed = [], calls = []
  let cursor = 0, result
  const list = { data: { pages: [structuredClone(native.page)] }, isError: false, isFetching: false, hasNextPage: false,
    refetch: () => calls.push('read'), fetchNextPage: () => calls.push('page') }
  const detail = { data: structuredClone(native.values[0].selected), isError: false, isFetching: false }
  const journal = { data: structuredClone(native.values[1]), isError: false, isFetching: false }
  const hook = load('domains/quality-loop/useHttpFixtureHistory.ts', {
    react: { useState: (initial) => { const key = cursor++; if (!(key in state)) state[key] = initial
      return [state[key], (value) => state[key] = value] } },
    '@tanstack/react-query': { useInfiniteQuery: (options) => { observed.push(['list', options]); return list },
      useQuery: (options) => { const kind = options.queryKey[0] === 'fixture-original-observation' ? 'journal' : 'detail'
        observed.push([kind, options]); return kind === 'journal' ? journal : detail } },
    './httpFixtureHistoryApi': { fixtureHistoryApi: { page: () => {}, read: () => {} } },
    './httpFixtureObservationApi': { fixtureObservationApi: { read: () => {} } },
  }).useHttpFixtureHistory
  return { list, detail, journal, observed, calls, get result() { return result },
    render: (project = native.page.request.project_id, actor = 'independent-admin') => { cursor = 0; result = hook(project, actor); return result } }
}
test('journal inspection is independently selected and folded; reload/new selection clears it', () => {
  const h = hookSpecimen(); h.render()
  assert.equal(h.result.observation, undefined)
  h.result.toggle(); h.render().choose(native.values[0].selected.invocation_id); h.render()
  assert.equal(h.result.inspect, false); assert.equal(h.result.observation, undefined)
  h.result.inspectJournal(); h.render()
  assert.equal(h.result.observation.state, 'outcome_unknown')
  assert(h.observed.at(-1)[1].enabled)
  assert(h.observed.every(([, options]) => options.retry === false && options.gcTime === 0))
  h.result.choose(native.values[0].selected.invocation_id); h.render()
  assert.equal(h.result.inspect, false); assert.equal(h.result.observation, undefined)
  h.result.inspectJournal(); h.render().reload(); h.render()
  assert.equal(h.result.observation, undefined); assert.deepEqual(h.calls, ['read'])
})
for (const fault of ['fetch', 'error', 'list-fetch', 'detail-fetch', 'project', 'signed-out', 'scope', 'selected']) {
  test(`protected original journal is hidden during ${fault}`, () => {
    const h = hookSpecimen(); h.render().toggle(); h.render().choose(native.values[0].selected.invocation_id)
    h.render().inspectJournal(); h.render()
    if (fault === 'fetch') h.journal.isFetching = true
    else if (fault === 'error') h.journal.isError = true
    else if (fault === 'list-fetch') h.list.isFetching = true
    else if (fault === 'detail-fetch') h.detail.isFetching = true
    else if (fault === 'scope') h.journal.data.source_scope_digest = 'sha256:' + 'a'.repeat(64)
    else if (fault === 'selected') h.journal.data.selected.invocation_id = 'other'
    const result = h.render(fault === 'project' ? 'other' : native.page.request.project_id, fault === 'signed-out' ? '' : 'independent-admin')
    assert.equal(result.observation, undefined)
    if (['fetch', 'error'].includes(fault)) { assert.equal(result.rows, undefined); assert.equal(result.metadata, undefined) }
  })
}
