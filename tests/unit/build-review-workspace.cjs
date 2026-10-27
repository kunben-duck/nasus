const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

function load(relative, modules) {
  const file = path.resolve(__dirname, '../../apps/portal/src', relative)
  const context = { exports: {}, URLSearchParams, require: (name) => {
    assert.ok(Object.hasOwn(modules, name), `Unexpected dependency: ${name}`)
    return modules[name]
  } }
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, context)
  return context.exports
}

const queryScope = load('shared/api/queryScope.ts', {})

function workspaceFixture() {
  const queries = [], project = { id: 'project', name: 'Original project' }
  const state = {
    project: { data: { project }, isLoading: false, isError: false },
    image: { data: { objects: ['cached-private-object'] }, isLoading: true, isError: true },
    release: { data: { release: 'cached-private-release' }, isLoading: true, isError: true },
  }
  const apiCalls = [], signals = []
  const { useProjectWorkspaceData } = load('domains/platform/useProjectWorkspaceData.ts', {
    '@tanstack/react-query': { useQuery: (options) => {
      queries.push(options)
      return state[options.queryKey[0] === 'system-image' ? 'image' : options.queryKey[0] === 'release-readiness' ? 'release' : 'project']
    } },
    '../quality-loop/api': { qualityLoopApi: {
      getProject: (id) => { apiCalls.push(['project', id]); return state.project.data },
      getReleaseReadiness: (id, signal) => { signals.push(signal); apiCalls.push(['release', id]); return state.release.data },
    } },
    '../system-image/api': { systemImageApi: { getSystemImage: (id, signal) => {
      signals.push(signal); apiCalls.push(['image', id]); return state.image.data
    } } },
    '../../shared/api/queryScope': queryScope,
  })
  return { queries, project, state, apiCalls, signals, read: useProjectWorkspaceData }
}

test('exact build review disables unrelated queries and hides their cached private data', () => {
  const v = workspaceFixture(), result = v.read('project', { reviewingBuild: true })
  assert.deepEqual(v.queries.map((query) => query.enabled), [true, false, false])
  assert.equal(result.project.id, 'project')
  assert.equal(result.systemImage, undefined)
  assert.equal(result.releaseReadiness, undefined)
  assert.equal(result.systemImageError, false)
  assert.equal(result.statusDependency.isLoading, false)
  assert.equal(result.statusDependency.isError, false)
  assert.deepEqual(v.apiCalls, [])
})

test('project authorization or loading still gates the read-only workspace', () => {
  const v = workspaceFixture()
  v.state.project.isLoading = true; v.state.project.isError = true
  const result = v.read('project', { reviewingBuild: true })
  assert.equal(result.statusDependency.isLoading, true)
  assert.equal(result.statusDependency.isError, true)
})

test('ordinary project navigation retains the full existing domain read contract', async () => {
  const v = workspaceFixture()
  v.state.image.isLoading = false; v.state.image.isError = false
  const result = v.read('project')
  assert.deepEqual(v.queries.map((query) => query.enabled), [true, true, true])
  const signal = new AbortController().signal
  for (const query of v.queries) await query.queryFn({ signal })
  assert.deepEqual(v.apiCalls, [['project', 'project'], ['image', 'project'], ['release', 'project']])
  assert.deepEqual(v.signals, [signal, signal])
  assert.equal(result.systemImage, v.state.image.data)
  assert.equal(result.releaseReadiness, v.state.release.data)
  assert.equal(result.statusDependency.isError, false)
})

test('old query callbacks cannot read an image or readiness after the route changes', async () => {
  const v = workspaceFixture()
  let current = true
  v.read('project', { canReadWorkspace: () => current })
  current = false
  for (const query of v.queries.slice(1)) await assert.rejects(query.queryFn({ signal: new AbortController().signal }), /no longer active/)
  assert.deepEqual(v.apiCalls, [])
})

test('a disabled review query cannot bypass the read boundary through manual refetch', async () => {
  const v = workspaceFixture(); v.read('project', { reviewingBuild: true })
  for (const query of v.queries.slice(1)) await assert.rejects(query.queryFn({ signal: new AbortController().signal }), /no longer active/)
  assert.deepEqual(v.apiCalls, [])
})

test('responses that arrive after leaving the workspace are not returned to its query cache', async () => {
  for (const index of [1, 2]) {
    const v = workspaceFixture()
    let current = true
    v.read('project', { canReadWorkspace: () => current })
    const reading = v.queries[index].queryFn({ signal: new AbortController().signal })
    current = false
    await assert.rejects(reading, /no longer active/)
    assert.equal(v.apiCalls.length, 1)
  }
})

test('a cancelled observer cannot start a new workspace read', async () => {
  const v = workspaceFixture(); v.read('project')
  const controller = new AbortController(); controller.abort()
  for (const query of v.queries.slice(1)) await assert.rejects(query.queryFn({ signal: controller.signal }), { name: 'AbortError' })
  assert.deepEqual(v.apiCalls, [])
})

