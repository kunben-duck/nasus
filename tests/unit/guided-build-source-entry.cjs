const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

function fixture({ status = 'completed', failAt, turnStatus = 'delegated', result = {
  agent_goal: { id: 'goal', project_id: 'project', conversation_id: 'conversation', goal_template: 'system_image_build' },
} } = {}) {
  const calls = []
  const directory = path.resolve(__dirname, '../../apps/portal/src/domains/platform/tool-actions')
  const load = (name) => {
    const context = { exports: {}, require: (dependency) => {
      if (dependency === '../../agent/api') return { agentApi: {
        ensureConversation: async (...args) => { calls.push(['conversation', ...args]); return { id: 'conversation' } },
        postMessage: async (...args) => { calls.push(['message', ...args]); return { turn_id: 'turn' } },
      } }
      if (dependency === '../../agent/conversationTurns') return { waitForConversationTurn: async (...args) => {
        calls.push(['wait', ...args]); return { status: turnStatus, result }
      } }
      if (dependency === '../api') return { platformApi: { invokeTool: async (command) => {
        calls.push(['tool', command])
        if (command.tool_id === failAt) throw new Error('Unknown command outcome')
        return { status }
      } } }
      if (dependency.startsWith('./')) return load(dependency.slice(2))
      throw new Error('Unexpected dependency ' + dependency)
    } }
    vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(directory, name + '.ts'), 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText, context)
    return context.exports
  }
  return { calls, api: load('projectActionExecutor'), commands: load('studioActionCommand'), sourcePlan: load('systemImageSourcePlan') }
}

test('an explicit Git ref is passed only to the code source canonical registration', async () => {
  const v = fixture()
  await v.api.executeSystemImageSourceActionPlan({ id: 'project' },
    { code: ' https://example.com/repo.git ', codeRef: ' refs/heads/release ', usDoc: '/us', testAsset: '/tests' })
  const registration = v.calls.find((call) => call[0] === 'tool')[1]
  assert.equal(registration.input.source_specs[0].tracked_ref, 'refs/heads/release')
  assert.equal(registration.input.source_specs[0].source_uri, 'https://example.com/repo.git')
  assert.ok(registration.input.source_specs.slice(1).every((source) => !Object.hasOwn(source, 'tracked_ref')))
})

for (const ref of [undefined, '', ' ']) {
  test(`a ${JSON.stringify(ref)} Git ref preserves the legacy registration payload`, () => {
    const v = fixture()
    const sources = v.sourcePlan.buildSystemImageSourceActionPlan('project',
      { code: '/code', codeRef: ref, usDoc: '', testAsset: '' })[0].input.source_specs
    assert.equal(sources.length, 1)
    assert.ok(!Object.hasOwn(sources[0], 'tracked_ref'))
  })
}

for (const locale of ['en', 'zh']) {
  test(`the ${locale} missing-code goal message preserves an explicit ref without changing optional sources`, () => {
    const message = fixture().sourcePlan.buildSystemImageSourceBindingMessage(
      { code: ' https://example.com/repo.git ', codeRef: ' refs/tags/v1 ', usDoc: '/us', testAsset: '/tests' }, locale)
    assert.ok(message.includes('tracked_ref=refs/tags/v1'))
    assert.ok(message.includes('https://example.com/repo.git'))
    assert.ok(message.includes('/us') && message.includes('/tests'))
    assert.equal(message.split('tracked_ref=').length, 2)
  })
}

function defaults(systemImage) {
  const source = path.resolve(__dirname, '../../apps/portal/src/routes/project-overview/components/sourceBindingDefaults.ts')
  const context = { exports: {} }
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(source, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, context)
  return JSON.parse(JSON.stringify(context.exports.sourceBindingDefaults(systemImage)))
}

test('saved tracked source defaults restore its ref and never borrow one from another code source', () => {
  const sources = [
    { source_type: 'code', source_uri: 'https://example.com/first.git', tracked_ref: 'refs/heads/release',
      content_hash: 'hash', evidence_refs: [], ingestion_status: 'indexed' },
    { source_type: 'code', source_uri: 'https://example.com/other.git', tracked_ref: 'refs/tags/other',
      content_hash: 'hash', evidence_refs: [], ingestion_status: 'indexed' },
  ]
  assert.deepEqual(defaults({ sources }), { code: sources[0].source_uri, codeRef: sources[0].tracked_ref, usDoc: '', testAsset: '' })
})

test('legacy defaults do not invent a ref or silently select another source branch', () => {
  assert.deepEqual(defaults(), { code: '', usDoc: '', testAsset: '' })
  assert.deepEqual(defaults({ sources: [{ source_type: 'code', source_uri: '/old', content_hash: 'hash',
    evidence_refs: [], ingestion_status: 'indexed' }] }), { code: '/old', usDoc: '', testAsset: '' })
})

