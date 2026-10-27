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
  const context = { exports: {}, crypto: webcrypto, TextEncoder, URL, URLSearchParams, require: (name) => {
    if (Object.hasOwn(overrides, name)) return overrides[name]
    return load(path.relative(root, path.resolve(path.dirname(file), `${name}.ts`)), overrides, modules)
  } }
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, context)
  modules.set(file, context.exports); return context.exports
}
const { canonicalDigest: digest } = load('shared/utils/canonicalDigest.ts')
const validation = load('domains/quality-loop/runPlanValidation.ts'), drafts = load('domains/quality-loop/runPlanDraft.ts')
const recovery = load('domains/quality-loop/runPlanRecovery.ts'), plain = (v) => JSON.parse(JSON.stringify(v))
const hash = (c) => 'sha256:' + c.repeat(64)
// The independent Python compiler supplies this contract specimen, not business gold.
const native = JSON.parse(execFileSync(path.join(repo, '.venv/bin/python'), ['-c',
  'import json; from apps.api.tests.test_run_plans import plan_inputs; from apps.api.app.domain.quality_loop.run_plan import compile_run_plan; d,r,s,v=plan_inputs(); print(json.dumps(dict(draft=d,review=r,sources=s,selection=v.model_dump(mode="json"),plan=compile_run_plan(d,r,v.model_dump(mode="json"),s)),ensure_ascii=False))'], { cwd: repo, encoding: 'utf8' }))
const nativeBindings = JSON.parse(execFileSync(path.join(repo, '.venv/bin/python'), ['-c',
  'import json; from apps.api.tests.test_http_binding_scripts import binding_plan_inputs; from apps.api.app.domain.quality_loop.run_plan import compile_run_plan; d,r,s,v=binding_plan_inputs(); print(json.dumps(dict(draft=d,review=r,sources=s,selection=v,plan=compile_run_plan(d,r,v,s)),ensure_ascii=False))'], { cwd: repo, encoding: 'utf8' }))
const nativeFixtures = JSON.parse(execFileSync(path.join(repo, '.venv/bin/python'), ['-c',
  'import json; from apps.api.tests.test_http_fixture_binding_scripts import fixture_plan_inputs; from apps.api.app.domain.quality_loop.run_plan import compile_run_plan; d,r,s,v=fixture_plan_inputs(); print(json.dumps(dict(draft=d,review=r,sources=s,selection=v,plan=compile_run_plan(d,r,v,s)),ensure_ascii=False))'], { cwd: repo, encoding: 'utf8' }))
