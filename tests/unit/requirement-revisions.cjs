const assert = require('node:assert/strict')
const test = require('node:test')
const { readFileSync } = require('node:fs')
const { resolve } = require('node:path')
const { runInNewContext } = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')
const root = resolve(__dirname, '../../apps/portal/src/domains/quality-loop')

function load(name = 'requirementRevisions', stubs = {}) {
  const exports = {}
  const source = ts.transpileModule(readFileSync(resolve(root, name + '.ts'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2023 },
  }).outputText
  runInNewContext(source, { exports, URLSearchParams, require(id) {
    if (stubs[id]) return stubs[id]
    if (id.startsWith('./')) return load(id.slice(2), stubs)
    if (id === '../../shared/api/client') return { request() { throw Error('Unexpected network') } }
    if (id === '../platform/api') return { platformApi: {} }
    throw Error(id)
  } })
  return exports
}

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
