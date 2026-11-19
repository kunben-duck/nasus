const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')
const root = path.resolve(__dirname, '../../apps/portal/src')
function load(relative) {
  const file = path.resolve(root, relative), exports = {}
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
  } }).outputText, { exports, require: (name) => load(path.relative(root, path.resolve(path.dirname(file), name + '.ts'))) })
  return exports
}
const { caseRevisionRequest, verifySavedCaseRevision } = load('domains/quality-loop/caseRevisionValidation.ts')
const { verifyGenerationMetadata } = load('domains/quality-loop/generationResultMetadata.ts')
const hash = 'sha256:' + 'a'.repeat(64)
function specimen() {
  const original = { case_id: 'case', title: 'Non-author denied', preconditions: ['Article owned by A'],
    inputs: ['User B'], steps: ['Update as B', 'Read article'], global_constraint_ids: ['AC-deny'], supporting_fact_ids: ['code'], reused_case_ids: [],
    assertions: [{ row_id: 'AC-deny', step_index: 0, oracle_digest: hash,
      oracle: { preconditions: 'Article owned by A', action: 'B updates', observation: 'response', expected_result: '403 and no change' } }] }
  const draft = { metadata: { project_id: 'p', generation_id: 'parent', artifact_hash: hash },
    result: { proposal: { cases: [original] }, context_pin: { context_id: 'context' }, scope_pin: { revision_id: 'scope' } },
    current_use: { scope_current: true } }
  const edit = { ...structuredClone(original), title: 'Non-author denied and original data retained' }
  const request = caseRevisionRequest(draft, [edit], 'Clarify title')
  const saved = { metadata: { project_id: 'p', generation_id: 'child', scope_revision_id: 'scope', invocation_id: 'command',
    artifact_hash: hash, call_id: null, schema: 'nasus.test-design-case-revision.v1', status: 'draft', case_count: 1, gap_count: 0 },
    result: { schema: 'nasus.test-design-case-revision.v1', actor_id: 'editor', original_generation_id: 'parent', edit_sequence: 1,
      edit_request: request, parent: { generation_id: 'parent', artifact_hash: hash },
      context_pin: draft.result.context_pin, scope_pin: draft.result.scope_pin, proposal: { cases: [edit] } } }
  return structuredClone({ draft, edit, request, saved })
}
test('case editing creates a separately identified human archive without a fake model call', () => {
  const v = specimen(), before = structuredClone(v.draft)
  assert.equal(verifyGenerationMetadata(v.saved.metadata), true)
  assert.equal(verifySavedCaseRevision(v.saved, v.draft, v.request, 'editor', 'command'), v.saved)
  assert.deepEqual(v.draft, before)
  assert.equal(v.request.generation_id, 'parent')
})
for (const [name, change] of Object.entries({
  superseded: v => { v.draft.current_use.scope_current = false }, no_changes: v => { v.edit = v.draft.result.proposal.cases[0] },
  foreign: v => { v.edit.case_id = 'foreign' }, expected: v => { v.edit.assertions[0].oracle.expected_result = '200' },
  removed_assertion: v => { v.edit.assertions = [] }, source: v => { v.edit.supporting_fact_ids = [] },
  out_of_range: v => { v.edit.assertions[0].step_index = 99 }, empty_step: v => { v.edit.steps.push('') },
})) test('case edit rejects ' + name + ' before submitting a command', () => {
  const v = specimen(); change(v)
  assert.throws(() => caseRevisionRequest(v.draft, [v.edit], 'Reason'))
})
test('only the assertion step may change without changing its approved oracle', () => {
  const v = specimen(); v.edit.assertions[0].step_index = 1
  assert.equal(caseRevisionRequest(v.draft, [v.edit], 'Move assertion to readback').cases[0].assertions[0].step_index, 1)
  assert.throws(() => caseRevisionRequest(v.draft, [v.edit, v.edit], 'Duplicate'))
  assert.throws(() => caseRevisionRequest(v.draft, [v.edit], ' '))
})
test('case text uses backend whitespace and line limits before hashing the command', () => {
  const v = specimen(); v.edit.title = ' Clarified title '; v.edit.steps[0] = ' Updated step '
  const request = caseRevisionRequest(v.draft, [v.edit], ' Reason ')
  assert.equal(request.cases[0].title, 'Clarified title')
  assert.equal(request.cases[0].steps[0], 'Updated step')
  assert.equal(request.reason, 'Reason')
  v.edit.steps = Array.from({ length: 65 }, () => 'step')
  assert.throws(() => caseRevisionRequest(v.draft, [v.edit], 'Reason'))
})
for (const [name, change] of Object.entries({
  command: v => { v.saved.metadata.invocation_id = 'different' }, actor: v => { v.saved.result.actor_id = 'another' },
  parent: v => { v.saved.result.parent.generation_id = 'other' }, model: v => { v.saved.result.schema = 'nasus.test-design-result.v1' },
  scope: v => { v.saved.result.scope_pin = { revision_id: 'other' } }, sequence: v => { v.saved.result.edit_sequence = 3 },
  different_edit: v => { v.saved.result.proposal.cases = v.draft.result.proposal.cases },
})) test('saved case receipt rejects ' + name, () => {
  const v = specimen(); change(v)
  assert.throws(() => verifySavedCaseRevision(v.saved, v.draft, v.request, 'editor', 'command'))
})
