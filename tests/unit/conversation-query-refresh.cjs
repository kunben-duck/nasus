const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

function fixture({ alreadyReading = false, canRefresh = () => true } = {}) {
  let now = 0, timerId = 0
  const timers = new Map(), reads = [], queries = new Map()
  const matches = (query, filter) => filter.queryKey.every((part, index) =>
    JSON.stringify(part) === JSON.stringify(query.queryKey[index]))
    && (!filter.predicate || filter.predicate(query))
  const startRead = (queryKey) => {
    const query = { queryKey, queryHash: JSON.stringify(queryKey), promise: {},
      state: { status: 'pending', fetchStatus: 'fetching', dataUpdateCount: 0, errorUpdateCount: 0 } }
    queries.set(query.queryHash, query)
    return { query, complete(error = false) {
      query.state.fetchStatus = 'idle'
      query.state.status = error ? 'error' : 'success'
      query.state[error ? 'errorUpdateCount' : 'dataUpdateCount'] += 1
    } }
  }
  const file = path.resolve(__dirname, '../../apps/portal/src/domains/agent/conversationQueryRefresh.ts')
  const context = { exports: {},
    setTimeout: (fn, ms) => { timers.set(++timerId, { fn, at: now + ms }); return timerId },
    clearTimeout: (id) => timers.delete(id),
  }
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, context)
  const client = {
    isFetching: () => alreadyReading || [...queries.values()].some((query) => query.state.fetchStatus === 'fetching') ? 1 : 0,
    getQueryCache: () => ({ findAll: (filter) => {
      if (alreadyReading && !queries.size) startRead(Array.from(filter.queryKey))
      return [...queries.values()].filter((query) => matches(query, filter)
        && (!filter.fetchStatus || query.state.fetchStatus === filter.fetchStatus))
    } }),
    invalidateQueries: (filter, options) => new Promise((resolve, reject) => {
      assert.equal(options.cancelRefetch, false)
      reads.push({ key: Array.from(filter.queryKey), matches: (key) => matches(queries.get(JSON.stringify(key)), filter),
        filter, resolve, reject })
    }),
  }
  const create = context.exports.createConversationQueryRefresh
  const queue = create(client, canRefresh)
  const settle = () => new Promise((resolve) => setImmediate(resolve))
  return { queue, reads, timers, startRead, forRealClient: (value) => create(value),
    mountEvents({ canRefreshDomainQueries, existingOnly = false, domainEvents = false, nativeDomainEvents = false } = {}) {
      let source, cleanup, snapshot = { tokens: '' }
      const hookFile = path.resolve(__dirname, '../../apps/portal/src/domains/agent/useConversationEvents.ts')
      const hookContext = { ...context, exports: {}, EventSource: class {
        constructor() { this.listeners = new Map(); source = this }
        addEventListener(name, handler) { this.listeners.set(name, handler) }
        close() { this.closed = true }
      }, require: (name) => {
        if (name === 'react') return { useRef: (value) => ({ current: value }), useEffect: (effect) => { cleanup = effect() } }
        if (name === '@tanstack/react-query') return { useQueryClient: () => ({ ...client,
          setQueryData: (_, update) => { snapshot = update(snapshot) },
        }) }
        if (name === '../platform/authTokenStorage') return { platformApiAuthToken: () => null }
        if (name === './conversationQueryRefresh') return { createConversationQueryRefresh: create }
        if (name === './eventQueryInvalidation') {
          if (!nativeDomainEvents) return { shouldInvalidateDomainQueries: () => domainEvents }
          const policy = { exports: {} }
          vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.resolve(__dirname,
            '../../apps/portal/src/domains/agent/eventQueryInvalidation.ts'), 'utf8'), {
            compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
          }).outputText, policy)
          return policy.exports
        }
        if (name === './conversationEventReducer') return { reduceConversationEvent: (current, event) =>
          event.event_type.endsWith('.delta') ? { tokens: current.tokens + event.payload.delta } : current }
        throw new Error(`Unexpected dependency ${name}`)
      } }
      vm.runInNewContext(ts.transpileModule(fs.readFileSync(hookFile, 'utf8'), {
        compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
      }).outputText, hookContext)
      hookContext.exports.useConversationEvents({ conversationId: 'original', enabled: true, existingOnly,
        canReadWorkspace: canRefreshDomainQueries })
      return { source, cleanup, snapshot: () => snapshot,
        emit(event) { source.listeners.get(event.event_type)({ data: JSON.stringify(event) }) },
      }
    },
    async advance(ms) {
      const end = now + ms
      for (;;) {
        const entry = [...timers].filter(([, value]) => value.at <= end).sort((a, b) => a[1].at - b[1].at)[0]
        if (!entry) break
        now = entry[1].at; timers.delete(entry[0]); entry[1].fn(); await settle()
      }
      now = end; await settle()
    },
    async finish(index, error) {
      alreadyReading = false
      for (const query of queries.values()) {
        if (!matches(query, reads[index].filter)) continue
        query.state.fetchStatus = 'idle'
        query.state.status = error ? 'error' : 'success'
        query.state[error ? 'errorUpdateCount' : 'dataUpdateCount'] += 1
      }
      if (error) reads[index].reject(error)
      else reads[index].resolve()
      await settle()
    },
  }
}

