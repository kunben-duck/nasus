const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

const root = path.resolve(__dirname, '../../apps/portal/src')
function load(relative, overrides, modules = new Map()) {
  const file = path.resolve(root, relative)
  if (modules.has(file)) return modules.get(file)
  const context = { exports: {}, URLSearchParams, require: (name) => {
    if (Object.hasOwn(overrides, name)) return overrides[name]
    return load(path.relative(root, path.resolve(path.dirname(file), `${name}.ts`)), overrides, modules)
  } }
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, context)
  modules.set(file, context.exports)
  return context.exports
}
const { ApiRequestError } = load('shared/api/errors.ts', {})
const digest = (character) => 'sha256:' + character.repeat(64)
const pair = { before: { project_id: 'project', image_revision_id: 'before', artifact_hash: digest('a'), code_member_count: 41 },
  after: { project_id: 'project', image_revision_id: 'after', artifact_hash: digest('b'), code_member_count: 41 } }

function page(offset, limit, kind = null) {
  const total = kind === null || kind === 'revision_changed' ? 41 : 0
  const end = Math.min(offset + limit, total)
  return { project_id: 'project', before_image_revision_id: 'before', before_image_hash: digest('a'),
    after_image_revision_id: 'after', after_image_hash: digest('b'), content_hash: digest('c'),
    counts: { added_member: 0, removed_member: 0, revision_changed: 41, projection_changed: 0, unchanged: 0 },
    source_scope_changed: false, kind, total, next_offset: end < total ? end : null,
    schema: 'nasus.code-member-delta.v1', comparison_scope: 'registered_members_of_two_frozen_images',
    source_deletions_verified: false, rename_lineage_transferred: false, impact_complete: false,
    approval_transferred: false, execution_authorized: false,
    items: Array.from({ length: end - offset }, (_, index) => {
      const id = String(offset + index).padStart(3, '0')
      const pin = (side) => ({ object_id: `object-${id}`, entity_revision_id: `revision-${side}-${id}`,
        source_revision_id: `source-${side}`, object_hash: digest('d'), evidence_ids: [`evidence-${side}-${id}`] })
      return { binding_id: 'binding', entity_id: `entity-${id}`, kind: 'revision_changed', before: pin('before'), after: pin('after') }
    }) }
}

function fixture(reply) {
  const calls = [], controller = new AbortController()
  const api = load('domains/system-image/codeMemberDeltaApi.ts', {
    '../../shared/api/client': { request: async (url, options) => {
      const params = new URL(url, 'http://localhost').searchParams
      calls.push({ url, offset: Number(params.get('offset')), limit: Number(params.get('limit')) })
      assert.equal(options.cache, 'no-store')
      assert.equal(options.method, undefined)
      assert.equal(options.signal, controller.signal)
      for (const [name, value] of Object.entries({ before_image_revision_id: 'before', before_image_hash: digest('a'),
        after_image_revision_id: 'after', after_image_hash: digest('b') })) assert.equal(params.get(name), value)
      return reply(params, controller)
    } }, '../../shared/api/errors': { ApiRequestError },
  }).readCodeMemberDelta
  return { calls, controller, read: (kind = null, offset = 0, expected = digest('c'), selected = pair) =>
    api('project', selected, { kind, offset }, controller.signal, expected) }
}

test('only explicit byte errors reduce complete delta pages, preserving both image pins and offset', async () => {
  const v = fixture((params) => {
    const offset = Number(params.get('offset')), limit = Number(params.get('limit'))
    if (limit > 5) throw new ApiRequestError('Large page', 413, 'image_page_too_large')
    return page(offset, limit, params.get('kind'))
  })
  const result = await v.read('revision_changed', 7)
  assert.deepEqual(v.calls.map(({ offset, limit }) => [offset, limit]), [[7, 20], [7, 10], [7, 5]])
  assert.equal(result.items[0].entity_id, 'entity-007')
  assert.equal(result.next_offset, 12)
})

test('all pages, empty categories and final offsets retain complete inventory counts', async () => {
  const v = fixture((params) => page(Number(params.get('offset')), Number(params.get('limit')), params.get('kind')))
  const first = await v.read()
  const second = await v.read(null, first.next_offset)
  const last = await v.read(null, second.next_offset)
  assert.equal(last.items.length, 1)
  assert.equal(last.next_offset, null)
  assert.equal(new Set([...first.items, ...second.items, ...last.items].map((item) => item.entity_id)).size, 41)
  const empty = await v.read('added_member')
  assert.equal(empty.total, 0)
  assert.equal(empty.items.length, 0)
  assert.equal(empty.counts.revision_changed, 41)
})

