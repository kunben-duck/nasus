const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const { resolve, dirname } = require('node:path')
const test = require('node:test')
const { runInNewContext } = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')
const root = resolve(__dirname, '../../apps/portal/src/domains/quality-loop')

function load(name, stubs = {}) {
  const path = resolve(root, `${name}.ts`), exports = {}
  const source = ts.transpileModule(readFileSync(path, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2023 } }).outputText
  runInNewContext(source, { exports, AbortController, URLSearchParams, require: (id) => {
    if (stubs[id]) return stubs[id]
    if (id.startsWith('./')) return load(resolve(dirname(path), id), stubs)
    throw new Error(`Unexpected dependency ${id}`)
  } })
  return exports
}

const hash = `sha256:${'a'.repeat(64)}`
const pin = { publication_id: 'pub-1', baseline_id: 'base-1', image_revision_id: 'image-1', image_artifact_hash: hash,
  manifest_id: 'manifest-1', manifest_hash: hash, sequence: 1, quality_generation_authorized: false, release_authorized: false }
const binding = { publication_id: pin.publication_id, image_revision_id: pin.image_revision_id, image_artifact_hash: hash, expected_head_id: pin.publication_id }
const attempt = { actor_id: 'actor-1', idempotency_key: 'original-key', input: { project_id: 'project-1', name: 'Sprint 1', image_binding: binding } }
const view = { project_id: 'project-1', version_id: 'version-1', name: 'Sprint 1', enabled: true, stage: 'image_pinned', baseline: pin, iteration_image: pin,
  code_revisions: [{ binding_id: 'binding-1', source_id: 'source-1', source_revision_id: 'source-rev-1', repository: 'fixture', tracked_ref: 'main',
    external_revision: 'a'.repeat(40), commit_sha: 'a'.repeat(40), content_hash: hash, manifest_hash: hash }],
  blockers: ['delivery_m2_not_implemented'], pending_confirmations: [], available_actions: ['view_pinned_image'] }
const receipt = { id: 'command-1', tool_id: 'version.create', input_payload: attempt.input, status: 'completed',
  result: { invocation_id: 'command-1', status: 'completed', requires_followup: false, object_refs: ['version:version-1'] } }
const clone = (value) => JSON.parse(JSON.stringify(value))

test('delivery validates immutable and current pins independently without release authority', () => {
  const { verifyVersionDelivery, verifyCreatedIteration } = load('versionDeliveryValidation')
  const changed = clone(view)
  changed.iteration_image = { ...pin, publication_id: 'pub-2', image_revision_id: 'image-2', sequence: 2 }
  assert.equal(verifyVersionDelivery(changed, 'project-1', 'version-1'), changed)
  assert.equal(verifyCreatedIteration(changed, binding), changed)
  assert.equal(verifyVersionDelivery({ ...view, enabled: false, stage: 'legacy', baseline: null, iteration_image: null,
    code_revisions: [], available_actions: [] }, 'project-1', 'version-1').enabled, false)
})

for (const [label, alter] of Object.entries({
  'wrong project': (v) => { v.project_id = 'other' },
  'wrong version': (v) => { v.version_id = 'other' },
  'invented completion': (v) => { v.stage = 'released' },
  'missing baseline': (v) => { v.baseline = null },
  'generation authority': (v) => { v.baseline.quality_generation_authorized = true },
  'release authority': (v) => { v.iteration_image.release_authorized = true },
  'malformed digest': (v) => { v.baseline.image_artifact_hash = 'latest' },
  'no source evidence': (v) => { v.code_revisions = [] },
  'branch masquerading as commit': (v) => { v.code_revisions[0].commit_sha = 'main' },
  'unsupported release action': (v) => { v.available_actions = ['release'] },
})) test(`delivery rejects ${label}`, () => {
  const v = clone(view); alter(v)
  assert.throws(() => load('versionDeliveryValidation').verifyVersionDelivery(v, 'project-1', 'version-1'), /mismatch/)
})

test('creation requires an explicit current publication and exact command and result', () => {
  const { verifyIterationInput, createdIterationId } = load('iterationCreation')
  assert.equal(createdIterationId(receipt, attempt), 'version-1')
  for (const bad of [undefined, {}, { ...binding, expected_head_id: 'latest' }, { ...binding, image_artifact_hash: '' }]) {
    assert.throws(() => verifyIterationInput({ ...attempt.input, image_binding: bad }), /mismatch/)
  }
  for (const alter of [
    (r) => { r.tool_id = 'baseline.promote' }, (r) => { r.input_payload.project_id = 'other' },
    (r) => { r.input_payload.image_binding.publication_id = 'other' }, (r) => { r.result.invocation_id = 'other' },
    (r) => { r.result.object_refs.push('version:other') }, (r) => { r.status = 'failed' },
    (r) => { r.result.requires_followup = true },
  ]) {
    const r = clone(receipt); alter(r)
    assert.throws(() => createdIterationId(r, attempt))
  }
})

