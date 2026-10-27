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
const hash = 'sha256:' + 'a'.repeat(64)

function page(section, offset, limit, total = 41) {
  const end = Math.min(offset + limit, total)
  const items = Array.from({ length: end - offset }, (_, index) => {
    const id = offset + index
    const common = { subject_object_id: `test-${id}`, reference_id: `US-${id}` }
    return section === 'gaps' ? { ...common, reason: 'target_not_in_selected_image' } : {
      ...common, assertion_id: `assertion-${id}`, subject_revision_id: `test-revision-${id}`,
      object_id: `requirement-${id}`, object_revision_id: `requirement-revision-${id}`,
      subject_evidence_ids: [`test-evidence-${id}`], object_evidence_ids: [`requirement-evidence-${id}`],
      predicate: 'references', semantic_kind: 'observed', status: 'proposed',
      applicability: 'selected_manifest_only_not_business_coverage',
    }
  })
  return { proposal_id: 'proposal', image_revision_id: 'image', image_artifact_hash: hash, digest: hash,
    status: 'proposed', method_version: 'nasus.explicit-requirement-reference.v1',
    section, assertion_count: total, gap_count: total, publication: 'not_in_image_membership',
    items, next_offset: end < total ? end : null }
}

function fixture(reply) {
  const calls = [], controller = new AbortController()
  const client = { ApiRequestError, request: async (url, options) => {
    const params = new URL(url, 'http://localhost').searchParams
    calls.push({ url, options, limit: Number(params.get('limit') ?? 20), offset: Number(params.get('offset')) })
    assert.equal(options.signal, controller.signal)
    assert.equal(options.cache, 'no-store')
    assert.equal(options.method, undefined)
    return reply(params, controller)
  } }
  const api = load('domains/system-image/referenceReviewApi.ts', {
    '../../shared/api/client': client, '../../shared/api/errors': { ApiRequestError },
    '../platform/api': { platformApi: {} },
  }).referenceReviewApi
  return { calls, controller, api, read: (section = 'assertions', offset = 0, pin = { imageArtifactHash: hash, proposalDigest: hash }) =>
    api.page('project', 'image', 'proposal', section, offset, controller.signal, pin) }
}

test('a byte-limited reference page reduces complete rows and preserves its exact offset', async () => {
  const v = fixture((params) => {
    const limit = Number(params.get('limit') ?? 20), offset = Number(params.get('offset'))
    if (limit > 5) throw new ApiRequestError('Oversized page', 413, 'image_page_too_large')
    return page(params.get('section'), offset, limit)
  })
  const result = await v.read('assertions', 7)
  assert.deepEqual(v.calls.map((call) => [call.offset, call.limit]), [[7, 20], [7, 10], [7, 5]])
  assert.equal(result.items.length, 5)
  assert.equal(result.items[0].assertion_id, 'assertion-7')
  assert.equal(result.next_offset, 12)
  assert.equal(result.items[0].subject_evidence_ids.length, 1)
})

test('an oversized single reference fails rather than being clipped or replaced by an empty page', async () => {
  const failure = new ApiRequestError('One complete assertion is too large', 413, 'image_page_too_large')
  const v = fixture(() => { throw failure })
  await assert.rejects(v.read(), (error) => error === failure)
  assert.deepEqual(v.calls.map((call) => call.limit), [20, 10, 5, 2, 1])
})

for (const [status, code] of [[403, 'source_access_denied'], [409, 'source_scope_changed'],
  [502, 'image_integrity_error'], [413, 'other_limit']]) {
  test(`a ${status}/${code} failure cannot authorize another read`, async () => {
    const failure = new ApiRequestError('Denied or invalid', status, code)
    const v = fixture(() => { throw failure })
    await assert.rejects(v.read(), (error) => error === failure)
    assert.equal(v.calls.length, 1)
  })
}