test('workspace lifetime is scoped to the exact project and excludes even malformed review links', () => {
  const { isCurrentProjectWorkspace } = load('routes/project/useProjectRouteData.ts', {
    react: {}, 'react-router-dom': {}, '../../domains/platform/useProjectWorkspaceData': {},
  })
  const allows = (pathname, search = '') => isCurrentProjectWorkspace('project', { pathname, search })
  assert.equal(allows('/projects/project'), true)
  assert.equal(allows('/projects/project/knowledge'), true)
  assert.equal(allows('/projects/project/knowledge', '?image_revision=saved'), true)
  assert.equal(allows('/projects/project/knowledge', '?build_review_goal=goal'), false)
  assert.equal(allows('/projects/project/knowledge', '?build_review_invocation='), false)
  assert.equal(allows('/projects/project-extra/knowledge'), false)
  assert.equal(allows('/projects/other/knowledge'), false)
  assert.equal(allows('/dashboard'), false)
  assert.equal(isCurrentProjectWorkspace(null, { pathname: '/projects/project', search: '' }), false)
})

test('switching from ordinary knowledge into exact review hides the previous projection', () => {
  const v = workspaceFixture()
  v.state.image.isLoading = false; v.state.image.isError = false
  assert.ok(v.read('project').systemImage)
  assert.equal(v.read('project', { reviewingBuild: true }).systemImage, undefined)
})

function conversationFixture() {
  const calls = [], goal = { id: 'goal', status: 'paused' }
  const { useProjectConversationModel } = load('routes/project/useProjectConversationModel.ts', {
    react: { useMemo: (fn) => fn() },
    '../../domains/agent/useConversation': { useConversation: (...args) => {
      calls.push(['conversation', ...args])
      return { conversationId: 'original', conversation: { agent_goals: [goal] } }
    } },
    '../../domains/agent/useAgentGoalExplanation': { useAgentGoalExplanation: (...args) => {
      calls.push(['explanation', ...args]); return { data: undefined }
    } },
    '../../domains/agent/useAgentRuntimeDetails': { useAgentRuntimeDetails: (...args) => {
      calls.push(['runtime', ...args]); return { memoryContext: undefined, swarmRuns: [] }
    } },
    './projectRouteMessages': { toMessageRows: () => [], fallbackProjectMessages: () => [] },
    '../../shared/i18n/I18nProvider': { useI18n: () => ({ t: (value) => value }) },
  })
  return { calls, goal, read: (options) => useProjectConversationModel({ id: 'project', name: 'Original' }, options) }
}

test('read-only review keeps the original goal but disables memory, swarm and explanation reads', () => {
  const v = conversationFixture(), result = v.read({ existingOnly: true })
  assert.equal(result.latestProjectGoal, v.goal)
  assert.equal(result.pausedProjectGoal, v.goal)
  assert.equal(v.calls[0][4].existingOnly, true)
  assert.deepEqual(v.calls.slice(1), [['explanation', undefined, undefined], ['runtime', undefined, undefined, undefined]])
})

test('ordinary project conversation continues loading its original runtime details', () => {
  const v = conversationFixture(); v.read()
  assert.deepEqual(v.calls.slice(1), [['explanation', v.goal, undefined], ['runtime', 'original', v.goal, undefined]])
})

test('the route lifetime guard reaches conversation creation, explanation, memory and swarm hooks', () => {
  const canReadWorkspace = () => false, v = conversationFixture()
  v.read({ canReadWorkspace })
  assert.equal(v.calls[0][4].canReadWorkspace, canReadWorkspace)
  assert.equal(v.calls[1][2], canReadWorkspace)
  assert.equal(v.calls[2][3], canReadWorkspace)
})

for (const file of ['useAgentGoalExplanation', 'useAgentRuntimeDetails']) {
  test(`${file} checks the route before dispatch and before returning private data`, async () => {
    const queries = [], calls = []
    const module = load(`domains/agent/${file}.ts`, {
      '@tanstack/react-query': { useQuery: (options) => { queries.push(options); return {} } },
      './api': { agentApi: {
        getAgentGoalExplanation: () => { calls.push('explanation'); return {} },
        getAgentMemoryContext: () => { calls.push('memory'); return {} },
        listAgentSwarms: () => { calls.push('swarm'); return [] },
      } },
      '../../shared/api/queryScope': queryScope,
    })
    let current = true
    if (file === 'useAgentGoalExplanation') module[file]({ id: 'goal', status: 'paused' }, () => current)
    else module[file]('original', { id: 'goal' }, () => current)
    const signal = new AbortController().signal
    current = false
    for (const query of queries) await assert.rejects(query.queryFn({ signal }), /no longer active/)
    assert.deepEqual(calls, [])
    for (const query of queries) {
      current = true
      const reading = query.queryFn({ signal })
      current = false
      await assert.rejects(reading, /no longer active/)
    }
    assert.equal(calls.length, queries.length)
  })
}
