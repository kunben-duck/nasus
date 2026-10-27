const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')
const jsx = require('../../apps/portal/node_modules/react/jsx-runtime')

function gate({ disabled = false, tool = 'system_image.links.propose_references' } = {}) {
  const source = fs.readFileSync(path.resolve(__dirname,
    '../../apps/portal/src/routes/project-overview/components/ConfirmationGates.tsx'), 'utf8')
  const calls = []
  let finish
  const held = new Promise((resolve) => { finish = resolve })
  const context = { exports: {}, require: (name) => {
    if (name === 'react') return { useRef: (value) => ({ current: value }), useState: (value) => [value, () => {}] }
    if (name === 'react/jsx-runtime') return jsx
    if (name === 'react-router-dom') return { Link: 'a' }
    if (name.endsWith('I18nProvider')) return { useI18n: () => ({ t: (value) => value, tx: (value) => value }) }
    if (name.endsWith('activePlanPhase')) return { activeGoalSteps: (goal) => goal.steps }
    if (name.endsWith('buildReviewHandoff')) return { buildReviewHref: () => undefined }
    throw new Error(`Unexpected dependency ${name}`)
  } }
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText, context)
  const tree = context.exports.ConfirmationGates({ disabled, loading: false,
    pendingGoal: { id: 'goal', title: 'Fixed investigation', pause_reason: 'reference_candidate_review',
      steps: [{ phase: 'acting', status: 'blocked', selected_tool_id: tool, tool_invocation_id: 'proposal' }] },
    confirmPendingGoal: async () => { calls.push('resume-original-goal'); await held },
    continueStructuralInvestigation: async () => { calls.push('wrong-structural-consent') },
    confirmToolInvocation: () => { calls.push('wrong-command-confirmation') },
  })
  const nodes = []
  function walk(value) {
    if (Array.isArray(value)) return value.forEach(walk)
    if (!value || typeof value !== 'object') return
    nodes.push(value)
    walk(value.props?.children)
  }
  walk(tree)
  return { calls, finish, nodes, button: nodes.find((value) => value.props?.['data-testid'] === 'inspect-agent-reference-candidates') }
}

test('reference checkpoint shows inspection rather than high-risk consent or approval', () => {
  const value = gate()
  assert.equal(value.button.type, 'button')
  assert.equal(value.button.props.children, 'Inspect reference candidates')
  assert.ok(value.nodes.some((node) => node.props?.children === 'Reference candidates saved'))
  assert.ok(value.nodes.some((node) => node.props?.children ===
    'Continue this goal to inspect every reference candidate and gap. This does not accept relationships, approve requirements or prove test coverage.'))
  assert.ok(!value.nodes.some((node) => node.props?.children === 'Confirm and continue'))
  assert.deepEqual(value.calls, [])
})

test('duplicate inspection clicks only resume the original goal once', async () => {
  const value = gate()
  value.button.props.onClick()
  value.button.props.onClick()
  assert.deepEqual(value.calls, ['resume-original-goal'])
  value.finish()
  await new Promise((resolve) => setImmediate(resolve))
})

test('disabled reference inspection cannot dispatch a resume', () => {
  const value = gate({ disabled: true })
  assert.equal(value.button.props.disabled, true)
  value.button.props.onClick()
  assert.deepEqual(value.calls, [])
})

test('a mismatched blocked tool cannot use the reference inspection button', () => {
  const value = gate({ tool: 'system_image.links.review' })
  assert.equal(value.button, undefined)
  assert.deepEqual(value.calls, [])
})