const scriptEvents = ['quality.automation.call_reserved', 'quality.automation.reply_archived',
  'quality.automation.draft_saved', 'quality.automation.script_reviewed', 'quality.test_design_cases.reviewed']
for (const eventType of scriptEvents) {
  test(`native ${eventType} revalidates its exact private queries without a snapshot hint`, async () => {
    const v = fixture(), hook = v.mountEvents({ nativeDomainEvents: true })
    const key = eventType === 'quality.test_design_cases.reviewed' ? ['test-design-case-approvals', 'project']
      : eventType.endsWith('script_reviewed') ? ['automation-script-reviews', 'project', 'original-script'] : ['automation-script-revisions', 'project']
    const event = { event_id: 'script-event', entity_id: 'original-command', entity_type: 'tool_invocation',
      entity_version: 1, event_type: eventType, patch: {}, payload: {}, query_keys: [key], snapshot_hint: false }
    hook.emit(event)
    hook.emit(event)
    await v.advance(200)
    assert.deepEqual(v.reads.map((read) => read.key), [key, ['conversation', 'original']])
    hook.cleanup()
  })
}

test('case admission changes recheck mounted script and run plan consumers without writes', async () => {
  const v = fixture(), hook = v.mountEvents({ nativeDomainEvents: true })
  const event = { event_id: 'admission-event', entity_id: 'case-admission', entity_type: 'test_design_case_approval',
    entity_version: 1, event_type: 'quality.test_design_cases.reviewed', correlation_id: 'project',
    patch: { project_id: 'project', revision_id: 'case-admission', status: 'withdrawn' }, payload: {},
    query_keys: [['test-design-case-approvals', 'project']], snapshot_hint: true }
  hook.emit(event); hook.emit(event)
  await v.advance(200)
  assert.deepEqual(v.reads.map((read) => read.key), [['test-design-case-approvals', 'project'],
    ['automation-script-revisions', 'project'], ['automation-script-reviews', 'project'], ['run-plans', 'project'], ['conversation', 'original']])
  hook.cleanup()
})

for (const mode of ['existing-only', 'revoked-workspace', 'navigation']) {
  test(`native script events cannot refresh private domain queries after ${mode}`, async () => {
    let current = mode !== 'revoked-workspace'
    const v = fixture(), hook = v.mountEvents({ nativeDomainEvents: true, existingOnly: mode === 'existing-only',
      canRefreshDomainQueries: () => current })
    for (const [index, eventType] of scriptEvents.entries()) hook.emit({ event_id: `script-${index}`,
      entity_id: 'original-command', entity_type: 'tool_invocation', entity_version: index + 1,
      event_type: eventType, patch: {}, payload: {}, snapshot_hint: false,
      query_keys: [['automation-script-revisions', 'project'], ['automation-script-reviews', 'project', 'original-script']] })
    current = false
    await v.advance(200)
    assert.deepEqual(v.reads.map((read) => read.key), [['conversation', 'original']])
    hook.cleanup()
  })
}

