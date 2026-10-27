const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

const directory = path.resolve(__dirname, '../../apps/portal/src/domains/system-image')
function load(file, dependencies) {
  const code = ts.transpileModule(fs.readFileSync(path.join(directory, file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const context = { URLSearchParams, exports: {}, require: (name) => {
    assert.ok(Object.hasOwn(dependencies, name), `Unexpected dependency ${name}`)
    return dependencies[name]
  } }
  vm.runInNewContext(code, context)
  return context.exports
}
const hash = (letter) => 'sha256:' + letter.repeat(64)
const head = (sequence) => ({ publication_id: `publication-${sequence}`, project_id: 'project', baseline_id: 'baseline',
  image_revision_id: `image-${sequence}`, image_artifact_hash: hash('a'), sequence,
  recorded_at: '2026-10-07T01:00:00Z', actor_id: 'reviewer', quality_generation_authorized: false, release_authorized: false })
const target = () => ({ project_id: 'project', image_revision_id: 'image-1', image_artifact_hash: hash('a'),
  target_baseline_id: 'baseline', expected_head_id: 'publication-2', rollback_publication_id: 'publication-1',
  policy_revision: 'nasus.image-rollback.v1' })
const page = () => ({ baseline: { project_id: 'project', baseline_id: 'baseline', kind: 'official' },
  head: head(2), items: [head(1), head(2)], next_after_sequence: null })
const preview = () => ({ target: target(), preview_digest: hash('b'), baseline: page().baseline, head: head(2),
  image: { project_id: 'project', image_revision_id: 'image-1', artifact_hash: hash('a') },
  review: null, can_review: true, rollback_source: head(1), readiness: { scope: 'knowledge_snapshot_only',
    quality_generation_authorized: false, release_authorized: false, unverified_observation_count: 0 } })
function api(response, mutate = () => {}) {
  const calls = []
  const publication = load('imagePublicationApi.ts', {
    '../../shared/api/client': { request: async () => { throw new Error('Unexpected normal publication read') } },
    '../platform/api': { platformApi: {
      invokeTool: async (request) => {
        calls.push(['invoke', request])
        const review = request.tool_id === 'system_image.revisions.review_rollback'
        const result = { id: 'command', tool_id: request.tool_id, input_payload: request.input,
          status: review ? 'waiting_confirmation' : 'completed',
          result: review ? null : { invocation_id: 'command', object_refs: ['image_publication:restored'] } }
        mutate(result, 'invoke')
        return result
      },
      confirmToolInvocation: async (id) => {
        calls.push(['confirm', id])
        const request = calls.find((call) => call[0] === 'invoke')[1]
        const result = { id, tool_id: request.tool_id, input_payload: request.input, status: 'completed',
          result: { invocation_id: id, object_refs: ['publication_review:approved'] } }
        mutate(result, 'confirm')
        return result
      },
    } },
  })
  const rollback = load('imageRollbackApi.ts', {
    './imagePublicationApi': publication,
    '../../shared/api/client': { request: async (url, options) => { calls.push(['read', url, options]); return response } },
  })
  return { publication: publication.imagePublicationApi, ...rollback, calls }
}

test('history accepts bounded ordered pages, a full cursor and an empty terminal page', () => {
  const { verifyRollbackHistory: verify } = api()
  const value = page()
  assert.equal(verify(value, 'project', 'baseline', 0), value)
  const full = { ...value, head: head(11), items: Array.from({ length: 10 }, (_, i) => head(i + 1)), next_after_sequence: 10 }
  assert.equal(verify(full, 'project', 'baseline', 0), full)
  assert.equal(verify({ ...value, items: [], next_after_sequence: null }, 'project', 'baseline', 2).items.length, 0)
})
for (const change of ['project', 'baseline', 'head', 'order', 'duplicate', 'after-head', 'bad-sequence', 'authority', 'hash', 'cursor', 'limit', 'missing-head']) {
  test(`history rejects ${change} before choices can render`, () => {
    const value = page()
    if (change === 'project') value.items[0].project_id = 'foreign'
    if (change === 'baseline') value.items[0].baseline_id = 'foreign'
    if (change === 'head') value.head.project_id = 'foreign'
    if (change === 'order') value.items.reverse()
    if (change === 'duplicate') value.items[1].publication_id = value.items[0].publication_id
    if (change === 'after-head') value.items[1].sequence = 3
    if (change === 'bad-sequence') value.items[0].sequence = 1.5
    if (change === 'authority') value.items[0].release_authorized = true
    if (change === 'hash') value.items[0].image_artifact_hash = 'unchecked'
    if (change === 'cursor') value.next_after_sequence = 2
    if (change === 'limit') value.items = Array.from({ length: 11 }, (_, i) => head(i + 1))
    if (change === 'missing-head') value.head = null
    assert.throws(() => api().verifyRollbackHistory(value, 'project', 'baseline', 0))
  })
}
test('history rejects malformed responses, before-cursor records and invalid cursors', () => {
  const { verifyRollbackHistory: verify } = api()
  for (const invalid of [null, {}, { ...page(), items: [null] }]) assert.throws(() => verify(invalid, 'project', 'baseline', 0))
  for (const after of [-1, 0.5, Number.MAX_SAFE_INTEGER + 1, 1]) assert.throws(() => verify(page(), 'project', 'baseline', after))
})
test('rollback reads are no-store and pin the exact historical source and current head', async () => {
  const v = preview(), { imageRollbackApi: application, calls } = api(v)
  assert.equal(await application.preview(target(), new AbortController().signal), v)
  assert.equal(calls[0][2].cache, 'no-store')
  const url = new URL(calls[0][1], 'https://local.invalid')
  assert.equal(url.searchParams.get('rollback_publication_id'), 'publication-1')
  assert.equal(url.searchParams.get('expected_head_id'), 'publication-2')
})
for (const change of ['project', 'source', 'target-source', 'source-image', 'source-hash', 'not-historical', 'no-op', 'policy', 'authority', 'head', 'review']) {
  test(`rollback preview rejects ${change}`, async () => {
    const v = preview()
    if (change === 'project') v.rollback_source.project_id = 'foreign'
    if (change === 'source') v.rollback_source.publication_id = 'foreign'
    if (change === 'target-source') v.target.rollback_publication_id = 'foreign'
    if (change === 'source-image') v.rollback_source.image_revision_id = 'foreign'
    if (change === 'source-hash') v.rollback_source.image_artifact_hash = hash('c')
    if (change === 'not-historical') v.rollback_source.sequence = 2
    if (change === 'no-op') v.head.image_revision_id = 'image-1'
    if (change === 'policy') v.target.policy_revision = 'nasus.image-publication.v1'
    if (change === 'authority') v.readiness.quality_generation_authorized = true
    if (change === 'head') v.head.publication_id = 'changed'
    if (change === 'review') v.review = { review_id: 'review', project_id: 'foreign' }
    await assert.rejects(api(v).imageRollbackApi.preview(target(), new AbortController().signal))
  })
}
test('rollback review uses its own canonical tool and separate confirmation', async () => {
  const { publication, calls } = api()
  assert.equal(await publication.write(preview(), 'review', 'approve', 'Knowledge only', 'attempt'), 'approved')
  assert.deepEqual(calls.map((call) => call[0]), ['invoke', 'confirm'])
  assert.equal(calls[0][1].tool_id, 'system_image.revisions.review_rollback')
  assert.equal(calls[0][1].input.rollback_publication_id, 'publication-1')
  assert.equal(calls[0][1].idempotency_key, 'attempt')
})
test('restore uses baseline.rollback and the exact independent approval', async () => {
  const { publication, calls } = api(), v = preview()
  v.review = { review_id: 'approved' }
  assert.equal(await publication.write(v, 'publish', 'approve', '', 'attempt'), 'restored')
  assert.equal(calls.length, 1)
  assert.equal(calls[0][1].tool_id, 'baseline.rollback')
  assert.equal(calls[0][1].input.approval_id, 'approved')
  assert.equal(calls[0][1].input.expected_head_id, 'publication-2')
})
for (const boundary of ['tool', 'input', 'id', 'unconfirmed', 'failed', 'reference', 'result-command']) {
  test(`canonical ${boundary} mismatch fails without an automatic retry`, async () => {
    const { publication, calls } = api(undefined, (result, phase) => {
      if (boundary === 'tool') result.tool_id = 'baseline.promote'
      if (boundary === 'input') result.input_payload = { ...result.input_payload, rollback_publication_id: 'foreign' }
      if (phase === 'invoke' && boundary === 'unconfirmed') result.status = 'completed'
      if (phase === 'confirm') {
        if (boundary === 'id') result.id = 'other'
        if (boundary === 'failed') result.status = 'failed'
        if (boundary === 'reference') result.result.object_refs = ['image_publication:foreign']
        if (boundary === 'result-command') result.result.invocation_id = 'other'
      }
    })
    await assert.rejects(publication.write(preview(), 'review', 'approve', 'Knowledge only', 'attempt'))
    assert.equal(calls.filter((call) => call[0] === 'invoke').length, 1)
    assert.ok(calls.filter((call) => call[0] === 'confirm').length <= 1)
  })
}
