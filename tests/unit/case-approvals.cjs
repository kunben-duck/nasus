const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { webcrypto } = require('node:crypto')
const { execFileSync } = require('node:child_process')
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
  modules.set(file, context.exports); return context.exports
}
const { canonicalDigest } = load('shared/utils/canonicalDigest.ts')
const { caseAdmissionBasis, caseAdmissionCohort, verifyCaseAdmissionPreview } = load('domains/quality-loop/caseApprovalValidation.ts')
const { automationInputGaps } = load('domains/quality-loop/types/automationInput.ts')
const hash = 'sha256:' + 'a'.repeat(64)
async function specimen() {
  const oracle = { observation: 'response status', expected_result: '400', tolerance: 'exact', evaluator: 'equality' }
  const digest = await canonicalDigest(oracle), ids = ['case-\ue000', 'case-\u{10000}']
  const cases = ids.map((case_id) => ({ case_id, title: 'Explicit protocol specimen', preconditions: [], inputs: [], steps: ['Send invalid input'],
    assertions: [{ row_id: 'AC-1', oracle_digest: digest, oracle, step_index: 0 }], global_constraint_ids: [], supporting_fact_ids: [], reused_case_ids: [] }))
  const context = { context_id: 'context', artifact_hash: hash }, scope = { revision_id: 'scope', artifact_hash: hash }
  const pin = { generation_id: 'generation', artifact_hash: hash, context_pin: context, scope_pin: scope }
  const row = { row_id: 'AC-1', kind: 'acceptance_criterion', constraint_ids: ['AC-1'], oracle_digest: digest,
    accepted_case_ids: ids, gap_ids: [], automated: false, executed_on_target: false, passed: false, unknown: true }
  const draft = { metadata: { project_id: 'project /1', generation_id: 'generation', artifact_hash: hash },
    result: { status: 'draft', context_pin: context, scope_pin: scope, proposal: { cases } }, current_use: { scope_current: true } }
  const mapping = { revision: { project_id: 'project /1', revision_id: 'mapping /1', artifact_hash: hash, request_hash: hash, status: 'reviewed' },
    generation_pin: pin, assessment: { mapping_complete: true, accepted_case_ids: ids, coverage: { constraint_denominator: 1, obligation_denominator: 1, rows: [row] } },
    current_use: { scope_current: true, mapping_current: true, mapping_complete: true } }
  const prepared = { schema: 'nasus.automation-input-preview.v1', purpose: 'automation', project_id: 'project /1', context_pin: context, scope_pin: scope,
    generation_pin: pin, mapping_pin: { revision_id: 'mapping /1', artifact_hash: hash, request_hash: hash }, selected_case_ids: ids, cases,
    required_constraints: [{ object_id: 'AC-1', semantic_class: 'expected', oracle, authority: { object_id: 'AC-1', revision_id: 'AC-approved', artifact_hash: hash, status: 'approved' } }],
    scope_contract: {}, supporting_facts: [], constraint_denominator: 1, obligation_denominator: 1,
    obligations: [{ row_id: row.row_id, kind: row.kind, constraint_ids: row.constraint_ids, oracle_digest: digest, oracle, selected_case_ids: ids }],
    readiness: { status: 'blocked', reason_codes: Array.from(automationInputGaps) }, source_policy: 'untrusted_evidence_not_instructions_or_independent_authority',
    generation_authorized: false, execution_authorized: false, automated_count: 0, executed_on_target_count: 0, passed_count: 0 }
  prepared.input_digest = await canonicalDigest(prepared)
  const basis = await caseAdmissionBasis(prepared), cohort_id = await caseAdmissionCohort(basis)
  const preview = { selection: { project_id: 'project /1', mapping_revision_id: 'mapping /1', mapping_artifact_hash: hash, case_ids: ids },
    prepared, basis, cohort_id, input_current: true, can_review: true, head: null, head_revision_id: null, history_count: 0,
    execution_authorized: false, business_coverage_verified: false }
  return structuredClone({ draft, mapping, preview })
}

