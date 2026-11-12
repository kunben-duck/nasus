const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

function load(file) {
  const exports = {}
  const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  vm.runInNewContext(code, { exports, require: (name) => load(path.resolve(path.dirname(file), `${name}.ts`)) })
  return exports
}
const { reduceConversationEvent: reduce } = load(path.resolve(__dirname,
  '../../apps/portal/src/domains/agent/conversationEventReducer.ts'))
const message = (changes = {}) => ({
  id: 'reply', role: 'assistant', status: 'streaming', stream_id: 'stream', sequence_max: 0,
  blocks: [{ type: 'text', text: '' }], ...changes,
})
const snapshot = (reply) => ({ id: 'conversation', messages: reply ? [reply] : [] })
const event = (type, payload) => ({ event_type: `conversation.message.${type}`, payload,
  entity_id: 'reply', entity_type: 'conversation_message', mutation_kind: 'replace', snapshot_hint: false })
const delta = (sequence, text = ' next', stream = 'stream') => event('delta', {
  message_id: 'reply', stream_id: stream, sequence, delta: text,
})

for (const status of ['completed', 'interrupted', 'failed']) {
  test(`${status} history cannot be restarted or extended by SSE replay`, () => {
    const current = snapshot(message({ status, sequence_max: 3, blocks: [{ type: 'text', text: 'Saved reply' }] }))
    assert.equal(reduce(current, event('started', { message: message() })), current)
    assert.equal(reduce(current, delta(1)), current)
    assert.equal(reduce(current, delta(4)), current)
    assert.equal(reduce(current, event('completed', { message: message({ status: 'completed' }) })), current)
    assert.equal(current.messages[0].blocks[0].text, 'Saved reply')
  })
}

test('restored streaming text keeps its prefix and only accepts new sequences', () => {
  const current = snapshot(message({ sequence_max: 3, blocks: [{ type: 'text', text: 'Saved prefix' }] }))
  assert.equal(reduce(current, event('started', { message: message() })), current)
  assert.equal(reduce(current, delta(3)), current)
  assert.equal(reduce(current, delta(4, 'wrong stream', 'other')), current)
  const next = reduce(current, delta(4))
  assert.equal(next.messages[0].blocks[0].text, 'Saved prefix next')
  assert.equal(next.messages[0].sequence_max, 4)
  assert.equal(reduce(next, delta(4)), next)
})

test('stale terminal snapshots cannot truncate restored streaming content', () => {
  const current = snapshot(message({ sequence_max: 3, blocks: [{ type: 'text', text: 'Saved prefix' }] }))
  for (const status of ['completed', 'interrupted', 'failed']) {
    assert.equal(reduce(current, event(status, { message: message({ status, sequence_max: 2 }) })), current)
    assert.equal(reduce(current, event(status, { message: message({ status, stream_id: 'other', sequence_max: 3 }) })), current)
    const final = message({ status, sequence_max: 3, blocks: current.messages[0].blocks })
    assert.equal(reduce(current, event(status, { message: final })).messages[0], final)
  }
})

test('new replies still progress through started, deltas and completion', () => {
  let current = reduce(snapshot(), event('started', { message: message() }))
  assert.equal(current.messages[0].status, 'streaming')
  current = reduce(current, delta(1, 'Live'))
  current = reduce(current, delta(2, ' reply'))
  assert.equal(current.messages[0].blocks[0].text, 'Live reply')
  const final = message({ status: 'completed', sequence_max: 2, blocks: current.messages[0].blocks })
  current = reduce(current, event('completed', { message: final }))
  assert.equal(current.messages[0], final)
  assert.equal(reduce(current, event('started', { message: message() })), current)
})