test('a large historical replay is coalesced into one uncancelled snapshot read', async () => {
  const v = fixture()
  for (let i = 0; i < 5000; i++) v.queue.schedule(['conversation', 'original'])
  assert.equal(v.timers.size, 1)
  await v.advance(199)
  assert.equal(v.reads.length, 0)
  await v.advance(1)
  assert.equal(v.reads.length, 1)
  assert.deepEqual(v.reads[0].key, ['conversation', 'original'])
  await v.finish(0)
  await v.advance(1000)
  assert.equal(v.reads.length, 1)
})

test('a route change drops pending domain refreshes but keeps the original conversation snapshot', async () => {
  let current = true
  const v = fixture({ canRefresh: (key) => key[0] === 'conversation' || current })
  v.queue.schedule(['system-image', 'project'])
  v.queue.schedule(['conversation', 'original'])
  current = false
  await v.advance(200)
  assert.deepEqual(v.reads.map((read) => read.key), [['conversation', 'original']])
  await v.finish(0)
  v.queue.schedule(['system-image', 'project'])
  await v.advance(1000)
  assert.equal(v.reads.length, 1)
})

test('a route change during an in-flight read prevents the queued second domain refresh', async () => {
  let current = true
  const v = fixture({ alreadyReading: true, canRefresh: () => current })
  v.queue.schedule(['system-image', 'project'])
  await v.advance(200)
  assert.equal(v.reads.length, 1)
  current = false
  await v.finish(0)
  await v.advance(1000)
  assert.equal(v.reads.length, 1)
})

test('the actual SSE hook does not revalidate domain data after review navigation', async () => {
  let current = true
  const v = fixture(), hook = v.mountEvents({ canRefreshDomainQueries: () => current, domainEvents: true })
  const event = (version) => ({ event_id: `event-${version}`, entity_id: 'goal', entity_type: 'agent_goal',
    entity_version: version, event_type: 'agent.goal.updated', payload: {},
    query_keys: [['system-image', 'project']], snapshot_hint: true })
  hook.emit(event(1))
  current = false
  await v.advance(200)
  assert.deepEqual(v.reads.map((read) => read.key), [['conversation', 'original']])
  await v.finish(0)
  hook.emit(event(2))
  await v.advance(200)
  assert.deepEqual(v.reads.map((read) => read.key), [['conversation', 'original'], ['conversation', 'original']])
  await v.finish(1)
  hook.cleanup()
})

test('an existing-only review never invalidates workspace queries even without a route guard', async () => {
  const v = fixture(), hook = v.mountEvents({ existingOnly: true, domainEvents: true })
  hook.emit({ event_id: 'event', entity_id: 'goal', entity_type: 'agent_goal', entity_version: 1,
    event_type: 'agent.goal.updated', payload: {}, query_keys: [['system-image', 'project']], snapshot_hint: true })
  await v.advance(200)
  assert.deepEqual(v.reads.map((read) => read.key), [['conversation', 'original']])
  await v.finish(0)
  hook.cleanup()
})

test('continuous events cannot keep postponing the first refresh', async () => {
  const v = fixture()
  for (let i = 0; i < 4; i++) {
    v.queue.schedule(['conversation', 'original'])
    await v.advance(50)
  }
  assert.equal(v.reads.length, 1)
  await v.finish(0)
})

test('events during a slow read cause one subsequent fresh read, not cancellations', async () => {
  const v = fixture()
  v.queue.schedule(['conversation', 'original'])
  await v.advance(200)
  for (let i = 0; i < 1000; i++) v.queue.schedule(['conversation', 'original'])
  await v.advance(5000)
  assert.equal(v.reads.length, 1)
  assert.equal(v.timers.size, 0)
  await v.finish(0)
  await v.advance(200)
  assert.equal(v.reads.length, 2)
  await v.finish(1)
  await v.advance(5000)
  assert.equal(v.reads.length, 2)
})

