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
const validation = load('domains/quality-loop/httpFixtureOperationValidation.ts')
const { createFixtureOperationRecovery: recovery, verifyOperationAttempt } = load('domains/quality-loop/httpFixtureOperationRecovery.ts')
const { canonicalDigest: digest } = load('shared/utils/canonicalDigest.ts')
const plain = (v) => JSON.parse(JSON.stringify(v)), hash = 'sha256:' + 'a'.repeat(64)
// Independent Python application/domain specimens, not PG, native deployment or business gold.
const native = JSON.parse(execFileSync(path.join(repo, '.venv/bin/python'), ['-c', `
import json
from copy import deepcopy
from apps.api.tests.test_http_fixture_native_grants import native_grant
from apps.api.tests.test_owned_target_environment import spec
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixture_recipe import RECIPE_SCHEMA,recipe_identity,validate_recipe_archive
from apps.api.app.domain.quality_loop.environment_observation_record import environment_record_metadata
from apps.api.app.domain.quality_loop.http_fixture_grant import grant_metadata
v=native_grant.__wrapped__(spec.__wrapped__()); m=v.service.issue(v.request,invocation_id='native-consent-command')
payload=deepcopy(v.state['issued'][m['record_id']]); p=v.saved; a=p['artifact']; plan=a['plan']
a.update(schema='nasus.run-plan-artifact.'+plan['schema'].rsplit('.',1)[1],invocation_id='original-plan-command',actor_id='admin',recorded_at=m['recorded_at'],request={**plan['selection'],'plan_digest':plan['plan_digest'],'source_scope_digest':m['source_scope_digest']})
p['metadata'].update(invocation_id=a['invocation_id'],image_revision_id=plan['source_pin']['image_revision_id'],manifest_id=plan['source_pin']['manifest_id'],artifact_hash=acceptance_digest(a))
e=v.environment; e['archive']['request']['run_plan_artifact_hash']=p['metadata']['artifact_hash']; e['metadata']=environment_record_metadata(e['archive'])
r={'schema':RECIPE_SCHEMA,'project_id':plan['project_id'],'record_id':recipe_identity('recipe-command'),'invocation_id':'recipe-command','actor_id':'admin','recorded_at':m['recorded_at'],'request':{'project_id':plan['project_id'],'run_plan_id':p['metadata']['run_plan_id'],'run_plan_artifact_hash':p['metadata']['artifact_hash'],'manifest':v.manifest},'parents':{'plan_digest':plan['plan_digest'],**{k:plan['source_pin'][k] for k in ('image_revision_id','image_artifact_hash','manifest_id','manifest_hash')}},'fixture_digest':acceptance_digest(plan['selection']['fixtures'][0])}
recipe={'archive':r,'metadata':validate_recipe_archive(r,r['request'],p),'historical_not_live':True}
payload['request'].update(recipe_artifact_hash=recipe['metadata']['artifact_hash'],environment_record_artifact_hash=e['metadata']['artifact_hash'])
payload['native_environment']['artifact_hash']=e['metadata']['artifact_hash']
print(json.dumps(dict(plan=p,recipe=recipe,environment=e,input=payload['request'],grant=dict(metadata=grant_metadata(payload),historical_not_live=True))))
`], { cwd: repo, encoding: 'utf8' }))
function fixture() {
  const v = structuredClone(native), m = v.grant.metadata
  v.attempt = { projectId: m.project_id, planId: v.plan.metadata.run_plan_id, planHash: v.plan.metadata.artifact_hash,
    recipeId: m.recipe_id, recipeHash: m.recipe_artifact_hash, environmentCommandId: v.environment.metadata.invocation_id,
    attemptId: m.attempt_id, operation: m.operation, timeoutMs: m.timeout_ms,
    grant: { requestKey: 'original-permission-key', requestHash: m.request_hash } }
  v.command = { id: m.invocation_id, tool_id: validation.fixtureTools.grant, status: 'completed',
    input_payload: { ...v.input, idempotency_key: v.attempt.grant.requestKey, confirmed_by_user: true, confirmed_actor_id: m.actor_id, confirmed_at: m.recorded_at },
    result: { invocation_id: m.invocation_id, status: 'completed', object_refs: ['http_fixture_grant:' + m.record_id], http_fixture_grant: v.grant } }
  return v
}
test('native grant matches independent Python metadata, exact target instance and bounded lifetime', async () => {
  const v = fixture(), before = structuredClone(v)
  assert.deepEqual(plain(await validation.fixtureGrantRequest(v.plan, v.recipe, v.environment, v.attempt)), v.input)
  assert.equal(await validation.verifyFixtureGrant(v.grant, v.input, v.plan, v.recipe, v.environment, v.command.id, 'admin'), v.grant)
  assert.notEqual(v.grant.metadata.scope.inventory_hash, v.grant.metadata.native_environment.operator_policy_digest)
  await validation.requireFixtureOperationCommand(v.command, 'grant', v.attempt.grant, v.input, 'admin')
  assert.deepEqual(v, before)
})
const grantFaults = {
  actor: (v) => v.grant.metadata.actor_id = 'foreign', command: (v) => v.grant.metadata.invocation_id = 'foreign',
  record: (v) => v.grant.metadata.record_id = 'foreign', project: (v) => v.grant.metadata.project_id = 'foreign',
  schema: (v) => v.grant.metadata.schema = 'nasus.http-fixture-grant.v1',
  policy: (v) => v.grant.metadata.policy_revision = 'nasus.http-fixture-grant.v1',
  recipe: (v) => v.grant.metadata.recipe_artifact_hash = hash, operation: (v) => v.grant.metadata.operation = 'cleanup',
  attempt: (v) => v.grant.metadata.attempt_id = 'other', timeout: (v) => v.grant.metadata.timeout_ms = true,
  scope: (v) => v.grant.metadata.scope.inventory_hash = v.grant.metadata.native_environment.operator_policy_digest,
  native: (v) => v.grant.metadata.native_environment.record_id = 'foreign',
  time: (v) => v.grant.metadata.recorded_at = '2026-10-13T00:00:00',
  expiry: (v) => v.grant.metadata.expires_at = v.grant.metadata.recorded_at,
  hash: (v) => v.grant.metadata.grant_digest = hash,
  authority: (v) => v.grant.metadata.execution_authorized = true,
  coverage: (v) => v.grant.metadata.business_coverage_verified = true,
  zero: (v) => v.grant.metadata.passed_count = false, live: (v) => v.grant.historical_not_live = false,
  extra: (v) => v.grant.metadata.claimed_pass = true,
}
for (const [name, mutate] of Object.entries(grantFaults)) test(`grant rejects altered metadata without authority promotion: ${name}`, async () => {
  const v = fixture(); mutate(v)
  await assert.rejects(validation.verifyFixtureGrant(v.grant, v.input, v.plan, v.recipe, v.environment, v.command.id, 'admin'))
})
for (const field of ['project_id', 'run_plan_id', 'run_plan_artifact_hash', 'plan_digest', 'image_revision_id', 'manifest_id',
  'environment_id', 'operator_policy_digest', 'target_artifact_hash']) test(`grant request cannot adopt a different environment parent: ${field}`, async () => {
    const v = fixture(); v.environment.metadata[field] = 'foreign'
    await assert.rejects(validation.fixtureGrantRequest(v.plan, v.recipe, v.environment, v.attempt))
  })