test('complete case admission preserves original Unicode cases and no execution authority', async () => {
  const v = await specimen(), original = structuredClone(v)
  assert.equal(await verifyCaseAdmissionPreview(v.preview, v.draft, v.mapping), v.preview)
  assert.deepEqual(v, original)
  const backend = execFileSync(path.resolve(__dirname, '../../.venv/bin/python'), ['-c',
    'import json,sys; from apps.api.app.domain.quality_loop.case_approval import case_approval_cohort; print(case_approval_cohort(json.load(sys.stdin)))'],
    { input: JSON.stringify(v.preview.basis), cwd: path.resolve(__dirname, '../..'), encoding: 'utf8' }).trim()
  assert.equal(v.preview.cohort_id, backend)
})
test('historical case preview never promotes withdrawn inputs', async () => {
  const v = await specimen(); v.mapping.current_use.mapping_current = false; v.draft.current_use.scope_current = false
  v.preview.input_current = false
  assert.equal((await verifyCaseAdmissionPreview(v.preview, v.draft, v.mapping)).input_current, false)
})
for (const [name, change] of Object.entries({
  cohort: (v) => { v.preview.cohort_id = 'f'.repeat(36) }, case: (v) => { v.preview.basis.case_pins[0].case_digest = 'sha256:' + 'b'.repeat(64) },
  oracle: (v) => { v.preview.prepared.obligations[0].oracle.expected_result = '200' }, scope: (v) => { v.preview.basis.scope_pin.revision_id = 'other' },
  subset: (v) => { v.preview.selection.case_ids.pop() }, denominator: (v) => { v.preview.basis.obligation_denominator = 0 },
  authority: (v) => { v.preview.execution_authorized = true }, count: (v) => { v.preview.history_count = 1 },
  head: (v) => { v.preview.head_revision_id = 'another' }, policy: (v) => { v.preview.prepared.execution_authorized = true },
})) test(`admission rejects ${name} rather than returning partial content`, async () => {
  const v = await specimen(); change(v)
  await assert.rejects(verifyCaseAdmissionPreview(v.preview, v.draft, v.mapping))
})

function api(reply, platform) {
  const requests = [], { caseApprovalApi } = load('domains/quality-loop/caseApprovalApi.ts', {
    '../../shared/api/client': { request: async (url, options) => { requests.push({ url, options }); return reply() } },
    '../platform/api': { platformApi: platform ?? {} },
  })
  return { api: caseApprovalApi, requests }
}
test('case preview uses explicit encoded IDs, no-store and cancellable reads', async () => {
  const v = await specimen(), controller = new AbortController(), r = api(() => v.preview)
  await r.api.preview(v.draft, v.mapping, controller.signal)
  assert.equal(r.requests.length, 1)
  assert.match(r.requests[0].url, /projects\/project%20%2F1\/quality\/test-design-case-approvals\/preview/)
  const params = new URL(r.requests[0].url, 'http://localhost').searchParams
  assert.equal(params.get('mapping_revision_id'), 'mapping /1')
  assert.deepEqual(params.getAll('case_ids'), v.preview.selection.case_ids)
  assert.equal(r.requests[0].options.cache, 'no-store')
  controller.abort(); await assert.rejects(r.api.preview(v.draft, v.mapping, controller.signal), { name: 'AbortError' })
  assert.equal(r.requests.length, 1)
})
test('case decision is a single canonical pending/confirm pair with fixed receipt readback', async () => {
  const v = await specimen(), calls = [], input = { ...v.preview.selection, expected_input_digest: v.preview.basis.input_digest,
    expected_previous_revision_id: null, decision: 'approve', reason: 'Independent original case review', policy_revision: 'nasus.test-design-case-admission.v1' }
  const command = { id: 'command', tool_id: 'quality.test_design_cases.review', status: 'waiting_confirmation', input_payload: input }
  const recorded = { revision: { revision_id: 'recorded', project_id: input.project_id, generation_id: v.preview.basis.generation_pin.generation_id,
    mapping_revision_id: input.mapping_revision_id, input_digest: input.expected_input_digest, case_count: input.case_ids.length,
    invocation_id: command.id, cohort_id: v.preview.cohort_id, request_hash: await canonicalDigest(input), status: 'approved', previous_revision_id: null, sequence: 1 },
    basis: v.preview.basis, historical_not_live: true, current_use: { case_admission_current: true, generation_authorized: false,
      execution_authorized: false, business_coverage_verified: false } }
  const r = api(() => recorded, {
    invokeTool: async (request) => { calls.push(request); return structuredClone(command) },
    confirmToolInvocation: async (id) => { calls.push(id); return { ...structuredClone(command), status: 'completed',
      input_payload: { ...input, confirmed_by_user: true }, result: { object_refs: ['test_design_case_approval:recorded'] } } },
  })
  assert.equal(await r.api.review(input, v.preview, 'original-attempt'), 'command')
  assert.equal(calls.length, 2); assert.equal(calls[0].idempotency_key, 'original-attempt'); assert.equal(calls[1], 'command')
  assert.equal(r.requests.length, 1); assert.match(r.requests[0].url, /case-approvals\/recorded$/)
  recorded.revision.request_hash = hash
  await assert.rejects(r.api.review(input, v.preview, 'next-independent-attempt'))
})
test('wrong selection and stale input cannot dispatch a case approval', async () => {
  const v = await specimen(), calls = [], r = api(() => v.preview, { invokeTool: async (input) => { calls.push(input) } })
  const input = { ...v.preview.selection, expected_input_digest: v.preview.basis.input_digest, expected_previous_revision_id: null,
    decision: 'approve', reason: 'Independent review', policy_revision: 'nasus.test-design-case-admission.v1' }
  await assert.rejects(r.api.review({ ...input, project_id: 'foreign' }, v.preview, 'attempt'))
  v.preview.input_current = false; await assert.rejects(r.api.review(input, v.preview, 'attempt'))
  assert.equal(calls.length, 0)
})
