const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { webcrypto, createHash } = require('node:crypto')
const ts = require('../../apps/portal/node_modules/typescript')
const root = path.resolve(__dirname, '../../apps/portal/src')
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
const validation = load('domains/quality-loop/automationScriptValidation.ts')
const review = load('domains/quality-loop/automationScriptReviewValidation.ts')
const hash = (c) => 'sha256:' + c.repeat(64)
const plain = (value) => JSON.parse(JSON.stringify(value))
async function fixture() {
  const oracle = { preconditions: 'Signed in', action: 'Submit empty input', observation: 'HTTP response', expected_result: '400' }
  const oracleHash = await digest(oracle), context = { context_id: 'context', artifact_hash: hash('a'), input_digest: hash('b'), image_revision_id: 'image', image_artifact_hash: hash('c') }
  const scope = { revision_id: 'scope', artifact_hash: hash('d'), request_hash: hash('e') }
  const caseValue = { case_id: 'case-中文', title: 'Reject empty input', preconditions: ['Signed in'], inputs: [''], steps: ['Submit empty input'],
    assertions: [{ row_id: 'AC-1', oracle_digest: oracleHash, oracle, step_index: 0 }], global_constraint_ids: [], supporting_fact_ids: [], reused_case_ids: [] }
  const draft = { metadata: { project_id: 'project /1', generation_id: 'generation', artifact_hash: hash('f') },
    result: { status: 'draft', context_pin: context, scope_pin: scope, proposal: { cases: [caseValue] } }, current_use: { scope_current: true } }
  const generation = { generation_id: 'generation', artifact_hash: hash('f'), context_pin: context, scope_pin: scope, input_digest: hash('1'), proposal_hash: hash('2') }
  const mapping = { revision: { project_id: 'project /1', revision_id: 'mapping /1', artifact_hash: hash('3'), request_hash: hash('4'), status: 'reviewed' },
    generation_pin: generation, assessment: { mapping_complete: true, accepted_case_ids: [caseValue.case_id], coverage: { constraint_denominator: 1, obligation_denominator: 1,
      rows: [{ row_id: 'AC-1', kind: 'acceptance_criterion', constraint_ids: ['constraint'], oracle_digest: oracleHash, accepted_case_ids: [caseValue.case_id], gap_ids: [],
        automated: false, executed_on_target: false, passed: false, unknown: true }] } }, current_use: { scope_current: true, mapping_current: true, mapping_complete: true } }
  const body = { schema: 'nasus.automation-input-preview.v1', purpose: 'automation', project_id: 'project /1', context_pin: context, scope_pin: scope,
    generation_pin: generation, mapping_pin: { revision_id: 'mapping /1', artifact_hash: hash('3'), request_hash: hash('4') }, selected_case_ids: [caseValue.case_id], cases: [caseValue],
    required_constraints: [{ object_id: 'constraint', semantic_class: 'expected', oracle, authority: { object_id: 'constraint', revision_id: 'approved-AC', artifact_hash: hash('5'), status: 'approved' } }],
    scope_contract: {}, supporting_facts: [], constraint_denominator: 1, obligation_denominator: 1,
    obligations: [{ row_id: 'AC-1', kind: 'acceptance_criterion', constraint_ids: ['constraint'], oracle_digest: oracleHash, oracle, selected_case_ids: [caseValue.case_id] }],
    readiness: { status: 'blocked', reason_codes: ['automation_environment_not_bound', 'api_or_dom_locator_evidence_not_bound', 'fixture_setup_cleanup_not_bound', 'model_budget_not_bound', 'script_generation_and_independent_review_required'] },
    source_policy: 'untrusted_evidence_not_instructions_or_independent_authority', generation_authorized: false, execution_authorized: false, automated_count: 0, executed_on_target_count: 0, passed_count: 0 }
  const prepared = { ...body, input_digest: await digest(body) }, budget = { currency: 'USD', max_calls: 1, max_reserved_tokens: 11000,
    max_reserved_cost_nanos: 100000, max_input_tokens_per_call: 9000, max_output_tokens_per_call: 1000 }
  const policy = { config_id: 'model', provider: 'openai_compatible', model_name: 'fixture', base_url: 'https://model.example/v1', currency: 'USD', context_tokens: 10000,
    max_output_tokens: 1000, input_nanos_per_token: 1, output_nanos_per_token: 2, tokenizer_kind: 'tiktoken', tokenizer_id: 'counter', tokenizer_digest: hash('6'), framing_tokens: 8, policy_id: 'operator', revision: 'v1' }
  const selection = { project_id: body.project_id, mapping_revision_id: 'mapping /1', mapping_artifact_hash: hash('3'), case_ids: [caseValue.case_id], model_config_id: 'model', budget,
    case_approval_revision_id: 'explicit-ui-admission', case_approval_artifact_hash: hash('a') }
  const request = { ...selection, input_digest: prepared.input_digest, model_config_digest: hash('7'), execution: { purpose: 'draft_automation_source_egress',
    policy_digest: await digest(policy), plan_digest: hash('8'), source_binding_ids: ['binding'], source_scope_digest: hash('9'), budget } }
  const preview = { request, policy, provider: policy.provider, model_name: policy.model_name, destination: policy.base_url,
    reservation: { currency: 'USD', call_count: 1, estimated_input_tokens: 300, reserved_input_tokens_per_call: 10000, max_output_tokens_per_call: 1000,
      reserved_tokens: 11000, reserved_cost_nanos: 12000, count_basis: 'local_tokenizer_with_operator_framing', cost_basis: 'operator_rate_ceiling_not_provider_invoice' },
    input_bytes: 4000, timeout_seconds: 120, call_count: 1, generation_authorized: false, execution_authorized: false,
    remaining_gates: ['fresh_user_confirmation', 'durable_call_reservation', 'independent_script_review', 'immutable_run_plan'] }
  const script = { case_id: caseValue.case_id, case_digest: await digest(caseValue), kind: 'http', actions: [
    { action: 'request', request_id: 'req', method: 'POST', path: '/search', headers_json: '{}', body_json: '{}', source_step_indices: [0] },
    { action: 'assert_status', request_id: 'req', value: '400', source_step_indices: [0] }],
    assertions: [{ row_id: 'AC-1', oracle_digest: oracleHash, oracle, source_step_index: 0, action_index: 1 }] }
  const raw_output = JSON.stringify({ input_digest: prepared.input_digest, scripts: [script], gaps: [] })
  const proposal = { schema: 'nasus.automation-script-proposal.v1', input_digest: prepared.input_digest, scripts: [script], gaps: [], case_count: 1, script_count: 1, gap_count: 0,
    status: 'draft', review_status: 'pending_independent_review', execution_authorized: false, automated_count: 0, executed_on_target_count: 0, passed_count: 0, remaining_gates: Array.from(validation.scriptGates) }
  const result = { schema: 'nasus.automation-script-result.v1', project_id: body.project_id, script_revision_id: 'script /1', invocation_id: 'command-1', actor_id: 'author',
    call_id: 'call', response_hash: 'sha256:' + createHash('sha256').update(raw_output).digest('hex'), request,
    model_binding: { config_id: 'model', config_digest: hash('7'), provider: policy.provider, model_name: policy.model_name, base_url: policy.base_url }, prepared, raw_output, proposal, status: 'draft' }
  const archive = { metadata: { project_id: body.project_id, script_revision_id: result.script_revision_id, invocation_id: result.invocation_id, call_id: result.call_id,
    response_hash: result.response_hash, status: 'draft', artifact_hash: await digest(result), input_digest: prepared.input_digest, mapping_revision_id: 'mapping /1', mapping_artifact_hash: hash('3'),
    script_count: 1, gap_count: 0, execution_authorized: false }, result, historical_not_live: true, current_use: { input_current: true, execution_authorized: false } }
  const item = { invocation_id: 'command-1', status: 'completed', call_reserved: true, reply_archived: true, provider_outcome_unknown: false,
    script_revision_id: result.script_revision_id, artifact_hash: archive.metadata.artifact_hash }
  return { draft, mapping, prepared, selection, preview, archive, item }
}
async function refreshArchive(v) {
  const r = v.archive.result, p = r.proposal
  r.raw_output = JSON.stringify({ input_digest: p.input_digest, scripts: p.scripts, gaps: p.gaps })
  r.response_hash = v.archive.metadata.response_hash = 'sha256:' + createHash('sha256').update(r.raw_output).digest('hex')
  v.item.artifact_hash = v.archive.metadata.artifact_hash = await digest(r)
}
async function bindingFixture() {
  const v = await fixture(), p = v.archive.result.proposal, script = p.scripts[0]
  v.selection.http_protocol = v.preview.request.http_protocol = 'nasus.runner-http-execution.v2'
  p.schema = 'nasus.automation-script-proposal.v2'; p.http_protocol = 'nasus.runner-http-execution.v2'
  script.actions[0].path = '/sessions/{{session}}'
  script.actions.unshift({ action: 'request', request_id: 'create', method: 'POST', path: '/sessions', headers_json: '{}', body_json: '{}', source_step_indices: [0] },
    { action: 'capture_json', request_id: 'create', pointer: '/sessionId', binding_id: 'session', source_step_indices: [0] })
  script.assertions[0].action_index += 2
  await refreshArchive(v)
  return v
}
async function fixtureImport() {
  const v = await fixture(), p = v.archive.result.proposal, script = p.scripts[0]
  v.selection.http_protocol = v.preview.request.http_protocol = 'nasus.runner-http-execution.v3'
  p.schema = 'nasus.automation-script-proposal.v3'; p.http_protocol = 'nasus.runner-http-execution.v3'
  script.actions[0].path = '/sessions/{{session}}'
  script.actions.unshift({ action: 'use_fixture_binding', binding_id: 'session', source_step_indices: [0] })
  script.assertions[0].action_index++
  await refreshArchive(v)
  return v
}
test('v3 fixture imports are explicit draft actions and require independent review without changing the oracle', async () => {
  const v = await fixtureImport()
  assert.equal(await validation.verifyScriptPreview(v.preview, v.selection, v.prepared), v.preview)
  assert.equal(await validation.verifyScriptArchive(v.archive, v.draft, v.mapping, v.item), v.archive)
  const entries = await review.newScriptDecisions(v.archive)
  assert.equal(entries.actions.length, 3); assert.equal(entries.assertions.length, 1)
  assert.equal(entries.actions[0].action_index, 0); assert.equal(entries.actions[0].decision, 'defer')
  assert.equal(v.archive.result.proposal.scripts[0].assertions[0].oracle.expected_result, '400')
  assert.equal(v.archive.result.proposal.executed_on_target_count, 0)
  assert.throws(() => validation.verifyHttpBindingActions(v.archive.result.proposal.scripts[0].actions))
})
for (const fault of ['old_schema', 'old_request', 'v2_protocol', 'foreign_resource', 'unsafe_id', 'extra_value', 'extra_request',
  'missing_indices', 'duplicate_import', 'forward_import', 'query_path', 'partial_path', 'import_as_oracle', 'browser_import', 'too_many_imports']) {
  test(`v3 fixture import refuses a rehashed incomplete or forged draft: ${fault}`, async () => {
    const v = await fixtureImport(), p = v.archive.result.proposal, script = p.scripts[0], imported = script.actions[0]
    if (fault === 'old_schema') p.schema = 'nasus.automation-script-proposal.v2'
    if (fault === 'old_request') delete v.archive.result.request.http_protocol
    if (fault === 'v2_protocol') p.http_protocol = v.archive.result.request.http_protocol = 'nasus.runner-http-execution.v2'
    if (fault === 'foreign_resource') script.actions[1].path = '/sessions/{{another}}'
    if (fault === 'unsafe_id') imported.binding_id = 'session/unsafe'
    if (fault === 'extra_value') imported.value = 'forged-resource'
    if (fault === 'extra_request') imported.request_id = 'foreign-setup'
    if (fault === 'missing_indices') delete imported.source_step_indices
    if (fault === 'duplicate_import') script.actions.push(structuredClone(imported))
    if (fault === 'forward_import') [script.actions[0], script.actions[1]] = [script.actions[1], script.actions[0]]
    if (fault === 'query_path') script.actions[1].path = '/sessions?id={{session}}'
    if (fault === 'partial_path') script.actions[1].path = '/sessions/id-{{session}}'
    if (fault === 'import_as_oracle') script.assertions[0].action_index = 0
    if (fault === 'browser_import') script.kind = 'browser'
    if (fault === 'too_many_imports') script.actions.push(...Array.from({ length: 16 }, (_, i) => ({ ...imported, binding_id: `resource${i}` })))
    await refreshArchive(v)
    await assert.rejects(validation.verifyScriptArchive(v.archive, v.draft, v.mapping, v.item))
  })
}
test('response bindings require an explicit preview version and preserve the independent oracle', async () => {
  const v = await bindingFixture()
  assert.equal(await validation.verifyScriptPreview(v.preview, v.selection, v.prepared), v.preview)
  assert.equal(await validation.verifyScriptArchive(v.archive, v.draft, v.mapping, v.item), v.archive)
  await assert.rejects(validation.verifyScriptPreview(v.preview, { ...v.selection, http_protocol: undefined }, v.prepared))
  assert.equal(v.archive.result.proposal.scripts[0].assertions[0].oracle.expected_result, '400')
  const entries = await review.newScriptDecisions(v.archive)
  assert.equal(entries.actions.length, 4); assert.equal(entries.assertions.length, 1)
  assert.equal(entries.actions[1].action_index, 1); assert.equal(entries.actions[1].decision, 'defer')
})
for (const [label, operand] of [
  ['duplicate keys', '{"title":"first","title":"second"}'],
  ['escaped duplicate keys', '{"title":"first","\\u0074itle":"second"}'],
  ['nested duplicate keys', '[{"name":"first","name":"second"}]'],
  ['unsafe integer', '{"id":9007199254740993}'],
  ['unsafe exponent integer', '{"id":9.007199254740993e15}'],
  ['nonfinite exponent', '{"id":1e400}'],
  ['oversized number', '{"value":0.' + '1'.repeat(255) + '}'],
  ['deep container', '['.repeat(65) + 'null' + ']'.repeat(65)],
]) {
  test(`v2 archive refuses ${label} after all raw and archive hashes are recomputed`, async () => {
    const v = await bindingFixture()
    v.archive.result.proposal.scripts[0].actions[0].body_json = operand
    await refreshArchive(v)
    await assert.rejects(validation.verifyScriptArchive(v.archive, v.draft, v.mapping, v.item))
  })
}
test('v2 operands retain valid repeated names in separate objects and exact numeric bounds', async () => {
  const v = await bindingFixture()
  v.archive.result.proposal.scripts[0].actions[0].body_json = '{"items":[{"id":9007199254740991},{"id":-9007199254740991},{"id":0.1234567890123456789}]}'
  await refreshArchive(v)
  assert.equal(await validation.verifyScriptArchive(v.archive, v.draft, v.mapping, v.item), v.archive)
})
for (const [field, operand] of [
  ['headers_json', '{"Accept":"application/json","Accept":"text/plain"}'],
  ['headers_json', '{"Accept":"application/json","\\u0041ccept":"text/plain"}'],
  ['value_json', '{"status":200,"status":400}'],
  ['value_json', '9007199254740993'],
]) {
  test(`v2 ${field} refuses ambiguous JSON without replacing the original independent oracle: ${operand}`, async () => {
    const v = await bindingFixture(), script = v.archive.result.proposal.scripts[0]
    if (field === 'headers_json') script.actions[0].headers_json = operand
    else script.actions[script.assertions[0].action_index] = { action: 'assert_json', request_id: 'req', pointer: '/status', value_json: operand, source_step_indices: [0] }
    await refreshArchive(v)
    assert.equal(script.assertions[0].oracle.expected_result, '400')
    await assert.rejects(validation.verifyScriptArchive(v.archive, v.draft, v.mapping, v.item))
  })
}
for (const protocol of ['v1', 'v2']) {
  test(`raw ${protocol} model JSON refuses duplicate decoded keys despite valid hashes`, async () => {
    const v = protocol === 'v2' ? await bindingFixture() : await fixture()
    const r = v.archive.result
    r.raw_output = '{"input_digest":"foreign",' + r.raw_output.slice(1)
    r.response_hash = v.archive.metadata.response_hash = 'sha256:' + createHash('sha256').update(r.raw_output).digest('hex')
    v.item.artifact_hash = v.archive.metadata.artifact_hash = await digest(r)
    await assert.rejects(validation.verifyScriptArchive(v.archive, v.draft, v.mapping, v.item))
  })
}
for (const fault of ['old_schema', 'missing_protocol', 'old_request', 'forward_binding', 'duplicate_binding', 'partial_path',
  'query_binding', 'unsafe_header', 'control_character', 'prototype_action', 'capture_as_oracle', 'changed_oracle', 'browser_capture']) {
  test(`rehashed response-binding archive fails closed: ${fault}`, async () => {
    const v = await bindingFixture(), p = v.archive.result.proposal, script = p.scripts[0]
    if (fault === 'old_schema') p.schema = 'nasus.automation-script-proposal.v1'
    if (fault === 'missing_protocol') delete p.http_protocol
    if (fault === 'old_request') delete v.archive.result.request.http_protocol
    if (fault === 'forward_binding') script.actions[0].path = '/sessions/{{session}}'
    if (fault === 'duplicate_binding') script.actions.push(structuredClone(script.actions[1]))
    if (fault === 'partial_path') script.actions[2].path = '/sessions/id-{{session}}'
    if (fault === 'query_binding') script.actions[2].path = '/sessions?id={{session}}'
    if (fault === 'unsafe_header') script.actions[0].headers_json = '{"Authorization":"unsafe"}'
    if (fault === 'control_character') script.actions[0].path += '\u0000'
    if (fault === 'prototype_action') script.actions[1].action = 'toString'
    if (fault === 'capture_as_oracle') script.assertions[0].action_index = 1
    if (fault === 'changed_oracle') script.assertions[0].oracle.expected_result = 'invented'
    if (fault === 'browser_capture') script.kind = 'browser'
    await refreshArchive(v)
    await assert.rejects(validation.verifyScriptArchive(v.archive, v.draft, v.mapping, v.item))
  })
}
test('script preview keeps exact full input and operator monetary ceiling', async () => {
  const v = await fixture(); assert.equal(await validation.verifyScriptPreview(v.preview, v.selection, v.prepared), v.preview)
  for (const change of [(p) => { p.request.execution.purpose = 'draft_test_design_source_egress' }, (p) => { p.call_count = 2 },
    (p) => { p.request.case_ids = [] }, (p) => { p.request.mapping_artifact_hash = hash('a') }, (p) => { p.reservation.reserved_tokens-- },
    (p) => { p.destination = 'http://model.example' }, (p) => { p.execution_authorized = true }, (p) => { p.policy.input_nanos_per_token++ }]) {
    const bad = structuredClone(v.preview); change(bad)
    await assert.rejects(validation.verifyScriptPreview(bad, v.selection, v.prepared))
  }
})
test('fixed script history checks page scope, cursor, unknown reservations and no execution grants', async () => {
  const v = await fixture(), input = { project_id: 'project /1', mapping_revision_id: 'mapping /1', mapping_artifact_hash: hash('3'), after_id: '', limit: 1 }
  const page = { request: input, items: [v.item], next_after_id: 'command-1', generation_authorized: false, execution_authorized: false }
  assert.equal(validation.verifyScriptHistory(page, input), page)
  for (const change of [(p) => { p.request.project_id = 'foreign' }, (p) => { p.items[0].provider_outcome_unknown = true },
    (p) => { p.items[0].script_revision_id = null }, (p) => { p.items.push(p.items[0]) }, (p) => { p.next_after_id = 'other' }, (p) => { p.execution_authorized = true }]) {
    const bad = structuredClone(page); change(bad); assert.throws(() => validation.verifyScriptHistory(bad, input))
  }
})
test('script archive preserves source cases, steps, oracles and zero verified coverage', async () => {
  const v = await fixture(); assert.equal(await validation.verifyScriptArchive(v.archive, v.draft, v.mapping, v.item), v.archive)
  for (const change of [(p) => { p.result.prepared.context_pin.context_id = 'foreign' }, (p) => { p.result.proposal.passed_count = 1 },
    (p) => { p.result.request.mapping_revision_id = 'other' }, (p) => { p.result.proposal.scripts[0].assertions[0].oracle.expected_result = '200' },
    (p) => { p.result.proposal.scripts[0].assertions[0].action_index = 0 }, (p) => { p.result.proposal.scripts[0].actions[0].source_step_indices = [] },
    (p) => { p.result.raw_output += ' ' }]) {
    const bad = structuredClone(v.archive); change(bad); bad.metadata.artifact_hash = await digest(bad.result)
    await assert.rejects(validation.verifyScriptArchive(bad, v.draft, v.mapping, { ...v.item, artifact_hash: bad.metadata.artifact_hash }))
  }
})
test('stale script archives remain historical but cannot claim current use', async () => {
  const v = await fixture(); v.draft.current_use.scope_current = false; v.mapping.current_use.mapping_current = false
  await assert.rejects(validation.verifyScriptArchive(v.archive, v.draft, v.mapping, v.item))
  v.archive.current_use.input_current = false
  assert.equal(await validation.verifyScriptArchive(v.archive, v.draft, v.mapping, v.item), v.archive)
})
async function reviewFixture(v) {
  const entries = plain(await review.newScriptDecisions(v.archive))
  for (const item of [...entries.actions, ...entries.assertions]) Object.assign(item, { decision: 'accept', reason: 'Independent protocol review; not target execution' })
  const request = { project_id: v.archive.metadata.project_id, script_revision_id: v.archive.metadata.script_revision_id,
    script_artifact_hash: v.archive.metadata.artifact_hash, expected_previous_revision_id: null, decision: 'review', ...entries,
    reason: 'Explicit independent specimen', policy_revision: 'nasus.automation-script-review.v1' }
  const assessment = { review_complete: true, reviewed_action_count: 2, reviewed_oracle_count: 1, accepted_count: 3, rejected_count: 0, deferred_count: 0,
    gap_count: 0, automated_count: 0, executed_on_target_count: 0, passed_count: 0, execution_authorized: false,
    remaining_gates: ['target_build_environment_binding', 'api_or_dom_locator_evidence', 'fixture_setup_cleanup', 'immutable_run_plan'] }
  const script_pin = plain(await review.scriptPin(v.archive)), authority_actor = 'reviewer', invocation_id = 'review-command', recorded_at = '2026-10-10T10:00:00Z'
  const artifact_hash = await digest({ schema: 'nasus.automation-script-review.v1', project_id: request.project_id, request, assessment, script_pin, authority_actor, invocation_id, recorded_at })
  return { request, assessment, script_pin, revision: { revision_id: 'review-1', project_id: request.project_id, script_revision_id: request.script_revision_id,
    script_artifact_hash: request.script_artifact_hash, sequence: 1, previous_revision_id: null, status: 'reviewed', artifact_hash, request_hash: await digest(request), authority_actor, invocation_id, recorded_at } }
}
test('review starts with deferred empty reasons and requires every original action and oracle', async () => {
  const v = await fixture(), entries = await review.newScriptDecisions(v.archive)
  assert.equal(review.scriptDecisionsValid(entries.actions, entries.assertions), false)
  const archive = await reviewFixture(v)
  assert.equal(await review.verifyScriptReviewArchive(archive, v.archive), archive)
  for (const change of [(r) => { r.request.actions.pop() }, (r) => { r.request.assertions[0].source_step_index++ },
    (r) => { r.assessment.execution_authorized = true }, (r) => { r.request.actions[0].action_digest = hash('a') },
    (r) => { r.request.actions[0].reason = '' }, (r) => { r.assessment.passed_count = 1 }]) {
    const bad = structuredClone(archive); change(bad); bad.revision.request_hash = await digest(bad.request)
    await assert.rejects(review.verifyScriptReviewArchive(bad, v.archive))
  }
})
test('review view pins the complete predecessor chain and exact current head', async () => {
  const v = await fixture(), head = await reviewFixture(v), view = { project_id: 'project /1', script_revision_id: v.item.script_revision_id,
    script_artifact_hash: v.item.artifact_hash, script_pin: head.script_pin, head, history: [head.revision], input_current: true, can_review: true, execution_authorized: false }
  assert.equal(await review.verifyScriptReviewView(view, v.archive), view)
  for (const change of [(r) => { r.history[0].sequence++ }, (r) => { r.history[0].previous_revision_id = 'foreign' },
    (r) => { r.head = null }, (r) => { r.script_artifact_hash = hash('b') }, (r) => { r.history.push(r.history[0]) }, (r) => { r.execution_authorized = true }]) {
    const bad = structuredClone(view); change(bad); await assert.rejects(review.verifyScriptReviewView(bad, v.archive))
  }
})
test('canonical generation confirms once and never retries a lost acknowledgement', async () => {
  const v = await fixture(), calls = [], seen = []
  const platformApi = { invokeTool: async (input) => { calls.push(input); return { id: 'canonical', tool_id: input.tool_id, input_payload: input.input, status: 'waiting_confirmation' } },
    confirmToolInvocation: async (id) => { calls.push(id); throw new Error('Explicit lost response') } }
  const { automationScriptApi: api } = load('domains/quality-loop/automationScriptApi.ts', { '../platform/api': { platformApi }, '../../shared/api/client': {} })
  await assert.rejects(api.generate(v.preview, 'same-attempt', (id) => seen.push(id)))
  assert.deepEqual(seen, ['canonical']); assert.equal(calls.length, 2); assert.equal(calls[0].idempotency_key, 'same-attempt')
  assert.deepEqual(plain(calls[0].input), v.preview.request)
})
test('readonly script history encodes pins and propagates cancellation without a write', async () => {
  const v = await fixture(), controller = new AbortController(), calls = []
  const { automationScriptApi: api } = load('domains/quality-loop/automationScriptApi.ts', { '../platform/api': {}, '../../shared/api/client': {
    request: async (url, options) => { calls.push({ url, options }); controller.abort(); return {} } } })
  await assert.rejects(api.history(v.mapping, '', controller.signal)); assert.equal(calls.length, 1)
  assert.match(calls[0].url, /projects\/project%20%2F1\/quality\/automation-script-history/)
  assert.equal(calls[0].options.signal, controller.signal); assert.equal(calls[0].options.cache, 'no-store'); assert.equal(calls[0].options.method, undefined)
  await assert.rejects(api.history(v.mapping, '', controller.signal), { name: 'AbortError' }); assert.equal(calls.length, 1)
})
test('closed script panel does not observe adjacent input failures or lock its toggle', async () => {
  const v = await fixture()
  for (const open of [false, true]) {
    let states = 0, failures = 0
    const queries = [], mutation = { isPending: false, isIdle: true, reset() {} }
    const { useAutomationScripts } = load('domains/quality-loop/useAutomationScripts.ts', {
      react: { useState: (value) => [states++ === 0 ? open : value, () => {}], useRef: () => ({ current: false }), useEffect: (effect) => effect() },
      '@tanstack/react-query': {
        useInfiniteQuery: (options) => { queries.push(options); return { isError: false, isFetching: false } },
        useQuery: (options) => { queries.push(options); return { isError: options.queryKey[0] === 'automation-script-input', isFetching: !open } },
        useMutation: () => mutation,
      },
      '../platform/api': { platformApi: {} }, './automationScriptApi': { automationScriptApi: {} },
      './caseApprovalApi': { caseApprovalApi: {} },
      './automationInputApi': { readAutomationInput() {} }, './useTestDesignGeneration': { budgetValue: () => null },
    })
    const result = useAutomationScripts(v.draft, v.mapping, 'session', () => { failures++ })
    assert.equal(result.failed, open); assert.equal(failures, open ? 1 : 0); assert.equal(result.busy, false)
    assert.equal(queries.length, 5)
    assert.equal(queries[2].queryKey[0], 'automation-script-input')
    assert.equal(queries[3].queryKey[0], 'test-design-case-approvals')
    assert.equal(queries.some((query) => query.queryKey[0] === 'automation-input'), false)
    if (!open) assert.equal(queries.every((query) => !query.enabled), true)
    for (const query of queries) { assert.equal(query.retry, false); assert.equal(query.gcTime, 0) }
  }
})

test('new script previews reject missing, partial or substituted independent admission pins', async () => {
  const v = await fixture()
  for (const fault of ['missing', 'partial', 'revision', 'hash']) {
    const preview = structuredClone(v.preview)
    if (fault === 'missing' || fault === 'partial') delete preview.request.case_approval_revision_id
    if (fault === 'missing') delete preview.request.case_approval_artifact_hash
    if (fault === 'revision') preview.request.case_approval_revision_id = 'substituted-approval'
    if (fault === 'hash') preview.request.case_approval_artifact_hash = hash('b')
    await assert.rejects(validation.verifyScriptPreview(preview, v.selection, v.prepared))
  }
})

test('legacy archived scripts stay readable but cannot claim current admission', async () => {
  const v = await fixture(), request = v.archive.result.request
  delete request.case_approval_revision_id; delete request.case_approval_artifact_hash
  await refreshArchive(v)
  await assert.rejects(validation.verifyScriptArchive(v.archive, v.draft, v.mapping, v.item))
  v.archive.current_use.input_current = false
  assert.equal(await validation.verifyScriptArchive(v.archive, v.draft, v.mapping, v.item), v.archive)
})
