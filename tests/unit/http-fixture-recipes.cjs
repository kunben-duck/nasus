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
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, context)
  modules.set(file, context.exports); return context.exports
}
const validation = load('domains/quality-loop/httpFixtureRecipeValidation.ts')
const { createLocatorRecovery } = load('domains/quality-loop/runPlanLocatorRecordRecovery.ts')
const { canonicalDigest: digest } = load('shared/utils/canonicalDigest.ts')
const plain = (v) => JSON.parse(JSON.stringify(v))
// Complete Python domain specimen; no real target, database or business approval.
const native = JSON.parse(execFileSync(path.join(repo, '.venv/bin/python'), ['-c', `
import json
from apps.api.tests.test_http_fixture_recipes import specimen
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixture_recipe import validate_recipe_archive
q,p,a=specimen(); artifact=p['artifact']; plan=artifact['plan']
artifact.update(schema='nasus.run-plan-artifact.'+plan['schema'].rsplit('.',1)[1],invocation_id='original-plan-command',actor_id='reviewer',recorded_at=a['recorded_at'],request={**plan['selection'],'plan_digest':plan['plan_digest'],'source_scope_digest':acceptance_digest('explicit-unit-source-scope')})
p['metadata'].update(invocation_id=artifact['invocation_id'],image_revision_id=plan['source_pin']['image_revision_id'],manifest_id=plan['source_pin']['manifest_id'],artifact_hash=acceptance_digest(artifact))
p['current_use']={'inputs_current':True}
a['request']['run_plan_artifact_hash']=p['metadata']['artifact_hash']
print(json.dumps(dict(plan=p,view=dict(metadata=validate_recipe_archive(a,a['request'],p),archive=a,historical_not_live=True))))
`], { cwd: repo, encoding: 'utf8' }))
function fixture() {
  const v = structuredClone(native), a = v.view.archive
  v.attempt = { projectId: a.project_id, planId: a.request.run_plan_id, planHash: a.request.run_plan_artifact_hash,
    requestKey: 'original-fixture-key', requestHash: v.view.metadata.request_hash }
  v.command = { id: a.invocation_id, tool_id: 'quality.http_fixture.register', status: 'completed',
    input_payload: { ...a.request, idempotency_key: v.attempt.requestKey, confirmed_by_user: true },
    result: { invocation_id: a.invocation_id, status: 'completed', object_refs: ['http_fixture_recipe:' + a.record_id],
      http_fixture_recipe: { metadata: v.view.metadata, historical_not_live: true } } }
  return v
}
test('complete Python definition retains exact parent pins, native UUID and no execution authority', async () => {
  const v = fixture(), before = structuredClone(v)
  assert.equal(await validation.fixtureRecipeIdentity(v.command.id), v.view.metadata.record_id)
  assert.deepEqual(plain(await validation.parseFixtureRecipe(v.plan, JSON.stringify(v.view.archive.request.manifest))), v.view.archive.request)
  assert.equal(await validation.verifyFixtureRecipe(v.view, v.plan, v.command.id, v.view.metadata.record_id), v.view)
  assert.deepEqual(plain(await validation.expectedFixtureMetadata(v.view.archive)), v.view.metadata)
  v.plan.current_use.inputs_current = false
  assert.equal(await validation.verifyFixtureRecipe(v.view, v.plan, v.command.id, v.view.metadata.record_id), v.view)
  before.plan.current_use.inputs_current = false; assert.deepEqual(v, before)
})
const faults = {
  project: (v) => v.view.archive.project_id = 'foreign',
  schema: (v) => v.view.archive.schema = 'nasus.run-plan-locator-record.v1',
  command: (v) => v.view.archive.invocation_id = 'foreign',
  record: (v) => v.view.archive.record_id = 'foreign',
  actor: (v) => v.view.archive.actor_id = '',
  time: (v) => v.view.archive.recorded_at = '2026-10-12T00:00:00',
  plan: (v) => v.view.archive.request.run_plan_id = 'foreign',
  image: (v) => v.view.archive.parents.image_artifact_hash = 'sha256:' + 'b'.repeat(64),
  manifest: (v) => v.view.archive.parents.manifest_id = 'foreign',
  oracle: (v) => v.view.archive.request.manifest.setup_steps.at(-1).value_json = '"ALTERED_EXPECTED"',
  cleanup: (v) => v.view.archive.request.manifest.cleanup_groups.session[0].path = '/sessions/foreign/close',
  declared: (v) => v.view.archive.request.manifest.cleanup.push('A different declaration'),
  authority: (v) => v.view.archive.execution_authorized = true,
  case: (v) => v.view.archive.request.manifest.case_id = 'foreign',
  request: (v) => v.view.archive.request.extra = 'untrusted',
}
for (const [name, mutate] of Object.entries(faults)) test(`rehashed archive rejects original-scope tampering: ${name}`, async () => {
  const v = fixture(); mutate(v)
  v.view.metadata = plain(await validation.expectedFixtureMetadata(v.view.archive))
  await assert.rejects(validation.verifyFixtureRecipe(v.view, v.plan, v.command.id, native.view.metadata.record_id))
})
for (const [field, value] of [['recipe_bytes_verified', 1], ['execution_authorized', 0], ['fixtures_verified', 0], ['passed_count', false]])
  test(`metadata does not coerce types: ${field}`, async () => {
    const v = fixture(); v.view.metadata[field] = value
    await assert.rejects(validation.verifyFixtureRecipe(v.view, v.plan, v.command.id, native.view.metadata.record_id))
  })
