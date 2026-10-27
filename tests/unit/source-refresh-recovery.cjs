const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

const attempt = () => ({ requestKey: 'request', input: { project_id: 'project', source_ids: ['code', 'us'],
  expected_manifest_id: 'manifest', expected_manifest_hash: 'sha256:' + 'a'.repeat(64) } })
const filename = path.resolve(__dirname, '../../apps/portal/src/domains/system-image/sourceRefreshRecovery.ts')
function fixture() {
  const exports = {}, values = new Map(), calls = []
  const storage = { getItem: (key) => { calls.push(['get', key]); return values.get(key) ?? null },
    setItem: (key, value) => { calls.push(['set', key]); values.set(key, value) },
    removeItem: (key) => { calls.push(['remove', key]); values.delete(key) } }
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, { exports })
  return { api: exports.createSourceRefreshRecovery(() => storage), exports, storage, values, calls }
}

test('a fresh tab has no attempt; reload restores only original request pins, not a result or authorization', () => {
  const { api, values } = fixture(), original = attempt()
  assert.equal(api.read('actor', 'project').status, 'missing')
  api.save('actor', original)
  original.input.source_ids.pop()
  const read = api.read('actor', 'project')
  assert.equal(read.status, 'saved')
  assert.deepEqual(JSON.parse(JSON.stringify(read.attempt)), attempt())
  const text = [...values.values()][0]
  assert.equal(text.includes('source_uri'), false)
  assert.equal(text.includes('access_token'), false)
  assert.equal(text.includes('confirmed'), false)
  assert.equal(text.includes('result'), false)
})
test('another account or project cannot discover or clear this recovery marker', () => {
  const { api } = fixture()
  api.save('actor', attempt())
  assert.equal(api.read('other', 'project').status, 'missing')
  assert.equal(api.read('actor', 'other-project').status, 'missing')
  assert.throws(() => api.clear('other', attempt()))
  assert.equal(api.read('actor', 'project').status, 'saved')
})
test('an unresolved marker cannot be replaced by a new request or silently reset', () => {
  const { api } = fixture()
  api.save('actor', attempt())
  assert.throws(() => api.save('actor', { ...attempt(), requestKey: 'replacement' }))
  assert.throws(() => api.clear('actor', { ...attempt(), requestKey: 'replacement' }))
  assert.equal(api.read('actor', 'project').attempt.requestKey, 'request')
  api.clear('actor', attempt())
  assert.equal(api.read('actor', 'project').status, 'missing')
})
test('verified command ID is saved without changing original pins and cannot later be replaced', () => {
  const { api } = fixture()
  api.save('actor', attempt())
  const acknowledged = { ...attempt(), commandId: 'command' }
  api.acknowledge('actor', acknowledged)
  assert.equal(api.read('actor', 'project').attempt.commandId, 'command')
  api.acknowledge('actor', acknowledged)
  assert.throws(() => api.acknowledge('actor', { ...acknowledged, commandId: 'another-command' }))
  assert.throws(() => api.acknowledge('actor', { ...acknowledged, requestKey: 'other' }))
  api.clear('actor', acknowledged)
  assert.equal(api.read('actor', 'project').status, 'missing')
})
for (const change of ['schema', 'actor', 'project', 'missing-input', 'source-duplicate', 'source-overflow',
  'bad-hash', 'empty-key', 'extra-field', 'extra-input', 'bad-command', 'malformed-json', 'oversized']) {
  test(`corrupt ${change} marker stays blocked and is never discarded`, () => {
    const { api, values } = fixture()
    api.save('actor', attempt())
    const [key, raw] = [...values.entries()][0], record = JSON.parse(raw)
    if (change === 'schema') record.schema = 'unknown'
    if (change === 'actor') record.actor_id = 'other'
    if (change === 'project') record.input.project_id = 'other'
    if (change === 'missing-input') delete record.input
    if (change === 'source-duplicate') record.input.source_ids = ['code', 'code']
    if (change === 'source-overflow') record.input.source_ids = Array.from({ length: 101 }, (_, i) => 'source-' + i)
    if (change === 'bad-hash') record.input.expected_manifest_hash = 'unverified'
    if (change === 'empty-key') record.requestKey = ''
    if (change === 'extra-field') record.access_token = 'secret'
    if (change === 'extra-input') record.input.source_uri = 'private-uri'
    if (change === 'bad-command') record.commandId = 'bad\x00id'
    const bad = change === 'malformed-json' ? '{' : change === 'oversized' ? 'x'.repeat(32769) : JSON.stringify(record)
    values.set(key, bad)
    assert.equal(api.read('actor', 'project').status, 'invalid')
    assert.throws(() => api.save('actor', attempt()))
    assert.throws(() => api.clear('actor', attempt()))
    assert.equal(values.get(key), bad)
  })
}
test('unavailable browser storage blocks saving before a write can be dispatched', () => {
  const { exports } = fixture()
  const api = exports.createSourceRefreshRecovery(() => { throw new Error('Storage disabled') })
  assert.equal(api.read('actor', 'project').status, 'unavailable')
  assert.throws(() => api.save('actor', attempt()))
})
test('quota failure or silent storage failure never claims a durable marker', () => {
  const { api, storage } = fixture()
  storage.setItem = () => { throw new Error('Quota exceeded') }
  assert.throws(() => api.save('actor', attempt()))
  storage.setItem = () => {}
  assert.throws(() => api.save('actor', attempt()))
})
test('a marker lost before acknowledgement is not rebuilt from current in-memory data', () => {
  const { api, values } = fixture()
  api.save('actor', attempt())
  values.clear()
  assert.throws(() => api.acknowledge('actor', { ...attempt(), commandId: 'command' }))
  assert.equal(values.size, 0)
})
for (const actor of ['', ' actor', 'actor\x00']) {
  test(`invalid actor ${JSON.stringify(actor)} is blocked before storage access`, () => {
    const { api, calls } = fixture()
    assert.equal(api.read(actor, 'project').status, 'invalid')
    assert.throws(() => api.save(actor, attempt()))
    assert.equal(calls.length, 0)
  })
}
