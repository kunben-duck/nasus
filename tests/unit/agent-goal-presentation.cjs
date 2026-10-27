const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

const root = path.resolve(__dirname, '../../apps/portal/src')
function load(relative, overrides = {}) {
  const file = path.resolve(root, relative), context = { exports: {}, require: (name) => {
    if (Object.hasOwn(overrides, name)) return overrides[name]
    const dependency = path.resolve(path.dirname(file), name)
    return load(path.relative(root, `${dependency}.ts`), overrides)
  } }
  const source = fs.readFileSync(file, 'utf8')
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText, context)
  return context.exports
}
const messages = load('shared/i18n/messages.ts')
function translate(source) {
  return messages.zhCN[source] ?? messages.zhCN[source.toLowerCase().replaceAll('_', ' ')]
    ?? messages.translateDynamicZhCN(source) ?? source
}
function render(goal, explanation) {
  const jsx = (type, props) => ({ type, props })
  const { AgentGoalPanel } = load('routes/project-overview/components/AgentGoalPanel.tsx', {
    'react/jsx-runtime': { jsx, jsxs: jsx },
    '../../../shared/i18n/I18nProvider': { useI18n: () => ({ t: translate, tx: translate }) },
  })
  return AgentGoalPanel({ goal, explanation })
}
function find(node, id) {
  if (!node || typeof node !== 'object') return undefined
  if (Array.isArray(node)) return node.map((child) => find(child, id)).find(Boolean)
  return node.props?.['data-testid'] === id ? node : find(node.props?.children, id)
}
function text(node) {
  if (node == null || typeof node === 'boolean') return ''
  if (Array.isArray(node)) return node.map(text).join(' ')
  return typeof node === 'object' ? text(node.props?.children) : String(node)
}
function goal() {
  return { id: 'goal', title: 'Prepare a source-pinned system image', status: 'paused',
    summary: 'Waiting for captured code; optional requirements and tests can be added later.',
    steps: [], target_refs: [], query_keys: [], model_calls_used: 0, max_model_calls: 2,
    thinking_tokens_used: 0, max_thinking_tokens: 100, no_progress_observations: 0,
    max_no_progress_observations: 3 }
}
const guidance = [
  ['source_capture', 'Waiting for captured code', '等待采集代码',
    'Add and capture the required code sources, then continue this same goal. Requirements and tests are optional; confirm the structural budget separately after capture.'],
  ['candidate_review', 'Review the structural candidate', '审阅结构候选',
    'Review the saved structural candidate and its gaps, then continue this goal to prepare evidence investigation. Confirm the investigation budget separately; this does not publish the image.'],
  ['plan_phase_review', 'Review the new build phase', '核对新增构建阶段',
    "Review the new plan and its fixed sources, then continue the same goal. Confirm the new phase budget separately; the previous plan's consent does not authorize it."],
  ['completion_review', 'Review findings before publication', '发布前审阅调查结果',
    'Review the saved findings and remaining gaps. Publication requires an independent review and approval; investigation completion does not publish the image.'],
]
for (const [waitingOn, englishLabel, chineseLabel, action] of guidance) {
  test(`${waitingOn} renders localized state and preserves the independent consent boundary`, () => {
    const explanation = { waiting_on: waitingOn, next_action: action, phase: 'paused', reasoning_summary: '',
      tool_invocation_refs: [], memory_refs: [], audit_event_refs: [] }
    const content = text(find(render(goal(), explanation), 'agent-goal-explanation'))
    assert.ok(content.includes(chineseLabel), content)
    assert.ok(!content.includes(waitingOn.replaceAll('_', ' ')), content)
    assert.notEqual(translate(action), action)
    assert.equal(typeof messages.zhCN[englishLabel], 'string')
    assert.match(translate(action), /单独|独立/)
  })
}
test('captured-source waiting summary and status query reason are localized', () => {
  const content = text(render(goal()))
  assert.match(content, /准备构建系统画像/)
  assert.match(content, /等待采集代码/)
  assert.doesNotMatch(content, /Waiting for captured code/)
  assert.notEqual(translate('Read project status and retain the original target while code capture is missing.'),
    'Read project status and retain the original target while code capture is missing.')
})
for (const status of ['pending', 'running', 'blocked']) {
  test(`current ${status} phase never selects a historical blocked step`, () => {
    const value = goal()
    value.target_refs = ['build_plan_phase:new-phase']
    value.steps = [
      { id: 'old-step', title: 'Old blocked command', status: 'blocked', phase: 'acting', selected_tool_id: 'old.tool' },
      { id: 'build_plan_phase:new-phase', title: 'Phase marker', status: 'completed' },
      { id: 'new-step', title: 'New phase command', status, phase: 'acting', selected_tool_id: 'new.tool' },
    ]
    const content = text(find(render(value), 'agent-current-step'))
    assert.match(content, /New phase command/)
    assert.doesNotMatch(content, /Old blocked command/)
    assert.match(text(find(render(value), 'agent-loop-trace')), /old.tool/)
  })
}
test('an empty new phase does not show an old command as current', () => {
  const value = goal()
  value.target_refs = ['build_plan_phase:new-phase']
  value.steps = [{ id: 'old-step', title: 'Old blocked command', status: 'blocked', phase: 'acting' },
    { id: 'build_plan_phase:new-phase', title: 'Phase marker', status: 'completed' }]
  assert.equal(find(render(value), 'agent-current-step'), undefined)
})
test('a legacy goal without phase markers retains its latest active step selection', () => {
  const value = goal()
  value.steps = [{ id: 'old-step', title: 'Earlier blocker', status: 'blocked', phase: 'acting' },
    { id: 'latest-step', title: 'Latest blocker', status: 'blocked', phase: 'acting' }]
  assert.equal(find(render(value), 'agent-current-step').props['data-step-id'], 'latest-step')
})
for (const markers of [[], ['other-phase'], ['new-phase', 'new-phase']]) {
  test(`invalid phase markers ${JSON.stringify(markers)} hide current work without hiding history`, () => {
    const value = goal()
    value.target_refs = ['build_plan_phase:new-phase']
    value.steps = [{ id: 'old-step', title: 'Old blocked command', status: 'blocked', phase: 'acting', selected_tool_id: 'old.tool' },
      ...markers.map((id) => ({ id: `build_plan_phase:${id}`, title: 'Historical phase marker', status: 'completed' }))]
    const result = render(value)
    assert.equal(find(result, 'agent-current-step'), undefined)
    assert.match(text(find(result, 'agent-current-step-unverified')), /无法核验/)
    assert.match(text(find(result, 'agent-loop-trace')), /old.tool/)
  })
}
test('cancelled or completed goals retain history without presenting a command as current work', () => {
  for (const status of ['cancelled', 'completed']) {
    const value = goal()
    value.status = status
    value.steps = [{ id: 'old-step', title: 'Old blocked command', status: 'blocked', phase: 'acting', selected_tool_id: 'old.tool' }]
    assert.equal(find(render(value), 'agent-current-step'), undefined)
    assert.match(text(find(render(value), 'agent-loop-trace')), /old.tool/)
  }
})