test('an initial snapshot that predates the event is followed by a fresh read', async () => {
  const v = fixture({ alreadyReading: true })
  v.queue.schedule(['conversation', 'original'])
  await v.advance(200)
  await v.finish(0)
  assert.equal(v.reads.length, 2)
  await v.finish(1)
  await v.advance(1000)
  assert.equal(v.reads.length, 2)
})

test('a private read started after a queued event does not receive a redundant follow-up', async () => {
  const v = fixture()
  v.queue.schedule(['system-image', 'project'])
  v.startRead(['system-image', 'project', 'image-page', 'private', 'revision', { offset: 0 }])
  await v.advance(200)
  await v.finish(0)
  await v.advance(1000)
  assert.equal(v.reads.length, 1)
})

test('follow-up revalidation targets only the actual pre-event read, not later private readers', async () => {
  const v = fixture()
  const original = ['system-image', 'project', 'working', 'private']
  const later = ['system-image', 'project', 'image-page', 'private', 'revision', { offset: 3 }]
  v.startRead(original)
  v.queue.schedule(['system-image', 'project'])
  v.startRead(later)
  await v.advance(200)
  await v.finish(0)
  assert.equal(v.reads.length, 2)
  assert.equal(v.reads[1].matches(original), true)
  assert.equal(v.reads[1].matches(later), false)
  await v.finish(1)
})

test('an old read settled before the coalescing window needs only the new refresh', async () => {
  const v = fixture()
  const old = v.startRead(['system-image', 'project', 'working', 'private'])
  v.queue.schedule(['system-image', 'project'])
  old.complete()
  v.startRead(['system-image', 'project', 'image-page', 'private', 'revision', { offset: 0 }])
  await v.advance(200)
  await v.finish(0)
  await v.advance(1000)
  assert.equal(v.reads.length, 1)
})

test('live token cache updates cannot disguise a snapshot fetch that predates an event', async () => {
  const v = fixture()
  const old = v.startRead(['conversation', 'original'])
  v.queue.schedule(['conversation', 'original'])
  old.query.state.dataUpdateCount += 1
  await v.advance(200)
  await v.finish(0)
  assert.equal(v.reads.length, 2)
  await v.finish(1)
})

const { QueryClient, QueryObserver } = require('../../apps/portal/node_modules/@tanstack/query-core')
function observedRead(client, queryKey) {
  let calls = 0, release
  const first = new Promise((resolve, reject) => { release = { resolve, reject } })
  const observer = new QueryObserver(client, { queryKey, retry: false,
    queryFn: () => { calls += 1; return calls === 1 ? first : Promise.resolve('fresh') },
  })
  const unsubscribe = observer.subscribe(() => {})
  return { calls: () => calls, release, unsubscribe, queryKey }
}

test('real QueryClient follows up an older snapshot without refetching a later private page', async () => {
  const client = new QueryClient(), v = fixture(), queue = v.forRealClient(client)
  const early = observedRead(client, ['system-image', 'project', 'working', 'private'])
  queue.schedule(['system-image', 'project'])
  const late = observedRead(client, ['system-image', 'project', 'image-page', 'private', 'revision', { offset: 3 }])
  try {
    await v.advance(200)
    assert.equal(early.calls(), 1)
    assert.equal(late.calls(), 1)
    early.release.resolve('old snapshot')
    late.release.resolve('current page')
    await v.advance(0)
    assert.equal(early.calls(), 2)
    assert.equal(late.calls(), 1)
    assert.equal(client.getQueryData(late.queryKey), 'current page')
  } finally { queue.close(); early.unsubscribe(); late.unsubscribe(); client.clear() }
})