const corruptions = {
  'different project': (value) => { value.project_id = 'other' },
  'different before image': (value) => { value.before_image_revision_id = 'other' },
  'different after image': (value) => { value.after_image_revision_id = 'other' },
  'different before hash': (value) => { value.before_image_hash = digest('e') },
  'different after hash': (value) => { value.after_image_hash = digest('e') },
  'changed comparison hash': (value) => { value.content_hash = digest('e') },
  'unknown schema': (value) => { value.schema = 'v2' },
  'source deletion authority': (value) => { value.source_deletions_verified = true },
  'rename transfer': (value) => { value.rename_lineage_transferred = true },
  'complete impact': (value) => { value.impact_complete = true },
  'approval transfer': (value) => { value.approval_transferred = true },
  'execution authority': (value) => { value.execution_authorized = true },
  'missing restriction': (value) => { delete value.execution_authorized },
  'missing counts': (value) => { delete value.counts.added_member },
  'fractional counts': (value) => { value.counts.revision_changed = 41.5 },
  'different image count': (value) => { value.counts.revision_changed = 40 },
  'different total': (value) => { value.total = 40 },
  'wrong filter': (value) => { value.kind = 'removed_member' },
  'missing row': (value) => { value.items.pop() },
  'repeated row': (value) => { value.items[1] = value.items[0] },
  'unordered row': (value) => { value.items.reverse() },
  'skipped cursor': (value) => { value.next_offset += 1 },
  'premature last page': (value) => { value.next_offset = null },
  'missing both endpoints': (value) => { value.items[0].before = null; value.items[0].after = null },
  'invented classification': (value) => { value.items[0].kind = 'unchanged' },
  'broken member hash': (value) => { value.items[0].before.object_hash = 'bad' },
  'repeated evidence': (value) => { value.items[0].after.evidence_ids = ['same', 'same'] },
  'control character identity': (value) => { value.items[0].entity_id = 'unsafe\x00identity' },
  'revision scope mutation': (value) => { value.items[0].after.entity_revision_id = value.items[0].before.entity_revision_id },
}
for (const [name, mutate] of Object.entries(corruptions)) {
  test(`a ${name} is rejected before displaying a comparison`, async () => {
    const v = fixture((params) => { const value = page(0, Number(params.get('limit'))); mutate(value); return value })
    await assert.rejects(v.read())
    assert.equal(v.calls.length, 1)
  })
}

for (const [status, code] of [[401, 'unauthorized'], [403, 'source_access_denied'], [409, 'source_access_changed'],
  [502, 'image_integrity_failed'], [503, 'image_artifact_unavailable'], [413, 'other_limit']]) {
  test(`failure ${status}/${code} cannot cause a second read`, async () => {
    const failure = new ApiRequestError('Failed read', status, code)
    const v = fixture(() => { throw failure })
    await assert.rejects(v.read(), (error) => error === failure)
    assert.equal(v.calls.length, 1)
  })
}

test('one oversized member is never clipped or replaced with an empty page', async () => {
  const v = fixture(() => { throw new ApiRequestError('Large member', 413, 'image_page_too_large') })
  await assert.rejects(v.read())
  assert.deepEqual(v.calls.map((item) => item.limit), [20, 10, 5, 2, 1])
})

for (const stage of ['before request', 'oversized reply', 'successful reply']) {
  test(`cancellation at ${stage} does not show a response or retry`, async () => {
    const v = fixture((params, controller) => {
      controller.abort()
      if (stage === 'oversized reply') throw new ApiRequestError('Large page', 413, 'image_page_too_large')
      return page(0, Number(params.get('limit')))
    })
    if (stage === 'before request') v.controller.abort()
    await assert.rejects(v.read(), { name: 'AbortError' })
    assert.equal(v.calls.length, stage === 'before request' ? 0 : 1)
  })
}

for (const selected of [null, {}, { ...pair, before: { ...pair.before, artifact_hash: 'bad' } },
  { ...pair, after: { ...pair.after, project_id: 'other' } },
  { ...pair, after: { ...pair.after, image_revision_id: 'before' } }]) {
  test(`invalid pair sends no request: ${JSON.stringify(selected)}`, async () => {
    const v = fixture((params) => page(0, Number(params.get('limit'))))
    await assert.rejects(v.read(null, 0, digest('c'), selected))
    assert.equal(v.calls.length, 0)
  })
}

test('all five categories validate their distinct pin semantics', () => {
  const { requireCodeDeltaPage } = load('domains/system-image/codeMemberDeltaValidation.ts', {})
  const value = page(0, 5)
  value.counts = { added_member: 1, removed_member: 1, revision_changed: 1, projection_changed: 1, unchanged: 1 }
  value.total = 5; value.next_offset = null
  value.items[0].before = null; value.items[0].kind = 'added_member'
  value.items[1].after = null; value.items[1].kind = 'removed_member'
  value.items[3].after = { ...value.items[3].before, object_hash: digest('e') }; value.items[3].kind = 'projection_changed'
  value.items[4].after = { ...value.items[4].before }; value.items[4].kind = 'unchanged'
  const selected = { before: { ...pair.before, code_member_count: 4 }, after: { ...pair.after, code_member_count: 4 } }
  assert.equal(requireCodeDeltaPage(value, 'project', selected, { offset: 0, kind: null }, 20, digest('c')), value)
})