const invalid = {
  empty: (v) => v.setup_steps = [],
  missingCapture: (v) => v.setup_steps.splice(1, 1),
  unsafeHeaders: (v) => v.setup_steps[0].headers_json = '{"Authorization":"Bearer untrusted"}',
  externalOrigin: (v) => v.setup_steps[0].path = '//foreign.example/session',
  missingStatus: (v) => v.setup_steps = v.setup_steps.filter((s) => s.action !== 'assert_status'),
  noCleanup: (v) => v.cleanup_groups = {},
  wrongOwner: (v) => v.cleanup_groups.session[0].path = '/sessions/{{foreign}}/close',
  fakeCapture: (v) => v.cleanup_groups.session.push({ action: 'capture_json', request_id: 'close', pointer: '/id', binding_id: 'extra' }),
  indices: (v) => v.setup_steps[0].source_step_indices = [true],
  getBody: (v) => v.setup_steps[0].method = 'GET',
  bounds: (v) => v.setup = ['x'.repeat(2001)],
}
for (const [name, mutate] of Object.entries(invalid)) test(`complete recipe validation rejects unsafe or incomplete steps: ${name}`, () => {
  const v = fixture().view.archive.request.manifest; mutate(v)
  assert.throws(() => validation.verifyFixtureManifest(v))
})
test('strict JSON rejects duplicated keys and over-budget input before registration', async () => {
  const v = fixture(), source = JSON.stringify(v.view.archive.request.manifest)
  await assert.rejects(validation.parseFixtureRecipe(v.plan, source.replace('"case_id":', '"case_id":"foreign","case_id":')))
  await assert.rejects(validation.parseFixtureRecipe(v.plan, ' '.repeat(128 * 1024 + 1)))
  await assert.rejects(validation.parseFixtureRecipe(v.plan, source.replace('"value_json":', '"value_json":"NaN","value_json":')))
})
test('a recomputed foreign wrapper cannot change the original plan project', async () => {
  const v = fixture(), plan = v.plan
  plan.metadata.project_id = plan.artifact.project_id = 'foreign'
  plan.metadata.artifact_hash = await digest(plan.artifact)
  await assert.rejects(validation.fixtureRecipeRequest(plan, v.view.archive.request.manifest))
})
test('resource and complete-step budgets apply to all groups, without truncation', () => {
  const grow = (resources, cleanupRequests) => {
    const v = fixture().view.archive.request.manifest, request = v.setup_steps[0]
    v.setup_steps = []; v.cleanup_groups = {}
    for (let i = 0; i < resources; i++) {
      const name = 'resource_' + i, id = 'create_' + i
      v.setup_steps.push({ ...request, request_id: id }, { action: 'capture_json', request_id: id, pointer: '/id', binding_id: name },
        { action: 'assert_status', request_id: id, value: '201' })
      v.cleanup_groups[name] = Array.from({ length: cleanupRequests }, (_, j) => [
        { action: 'request', request_id: 'remove_' + j, method: 'DELETE', path: '/sessions/{{' + name + '}}', headers_json: '{}', body_json: 'null' },
        { action: 'assert_status', request_id: 'remove_' + j, value: '204' },
      ]).flat()
    }
    return v
  }
  assert.equal(validation.verifyFixtureManifest(grow(16, 1)).setup_steps.length, 48)
  assert.throws(() => validation.verifyFixtureManifest(grow(17, 1)))
  assert.throws(() => validation.verifyFixtureManifest(grow(16, 12)))
})
test('recovery isolates actor and namespace and never persists the private definition', () => {
  const v = fixture(), values = new Map(), storage = () => ({ getItem: (k) => values.get(k) ?? null, setItem: (k, v) => values.set(k, v), removeItem: (k) => values.delete(k) })
  const r = createLocatorRecovery(storage, 'nasus.http-fixture-recipe.v1:'), locator = createLocatorRecovery(storage)
  r.save('owner', v.attempt)
  assert.equal(r.read('other', v.attempt.projectId, v.attempt.planId, v.attempt.planHash), null)
  assert.equal(locator.read('owner', v.attempt.projectId, v.attempt.planId, v.attempt.planHash), null)
  assert.doesNotMatch([...values.values()].join(''), /setup|cleanup|manifest|headers_json|value_json|password/)
  assert.throws(() => r.save('owner', { ...v.attempt, requestKey: 'duplicate' }))
  assert.throws(() => r.read('owner', v.attempt.projectId, v.attempt.planId, 'sha256:' + 'b'.repeat(64)))
  const ack = { ...v.attempt, commandId: v.command.id }; r.acknowledge('owner', ack)
  assert.throws(() => r.acknowledge('owner', { ...ack, requestHash: 'sha256:' + 'a'.repeat(64) }))
  r.clear('owner', ack); assert.equal(values.size, 0)
})
test('lost confirmation acknowledgement is recovered only by GET of the exact original command', async () => {
  const v = fixture(), calls = [], acknowledgements = [], pending = { ...v.command, status: 'waiting_confirmation', result: null }
  const api = load('domains/quality-loop/httpFixtureRecipeApi.ts', {
    '../platform/api': { platformApi: { invokeTool: async (body) => { calls.push(body); return pending },
      confirmToolInvocation: async (id) => { calls.push({ confirm: id }); throw new Error('Lost original acknowledgement') } } },
    '../../shared/api/client': { request: async (url, options) => { calls.push({ url, options }); return pending } },
  }).fixtureRecipeApi
  await assert.rejects(api.register(v.view.archive.request, v.attempt, v.plan, (v) => acknowledgements.push(v)))
  assert.equal(calls[0].tool_id, 'quality.http_fixture.register'); assert.equal(acknowledgements[0].commandId, v.command.id)
  await api.recover(v.attempt, v.plan, new AbortController().signal)
  assert.equal(calls.length, 3); assert.match(calls[2].url, /tool_id=quality.http_fixture.register/)
  assert.equal(calls[2].options.cache, 'no-store'); assert.equal(calls[2].options.method, undefined)
  await assert.rejects(api.recover(v.attempt, v.plan, AbortSignal.abort())); assert.equal(calls.length, 3)
})
test('private history requires original full command, archive and metadata without executing any request', async () => {
  const v = fixture(), calls = [], api = load('domains/quality-loop/httpFixtureRecipeApi.ts', {
    '../platform/api': { platformApi: {} }, '../../shared/api/client': { request: async (url, options) => { calls.push({ url, options }); return v.view } },
  }).fixtureRecipeApi
  assert.equal(await api.read(v.command, v.plan, new AbortController().signal), v.view)
  for (const mutate of [(v) => v.tool_id = 'query.quality.http_fixture_recipe', (v) => v.input_payload.run_plan_id = 'foreign',
    (v) => v.input_payload.confirmed_by_user = 1, (v) => v.input_payload.manifest.setup_steps[0].path = '/foreign',
    (v) => v.result.object_refs = ['run_plan:' + native.view.metadata.record_id]]) {
    const bad = structuredClone(v.command); mutate(bad)
    await assert.rejects(api.read(bad, v.plan, new AbortController().signal))
  }
  assert.equal(calls.length, 1)
  const bad = structuredClone(v.command); bad.result.http_fixture_recipe.metadata.execution_authorized = 0
  await assert.rejects(api.read(bad, v.plan, new AbortController().signal))
  assert.equal(calls.length, 2); assert.ok(calls.every((c) => c.url.includes('/quality/http-fixture-recipes/') && !c.options.method && c.options.cache === 'no-store'))
})