test('cleanup preserves the original attempt and has a distinct independently confirmed scope', async () => {
  const v = fixture(); v.plan.current_use.inputs_current = false
  const input = plain(await validation.fixtureGrantRequest(v.plan, v.recipe, v.environment, { ...v.attempt, operation: 'cleanup' }))
  assert.equal(input.attempt_id, v.input.attempt_id); assert.equal(input.operation, 'cleanup')
  assert.notEqual(await digest(input), v.attempt.grant.requestHash)
  for (const timeoutMs of [false, NaN, 999, 120001, 1000.5]) await assert.rejects(validation.fixtureGrantRequest(v.plan, v.recipe, v.environment, { ...v.attempt, timeoutMs }))
})
test('recovery persists only scoped identifiers and hashes and cannot overwrite another stage', () => {
  const v = fixture(), values = new Map(), s = recovery(() => ({ getItem: (k) => values.get(k) ?? null,
    setItem: (k, v) => values.set(k, v), removeItem: (k) => values.delete(k) }))
  const read = (actor = 'admin', planHash = v.attempt.planHash) => s.read(actor, v.attempt.projectId, v.attempt.planId, planHash, v.attempt.recipeId, v.attempt.recipeHash)
  s.save('admin', v.attempt); assert.deepEqual(plain(read()), v.attempt); assert.equal(read('foreign'), null)
  assert.throws(() => read('admin', hash)); assert.throws(() => s.save('admin', v.attempt))
  assert.throws(() => s.add('admin', v.attempt, 'execute', { requestKey: 'execution-key', requestHash: hash }))
  let operation = s.acknowledge('admin', v.attempt, 'grant', v.command.id)
  assert.throws(() => s.acknowledge('admin', operation, 'grant', 'foreign'))
  const old = operation; operation = s.add('admin', operation, 'execute', { requestKey: 'execution-key', requestHash: hash })
  assert.throws(() => s.clear('admin', old))
  operation = s.acknowledge('admin', operation, 'execute', 'original-execution')
  operation = s.add('admin', operation, 'cancel', { requestKey: 'cancel-key', requestHash: hash })
  operation = s.acknowledge('admin', operation, 'cancel', 'original-cancel')
  assert.doesNotMatch([...values.values()][0], /inventory|container|namespace|password|manifest|localhost|127\.0/)
  assert.throws(() => verifyOperationAttempt({ ...operation, secret: 'private' }))
  s.clear('admin', operation); assert.equal(values.size, 0)
})
async function executionFixture(state = 'outcome_unknown') {
  const v = fixture(), m = v.grant.metadata
  v.selection = { project_id: m.project_id, grant_id: m.record_id, grant_digest: m.grant_digest, operation: m.operation }
  v.execution = { id: 'original-execution', tool_id: validation.fixtureTools.execute, status: 'running', input_payload: {
    ...v.selection, idempotency_key: 'execution-key', confirmed_by_user: true, confirmed_actor_id: 'admin', confirmed_at: m.recorded_at,
    fixture_claim_protocol: 'nasus.http-fixture-preparation.v1' }, result: null }
  v.executionAttempt = { requestKey: 'execution-key', requestHash: await digest(v.selection), commandId: v.execution.id }
  v.job = { schema: 'nasus.http-fixture-job.v1', project_id: m.project_id, invocation_id: v.execution.id,
    request_digest: await digest({ tool_id: v.execution.tool_id, input_payload: v.execution.input_payload }), selection: v.selection,
    status: 'running', intent_digest: hash, phases: [{ phase: 'setup', claim_id: 'fixture_' + (await digest([m.project_id, m.attempt_id, m.scope.case_id, 'setup'])).slice(7), state,
      ...(state === 'not_dispatched' ? {} : { dispatch_digest: hash }), ...(state === 'observed' ? { result_status: 'failed', result_digest: hash } : {}) }],
    cancellation_requested: false, cancellation_delivered: false, ...Object.fromEntries(validation.fixtureFalseAuthorities.map((key) => [key, false])) }
  return v
}
test('unknown effects and recorded failures remain visible without any business-pass authority', async () => {
  for (const state of ['not_dispatched', 'outcome_unknown', 'observed']) {
    const v = await executionFixture(state)
    assert.equal(await validation.verifyFixtureJob(v.job, v.execution, v.grant, v.recipe), v.job)
    v.job.status = v.execution.status = 'completed'
    if (state !== 'observed') await assert.rejects(validation.verifyFixtureJob(v.job, v.execution, v.grant, v.recipe))
    else assert.equal((await validation.verifyFixtureJob(v.job, v.execution, v.grant, v.recipe)).phases[0].result_status, 'failed')
  }
})
test('binding-before-observation and cancellation do not fabricate intent, phases or rollback', async () => {
  const v = await executionFixture()
  for (const [status, phase] of [['running', 'preparing'], ['failed', 'preparation_failed'], ['cancelled', 'preparation_cancelled']]) {
    v.execution.status = status
    const job = { ...v.job, schema: 'nasus.http-fixture-job.v2', status, phase, preparation_digest: hash,
      intent_digest: null, phases: [], target_observation_verified: false, cancellation_requested: status === 'cancelled', cancellation_delivered: status === 'cancelled' }
    assert.equal(await validation.verifyFixtureJob(job, v.execution, v.grant, v.recipe), job)
    await assert.rejects(validation.verifyFixtureJob({ ...job, intent_digest: hash }, v.execution, v.grant, v.recipe))
    await assert.rejects(validation.verifyFixtureJob({ ...job, target_observation_verified: true }, v.execution, v.grant, v.recipe))
  }
})
const jobFaults = {
  extra: (v) => v.job.target_passed = true, partial: (v) => v.job.phases = [],
  phase: (v) => v.job.phases[0].phase = 'cleanup:foreign', claim: (v) => v.job.phases[0].claim_id = 'foreign',
  status: (v) => v.job.status = 'completed', request: (v) => v.job.request_digest = hash,
  selection: (v) => v.job.selection.operation = 'cleanup', schema: (v) => v.job.schema = 'imported',
  authority: (v) => v.job.execution_authorized = true, coverage: (v) => v.job.business_coverage_verified = true,
  boolean: (v) => v.job.cancellation_requested = 0, orphan: (v) => v.job.cancellation_delivered = true,
  cancel: (v) => v.job.cancellation_requested = true,
}
for (const [name, mutate] of Object.entries(jobFaults)) test(`job cannot rebind or promote original observations: ${name}`, async () => {
  const v = await executionFixture(); mutate(v)
  await assert.rejects(validation.verifyFixtureJob(v.job, v.execution, v.grant, v.recipe))
})
test('all three commands keep independent inputs, actor confirmation and unknown-ACK GET recovery', async () => {
  const v = fixture(), execution = await executionFixture()
  for (const stage of ['grant', 'execute', 'cancel']) {
    const input = stage === 'grant' ? v.input : stage === 'execute' ? execution.selection : { project_id: v.input.project_id, invocation_id: execution.execution.id }
    const attempt = { requestKey: stage + '-key', requestHash: await digest(input) }, calls = [], ids = []
    const pending = { id: stage + '-command', tool_id: validation.fixtureTools[stage], status: 'waiting_confirmation', input_payload: { ...input, idempotency_key: attempt.requestKey }, result: null }
    const { fixtureOperationApi: api } = load('domains/quality-loop/httpFixtureOperationApi.ts', {
      '../platform/api': { platformApi: { invokeTool: async (body) => { calls.push({ body }); return pending },
        getToolInvocation: async (id) => { calls.push({ get: id }); return pending },
        confirmToolInvocation: async (id) => { calls.push({ confirm: id }); throw new Error('lost acknowledgement') } } },
      '../../shared/api/client': { request: async (url, options) => { calls.push({ url, options }); return pending } },
    })
    await assert.rejects(api.submit(stage, attempt, input, 'admin', (id) => ids.push(id)))
    assert.deepEqual(ids, [pending.id]); assert.equal(calls.length, 3)
    assert.equal((await api.recover(stage, attempt, input, 'admin', new AbortController().signal)).id, pending.id)
    assert.equal(calls.length, 4); assert.equal(calls[3].options.method, undefined); assert.equal(calls[3].options.cache, 'no-store')
    await assert.rejects(api.recover(stage, attempt, input, 'admin', AbortSignal.abort()), { name: 'AbortError' }); assert.equal(calls.length, 4)
    await assert.rejects(validation.requireFixtureOperationCommand({ ...pending, input_payload: { ...pending.input_payload, undeclared: true } }, stage, attempt, input, 'admin'))
    await assert.rejects(validation.requireFixtureOperationCommand({ ...pending, status: 'running', input_payload: { ...pending.input_payload,
      confirmed_by_user: true, confirmed_actor_id: 'foreign', confirmed_at: v.grant.metadata.recorded_at } }, stage, attempt, input, 'admin'))
  }
})
test('grant archive GET verifies original receipt; a terminal read race retries the same ID without writes', async () => {
  const v = fixture(), calls = [], job = await executionFixture('observed'), signal = new AbortController().signal
  let count = 0
  const { fixtureOperationApi: api } = load('domains/quality-loop/httpFixtureOperationApi.ts', {
    '../platform/api': { platformApi: { getToolInvocation: async (id) => { calls.push({ command: id }); return { ...job.execution, status: count++ === 0 ? 'running' : 'completed' } } } },
    '../../shared/api/client': { request: async (url, options) => { calls.push({ url, options }); return url.includes('/http-fixture-grants/') ? v.grant : { ...job.job, status: 'completed' } } },
  })
  assert.equal(await api.readGrant(v.command, v.input, v.plan, v.recipe, v.environment, 'admin', signal), v.grant)
  const result = await api.readJob(job.executionAttempt, job.grant, job.recipe, 'admin', signal)
  assert.equal(result.command.status, 'completed'); assert.equal(result.job.phases[0].result_status, 'failed')
  assert.deepEqual(calls.filter((c) => c.command).map((c) => c.command), [job.execution.id, job.execution.id])
  assert.ok(calls.filter((c) => c.url).every((c) => !c.options.method && c.options.cache === 'no-store'))
})
function renderPanel(state) {
  const React = require('../../apps/portal/node_modules/react'), { renderToStaticMarkup } = require('../../apps/portal/node_modules/react-dom/server')
  const { HttpFixtureOperationPanel } = load('routes/project/sections/knowledge/scope/HttpFixtureOperationPanel.tsx', {
    react: React, 'react/jsx-runtime': require('../../apps/portal/node_modules/react/jsx-runtime'),
    '../../../../../shared/i18n/I18nProvider': { useI18n: () => ({ t: (key) => key }) },
    '../../../../../domains/quality-loop/useHttpFixtureOperation': { useHttpFixtureOperation: () => state },
  })
  return renderToStaticMarkup(React.createElement(HttpFixtureOperationPanel, { plan: native.plan, recipe: native.recipe, actorId: 'admin', current: true, onFailure: () => {} }))
}
test('folded panel performs no visible implicit operation; opening separates grant, execution and cancellation', async () => {
  const base = { open: false, busy: false, stored: { attempt: null, invalid: false }, fields: fixture().attempt, write: {}, canOperate: true,
    confirmed: () => false, mayWrite: () => false }
  assert.doesNotMatch(renderPanel(base), /Original environment command ID|Record independent fixture permission/)
  const opened = renderPanel({ ...base, open: true, prepared: { input: native.input, value: native.environment } })
  assert.match(opened, /Record independent fixture permission/); assert.doesNotMatch(opened, /Execute confirmed fixture operation/)
  const v = await executionFixture()
  const running = renderPanel({ ...base, open: true, stored: { attempt: { ...v.attempt, execute: v.executionAttempt }, invalid: false },
    prepared: { input: native.input, value: native.environment }, grant: { command: fixture().command, grant: v.grant }, execution: { command: v.execution, job: v.job } })
  assert.match(running, /Cancel original fixture operation/); assert.match(running, /unknown outcome/)
  assert.doesNotMatch(running, /Prepare the next independently confirmed operation/)
})
test('invalid inputs are rejected before invoke, confirm or original-command reads', async () => {
  const v = fixture(), calls = []
  const { fixtureOperationApi: api } = load('domains/quality-loop/httpFixtureOperationApi.ts', {
    '../platform/api': { platformApi: { invokeTool: async () => calls.push('invoke'), getToolInvocation: async () => calls.push('get'),
      confirmToolInvocation: async () => calls.push('confirm') } },
    '../../shared/api/client': { request: async () => calls.push('request') },
  })
  for (const input of [{ ...v.input, policy_revision: 'nasus.http-fixture-grant.v1' }, { ...v.input, timeout_ms: true },
    { ...v.input, environment_record_id: 'foreign' }, { ...v.input, unexpected: true }]) {
    await assert.rejects(api.submit('grant', v.attempt.grant, input, 'admin', () => {}))
    await assert.rejects(api.confirm('grant', { ...v.attempt.grant, commandId: v.command.id }, input, 'admin'))
    await assert.rejects(api.recover('grant', v.attempt.grant, input, 'admin', new AbortController().signal))
  }
  assert.deepEqual(calls, [])
})
function hookFixture() {
  const v = fixture(), slots = [], queryStates = Array.from({ length: 4 }, () => ({ isFetching: false, isError: false, dataUpdatedAt: 1 })), values = new Map(), calls = []
  const storage = recovery(() => ({ getItem: (k) => values.get(k) ?? null, setItem: (k, v) => values.set(k, v), removeItem: (k) => values.delete(k) }))
  let index = 0, queryIndex = 0, pending
  const mutation = { isPending: false, isError: false, reset() { this.isError = false }, mutate(args) {
    this.isPending = true
    pending = Promise.resolve().then(() => mutation.options.mutationFn(args)).then((value) => { this.isPending = false; mutation.options.onSettled(); return value },
      (error) => { this.isPending = false; this.isError = true; mutation.options.onSettled(); return error })
  } }
  const { useHttpFixtureOperation } = load('domains/quality-loop/useHttpFixtureOperation.ts', {
    react: { useState: (initial) => { const slot = index++; if (!(slot in slots)) slots[slot] = typeof initial === 'function' ? initial() : initial
      return [slots[slot], (value) => { slots[slot] = value }] },
    useRef: (initial) => { const slot = index++; if (!(slot in slots)) slots[slot] = { current: initial }; return slots[slot] }, useEffect: () => {} },
    '@tanstack/react-query': { useQueryClient: () => ({ invalidateQueries: async () => {} }),
      useMutation: (options) => { mutation.options = options; return mutation }, useQuery: (options) => { const state = queryStates[queryIndex++]; state.options = options; return state } },
    '../../shared/api/client': { ApiRequestError: class ApiRequestError extends Error {} },
    './httpFixtureOperationRecovery': { fixtureOperationRecovery: storage },
    './httpFixtureEnvironmentApi': { readFixtureEnvironment: async () => v.environment },
    './httpFixtureOperationApi': { fixtureOperationApi: {
      submit: async (stage, attempt, input, actor, ack) => { calls.push({ submit: stage, attempt: plain(attempt), input: plain(input), actor }); ack(stage + '-original'); throw new Error('unknown acknowledgement') },
      confirm: async (stage, attempt, input, actor) => { calls.push({ confirm: stage, attempt: plain(attempt), input: plain(input), actor }); return v.command },
      recover: async () => ({ ...v.command, id: 'grant-original', status: 'waiting_confirmation', result: null }),
    } },
  })
  const render = (current = true) => { index = queryIndex = 0; return useHttpFixtureOperation(v.plan, v.recipe, 'admin', current, () => {}) }
  return { v, calls, queryStates, render, wait: () => pending, values, storage }
}
test('actual hook requires fresh per-stage consent, prevents duplicate clicks and never retries an unknown write', async () => {
  const h = hookFixture(); let s = h.render(); s.toggle(); s = h.render()
  s.edit({ environmentCommandId: h.v.environment.metadata.invocation_id, attemptId: h.v.input.attempt_id }); s = h.render()
  s.verifyEnvironment(); s = h.render()
  assert.equal(h.queryStates[0].options.enabled, true)
  h.queryStates[0].data = await h.queryStates[0].options.queryFn({ signal: new AbortController().signal }); s = h.render()
  assert.equal(s.mayWrite('grant'), false); s.confirm('grant', true); s = h.render()
  assert.equal(s.mayWrite('grant'), true); assert.equal(s.mayWrite('execute'), false)
  s.submit('grant'); s.submit('grant'); await h.wait(); s = h.render()
  assert.equal(h.calls.length, 1); assert.equal(h.calls[0].submit, 'grant'); assert.equal(s.stored.attempt.grant.commandId, 'grant-original')
  assert.equal(s.mayWrite('grant'), false)
  s.reload(); s = h.render()
  h.queryStates[1].data = await h.queryStates[1].options.queryFn({ signal: new AbortController().signal }); s = h.render()
  assert.equal(h.calls.length, 1); assert.equal(s.confirmed('grant'), false)
  s.confirm('grant', true); s = h.render(); s.submit('grant'); await h.wait()
  assert.equal(h.calls.length, 2); assert.equal(h.calls[1].confirm, 'grant')
  assert.equal(h.calls[1].attempt.commandId, 'grant-original')
})
test('actual hook restores lost invoke acknowledgement by GET and confirms only the recovered original ID', async () => {
  const h = hookFixture(); h.storage.save('admin', h.v.attempt)
  let s = h.render(); s.toggle(); s = h.render()
  h.queryStates[0].data = await h.queryStates[0].options.queryFn({ signal: new AbortController().signal }); s = h.render()
  h.queryStates[1].data = await h.queryStates[1].options.queryFn({ signal: new AbortController().signal }); s = h.render()
  assert.equal(s.stored.attempt.grant.commandId, undefined)
  assert.equal(h.calls.length, 0); s.confirm('grant', true); s = h.render(); s.submit('grant'); await h.wait()
  assert.equal(h.calls.length, 1); assert.equal(h.calls[0].confirm, 'grant'); assert.equal(h.calls[0].attempt.commandId, 'grant-original')
})
test('actual hook clears consent on refreshed evidence and refuses a next operation for unknown or cancelled effects', async () => {
  const h = hookFixture(); let s = h.render(); s.toggle(); s = h.render()
  s.edit({ environmentCommandId: h.v.environment.metadata.invocation_id, attemptId: h.v.input.attempt_id }); s = h.render(); s.verifyEnvironment(); s = h.render()
  h.queryStates[0].data = { value: h.v.environment, input: h.v.input }; s = h.render(); s.confirm('grant', true); s = h.render()
  assert.equal(s.confirmed('grant'), true); h.queryStates[0].dataUpdatedAt++; s = h.render(); assert.equal(s.confirmed('grant'), false)
  h.queryStates[0].isFetching = true; s = h.render(); assert.equal(s.mayWrite('grant'), false); assert.equal(s.prepared, undefined)
  h.queryStates[0].isFetching = false
  const v = await executionFixture(), operation = { ...h.v.attempt, grant: { ...h.v.attempt.grant, commandId: h.v.command.id }, execute: v.executionAttempt }
  h.storage.save('admin', h.v.attempt); let saved = h.storage.acknowledge('admin', h.v.attempt, 'grant', h.v.command.id)
  saved = h.storage.add('admin', saved, 'execute', { requestKey: v.executionAttempt.requestKey, requestHash: v.executionAttempt.requestHash })
  h.storage.acknowledge('admin', saved, 'execute', v.execution.id)
  s.reload(); s = h.render(); h.queryStates[1].data = { command: h.v.command, grant: h.v.grant }
  h.queryStates[2].data = { command: v.execution, job: v.job }; s = h.render()
  const before = [...h.values.values()]; s.next(); assert.deepEqual([...h.values.values()], before)
  h.queryStates[2].data = { command: { ...v.execution, status: 'cancelled' }, job: { ...v.job, status: 'cancelled', cancellation_requested: true, cancellation_delivered: true } }
  s = h.render(); s.next(); assert.deepEqual([...h.values.values()], before)
  assert.deepEqual(plain(h.storage.read('admin', operation.projectId, operation.planId, operation.planHash, operation.recipeId, operation.recipeHash)), operation)
})
test('actual hook never inherits grant consent for execution or execution consent for cancellation', async () => {
  const h = hookFixture(), v = await executionFixture()
  h.storage.save('admin', h.v.attempt); h.storage.acknowledge('admin', h.v.attempt, 'grant', h.v.command.id)
  let s = h.render(); s.toggle(); s = h.render()
  h.queryStates[0].data = { value: h.v.environment, input: h.v.input }; h.queryStates[1].data = { command: h.v.command, grant: h.v.grant }; s = h.render()
  assert.equal(h.calls.length, 0); s.confirm('grant', true); s = h.render(); assert.equal(s.mayWrite('execute'), false)
  s.confirm('execute', true); s = h.render(); assert.equal(s.mayWrite('execute'), true)
  s.submit('execute'); await h.wait(); s = h.render(); assert.equal(h.calls.length, 1); assert.equal(h.calls[0].submit, 'execute')
  assert.equal(h.calls[0].input.grant_id, h.v.grant.metadata.record_id)
  s.reload(); s = h.render(); h.queryStates[2].data = { command: { ...v.execution, id: 'execute-original' }, job: { ...v.job, invocation_id: 'execute-original' } }; s = h.render()
  assert.equal(s.mayWrite('cancel'), false); s.confirm('cancel', true); s = h.render(); assert.equal(s.mayWrite('cancel'), true)
  s.submit('cancel'); await h.wait(); s = h.render()
  assert.equal(h.calls.length, 2); assert.equal(h.calls[1].submit, 'cancel'); assert.equal(h.calls[1].input.invocation_id, 'execute-original')
  assert.equal(s.stored.attempt.cancel.commandId, 'cancel-original'); assert.equal(s.stored.attempt.execute.commandId, 'execute-original')
})
for (const stage of ['grant', 'execute', 'cancel']) test(`pending ${stage} uses the verified click-time input after sensitive query data disappears`, async () => {
  const h = hookFixture(), v = await executionFixture()
  if (stage !== 'grant') {
    h.storage.save('admin', h.v.attempt)
    let saved = h.storage.acknowledge('admin', h.v.attempt, 'grant', h.v.command.id)
    if (stage === 'cancel') {
      saved = h.storage.add('admin', saved, 'execute', { requestKey: v.executionAttempt.requestKey, requestHash: v.executionAttempt.requestHash })
      h.storage.acknowledge('admin', saved, 'execute', v.execution.id)
    }
  }
  let s = h.render(); s.toggle(); s = h.render()
  if (stage === 'grant') {
    s.edit({ environmentCommandId: h.v.environment.metadata.invocation_id, attemptId: h.v.input.attempt_id })
    s = h.render(); s.verifyEnvironment(); s = h.render()
  }
  h.queryStates[0].data = { value: h.v.environment, input: h.v.input }
  if (stage !== 'grant') h.queryStates[1].data = { command: h.v.command, grant: h.v.grant }
  if (stage === 'cancel') h.queryStates[2].data = { command: v.execution, job: v.job }
  s = h.render(); s.confirm(stage, true); s = h.render(); assert.equal(s.mayWrite(stage), true)
  s.submit(stage)
  for (const state of h.queryStates) { state.data = undefined; state.isFetching = true }
  h.render(); await h.wait()
  assert.equal(h.calls.length, 1); assert.equal(h.calls[0].submit, stage)
  const expected = stage === 'grant' ? h.v.input : stage === 'execute' ? v.selection : { project_id: h.v.input.project_id, invocation_id: v.execution.id }
  assert.deepEqual(h.calls[0].input, expected)
  const saved = h.render().stored.attempt
  assert.equal(saved.environmentCommandId, h.v.environment.metadata.invocation_id)
  assert.equal(saved.attemptId, h.v.input.attempt_id)
  assert.equal(saved[stage].commandId, stage + '-original')
})
test('actual hook allows a completed fully observed setup to prepare cleanup of the same attempt, without sending it', async () => {
  const h = hookFixture(), v = await executionFixture('observed')
  h.storage.save('admin', h.v.attempt); let operation = h.storage.acknowledge('admin', h.v.attempt, 'grant', h.v.command.id)
  operation = h.storage.add('admin', operation, 'execute', { requestKey: v.executionAttempt.requestKey, requestHash: v.executionAttempt.requestHash })
  h.storage.acknowledge('admin', operation, 'execute', v.execution.id)
  let s = h.render(); s.toggle(); s = h.render(); h.queryStates[0].data = { value: h.v.environment, input: h.v.input }
  h.queryStates[1].data = { command: h.v.command, grant: h.v.grant }; h.queryStates[2].data = { command: { ...v.execution, status: 'completed' }, job: { ...v.job, status: 'completed' } }
  s = h.render(); s.next(); s = h.render()
  assert.equal(s.fields.operation, 'cleanup'); assert.equal(s.fields.attemptId, h.v.input.attempt_id)
  assert.equal(s.stored.attempt, null); assert.equal(h.calls.length, 0); assert.equal(s.confirmed('grant'), false)
  assert.equal(s.prepared, undefined)
})
const originalEnvironment = JSON.parse(execFileSync(path.join(repo, '.venv/bin/python'), ['-c', `
import json
from dataclasses import replace
from apps.api.tests.test_run_plan_builds import binding_inputs,refresh_pins
from apps.api.tests.test_owned_target_environment import spec,Commands
from apps.api.app.infrastructure.runner.owned_target_environment import OwnedTargetEnvironmentInspector
from apps.api.app.domain.quality_loop.run_plan_build import compile_run_plan_build
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.environment_observation_record import ENVIRONMENT_RECORD_SCHEMA,record_identity,environment_record_metadata
p,selection,builds=binding_inputs(multiple=True); owned=replace(spec.__wrapped__(),project_id='p'); plan=p['artifact']['plan']
plan['selection']['environment'].update(kind='local',base_url='http://127.0.0.1:8080',environment_id=owned.environment_id,inventory_hash=owned.digest)
selected=selection.model_dump(mode='json'); refresh_pins(p,selected,builds); bound=compile_run_plan_build(p,selected,builds)
p['metadata'].update(project_id='p',run_plan_id='plan',plan_digest=bound['plan_digest'],image_revision_id=bound['source_pin']['image_revision_id'],manifest_id=bound['source_pin']['manifest_id'])
request={**selected,'binding_digest':bound['binding_digest'],'source_scope_digest':acceptance_digest('explicit-source-scope')}
artifact={'schema':'nasus.run-plan-build-artifact.v1','project_id':'p','binding_id':'original-binding','invocation_id':'binding-command','actor_id':'admin','recorded_at':'2026-10-13T00:00:00Z','request':request,'binding':bound}
binding={'artifact':artifact,'metadata':{**{k:artifact[k] for k in ('project_id','binding_id','invocation_id','actor_id','recorded_at')},**{k:bound[k] for k in ('run_plan_id','run_plan_artifact_hash','plan_digest','binding_digest','target_artifact_hash')},'image_revision_id':bound['source_pin']['image_revision_id'],'manifest_id':bound['source_pin']['manifest_id'],'artifact_hash':acceptance_digest(artifact),'request_hash':acceptance_digest(request)},'historical_not_live':True,'current_use':{'inputs_current':True,'native_build_source_attested':True,'environment_verified':False,'fixtures_verified':False,'execution_authorized':False}}
commands=Commands(owned); commands.body=bound['target_artifact_hash'][7:].encode()+b'  /app/target.jar\\n'
observed=OwnedTargetEnvironmentInspector(owned,command=commands).inspect(bound['target_artifact_hash'],require_work=lambda:None)
env={'schema':ENVIRONMENT_RECORD_SCHEMA,'project_id':'p','record_id':record_identity('environment-command'),'invocation_id':'environment-command','actor_id':'admin','recorded_at':'2026-10-13T00:00:00Z','request':{'project_id':'p','run_plan_id':'plan','run_plan_artifact_hash':p['metadata']['artifact_hash'],'build_binding_id':'original-binding','build_binding_artifact_hash':binding['metadata']['artifact_hash']},'parents':{'plan_digest':bound['plan_digest'],'image_revision_id':bound['source_pin']['image_revision_id'],'manifest_id':bound['source_pin']['manifest_id'],'environment_id':owned.environment_id,'operator_policy_digest':owned.digest,'target_artifact_hash':bound['target_artifact_hash']},'observation':{'inventory':observed.inventory,'inventory_hash':observed.inventory_hash,'observed_at':observed.observed_at}}
for b in builds: b.update(status='completed',execution_authorized=False,historical_not_live=True)
print(json.dumps(dict(plan=p,binding=binding,builds=builds,environment=dict(metadata=environment_record_metadata(env),archive=env,historical_not_live=True))))
`], { cwd: repo, encoding: 'utf8' }))
function environmentReader(v, fault) {
  const calls = [], e = v.environment, binding = v.binding
  const envCommand = { id: e.metadata.invocation_id, tool_id: 'quality.run_plan.record_environment', status: 'completed',
    input_payload: { ...e.archive.request, idempotency_key: 'environment-key', confirmed_by_user: true },
    result: { invocation_id: e.metadata.invocation_id, status: 'completed', object_refs: ['run_plan_environment:' + e.metadata.record_id], run_plan_environment_record: { metadata: e.metadata, historical_not_live: true } } }
  const buildCommand = { id: binding.metadata.invocation_id, tool_id: 'quality.run_plan.bind_native_build', status: 'completed',
    input_payload: { ...binding.artifact.request, idempotency_key: 'binding-key', confirmed_by_user: true },
    result: { invocation_id: binding.metadata.invocation_id, status: 'completed', object_refs: ['run_plan_build:' + binding.metadata.binding_id] } }
  if (fault === 'environment-command') envCommand.input_payload.run_plan_id = 'foreign'
  if (fault === 'binding-command') buildCommand.input_payload.run_plan_artifact_hash = hash
  const { readFixtureEnvironment } = load('domains/quality-loop/httpFixtureEnvironmentApi.ts', {
    '../platform/api': { platformApi: { getToolInvocation: async (id, options) => { calls.push({ command: id, options }); return id === envCommand.id ? envCommand : buildCommand } } },
    '../../shared/api/client': { request: async (url, options) => {
      calls.push({ url, options })
      if (url.includes('/run-plan-builds/')) return binding
      if (url.includes('/native-builds/')) return v.builds.find((b) => url.endsWith('/' + b.invocation_id))
      if (url.includes('/run-plan-environments/')) return e
      throw new Error('Unexpected request')
    } },
  })
  return { read: (signal = new AbortController().signal) => readFixtureEnvironment(v.plan, envCommand.id, signal), calls }
}
test('environment selection replays complete original native-build members and inventory using GET only', async () => {
  const v = structuredClone(originalEnvironment), before = structuredClone(v), reader = environmentReader(v)
  assert.equal(await reader.read(), v.environment); assert.deepEqual(v, before)
  assert.equal(reader.calls.filter((c) => c.url?.includes('/native-builds/')).length, v.builds.length)
  assert.equal(reader.calls.filter((c) => c.url?.includes('/run-plan-environments/')).length, 1)
  assert.ok(reader.calls.filter((c) => c.url).every((c) => c.options.cache === 'no-store' && !c.options.method))
  const calls = reader.calls.length; await assert.rejects(reader.read(AbortSignal.abort()), { name: 'AbortError' }); assert.equal(reader.calls.length, calls)
})
for (const fault of ['environment-command', 'binding-command', 'binding-hint', 'missing-source', 'source-revision', 'target-inventory'])
  test(`environment selection rejects incomplete or different original parents: ${fault}`, async () => {
    const v = structuredClone(originalEnvironment)
    if (fault === 'binding-hint') v.binding.metadata.artifact_hash = hash
    if (fault === 'missing-source') v.builds.pop()
    if (fault === 'source-revision') v.builds[0].receipt.source.pin.source_revision_id = 'foreign'
    if (fault === 'target-inventory') v.environment.archive.observation.inventory.target.container_id = 'a'.repeat(64)
    await assert.rejects(environmentReader(v, fault).read())
  })