for (const [locale, message] of [['en', 'Build the system image for this project.'], ['zh', '构建当前项目的系统画像。']]) {
  test(`guided ${locale} source entry captures first, then uses the shared fixed-input goal without publication`, async () => {
    const v = fixture()
    await v.api.executeSystemImageSourceActionPlan({ id: 'project', name: 'Project' },
      { code: '/code', usDoc: '/requirements', testAsset: '/tests' }, locale)
    const tools = v.calls.filter((call) => call[0] === 'tool').map((call) => call[1])
    assert.deepEqual(tools.map((command) => command.tool_id), ['system_image.sources.register', 'system_image.sources.ingest'])
    assert.equal(tools[0].input.source_specs.length, 3)
    assert.ok(tools.every((command) => command.conversation_id === 'conversation' && command.input.project_id === 'project'))
    assert.equal(v.calls[3][0], 'message')
    assert.equal(v.calls[3][1], 'conversation')
    assert.equal(v.calls[3][2], message)
    assert.equal(v.calls[3][3].canonicalActionId, 'system-image.build-goal')
    assert.deepEqual(v.calls.filter((call) => call[0] === 'wait').map((call) => call.slice(1)), [['conversation', 'turn']])
    const card = v.commands.buildStudioActionCommand('system-image.build-goal', { projectId: 'project' }, locale)
    assert.equal(card.content, message)
  })
}

test('code-only preparation does not invent optional sources', async () => {
  const v = fixture()
  await v.api.executeSystemImageSourceActionPlan({ id: 'project', name: 'Project' }, { code: ' /code ', usDoc: '', testAsset: '' })
  const registration = v.calls.find((call) => call[0] === 'tool')[1]
  assert.equal(registration.input.source_specs.length, 1)
  assert.equal(registration.input.source_specs[0].source_uri, '/code')
})

test('missing mandatory code has no conversation or tool side effect', async () => {
  const v = fixture()
  await assert.rejects(v.api.executeSystemImageSourceActionPlan({ id: 'project' }, { code: ' ', usDoc: '/us', testAsset: '' }))
  assert.deepEqual(v.calls, [])
})

for (const status of ['failed', 'waiting_confirmation', 'running', undefined]) {
  test(`a ${status} source command cannot start ingestion, create a goal or imply consent`, async () => {
    const v = fixture({ status: status === undefined ? null : status })
    await assert.rejects(v.api.executeSystemImageSourceActionPlan({ id: 'project' }, { code: '/code', usDoc: '', testAsset: '' }))
    assert.equal(v.calls.filter((call) => call[0] === 'tool').length, 1)
    assert.equal(v.calls.filter((call) => call[0] === 'message').length, 0)
  })
}

for (const tool of ['system_image.sources.register', 'system_image.sources.ingest']) {
  test(`a lost ${tool} acknowledgement is not resubmitted or followed by a build`, async () => {
    const v = fixture({ failAt: tool })
    await assert.rejects(v.api.executeSystemImageSourceActionPlan({ id: 'project' }, { code: '/code', usDoc: '', testAsset: '' }), /Unknown command outcome/)
    assert.equal(v.calls.filter((call) => call[0] === 'tool' && call[1].tool_id === tool).length, 1)
    assert.equal(v.calls.filter((call) => call[0] === 'message').length, 0)
  })
}

for (const turnStatus of ['failed', 'interrupted']) {
  test(`a ${turnStatus} build turn is not reported as successful or retried`, async () => {
    const v = fixture({ turnStatus })
    await assert.rejects(v.api.executeSystemImageSourceActionPlan({ id: 'project' }, { code: '/code', usDoc: '', testAsset: '' }))
    assert.equal(v.calls.filter((call) => call[0] === 'message').length, 1)
  })
}

for (const mismatch of ['clarification', 'missing', 'project', 'conversation', 'template', 'id']) {
  test(`a ${mismatch} build receipt cannot report successful preparation or submit another message`, async () => {
    const goal = { id: 'goal', project_id: 'project', conversation_id: 'conversation', goal_template: 'system_image_build' }
    if (mismatch === 'project') goal.project_id = 'other'
    if (mismatch === 'conversation') goal.conversation_id = 'other'
    if (mismatch === 'template') goal.goal_template = 'quality_loop'
    if (mismatch === 'id') goal.id = ''
    const result = mismatch === 'clarification' ? { clarification: { question: 'Select a target' } }
      : mismatch === 'missing' ? {} : { agent_goal: goal }
    const v = fixture({ result, turnStatus: 'completed' })
    await assert.rejects(v.api.executeSystemImageSourceActionPlan({ id: 'project' }, { code: '/code', usDoc: '', testAsset: '' }), /goal could not be verified/)
    assert.equal(v.calls.filter((call) => call[0] === 'message').length, 1)
    assert.equal(v.calls.filter((call) => call[0] === 'tool').length, 2)
  })
}
