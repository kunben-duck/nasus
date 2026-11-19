const assert = require('node:assert/strict')
const test = require('node:test')
const { readFileSync } = require('node:fs')
const { resolve } = require('node:path')
const { runInNewContext } = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')
const root = resolve(__dirname, '../../apps/portal/src/domains/quality-loop')

function load(name = 'requirementRevisions', stubs = {}, globals = {}) {
  const exports = {}
  const source = ts.transpileModule(readFileSync(resolve(root, name + '.ts'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2023 },
  }).outputText
  runInNewContext(source, { exports, URLSearchParams, ...globals, require(id) {
    if (stubs[id]) return stubs[id]
    if (id.startsWith('./')) return load(id.slice(2), stubs, globals)
    if (id === '../../shared/api/client') return { request() { throw Error('Unexpected network') } }
    if (id === '../platform/api') return { platformApi: {} }
    throw Error(id)
  } })
  return exports
}

function reviewRuntime() {
  const values = new Map()
  return { crypto: require('node:crypto').webcrypto, TextEncoder, values,
    sessionStorage: { getItem: key => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) } }
}

test('review commands accept JSONB property ordering and retain exact nested values', async () => {
  const input = { project_id: 'project', cases: [{ case_id: 'case', title: 'Edited', inputs: ['A', 'B'] }] }
  const result = { id: 'command', tool_id: 'quality.test_design.cases.revise', status: 'waiting_confirmation',
    input_payload: { cases: [{ inputs: ['A', 'B'], title: 'Edited', case_id: 'case' }], project_id: 'project' } }
  const runtime = reviewRuntime()
  const { requirementReviewsApi: api } = load('requirementReviews', { '../platform/api': { platformApi: {
    invokeTool: async () => result,
    confirmToolInvocation: async id => ({ ...result, id, status: 'completed', result: { invocation_id: id, status: 'completed' } }),
  } } }, runtime)
  assert.equal((await api.execute('actor', result.tool_id, input)).id, 'command')
  assert.equal(runtime.values.size, 0)
})

for (const [name, change] of Object.entries({
  identity: result => { result.id = 'foreign' }, tool: result => { result.tool_id = 'other' },
  input: result => { result.input_payload.code_commits.code = 'other-sha' },
  receipt: result => { result.result.invocation_id = 'foreign' },
  state: result => { result.result.status = 'failed' },
})) test('confirmation rejects substituted ' + name + ' and retains original recovery key', async () => {
  const input = { project_id: 'project', code_commits: { code: 'selected-sha' } }
  const pending = { id: 'command', tool_id: 'quality.iteration_image.adopt', status: 'waiting_confirmation', input_payload: input }
  const runtime = reviewRuntime(), keys = []
  const { requirementReviewsApi: api } = load('requirementReviews', { '../platform/api': { platformApi: {
    invokeTool: async value => { keys.push(value.idempotency_key); return pending },
    confirmToolInvocation: async () => {
      const done = { ...structuredClone(pending), status: 'completed', result: { invocation_id: 'command', status: 'completed' } }
      change(done); return done
    },
  } } }, runtime)
  await assert.rejects(() => api.execute('actor', pending.tool_id, input), /confirmed review command/)
  await assert.rejects(() => api.execute('actor', pending.tool_id, input), /confirmed review command/)
  assert.equal(runtime.values.size, 1)
  assert.equal(keys[0], keys[1])
})

const hash = 'sha256:' + 'a'.repeat(64)
const input = { project_id: 'project', version_id: 'version', image_revision_id: 'image', image_artifact_hash: hash,
  title: 'Article editing', text: 'Only the author may edit', clarification_answers: [] }
const revision = { ...input, us_id: 'us', revision_id: 'revision', sequence: 1, previous_revision_id: null,
  original_text: input.text, recorded_at: '2026-11-12T00:00:00Z', actor_id: 'actor', invocation_id: 'command',
  content_hash: hash, status: 'draft', generation_authorized: false }
const page = { project_id: 'project', version_id: 'version', items: [revision], next_offset: null, blockers: ['requirement_semantic_review_pending'] }

