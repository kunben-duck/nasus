const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

function fixture(reason, { resumeError, refreshError, snapshotScope, workspaceError } = {}) {
  const calls = [], held = new Promise(() => {})
  const expected = { id: 'goal', conversation_id: 'conversation', project_id: 'project', pause_reason: reason }
  const current = { ...expected, pause_reason: 'waiting_confirmation' }
  const source = fs.readFileSync(path.resolve(__dirname, '../../apps/portal/src/routes/project/projectRouteActionHandlers.ts'), 'utf8')
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  const context = { exports: {}, require: (name) => {
    if (name.endsWith('agentGoalCommands')) return { resumeAgentGoal: async (id, pin) => {
      calls.push(['resume', id, pin]); if (resumeError) throw resumeError; return current
    } }
    if (name.endsWith('projectWorkspaceInvalidation')) return { invalidateProjectWorkspaceQueries: () => {
      calls.push(['workspace']); return workspaceError ? Promise.reject(workspaceError) : held
    } }
    if (name.endsWith('tool-actions')) return {}
    throw new Error(`Unexpected dependency ${name}`)
  } }
  vm.runInNewContext(code, context)
  let locked = false
  const handlers = context.exports.createProjectRouteActionHandlers({
    project: { id: 'project' }, pausedProjectGoal: expected, queryClient: {}, locale: 'en',
    projectConversation: { refreshConversation: async () => {
      calls.push(['checkpoint']); if (refreshError) throw refreshError
      return { id: 'conversation', project_id: 'project', agent_goals: [current], ...snapshotScope }
    } },
    projectActionLock: { runLockedAction: async (id, operation) => {
      assert.equal(locked, false); locked = true
      try { await operation() } finally { locked = false; calls.push(['unlocked']) }
    } },
  })
  return { expected, calls, handlers, isLocked: () => locked }
}

for (const [reason, handler] of [
  ['structural_candidate_review', 'continueStructuralInvestigation'], ['waiting_confirmation', 'confirmPendingGoal'],
  ['build_plan_phase_prepared', 'confirmPendingGoal'],
  ['reference_candidate_review', 'confirmPendingGoal'],
]) {
  test(`${handler} unlocks after a fresh checkpoint, without waiting on held workspace panels`, { timeout: 1000 }, async () => {
    const value = fixture(reason)
    await value.handlers[handler]()
    assert.equal(value.isLocked(), false)
    assert.deepEqual(value.calls, [['resume', 'goal', value.expected], ['checkpoint'], ['workspace'], ['unlocked']])
  })
  test(`${handler} recovers a lost acknowledgement with reads, never an automatic resume retry`, { timeout: 1000 }, async () => {
    const lost = new Error('Acknowledgement lost'), value = fixture(reason, { resumeError: lost })
    await assert.rejects(value.handlers[handler](), lost)
    assert.equal(value.isLocked(), false)
    assert.deepEqual(value.calls, [['resume', 'goal', value.expected], ['checkpoint'], ['workspace'], ['unlocked']])
  })
  test(`${handler} propagates a revoked checkpoint read instead of enabling cached controls`, { timeout: 1000 }, async () => {
    const denied = new Error('Access revoked'), value = fixture(reason, { refreshError: denied })
    await assert.rejects(value.handlers[handler](), denied)
    assert.equal(value.isLocked(), false)
    assert.deepEqual(value.calls, [['resume', 'goal', value.expected], ['checkpoint'], ['unlocked']])
  })
  for (const snapshotScope of [
    { id: 'another_conversation' }, { project_id: 'another_project' }, { agent_goals: [] },
    { agent_goals: [{ id: 'goal', conversation_id: 'another_conversation', project_id: 'project' }] },
    { agent_goals: [{ id: 'goal', conversation_id: 'conversation', project_id: 'another_project' }] },
  ]) {
    test(`${handler} rejects an unrelated or missing current goal`, { timeout: 1000 }, async () => {
      const value = fixture(reason, { snapshotScope })
      await assert.rejects(value.handlers[handler](), /checkpoint/)
      assert.deepEqual(value.calls, [['resume', 'goal', value.expected], ['checkpoint'], ['unlocked']])
    })
  }
  test(`${handler} lets auxiliary query caches report their own refresh failures`, async () => {
    const value = fixture(reason, { workspaceError: new Error('Panel unavailable') })
    await value.handlers[handler]()
    await new Promise((resolve) => setImmediate(resolve))
    assert.equal(value.isLocked(), false)
    assert.deepEqual(value.calls, [['resume', 'goal', value.expected], ['checkpoint'], ['workspace'], ['unlocked']])
  })
}

for (const reason of ['build_completion_review', 'missing_source_binding', 'user_interrupt']) {
  test(`confirmation handler does not resume ${reason} through the execution gate`, async () => {
    const value = fixture(reason)
    await value.handlers.confirmPendingGoal()
    assert.deepEqual(value.calls, [])
    assert.equal(value.isLocked(), false)
  })
}

function conversationHook(refetch, snapshot = {}) {
  const source = fs.readFileSync(path.resolve(__dirname, '../../apps/portal/src/domains/agent/useConversation.ts'), 'utf8')
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  let queries = 0
  function load(name, dependencies) {
    const file = path.resolve(__dirname, '../../apps/portal/src', name)
    const context = { exports: {}, require: (dependency) => {
      assert.ok(Object.hasOwn(dependencies, dependency), `Unexpected dependency ${dependency}`)
      return dependencies[dependency]
    } }
    vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText, context)
    return context.exports
  }
  const sender = load('domains/agent/conversationMessageSender.ts', {
    '../../shared/api/queryScope': load('shared/api/queryScope.ts', {}),
  })
  const context = { exports: {}, require: (name) => {
    if (name === '@tanstack/react-query') return { useQueryClient: () => ({}), useQuery: () =>
      queries++ === 0 ? { data: { id: 'conversation' } } : { refetch, ...snapshot } }
    if (name === './api') return { agentApi: {} }
    if (name === './conversationScopeQuery') return { readConversationScope: () => {} }
    if (name === './useConversationEvents') return { useConversationEvents: () => {} }
    if (name === './useConversationTurn') return { useConversationTurn: () => ({ mutation: { isPending: false } }) }
    if (name === './conversationMessageSender') return sender
    throw new Error(`Unexpected dependency ${name}`)
  } }
  vm.runInNewContext(code, context)
  return context.exports.useConversation('project', 'project', 'Project')
}

test('conversation checkpoint refresh returns fresh data with strict refetch error handling', async () => {
  const current = { id: 'conversation', project_id: 'project', agent_goals: [] }
  const hook = conversationHook(async (options) => {
    assert.equal(options.throwOnError, true)
    return { data: current }
  })
  assert.equal(await hook.refreshConversation(), current)
})

test('conversation checkpoint refresh never returns cached data after a denied refetch', async () => {
  const denied = new Error('Access revoked')
  const hook = conversationHook(async (options) => {
    if (options?.throwOnError) throw denied
    return { data: { id: 'conversation', agent_goals: [] }, error: denied }
  })
  await assert.rejects(hook.refreshConversation(), denied)
})

test('conversation query failure hides cached goal controls until a successful read', () => {
  const cached = { id: 'conversation', agent_goals: [{ id: 'goal', pause_reason: 'waiting_confirmation' }] }
  assert.equal(conversationHook(async () => {}, { data: cached, isError: true }).conversation, undefined)
  assert.equal(conversationHook(async () => {}, { data: cached, isError: false }).conversation, cached)
})