test('aborting during an oversized reply prevents the next smaller read', async () => {
  const v = fixture((_, controller) => {
    controller.abort()
    throw new ApiRequestError('Oversized page', 413, 'image_page_too_large')
  })
  await assert.rejects(v.read(), { name: 'AbortError' })
  assert.equal(v.calls.length, 1)
})

test('an already cancelled reference read sends no request', async () => {
  const v = fixture((params) => page(params.get('section'), 0, 20))
  v.controller.abort()
  await assert.rejects(v.read(), { name: 'AbortError' })
  assert.equal(v.calls.length, 0)
})

const corruptions = {
  'wrong image hash': (value) => { value.image_artifact_hash = 'bad-hash' },
  'wrong proposal digest': (value) => { value.digest = 'bad-hash' },
  'different valid image hash': (value) => { value.image_artifact_hash = 'sha256:' + 'b'.repeat(64) },
  'different valid proposal digest': (value) => { value.digest = 'sha256:' + 'b'.repeat(64) },
  'approved report': (value) => { value.status = 'approved' },
  'unknown method': (value) => { value.method_version = 'nasus.explicit-requirement-reference.v999' },
  'fractional total': (value) => { value.assertion_count = 41.5 },
  'negative gaps': (value) => { value.gap_count = -1 },
  'skipped cursor': (value) => { value.next_offset += 1 },
  'boolean cursor': (value) => { value.next_offset = true },
  'premature last page': (value) => { value.next_offset = null },
  'missing row': (value) => { value.items.pop() },
  'extra row': (value) => { value.items.push(value.items[0]) },
  'duplicate assertion': (value) => { value.items[1] = value.items[0] },
  'semantic upgrade': (value) => { value.items[0].predicate = 'implements' },
  'accepted candidate': (value) => { value.items[0].status = 'accepted' },
  'missing source evidence': (value) => { value.items[0].subject_evidence_ids = [] },
}
for (const [name, change] of Object.entries(corruptions)) {
  test(`a ${name} fails before displaying a reference page`, async () => {
    const v = fixture((params) => {
      const value = page(params.get('section'), 0, Number(params.get('limit') ?? 20))
      change(value)
      return value
    })
    await assert.rejects(v.read())
    assert.equal(v.calls.length, 1)
  })
}

test('complete gap pages and an empty final section preserve the server cursor', async () => {
  const v = fixture((params) => page(params.get('section'), Number(params.get('offset')),
    Number(params.get('limit') ?? 20), 0))
  const result = await v.read('gaps')
  assert.equal(result.items.length, 0)
  assert.equal(result.next_offset, null)
})

for (const pin of [null, {}, { imageArtifactHash: 'bad', proposalDigest: hash },
  { imageArtifactHash: hash, proposalDigest: 'bad' }]) {
  test(`an invalid selected reference pin sends no read: ${JSON.stringify(pin)}`, async () => {
    const v = fixture((params) => page(params.get('section'), 0, Number(params.get('limit'))))
    await assert.rejects(v.read('assertions', 0, pin))
    assert.equal(v.calls.length, 0)
  })
}

test('a mismatched valid report digest on a shrunk page is not retried or displayed', async () => {
  const v = fixture((params) => {
    const limit = Number(params.get('limit'))
    if (limit === 20) throw new ApiRequestError('Oversized page', 413, 'image_page_too_large')
    return { ...page(params.get('section'), 0, limit), digest: 'sha256:' + 'b'.repeat(64) }
  })
  await assert.rejects(v.read())
  assert.deepEqual(v.calls.map((call) => call.limit), [20, 10])
})

test('reference history must remain pinned to the selected report digest', async () => {
  const v = fixture(() => ({ project_id: 'project', proposal_id: 'proposal', assertion_id: 'assertion',
    image_revision_id: 'image', proposal_digest: 'sha256:' + 'b'.repeat(64),
    publication: 'not_in_image_membership', items: [], total: 0, next_offset: null }))
  await assert.rejects(v.api.history('project', 'image', 'proposal', 'assertion', 0, v.controller.signal, hash))
  assert.equal(v.calls.length, 1)
})
