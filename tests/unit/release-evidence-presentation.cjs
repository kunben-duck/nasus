const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

const file = path.resolve(__dirname, '../../apps/portal/src/routes/project/sections/ReleaseReadinessSection.tsx')
function render(context) {
  const jsx = (type, props) => ({ type, props })
  const sandbox = { exports: {}, require: (name) => {
    if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx }
    if (name === './primitives/MetricCards') return { MetricCard: 'metric' }
    if (name === '../../../shared/i18n/I18nProvider') return { useI18n: () => ({ t: (value) => value, tx: (value) => value }) }
    throw new Error(`Unexpected dependency ${name}`)
  } }
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText, sandbox)
  return sandbox.exports.ReleaseReadinessSection({ context })
}
function nodes(node) {
  if (!node || typeof node !== 'object') return []
  if (Array.isArray(node)) return node.flatMap(nodes)
  return [node, ...nodes(node.props?.children)]
}
function metric(tree, label) {
  return nodes(tree).find((node) => node.type === 'metric' && node.props.label === label)?.props.value
}
function text(node) {
  if (node == null || typeof node === 'boolean') return ''
  if (Array.isArray(node)) return node.map(text).join(' ')
  return typeof node === 'object' ? text(node.props?.children) : String(node)
}
function context() {
  return { workspace: { approvals: [], quality_loop_state: { status: 'blocked', release_score: 25, blockers: ['Unknown quality evidence'] },
    release_decision: { status: 'ready', score: 90, rationale: 'Historical ready conclusion' } },
    releaseReadiness: { score: 25, blockers: 1, summary: 'Current quality evidence is unknown',
      evidence_summary: { quality_assessment_unknown: 1 } } }
}
test('current evidence takes precedence over a historical ready decision', () => {
  const tree = render(context())
  assert.equal(metric(tree, 'Status'), 'blocked')
  assert.equal(metric(tree, 'Score'), '25')
  assert.match(text(tree), /Current quality evidence is unknown/)
  assert.doesNotMatch(text(tree), /Historical ready conclusion/)
})
test('unknown current evidence cannot be hidden by a stale workflow status', () => {
  const value = context()
  value.workspace.quality_loop_state.status = 'ready_for_release'
  assert.equal(metric(render(value), 'Status'), 'blocked')
})
test('an unassessed release does not invent a zero score or reuse a historical score', () => {
  const value = context()
  delete value.releaseReadiness
  assert.equal(metric(render(value), 'Score'), 'Unknown')
})
test('a known current assessment keeps its real readiness score', () => {
  const value = context()
  value.workspace.quality_loop_state.status = 'ready_for_release'
  value.releaseReadiness = { score: 85, blockers: 0, summary: 'Current measured assessment', evidence_summary: {} }
  const tree = render(value)
  assert.equal(metric(tree, 'Status'), 'ready_for_release')
  assert.equal(metric(tree, 'Score'), '85')
  assert.match(text(tree), /Current measured assessment/)
})
