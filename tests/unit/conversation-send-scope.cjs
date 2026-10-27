const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

function load(name, dependencies, globals = {}) {
  const file = path.resolve(__dirname, '../../apps/portal/src', name)
  const context = { exports: {}, ...globals, require: (name) => {
    assert.ok(Object.hasOwn(dependencies, name), `Unexpected dependency ${name}`)
    return dependencies[name]
  } }
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, context)
  return context.exports
}

function conversationFixture({ id, failed = false, options = {} } = {}) {
  const calls = [], client = {}, mutation = { isPending: false,
    mutateAsync: async (input) => { calls.push(input); return { turn_id: 'turn', conversation_id: input.conversationId } } }
  const scope = load('shared/api/queryScope.ts', {})
  const sender = load('domains/agent/conversationMessageSender.ts', {
    '../../shared/api/queryScope': scope,
  }, { crypto: { randomUUID: () => 'original-key' } })
  const exported = load('domains/agent/useConversation.ts', {
    '@tanstack/react-query': { useQueryClient: () => client, useQuery: ({ queryKey }) => queryKey[0] === 'conversation-scope'
      ? { data: id ? { id } : undefined, isError: failed, isLoading: !id }
      : { data: undefined, isError: false, isLoading: false } },
    './api': { agentApi: {} }, './conversationScopeQuery': { readConversationScope: () => {} },
    './useConversationEvents': { useConversationEvents: () => {} },
    './useConversationTurn': { useConversationTurn: () => ({ mutation }) },
    './conversationMessageSender': sender,
  })
  return { calls, controller: exported.useConversation('project', 'project', 'Project', options) }
}

for (const specimen of [{}, { id: 'original', failed: true }, { id: 'original', options: { enabled: false } },
  { id: 'original', options: { existingOnly: true } }, { id: 'original', options: { canReadWorkspace: () => false } }]) {
  test(`unready or read-only conversation cannot send: ${JSON.stringify(specimen)}`, async () => {
    const value = conversationFixture(specimen)
    await assert.rejects(value.controller.sendMessage('Build the system image'), /not ready|no longer active/)
    assert.deepEqual(value.calls, [])
  })
}

test('a stale workspace handler rechecks its live route before any mutation', async () => {
  let current = true
  const value = conversationFixture({ id: 'original', options: { canReadWorkspace: () => current } })
  current = false
  await assert.rejects(value.controller.sendMessage('Build the system image'), /no longer active/)
  assert.deepEqual(value.calls, [])
})

test('a ready conversation fixes the target and canonical action in the send input', async () => {
  const value = conversationFixture({ id: 'original' })
  await value.controller.sendMessage('Build the system image', { canonicalActionId: 'system-image.build-goal' })
  assert.deepEqual(JSON.parse(JSON.stringify(value.calls)), [{ conversationId: 'original', content: 'Build the system image',
    idempotencyKey: 'original-key', canonicalActionId: 'system-image.build-goal' }])
})

test('turn cache and acknowledgement remain scoped to the sent conversation, not a later hook', async () => {
  let mutation
  const calls = [], snapshots = new Map([['original', { messages: [] }], ['later', { messages: [] }]])
  const exported = load('domains/agent/useConversationTurn.ts', {
    '@tanstack/react-query': { useMutation: (options) => { mutation = options; return {} } },
    './api': { agentApi: { postMessage: async (...args) => { calls.push(['post', ...args]); return {} } } },
    './conversationTurns': { waitForConversationTurn: async (...args) => calls.push(['wait', ...args]) },
  })
  const hook = exported.useConversationTurn({ conversationId: 'later', queryClient: {
    setQueryData: (key, update) => snapshots.set(key[1], update(snapshots.get(key[1]))),
    invalidateQueries: ({ queryKey }) => calls.push(['invalidate', ...Array.from(queryKey)]),
  } })
  const input = { conversationId: 'original', content: 'Build', idempotencyKey: 'key' }
  mutation.onMutate(input)
  await mutation.mutationFn(input)
  mutation.onSuccess({ conversation_id: 'original', turn_id: 'turn', user_message_id: 'message' }, input)
  assert.equal(snapshots.get('original').messages.length, 1)
  assert.equal(snapshots.get('original').active_turn.conversation_id, 'original')
  assert.deepEqual(snapshots.get('later'), { messages: [] })
  assert.equal(calls.length, 2)
  assert.deepEqual(calls[0].slice(0, 3), ['post', 'original', 'Build'])
  assert.deepEqual({ ...calls[0][3] }, { idempotencyKey: 'key', canonicalActionId: undefined })
  assert.deepEqual(calls[1], ['invalidate', 'conversation', 'original'])
  await hook.waitForTurn('later-turn')
  assert.deepEqual(calls.at(-1), ['wait', 'later', 'later-turn', 1800000])
})
