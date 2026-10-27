const assert = require('node:assert/strict'), test = require('node:test')
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm')
const { execFileSync } = require('node:child_process'), { webcrypto } = require('node:crypto')
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
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText, context)
  modules.set(file, context.exports); return context.exports
}
const validation = load('domains/quality-loop/runPlanLocatorRecordValidation.ts')
const { createLocatorRecovery } = load('domains/quality-loop/runPlanLocatorRecordRecovery.ts')
const { canonicalDigest: digest } = load('shared/utils/canonicalDigest.ts')
const plain = (v) => JSON.parse(JSON.stringify(v))
// Real Python parser and application ports, explicitly synthetic source/oracle data.
const native = JSON.parse(execFileSync(path.join(repo, '.venv/bin/python'), ['-c', `
import json
from datetime import datetime,timezone
from apps.api.tests.test_http_locator_records import service_specimen
s,q,state=service_specimen(); m=s.record(q,invocation_id='command',recorded_at=datetime.now(timezone.utc).isoformat())
p=s.locators.plans.read(q.project_id,q.run_plan_id); p['current_use']={'inputs_current':True}
print(json.dumps(dict(plan=p,view=s.read(q.project_id,m['record_id']))))
`], { cwd: repo, encoding: 'utf8' }))
function fixture(original = native) {
  const v = structuredClone(original), a = v.view.archive, input = a.request
  v.attempt = { projectId: input.project_id, planId: input.run_plan_id, planHash: input.run_plan_artifact_hash,
    requestKey: 'original-locator-key', requestHash: v.view.metadata.request_hash }
  v.command = { id: a.invocation_id, tool_id: 'quality.run_plan.record_locators', status: 'completed',
    input_payload: { ...input, idempotency_key: v.attempt.requestKey, confirmed_by_user: true },
    result: { invocation_id: a.invocation_id, status: 'completed', object_refs: ['run_plan_locators:' + a.record_id],
      run_plan_locator_record: { metadata: v.view.metadata, historical_not_live: true } } }
  return v
}
test('independent Python archive and full static report retain exact parents and zero execution authority', async () => {
  const v = fixture(), before = structuredClone(v)
  assert.equal(await validation.locatorRecordIdentity(v.command.id), v.view.metadata.record_id)
  assert.equal(await validation.verifyLocatorRecord(v.view, v.plan, v.command.id, v.view.metadata.record_id), v.view)
  assert.deepEqual(plain(await validation.expectedLocatorRecordMetadata(v.view.archive)), v.view.metadata)
  assert.equal(v.view.metadata.source_bytes_verified, true); assert.equal(v.view.metadata.durable_locator_evidence_verified, true)
  assert.equal(v.view.metadata.execution_authorized, false); assert.equal(v.view.metadata.passed_count, 0)
  v.plan.current_use.inputs_current = false
  assert.equal(await validation.verifyLocatorRecord(v.view, v.plan, v.command.id, v.view.metadata.record_id), v.view)
  before.plan.current_use.inputs_current = false; assert.deepEqual(v, before)
})
test('a new scoped locator archive is verified without changing its historical plan or authority', async () => {
  const original = JSON.parse(execFileSync(path.join(repo, '.venv/bin/python'), ['-c', `
import json
from datetime import datetime,timezone
from apps.api.tests.test_http_locator_records import service_specimen
from apps.api.tests.test_http_locator_uncertainty import scoped_plan
from apps.api.tests.test_run_plan_locators import JAVA
java=JAVA.replace('@PostMapping("/sessions")','@PostMapping(path="/sessions",produces="application/json")')
s,q,state=service_specimen(plan=scoped_plan(),java=java)
m=s.record(q,invocation_id='command',recorded_at=datetime.now(timezone.utc).isoformat())
p=s.locators.plans.read(q.project_id,q.run_plan_id); p['current_use']={'inputs_current':True}
print(json.dumps(dict(plan=p,view=s.read(q.project_id,m['record_id']))))
`], { cwd: repo, encoding: 'utf8' }))
  const v = fixture(original), before = structuredClone(v)
  assert.equal(await validation.verifyLocatorRecord(v.view, v.plan, v.command.id, v.view.metadata.record_id), v.view)
  assert.equal(v.view.archive.report.policy, 'nasus.http-locator-static-match.v2')
  assert.equal(v.view.metadata.summary.static_match, v.view.metadata.summary.locator_count)
  assert.equal(v.view.metadata.execution_authorized, false)
  assert.deepEqual(v, before)
})
const faults = {
  'scope': (v) => v.view.archive.project_id = 'foreign',
  'schema': (v) => v.view.archive.schema = 'nasus.run-plan-environment-record.v1',
  'command': (v) => v.view.archive.invocation_id = 'foreign',
  'record': (v) => v.view.archive.record_id = 'foreign',
  'actor': (v) => v.view.archive.actor_id = '',
  'time': (v) => v.view.archive.recorded_at = '2026-10-11T00:00:00',
  'plan': (v) => v.view.archive.request.run_plan_id = 'foreign',
  'image': (v) => v.view.archive.parents.image_artifact_hash = 'sha256:' + 'b'.repeat(64),
  'manifest': (v) => v.view.archive.parents.manifest_id = 'foreign',
  'action': (v) => v.view.archive.report.locators.pop(),
  'source': (v) => v.view.archive.report.inventory.sources.pop(),
  'summary': (v) => v.view.archive.report.summary.locator_count++,
  'runtime': (v) => v.view.archive.report.runtime_locators_verified = true,
  'count-boolean': (v) => v.view.archive.report.passed_count = false,
  'extra': (v) => v.view.archive.injected = 'untrusted',
}
for (const [fault, mutate] of Object.entries(faults)) test(`fully rehashed archive still rejects altered original scope: ${fault}`, async () => {
  const v = fixture(); mutate(v)
  const report = v.view.archive.report, { inventory_hash: _i, ...inventory } = report.inventory
  report.inventory.inventory_hash = await digest(inventory)
  const { report_hash: _r, ...body } = report; report.report_hash = await digest(body)
  v.view.metadata = plain(await validation.expectedLocatorRecordMetadata(v.view.archive))
  await assert.rejects(validation.verifyLocatorRecord(v.view, v.plan, v.command.id, native.view.metadata.record_id))
})
for (const [field, value] of [['source_bytes_verified', 1], ['durable_locator_evidence_verified', 1], ['execution_authorized', 0], ['passed_count', false]])
  test(`metadata is not type-coerced: ${field}`, async () => {
    const v = fixture(); v.view.metadata[field] = value
    await assert.rejects(validation.verifyLocatorRecord(v.view, v.plan, v.command.id, native.view.metadata.record_id))
  })