test('real QueryClient does not retry denied content until a later event requests authorization again', async () => {
  const client = new QueryClient(), v = fixture(), queue = v.forRealClient(client)
  const denied = observedRead(client, ['system-image', 'project', 'working', 'private'])
  queue.schedule(['system-image', 'project'])
  try {
    await v.advance(200)
    denied.release.reject(new Error('Source access denied'))
    await v.advance(0)
    assert.equal(denied.calls(), 1)
    assert.equal(client.getQueryState(denied.queryKey).status, 'error')
    queue.schedule(['system-image', 'project'])
    await v.advance(200)
    assert.equal(denied.calls(), 2)
    assert.equal(client.getQueryData(denied.queryKey), 'fresh')
  } finally { queue.close(); denied.unsubscribe(); client.clear() }
})

test('real QueryClient cache updates during a fetch still require a post-event snapshot', async () => {
  const client = new QueryClient(), v = fixture(), queue = v.forRealClient(client)
  const old = observedRead(client, ['conversation', 'original'])
  queue.schedule(old.queryKey)
  try {
    client.setQueryData(old.queryKey, 'live token')
    await v.advance(200)
    assert.equal(old.calls(), 1)
    old.release.resolve('old snapshot')
    await v.advance(0)
    assert.equal(old.calls(), 2)
    assert.equal(client.getQueryData(old.queryKey), 'fresh')
  } finally { queue.close(); old.unsubscribe(); client.clear() }
})

test('a slow conversation does not block another project-scoped domain refresh', async () => {
  const v = fixture()
  v.queue.schedule(['conversation', 'original'])
  v.queue.schedule(['system-image', 'project'])
  await v.advance(200)
  assert.deepEqual(v.reads.map((read) => read.key), [['conversation', 'original'], ['system-image', 'project']])
  await v.finish(1)
  v.queue.schedule(['system-image', 'project'])
  await v.advance(200)
  assert.equal(v.reads.length, 3)
  await v.finish(2)
  await v.finish(0)
})

test('a failed read is not silently retried, but a new event can revalidate', async () => {
  const v = fixture()
  v.queue.schedule(['conversation', 'original'])
  await v.advance(200)
  await v.finish(0, new Error('Access denied'))
  await v.advance(1000)
  assert.equal(v.reads.length, 1)
  v.queue.schedule(['conversation', 'original'])
  await v.advance(200)
  assert.equal(v.reads.length, 2)
  await v.finish(1)
})

test('unmount discards pending replay and cannot schedule reads in a later session', async () => {
  const v = fixture()
  v.queue.schedule(['conversation', 'original'])
  v.queue.close()
  v.queue.schedule(['conversation', 'other'])
  await v.advance(1000)
  assert.equal(v.reads.length, 0)
})

test('unmount during an initial in-flight read prevents its follow-up read', async () => {
  const v = fixture({ alreadyReading: true })
  v.queue.schedule(['conversation', 'original'])
  await v.advance(200)
  v.queue.schedule(['conversation', 'original'])
  v.queue.close()
  await v.finish(0)
  await v.advance(1000)
  assert.equal(v.reads.length, 1)
  assert.equal(v.timers.size, 0)
})

test('the actual event hook coalesces replay while reducing new tokens immediately', async () => {
  const v = fixture(), hook = v.mountEvents()
  const event = (version) => ({ event_id: `event-${version}`, entity_id: 'goal', entity_type: 'agent_goal',
    entity_version: version, event_type: 'agent.goal.updated', payload: {}, query_keys: [], snapshot_hint: true })
  for (let i = 1; i <= 5000; i++) hook.emit(event(i))
  assert.equal(v.reads.length, 0)
  assert.equal(v.timers.size, 1)
  hook.emit({ event_id: 'delta', entity_id: 'reply', entity_type: 'conversation_message', entity_version: 1,
    event_type: 'conversation.message.delta', payload: { delta: 'Live token' }, query_keys: [], snapshot_hint: false })
  assert.equal(hook.snapshot().tokens, 'Live token')
  await v.advance(200)
  assert.equal(v.reads.length, 1)
  await v.finish(0)
  hook.emit(event(5000))
  await v.advance(1000)
  assert.equal(v.reads.length, 1)
  hook.source.onmessage()
  hook.cleanup()
  assert.equal(hook.source.closed, true)
  await v.advance(1000)
  assert.equal(v.reads.length, 1)
})