test('recovery is actor/project isolated and keeps the original idempotency key', () => {
  const { readIterationAttempt, iterationAttemptKey } = load('iterationCreation')
  const store = new Map([[iterationAttemptKey('project-1', 'actor-1'), JSON.stringify(attempt)]])
  const storage = { getItem: (key) => store.get(key) ?? null }
  assert.equal(readIterationAttempt(storage, 'project-1', 'actor-1').idempotency_key, 'original-key')
  assert.equal(readIterationAttempt(storage, 'project-2', 'actor-1'), null)
  assert.equal(readIterationAttempt(storage, 'project-1', 'actor-2'), null)
  assert.throws(() => readIterationAttempt({ getItem: () => JSON.stringify(attempt) }, 'project-2', 'actor-1'), /scope mismatch/)
})

test('runtime recovery verifies a persisted receipt without creating or confirming again', async () => {
  let calls = 0, confirms = 0, reads = 0
  const api = load('iterationCreationApi', {
    '../platform/api': { platformApi: { invokeTool: () => { calls++; throw new Error('unexpected write') },
      confirmToolInvocation: () => { confirms++; throw new Error('unexpected confirmation') }, getToolInvocation: async () => receipt } },
    './versionDeliveryApi': { versionDeliveryApi: { read: async (project, version) => { reads++; assert.equal(project, 'project-1'); assert.equal(version, 'version-1'); return clone(view) } } },
  }).iterationCreationApi
  const result = await api.execute({ ...attempt, invocation_id: 'command-1' }, 'inspect', () => {})
  assert.equal(result.delivery.version_id, 'version-1')
  assert.equal(calls, 0); assert.equal(confirms, 0); assert.equal(reads, 1)
})

test('lost response retries the same command and refuses a mismatched created baseline', async () => {
  const calls = []
  const api = load('iterationCreationApi', {
    '../platform/api': { platformApi: { invokeTool: async (input) => { calls.push(clone(input)); if (calls.length === 1) throw new Error('lost'); return receipt } } },
    './versionDeliveryApi': { versionDeliveryApi: { read: async () => ({ ...clone(view), baseline: { ...pin, publication_id: 'other' } }) } },
  }).iterationCreationApi
  await assert.rejects(api.execute(attempt, 'submit', () => {}), /lost/)
  await assert.rejects(api.execute(attempt, 'submit', () => {}), /baseline mismatch/)
  assert.deepEqual(calls[1], calls[0]); assert.equal(calls[1].idempotency_key, 'original-key')
})

test('delivery transport rechecks scope after the read and disables cache', async () => {
  const calls = []
  const api = load('versionDeliveryApi', { '../../shared/api/client': { request: async (...args) => { calls.push(args); return clone(view) } } }).versionDeliveryApi
  await api.read('project-1', 'version-1', new AbortController().signal)
  assert.equal(calls[0][0], '/v1/projects/project-1/versions/version-1/delivery')
  assert.equal(calls[0][1].cache, 'no-store')
  await assert.rejects(api.read('project-1', 'another-version', new AbortController().signal), /scope mismatch/)
  const controller = new AbortController(); controller.abort()
  await assert.rejects(api.read('project-1', 'version-1', controller.signal))
})

test('Build restores a scoped proposal but treats a conversation delivery observation only as a navigation hint', () => {
  const { deliveryConversationState } = load('deliveryConversation')
  const proposal = { schema_version: 'nasus.delivery-dialogue.v1', project_id: 'project-1', proposal_id: 'proposal-1', name: 'Sprint 1',
    publication_id: 'pub-1', image_binding: binding, stage: 'confirmation' }
  const session = { project_id: 'project-1', messages: [{ role: 'assistant', metadata: { delivery_intake: proposal } }] }
  assert.equal(deliveryConversationState(session).proposal.proposal_id, 'proposal-1')
  assert.equal(deliveryConversationState({ ...session, project_id: 'project-2' }).proposal, undefined)
  session.messages.push({ role: 'assistant', metadata: { version_delivery: view } })
  assert.equal(deliveryConversationState(session).versionId, 'version-1')
  assert.equal(deliveryConversationState(session).proposal.proposal_id, 'proposal-1')
  session.messages.push({ role: 'assistant', metadata: { delivery_intake: { ...proposal, stage: 'selection', image_binding: null } } })
  assert.equal(deliveryConversationState(session).versionId, undefined)
})