test('recovery saves only identifiers, prevents replacement and is isolated by actor and plan hash', () => {
  const v = fixture(), values = new Map(), storage = () => ({ getItem: (k) => values.get(k) ?? null, setItem: (k, v) => values.set(k, v), removeItem: (k) => values.delete(k) })
  const r = createLocatorRecovery(storage), read = (actor) => r.read(actor, v.attempt.projectId, v.attempt.planId, v.attempt.planHash)
  r.save('owner', v.attempt); assert.equal(read('other'), null); assert.equal(read('owner').requestKey, v.attempt.requestKey)
  assert.throws(() => r.save('owner', { ...v.attempt, requestKey: 'duplicate' }))
  assert.throws(() => r.read('owner', v.attempt.projectId, v.attempt.planId, 'sha256:' + 'b'.repeat(64)))
  assert.doesNotMatch([...values.values()].join(''), /inventory|report|source_pin|Controller|password|receipt/)
  const ack = { ...v.attempt, commandId: v.command.id }; r.acknowledge('owner', ack)
  assert.throws(() => r.acknowledge('owner', { ...ack, commandId: 'foreign' }))
  r.clear('owner', ack); assert.equal(read('owner'), null)
})
test('a lost acknowledgement recovers only by GET, never re-registers or confirms automatically', async () => {
  const v = fixture(), calls = [], ack = [], pending = { ...v.command, status: 'waiting_confirmation', result: null }
  const api = load('domains/quality-loop/runPlanLocatorRecordApi.ts', {
    '../platform/api': { platformApi: { invokeTool: async (body) => { calls.push(body); return pending },
      confirmToolInvocation: async (id) => { calls.push({ confirm: id }); throw new Error('Lost original acknowledgement') } } },
    '../../shared/api/client': { request: async (url, options) => { calls.push({ url, options }); return pending } },
  }).locatorRecordApi
  await assert.rejects(api.register(v.view.archive.request, v.attempt, (v) => ack.push(v)))
  assert.equal(calls[0].tool_id, 'quality.run_plan.record_locators'); assert.equal(ack[0].commandId, v.command.id)
  await api.recover(v.attempt, v.plan, new AbortController().signal)
  assert.equal(calls.length, 3); assert.match(calls[2].url, /tool_id=quality.run_plan.record_locators/)
  assert.equal(calls[2].options.cache, 'no-store'); assert.equal(calls[2].options.method, undefined)
  await assert.rejects(api.recover(v.attempt, v.plan, AbortSignal.abort())); assert.equal(calls.length, 3)
})
test('private history verifies its original command and metadata before returning, and stops on abort', async () => {
  const v = fixture(), calls = [], exports = load('domains/quality-loop/runPlanLocatorRecordApi.ts', {
    '../platform/api': { platformApi: {} }, '../../shared/api/client': { request: async (url, options) => { calls.push({ url, options }); return v.view } },
  }), api = exports.locatorRecordApi
  assert.equal(await api.read(v.command, v.plan, new AbortController().signal), v.view)
  for (const mutate of [(v) => v.tool_id = 'query.quality.run_plan_locators', (v) => v.input_payload.run_plan_id = 'other',
    (v) => v.input_payload.confirmed_by_user = 1, (v) => v.result.object_refs = ['run_plan:' + native.view.metadata.record_id]]) {
    const bad = structuredClone(v.command); mutate(bad)
    await assert.rejects(api.read(bad, v.plan, new AbortController().signal))
  }
  assert.equal(calls.length, 1)
  const bad = structuredClone(v.command); bad.result.run_plan_locator_record.metadata.execution_authorized = 0
  await assert.rejects(api.read(bad, v.plan, new AbortController().signal))
  assert.equal(calls.length, 2); assert.ok(calls.every((c) => c.url.includes('/quality/run-plan-locators/') && !c.options.method && c.options.cache === 'no-store'))
  await assert.rejects(api.read(v.command, v.plan, AbortSignal.abort())); assert.equal(calls.length, 2)
})
function renderPanel(state) {
  const React = require('../../apps/portal/node_modules/react'), { renderToStaticMarkup } = require('../../apps/portal/node_modules/react-dom/server')
  const { RunPlanLocatorRecordPanel } = load('routes/project/sections/knowledge/scope/RunPlanLocatorRecordPanel.tsx', {
    react: React, 'react/jsx-runtime': require('../../apps/portal/node_modules/react/jsx-runtime'),
    '../../../../../domains/quality-loop/useRunPlanLocatorRecord': { useRunPlanLocatorRecord: () => state },
    '../../../../../shared/i18n/I18nProvider': { useI18n: () => ({ t: (key) => key }) },
  })
  return renderToStaticMarkup(React.createElement(RunPlanLocatorRecordPanel, { plan: native.plan, actorId: 'owner', current: true, onFailure: () => {} }))
}
test('independent registration is initially folded without request, consent or private archive DOM', () => {
  const html = renderPanel({ open: false, busy: false, toggle: () => {} })
  assert.match(html, /aria-expanded="false"/); assert.doesNotMatch(html, /<pre|checkbox|Controller|source_pin/)
})
test('a verified record displays its full denominator but does not eagerly render the private inventory', () => {
  const html = renderPanel({ open: true, busy: false, stored: {}, write: {}, recovery: {}, canRegister: true, result: native.view })
  assert.match(html, /original-locator-record/); assert.match(html, /Source locators archived; execution remains unauthorized/)
  assert.doesNotMatch(html, /<pre|Controller.java|source_pin|checkbox/)
})
