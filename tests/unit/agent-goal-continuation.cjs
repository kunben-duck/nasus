const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

const goal = (reason = 'structural_candidate_review') => ({
  id: 'original-goal', project_id: 'project', conversation_id: 'conversation', status: 'paused', pause_reason: reason,
  steps: [{ id: 'blocked-work', phase: 'acting', status: 'blocked', tool_invocation_id: 'original-command',
    selected_tool_id: reason === 'waiting_confirmation' ? 'system_image.build.investigate' : 'system_image.build.structure' }],
})
function fixture(current, { readError, resumeError } = {}) {
  const calls = []
  const source = fs.readFileSync(path.resolve(__dirname, '../../apps/portal/src/domains/agent/agentGoalCommands.ts'), 'utf8')
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  const context = { exports: {}, require: (name) => {
    if (name === './activePlanPhase') {
      const dependency = fs.readFileSync(path.resolve(__dirname, '../../apps/portal/src/domains/agent/activePlanPhase.ts'), 'utf8')
      const actual = { exports: {} }
      vm.runInNewContext(ts.transpileModule(dependency, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, actual)
      return actual.exports
    }
    assert.equal(name, './api')
    return { agentApi: {
      getAgentGoal: async (id) => { calls.push(['read', id]); if (readError) throw readError; return current },
      resumeAgentGoal: async (id, checkpoint) => { calls.push(['resume', id, checkpoint]); if (resumeError) throw resumeError; return current },
    } }
  } }
  vm.runInNewContext(code, context)
  return { ...context.exports, calls }
}

for (const reason of ['structural_candidate_review', 'waiting_confirmation']) {
  test(`${reason} checks the saved gate before resuming the original goal`, async () => {
    const expected = goal(reason), current = structuredClone(expected), value = fixture(current)
    assert.equal(await value.resumeAgentGoal(expected.id, expected), current)
    assert.deepEqual(value.calls, [['read', expected.id], ['resume', expected.id, expected]])
    assert.equal(value.calls[1][2], expected)
  })
}
for (const mismatch of ['expected_id', 'expected_status', 'id', 'status', 'project_id', 'conversation_id', 'pause_reason',
  'missing_blocked', 'extra_blocked', 'saved_missing_blocked', 'saved_extra_blocked', 'step_id', 'tool_id', 'command_id']) {
  test(`changed ${mismatch} rejects the old gate without issuing a resume`, async () => {
    const expected = goal(), current = structuredClone(expected)
    if (mismatch === 'expected_id') expected.id = 'foreign'
    else if (mismatch === 'expected_status') expected.status = 'running'
    else if (['id', 'status', 'project_id', 'conversation_id', 'pause_reason'].includes(mismatch)) current[mismatch] = 'changed'
    else if (mismatch === 'missing_blocked') current.steps = []
    else if (mismatch === 'extra_blocked') current.steps.push({ ...current.steps[0], id: 'second' })
    else if (mismatch === 'saved_missing_blocked') expected.steps = []
    else if (mismatch === 'saved_extra_blocked') expected.steps.push({ ...expected.steps[0], id: 'second' })
    else if (mismatch === 'step_id') current.steps[0].id = 'next-step'
    else if (mismatch === 'tool_id') current.steps[0].selected_tool_id = 'system_image.build.investigate'
    else current.steps[0].tool_invocation_id = 'next-command'
    const value = fixture(current)
    await assert.rejects(value.resumeAgentGoal('original-goal', expected), /checkpoint changed/)
    assert.deepEqual(value.calls, [['read', 'original-goal']])
  })
}
test('a denied checkpoint read never resumes with cached state', async () => {
  const denied = new Error('Access denied'), value = fixture(goal(), { readError: denied })
  await assert.rejects(value.resumeAgentGoal('original-goal', goal()), denied)
  assert.deepEqual(value.calls, [['read', 'original-goal']])
})
test('a lost acknowledgement does not automatically repeat a resume', async () => {
  const expected = goal(), lost = new Error('Response lost'), value = fixture(goal(), { resumeError: lost })
  await assert.rejects(value.resumeAgentGoal('original-goal', expected), lost)
  assert.deepEqual(value.calls, [['read', 'original-goal'], ['resume', 'original-goal', expected]])
})
test('one-argument callers read and send an explicit snapshot instead of an unpinned resume', async () => {
  const current = goal('user_interrupt'), value = fixture(current)
  assert.equal(await value.resumeAgentGoal('original-goal'), current)
  assert.deepEqual(value.calls, [['read', 'original-goal'], ['resume', 'original-goal', current]])
})
test('a refreshed budget or input must not replace the original user-visible precondition', async () => {
  const expected = goal(), current = structuredClone(expected)
  expected.max_steps = 20
  current.max_steps = 40
  current.steps[0].tool_input_payload = { changed_after_display: true }
  const value = fixture(current)
  await value.resumeAgentGoal(expected.id, expected)
  assert.equal(value.calls[1][2], expected)
  assert.equal(value.calls[1][2].max_steps, 20)
  assert.equal(value.calls[1][2].steps[0].tool_input_payload, undefined)
})

test('prepared phase resumes only its new work, not the old blocked structure', async () => {
  const expected = goal('build_plan_phase_prepared')
  expected.target_refs = ['build_plan:root', 'build_plan_phase:phase']
  expected.steps.push({ id: 'build_plan_phase:phase', status: 'completed' }, { id: 'new-work', status: 'pending', phase: 'acting' })
  const current = structuredClone(expected), value = fixture(current)
  await value.resumeAgentGoal(expected.id, expected)
  assert.deepEqual(value.calls, [['read', expected.id], ['resume', expected.id, expected]])
})
test('new authorization gate ignores historical blocked work while pinning the displayed active step', async () => {
  const expected = goal('waiting_confirmation')
  expected.target_refs = ['build_plan:root', 'build_plan_phase:phase']
  expected.steps.push({ id: 'build_plan_phase:phase', status: 'completed' }, { ...expected.steps[0], id: 'new-authorization',
    selected_tool_id: 'system_image.build.authorize', tool_invocation_id: 'new-command' })
  const value = fixture(structuredClone(expected))
  await value.resumeAgentGoal(expected.id, expected)
  assert.equal(value.calls[1][2], expected)
})
