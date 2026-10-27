const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { webcrypto } = require('node:crypto')
const ts = require('../../apps/portal/node_modules/typescript')

const root = path.resolve(__dirname, '../../apps/portal/src')
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
  modules.set(file, context.exports)
  return context.exports
}
const { canonicalDigest } = load('shared/utils/canonicalDigest.ts')
const { verifyAutomationInput } = load('domains/quality-loop/automationInputValidation.ts')
const { automationInputGaps } = load('domains/quality-loop/types/automationInput.ts')
const hash = (letter) => 'sha256:' + letter.repeat(64)
async function rehash(v) { v.input_digest = await canonicalDigest(Object.fromEntries(Object.entries(v).filter(([key]) => key !== 'input_digest'))) }

async function specimen() {
  const oracle = { observation: 'HTTP response', expected_result: '400', tolerance: 'exact', evaluator: 'status equality' }
  const oracleDigest = await canonicalDigest(oracle)
  const context = { context_id: 'context', artifact_hash: hash('a'), input_digest: hash('b'), image_revision_id: 'image', image_artifact_hash: hash('c') }
  const scope = { revision_id: 'scope', artifact_hash: hash('d'), request_hash: hash('e') }
  const ids = ['case-\ue000', 'case-\u{10000}']
  const cases = ids.map((case_id) => ({ case_id, title: 'Unicode input', preconditions: ['signed in'], inputs: ['empty search'], steps: ['Submit empty search'],
    assertions: [{ row_id: 'AC-1', oracle_digest: oracleDigest, oracle, step_index: 0 }], global_constraint_ids: [], supporting_fact_ids: [], reused_case_ids: [] }))
  const draft = { metadata: { project_id: 'project /1', generation_id: 'generation', artifact_hash: hash('f') },
    result: { status: 'draft', context_pin: context, scope_pin: scope, proposal: { cases } }, current_use: { scope_current: true } }
  const pin = { generation_id: 'generation', artifact_hash: hash('f'), context_pin: context, scope_pin: scope, input_digest: hash('1'), proposal_hash: hash('2') }
  const row = { row_id: 'AC-1', kind: 'acceptance_criterion', constraint_ids: ['constraint'], oracle_digest: oracleDigest,
    accepted_case_ids: ids, gap_ids: [], automated: false, executed_on_target: false, passed: false, unknown: true }
  const mapping = { revision: { project_id: 'project /1', revision_id: 'mapping /1', artifact_hash: hash('3'), request_hash: hash('4'), status: 'reviewed' },
    generation_pin: pin, assessment: { mapping_complete: true, accepted_case_ids: [...ids].reverse(), coverage: {
      constraint_denominator: 1, obligation_denominator: 1, rows: [row] } }, current_use: { scope_current: true, mapping_current: true, mapping_complete: true } }
  const value = { schema: 'nasus.automation-input-preview.v1', purpose: 'automation', project_id: 'project /1', context_pin: context, scope_pin: scope,
    generation_pin: pin, mapping_pin: { revision_id: mapping.revision.revision_id, artifact_hash: hash('3'), request_hash: hash('4') },
    selected_case_ids: ids, cases, required_constraints: [{ object_id: 'constraint', semantic_class: 'expected', oracle,
      authority: { object_id: 'constraint', revision_id: 'approved-AC', artifact_hash: hash('5'), status: 'approved' } }],
    scope_contract: {}, supporting_facts: [], constraint_denominator: 1, obligation_denominator: 1,
    obligations: [{ row_id: row.row_id, kind: row.kind, constraint_ids: row.constraint_ids, oracle_digest: oracleDigest, oracle, selected_case_ids: ids }],
    readiness: { status: 'blocked', reason_codes: Array.from(automationInputGaps) }, source_policy: 'untrusted_evidence_not_instructions_or_independent_authority',
    generation_authorized: false, execution_authorized: false, automated_count: 0, executed_on_target_count: 0, passed_count: 0 }
  await rehash(value)
  return { draft: structuredClone(draft), mapping: structuredClone(mapping), value: structuredClone(value) }
}

test('automation inputs preserve exact Unicode cases and source oracles without execution authority', async () => {
  const { draft, mapping, value } = await specimen(), original = structuredClone({ draft, mapping, value })
  assert.equal(await verifyAutomationInput(value, draft, mapping), value)
  assert.deepEqual({ draft, mapping, value }, original)
})