test('requirement intake keeps exact iteration and is not authority', () => {
  const api = load()
  assert.equal(api.verifyRequirementInput(input), input)
  assert.equal(api.verifyRequirementPage(page, 'project', 'version'), page)
  for (const change of [{ project_id: 'other' }, { version_id: 'other' }, { status: 'approved' },
    { generation_authorized: true }, { image_artifact_hash: 'latest' }, { sequence: 0 }]) {
    assert.throws(() => api.verifyRequirementPage({ ...page, items: [{ ...revision, ...change }] }, 'project', 'version'))
  }
})

test('editing must name its parent and cannot drop into an implicit version', () => {
  const api = load()
  for (const change of [{ version_id: '' }, { us_id: 'us' }, { expected_revision_id: 'rev' }, { title: ' ' },
    { clarification_answers: [{ question: 'Access?', answer: '' }] }]) {
    assert.throws(() => api.verifyRequirementInput({ ...input, ...change }))
  }
})

test('recovery hints cannot cross actor, project or version scopes', () => {
  const api = load(), raw = JSON.stringify({ actor_id: 'actor', key: 'original-key', input })
  assert.equal(api.restoreRequirementAttempt(raw, 'actor', 'project', 'version').key, 'original-key')
  for (const scope of [['other', 'project', 'version'], ['actor', 'other', 'version'], ['actor', 'project', 'other']]) {
    assert.throws(() => api.restoreRequirementAttempt(raw, ...scope), /scope mismatch/)
  }
})

test('save verifies the acknowledged command rather than trusting a success label', async () => {
  let payload
  const receipt = { id: 'command', tool_id: 'quality.requirement.revise', input_payload: input,
    status: 'completed', result: { invocation_id: 'command', status: 'completed' } }
  const api = load('requirementRevisions', { '../platform/api': { platformApi: { invokeTool: async (value) => { payload = value; return receipt } } } })
  const attempt = { actor_id: 'actor', key: 'original-key', input }
  assert.equal(await api.requirementRevisionsApi.save(attempt), receipt)
  assert.equal(payload.idempotency_key, 'original-key')
  receipt.input_payload = { ...input, version_id: 'another' }
  await assert.rejects(() => api.requirementRevisionsApi.save(attempt), /command mismatch/)
})

test('test design uses only the current exact independently confirmed iteration selection', () => {
  const { requirementTestDesignSelection: select } = load('requirementReviews')
  const selection = { project_id: 'project', image_revision_id: 'image', image_artifact_hash: hash,
    purpose: 'test_design', policy_revision: 'nasus.test-design-context.v6', iteration: {
      version_id: 'version', requirement_revision_id: 'revision', confirmation_id: 'confirmation', confirmation_hash: hash } }
  const review = { project_id: 'project', version_id: 'version', revision_id: 'revision', current: true, status: 'confirmed',
    generation_authorized: false, confirmation: { event_id: 'confirmation', content_hash: hash,
      payload: { projection: { image_revision_id: 'image', image_artifact_hash: hash } } }, test_design_context_request: selection }
  assert.equal(select(review), selection)
  for (const change of [{ status: 'awaiting_confirmation' }, { status: 'superseded' }, { current: false }, { confirmation: null },
    { test_design_context_request: null }, { generation_authorized: true }, { version_id: 'other' }, { project_id: 'other' }, { revision_id: 'other' }])
    assert.equal(select({ ...review, ...change }), null)
  for (const field of ['version_id', 'requirement_revision_id', 'confirmation_id', 'confirmation_hash'])
    assert.equal(select({ ...review, test_design_context_request: { ...selection, iteration: { ...selection.iteration, [field]: 'other' } } }), null)
  for (const change of [{ image_artifact_hash: 'other' }, { image_revision_id: 'other' }, { policy_revision: 'nasus.test-design-context.v4' },
    { purpose: 'automation' }, { iteration: null }])
    assert.equal(select({ ...review, test_design_context_request: { ...selection, ...change } }), null)
})
