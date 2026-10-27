const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

const root = path.resolve(__dirname, '../../apps/portal/src')
const modules = new Map()
function load(file) {
  if (modules.has(file)) return modules.get(file)
  const exports = {}
  modules.set(file, exports)
  const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  vm.runInNewContext(code, { exports, require: (name) => load(path.resolve(path.dirname(file), `${name}.ts`)) })
  return exports
}
const { reduceConversationEvent } = load(path.join(root, 'domains/agent/conversationEventReducer.ts'))
const snapshot = () => ({
  id: 'conversation', messages: [], tool_invocations: [],
  agent_goals: [{ id: 'goal', status: 'paused', pause_reason: 'build_completion_review',
    steps: [{ id: 'investigation', status: 'completed', phase: 'acting' }] }],
})
const event = (changes = {}) => ({
  event_type: 'agent.goal.updated', entity_type: 'agent_goal', entity_id: 'goal',
  entity_version: 1, mutation_kind: 'replace', snapshot_hint: false,
  agent_goal_id: 'goal', payload: {}, patch: {}, ...changes,
})

for (const reason of ['structural_candidate_review', 'waiting_confirmation', 'user_interrupt']) {
  test(`replayed ${reason} cannot replace the loaded completion-review checkpoint`, () => {
    const current = snapshot()
    const replay = event({ payload: { agent_goal: { id: 'goal', status: 'paused', pause_reason: reason,
      steps: [{ id: 'investigation', status: 'blocked', phase: 'acting' }] } } })
    assert.equal(reduceConversationEvent(current, replay), current)
    assert.equal(current.agent_goals[0].pause_reason, 'build_completion_review')
    assert.equal(current.agent_goals[0].steps[0].status, 'completed')
  })
}
test('new goal events also request a fresh snapshot rather than installing event authority', () => {
  const current = snapshot()
  assert.equal(reduceConversationEvent(current, event({ entity_id: 'new-goal',
    payload: { agent_goal: { id: 'new-goal', status: 'paused', pause_reason: 'waiting_confirmation' } } })), current)
  assert.equal(current.agent_goals.length, 1)
})
test('message tokens still render incrementally while goals are revalidated', () => {
  const current = snapshot()
  current.messages.push({ id: 'reply', stream_id: 'stream', status: 'streaming', sequence_max: 0,
    blocks: [{ type: 'text', text: 'Hello' }] })
  const delta = event({ event_type: 'conversation.message.delta', entity_type: 'conversation_message',
    payload: { message_id: 'reply', stream_id: 'stream', sequence: 1, delta: ' world' } })
  const next = reduceConversationEvent(current, delta)
  assert.notEqual(next, current)
  assert.equal(next.messages[0].blocks[0].text, 'Hello world')
  assert.equal(next.messages[0].sequence_max, 1)
  assert.equal(next.agent_goals, current.agent_goals)
  assert.equal(reduceConversationEvent(next, delta), next)
})
test('step detail events remain incremental without replacing the pause checkpoint', () => {
  const current = snapshot()
  const next = reduceConversationEvent(current, event({ event_type: 'agent.step.thinking.delta',
    entity_type: 'agent_step', patch: { agent_step: { ...current.agent_goals[0].steps[0], reasoning: 'Evidence read' } } }))
  assert.equal(next.agent_goals[0].steps[0].reasoning, 'Evidence read')
  assert.equal(next.agent_goals[0].pause_reason, 'build_completion_review')
})
test('an old complete step snapshot cannot restore a blocked command or its input', () => {
  const current = snapshot()
  const next = reduceConversationEvent(current, event({ event_type: 'agent.step.updated', entity_type: 'agent_step',
    patch: { agent_step: { id: 'investigation', status: 'blocked', phase: 'acting',
      tool_invocation_id: 'old-command', tool_input_payload: { confirmed_by_user: true } } } }))
  assert.equal(next, current)
  assert.equal(next.agent_goals[0].steps[0].status, 'completed')
})
for (const [kind, field] of [['thinking', 'reasoning'], ['observation', 'observation_summary'], ['decision', 'decision_rationale']]) {
  test(`${kind} text updates cannot change confirmation-relevant fields or regress archived text`, () => {
    const current = snapshot()
    const step = current.agent_goals[0].steps[0]
    Object.assign(step, { [field]: 'Saved', tool_invocation_id: 'current-command', tool_input_payload: { pin: 'fixed' } })
    const update = (text) => event({ event_type: `agent.step.${kind}.delta`, entity_type: 'agent_step',
      patch: { agent_step: { ...step, [field]: text, status: 'blocked', tool_invocation_id: 'old-command',
        tool_input_payload: { pin: 'wrong' } } } })
    const next = reduceConversationEvent(current, update('Saved evidence'))
    const changed = next.agent_goals[0].steps[0]
    assert.equal(changed[field], 'Saved evidence')
    assert.equal(changed.status, 'completed')
    assert.equal(changed.tool_invocation_id, step.tool_invocation_id)
    assert.equal(changed.tool_input_payload, step.tool_input_payload)
    assert.equal(reduceConversationEvent(next, update('Saved')), next)
    assert.equal(reduceConversationEvent(next, update('Unrelated')), next)
  })
}