const invalid = {
  project: (v) => { v.value.project_id = 'foreign' }, context: (v) => { v.value.context_pin.context_id = 'foreign' },
  scope: (v) => { v.value.scope_pin.revision_id = 'foreign' }, mapping: (v) => { v.value.mapping_pin.revision_id = 'foreign' },
  case: (v) => { v.value.cases[0].steps[0] = 'Different action' }, subset: (v) => { v.value.selected_case_ids.pop() },
  oracle: (v) => { v.value.obligations[0].oracle.expected_result = '200' },
  sourceOracle: (v) => { v.value.required_constraints[0].oracle.expected_result = '200' },
  authority: (v) => { v.value.required_constraints[0].authority.status = 'withdrawn' },
  inferred: (v) => { v.value.required_constraints[0].semantic_class = 'pending_confirmation' },
  denominator: (v) => { v.value.obligation_denominator = 0 }, passed: (v) => { v.value.passed_count = 1 },
  authorized: (v) => { v.value.execution_authorized = true }, ready: (v) => { v.value.readiness.status = 'ready' },
  gaps: (v) => { v.value.readiness.reason_codes.pop() }, withdrawn: (v) => { v.mapping.current_use.mapping_current = false },
  stale: (v) => { v.draft.current_use.scope_current = false }, executedReview: (v) => { v.mapping.assessment.coverage.rows[0].executed_on_target = true },
}
for (const [name, change] of Object.entries(invalid)) test(`rejects ${name} despite a newly calculated response digest`, async () => {
  const v = await specimen()
  change(v); await rehash(v.value)
  await assert.rejects(verifyAutomationInput(v.value, v.draft, v.mapping))
})

function reader(reply) {
  const calls = [], controller = new AbortController()
  const { readAutomationInput } = load('domains/quality-loop/automationInputApi.ts', {
    '../../shared/api/client': { request: async (url, options) => { calls.push({ url, options }); return reply(controller) } },
  })
  return { calls, controller, read: (v) => readAutomationInput(v.draft, v.mapping, controller.signal) }
}

test('reads explicit encoded mapping and case pins once with no-store and the active abort signal', async () => {
  const v = await specimen(), r = reader(() => v.value)
  assert.equal(await r.read(v), v.value)
  assert.equal(r.calls.length, 1)
  const { url, options } = r.calls[0], params = new URL(url, 'http://localhost').searchParams
  assert.match(url, /projects\/project%20%2F1\/quality\/test-design-mapping-reviews\/mapping%20%2F1\//)
  assert.deepEqual(params.getAll('case_ids'), v.value.selected_case_ids)
  assert.equal(params.get('artifact_hash'), v.mapping.revision.artifact_hash)
  assert.equal(options.cache, 'no-store'); assert.equal(options.method, undefined); assert.equal(options.signal, r.controller.signal)
})

test('a cancelled read cannot return private content or start another request', async () => {
  const v = await specimen(), r = reader((controller) => { controller.abort(); return v.value })
  await assert.rejects(r.read(v), { name: 'AbortError' }); assert.equal(r.calls.length, 1)
  await assert.rejects(r.read(v), { name: 'AbortError' }); assert.equal(r.calls.length, 1)
})

test('revocation and invalid inputs do not retry or dispatch any write', async () => {
  const v = await specimen(), denied = new Error('403: source access revoked'), r = reader(() => { throw denied })
  await assert.rejects(r.read(v), (error) => error === denied); assert.equal(r.calls.length, 1)
  v.mapping.assessment.accepted_case_ids = Array.from({ length: 513 }, (_, i) => `case-${i}`)
  await assert.rejects(r.read(v)); assert.equal(r.calls.length, 1)
  v.mapping.assessment.accepted_case_ids = ['same', 'same']
  await assert.rejects(r.read(v)); assert.equal(r.calls.length, 1)
})

test('mapping commit snapshot refreshes private consumers but deltas do not trigger unneeded reads', () => {
  const { shouldInvalidateDomainQueries } = load('domains/agent/eventQueryInvalidation.ts')
  assert.equal(shouldInvalidateDomainQueries({ event_type: 'quality.test_design_mapping.reviewed', snapshot_hint: true }), true)
  assert.equal(shouldInvalidateDomainQueries({ event_type: 'conversation.message.delta', snapshot_hint: false }), false)
})