function fixture(protocol = 'v1') {
  const v = structuredClone(protocol === 'v3' ? nativeFixtures : protocol === 'v2' ? nativeBindings : native), b = v.selection.target_build, e = v.selection.environment
  v.fields = { artifactName: b.artifact_name, artifactHash: b.artifact_hash, definitionHash: b.build_definition_hash,
    runtime: b.runtime, runtimeVersion: b.runtime_version, buildTool: b.build_tool, buildToolVersion: b.build_tool_version,
    environmentId: e.environment_id, kind: e.kind, origin: e.base_url, inventoryHash: e.inventory_hash, isolation: e.isolation,
    reason: v.selection.reason, fixtures: Object.fromEntries(v.selection.fixtures.map((f) => [f.case_id,
      { dataHash: f.data_manifest_hash, setup: f.setup.join('\n'), cleanup: f.cleanup.join('\n') }])) }
  v.request = { ...v.selection, plan_digest: v.plan.plan_digest, source_scope_digest: hash('a') }
  v.preview = { request: v.request, case_count: v.plan.prepared.cases.length, obligation_count: v.plan.prepared.obligation_denominator,
    status: 'preview', target_verification: v.plan.target_verification, execution_authorized: false,
    remaining_gates: ['fresh_prepare_confirmation', ...v.plan.remaining_gates] }
  return v
}
test('frontend RunPlan matches the independent Python compiler byte digest', async () => {
  const v = fixture(), result = await validation.expectedRunPlan(v.selection, v.draft, v.review, v.sources)
  assert.deepEqual(plain(result), v.plan)
  assert.deepEqual(plain(await drafts.runPlanSelection(v.fields, v.draft, v.review, v.sources)), v.selection)
  assert.equal(await validation.verifyRunPlanPreview(v.preview, v.selection, v.draft, v.review, v.sources), v.preview)
})
test('explicit v2 RunPlan matches Python without rewriting old plan policy', async () => {
  const v = fixture('v2'), original = structuredClone(v)
  assert.deepEqual(plain(await validation.expectedRunPlan(v.selection, v.draft, v.review, v.sources)), v.plan)
  assert.deepEqual(plain(await drafts.runPlanSelection(v.fields, v.draft, v.review, v.sources)), v.selection)
  assert.equal(v.selection.policy_revision, 'nasus.run-plan.v2')
  assert.equal(fixture().selection.policy_revision, 'nasus.run-plan.v1')
  const a = await archive(v)
  assert.equal(await validation.verifyRunPlanArchive(a, v.request, 'command', v.draft, v.review, v.sources), a)
  const bad = structuredClone(a); bad.artifact.schema = 'nasus.run-plan-artifact.v1'; bad.metadata.artifact_hash = await digest(bad.artifact)
  await assert.rejects(validation.verifyRunPlanArchive(bad, v.request, 'command', v.draft, v.review, v.sources))
  await assert.rejects(validation.expectedRunPlan({ ...v.selection, policy_revision: 'nasus.run-plan.v1' }, v.draft, v.review, v.sources))
  assert.deepEqual(v, original)
})
test('all original cases and code sources remain selected without editable version IDs', async () => {
  const v = fixture(); v.sources.source_members.push({ binding_id: 'code-two', source_revision_id: 'revision-two', source_type: 'code', status: 'captured' })
  const original = structuredClone(v)
  const selection = await drafts.runPlanSelection(v.fields, v.draft, v.review, v.sources)
  assert.equal(selection.target_build.code_sources.length, 2)
  assert.deepEqual(plain(selection.fixtures), v.selection.fixtures); assert.deepEqual(v, original)
  for (const change of [(s) => s.target_build.code_sources.pop(), (s) => s.target_build.code_sources.push(s.target_build.code_sources[0]),
    (s) => s.fixtures.pop(), (s) => s.fixtures[0].preconditions_digest = hash('b')]) {
    const bad = structuredClone(selection); change(bad)
    await assert.rejects(validation.expectedRunPlan(bad, v.draft, v.review, v.sources))
  }
})
test('new declarations start empty and every case needs setup, cleanup and manifest', () => {
  const v = fixture(); assert.equal(drafts.runPlanFieldsValid(drafts.emptyRunPlanFields(v.draft), v.draft), false)
  assert.equal(drafts.runPlanFieldsValid(v.fields, v.draft), true)
  for (const change of [(f) => f.artifactName = ' ', (f) => f.artifactHash = 'unverified', (f) => f.reason = '',
    (f) => f.fixtures[v.selection.fixtures[0].case_id].cleanup = '', (f) => f.fixtures.extra = f.fixtures[v.selection.fixtures[0].case_id]]) {
    const bad = structuredClone(v.fields); change(bad); assert.equal(drafts.runPlanFieldsValid(bad, v.draft), false)
  }
})
for (const origin of ['file:///etc/passwd', 'http://user:secret@localhost', 'http://localhost?key=secret', 'http://localhost?',
  'http://localhost#secret', 'http://localhost/api', 'http://localhost:0', 'http://localhost:99999', 'http://localhost\\evil', 'http://local host']) {
  test(`target origin rejects paths, credentials or invalid ports: ${origin}`, () => assert.equal(drafts.runPlanOrigin(origin), false))
}
test('preview rejects altered declarations, counts, authority and remaining gates', async () => {
  const v = fixture()
  for (const change of [(p) => p.request.environment.inventory_hash = hash('b'), (p) => p.case_count++,
    (p) => p.execution_authorized = true, (p) => p.remaining_gates.pop(), (p) => p.request.source_scope_digest = 'invalid']) {
    const bad = structuredClone(v.preview); change(bad)
    await assert.rejects(validation.verifyRunPlanPreview(bad, v.selection, v.draft, v.review, v.sources))
  }
})
async function archive(v) {
  const body = { schema: validation.runPlanArtifactSchema(v.selection.policy_revision), project_id: v.selection.project_id, run_plan_id: 'original-plan',
    invocation_id: 'command', actor_id: 'reviewer', recorded_at: '2026-10-10T00:00:00Z', request: v.request, plan: v.plan }
  return { artifact: body, metadata: { ...Object.fromEntries(['project_id', 'run_plan_id', 'invocation_id', 'actor_id', 'recorded_at'].map((k) => [k, body[k]])),
    artifact_hash: await digest(body), request_hash: await digest(v.request), plan_digest: v.plan.plan_digest, status: 'prepared', execution_authorized: false,
    context_id: v.plan.prepared.context_pin.context_id, image_revision_id: v.sources.image_revision_id, manifest_id: v.sources.manifest_id,
    script_revision_id: v.selection.script_revision_id, review_revision_id: v.selection.review_revision_id },
    historical_not_live: true, current_use: { inputs_current: true, target_verified: false, execution_authorized: false } }
}
test('saved plan preserves all steps and oracles, even when an attacker recomputes the archive hash', async () => {
  const v = fixture(), a = await archive(v)
  assert.equal(await validation.verifyRunPlanArchive(a, v.request, 'command', v.draft, v.review, v.sources), a)
  for (const change of [(p) => p.artifact.plan.prepared.cases[0].steps.pop(), (p) => p.artifact.plan.passed_count = 1,
    (p) => p.current_use.target_verified = true, (p) => p.metadata.context_id = 'foreign', (p) => p.artifact.plan.selection.fixtures.pop()]) {
    const bad = structuredClone(a); change(bad); bad.metadata.artifact_hash = await digest(bad.artifact)
    await assert.rejects(validation.verifyRunPlanArchive(bad, v.request, 'command', v.draft, v.review, v.sources))
  }
  v.draft.current_use.input_current = false
  await assert.rejects(validation.verifyRunPlanArchive(a, v.request, 'command', v.draft, v.review, v.sources))
  a.current_use.inputs_current = false
  assert.equal(await validation.verifyRunPlanArchive(a, v.request, 'command', v.draft, v.review, v.sources), a)
})
test('explicit v3 RunPlan matches the independent Python compiler and preserves all original cases and oracles', async () => {
  const v = fixture('v3'), original = structuredClone(v), a = await archive(v)
  assert.deepEqual(plain(await validation.expectedRunPlan(v.selection, v.draft, v.review, v.sources)), v.plan)
  assert.deepEqual(plain(await drafts.runPlanSelection(v.fields, v.draft, v.review, v.sources)), v.selection)
  assert.equal(await validation.verifyRunPlanPreview(v.preview, v.selection, v.draft, v.review, v.sources), v.preview)
  assert.equal(await validation.verifyRunPlanArchive(a, v.request, 'command', v.draft, v.review, v.sources), a)
  assert.deepEqual(v, original)
  assert.equal(a.artifact.schema, 'nasus.run-plan-artifact.v3')
  assert.equal(v.plan.proposal.http_protocol, 'nasus.runner-http-execution.v3')
  assert.equal(v.plan.passed_count, 0)
  for (const policy of ['nasus.run-plan.v1', 'nasus.run-plan.v2']) {
    await assert.rejects(validation.expectedRunPlan({ ...v.selection, policy_revision: policy }, v.draft, v.review, v.sources))
    const bad = structuredClone(a)
    bad.artifact.schema = validation.runPlanArtifactSchema(policy); bad.metadata.artifact_hash = await digest(bad.artifact)
    await assert.rejects(validation.verifyRunPlanArchive(bad, v.request, 'command', v.draft, v.review, v.sources))
  }
  assert.throws(() => validation.runPlanArtifactSchema('nasus.run-plan.v4'))
})
test('recovery stores only actor-scoped IDs and request digest, never target declarations or original text', async () => {
  const v = fixture(), values = new Map(), storage = { getItem: (k) => values.get(k) ?? null, setItem: (k, val) => values.set(k, val), removeItem: (k) => values.delete(k) }
  const r = recovery.createRunPlanRecovery(() => storage), attempt = { projectId: v.selection.project_id, scriptId: v.selection.script_revision_id,
    reviewId: v.selection.review_revision_id, requestKey: 'original-request', requestHash: await digest(v.request) }
  r.save('owner', attempt)
  assert.deepEqual(plain(r.read('owner', attempt.projectId, attempt.scriptId, attempt.reviewId)), attempt)
  assert.equal(r.read('other', attempt.projectId, attempt.scriptId, attempt.reviewId), null)
  assert.throws(() => r.save('owner', attempt)); assert.throws(() => recovery.verifyRunPlanAttempt({ ...attempt, base_url: 'secret' }))
  const ack = { ...attempt, commandId: 'command' }; r.acknowledge('owner', ack)
  assert.throws(() => r.acknowledge('owner', { ...ack, commandId: 'foreign' }))
  assert.throws(() => r.clear('owner', attempt)); assert.doesNotMatch([...values.values()][0], /base_url|preconditions|setup|cleanup/)
  r.clear('owner', ack); assert.equal(values.size, 0)
})
test('lost confirm acknowledgement is never resent and original recovery is GET-only', async () => {
  const v = fixture(), calls = [], seen = [], attempt = { projectId: v.selection.project_id, scriptId: v.selection.script_revision_id,
    reviewId: v.selection.review_revision_id, requestKey: 'original-request', requestHash: await digest(v.request) }
  const command = { id: 'command', tool_id: 'quality.run_plan.prepare', input_payload: { ...v.request, idempotency_key: attempt.requestKey }, status: 'waiting_confirmation' }
  const { runPlanApi: api } = load('domains/quality-loop/runPlanApi.ts', { '../platform/api': { platformApi: {
    invokeTool: async (input) => { calls.push(input); return command }, confirmToolInvocation: async (id) => { calls.push(id); throw new Error('Lost acknowledgement') },
  } }, '../system-image/imageRevisionApi': {}, '../../shared/api/client': { request: async (url, options) => { calls.push({ url, options }); return command } } })
  await assert.rejects(api.prepare(v.request, attempt, (a) => seen.push(plain(a))))
  assert.equal(calls.length, 2); assert.equal(seen[0].commandId, 'command')
  const recovered = await api.recover(attempt, new AbortController().signal)
  assert.equal(recovered.command.status, 'waiting_confirmation'); assert.equal(calls.length, 3)
  assert.match(calls[2].url, /tool-invocations\/resolve\?/); assert.equal(calls[2].options.cache, 'no-store'); assert.equal(calls[2].options.method, undefined)
  await assert.rejects(api.recover(attempt, AbortSignal.abort()), { name: 'AbortError' }); assert.equal(calls.length, 3)
})
test('original command lookup rejects a different request, actor key or plan reference', async () => {
  const v = fixture(), attempt = { projectId: v.selection.project_id, scriptId: v.selection.script_revision_id,
    reviewId: v.selection.review_revision_id, requestKey: 'original-request', requestHash: await digest(v.request), commandId: 'command' }
  const { requireRunPlanCommand } = load('domains/quality-loop/runPlanApi.ts', { '../platform/api': {}, '../system-image/imageRevisionApi': {}, '../../shared/api/client': {} })
  const command = { id: 'command', tool_id: 'quality.run_plan.prepare', input_payload: { ...v.request, idempotency_key: attempt.requestKey, confirmed_by_user: true },
    status: 'completed', result: { invocation_id: 'command', status: 'completed', object_refs: ['run_plan:plan'] } }
  await requireRunPlanCommand(command, attempt)
  for (const change of [(p) => p.id = 'foreign', (p) => p.input_payload.environment.base_url = 'http://foreign',
    (p) => p.input_payload.idempotency_key = 'other', (p) => p.result.object_refs.push('run_plan:other'), (p) => p.result.invocation_id = 'foreign']) {
    const bad = structuredClone(command); change(bad); await assert.rejects(requireRunPlanCommand(bad, attempt))
  }
})
test('source inventory reads every fixed page and rejects discontinuity, changed hash or duplicate bindings', async () => {
  const v = fixture(), pages = [{ revision: { project_id: v.sources.project_id, image_revision_id: v.sources.image_revision_id,
    artifact_hash: v.sources.image_artifact_hash, manifest_id: v.sources.manifest_id, manifest_hash: v.sources.manifest_hash },
    section: 'source_members', items: [v.sources.source_members[0]], total: 2, next_offset: 1 }]
  pages.push({ ...pages[0], items: [v.sources.source_members[1]], next_offset: null })
  let index = 0, offsets = []
  const { readRunPlanSources } = load('domains/quality-loop/runPlanApi.ts', { '../platform/api': {}, '../../shared/api/client': {}, '../system-image/imageRevisionApi': {
    imageRevisionApi: { page: async (_p, _i, selection) => { offsets.push(selection.offset); return pages[index++] } } } })
  assert.deepEqual(plain(await readRunPlanSources(v.draft, new AbortController().signal)), v.sources)
  assert.deepEqual(offsets, [0, 1])
  pages[1] = { ...pages[1], items: [pages[0].items[0]] }; index = 0
  await assert.rejects(readRunPlanSources(v.draft, new AbortController().signal))
  pages[1] = { ...pages[1], items: [v.sources.source_members[1]], revision: { ...pages[1].revision, artifact_hash: hash('b') } }; index = 0
  await assert.rejects(readRunPlanSources(v.draft, new AbortController().signal))
})
