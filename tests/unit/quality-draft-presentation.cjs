const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

function load(file, require) {
  const sandbox = { exports: {}, require }
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.resolve(__dirname, file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText, sandbox)
  return sandbox.exports
}
const messages = load('../../apps/portal/src/shared/i18n/messages.ts', () => { throw new Error('Unexpected translation dependency') })
function render(statuses, locale = 'en') {
  const jsx = (type, props) => typeof type === 'function' ? type(props) : ({ type, props })
  const draftNotice = load('../../apps/portal/src/routes/project-overview/components/quality-asset/QualityDraftNotice.tsx', (name) => {
    if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx }
    if (name === '../../../../shared/i18n/I18nProvider') return { useI18n: () => ({ t: (value) => locale === 'zh' ? messages.zhCN[value] : value }) }
    throw new Error(`Unexpected dependency ${name}`)
  })
  const component = load('../../apps/portal/src/routes/project-overview/components/QualityAssetPanel.tsx', (name) => {
    if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx }
    if (name === './quality-asset/QualityDraftNotice') return draftNotice
    if (name.startsWith('./quality-asset/')) return { [name.split('/').at(-1)]: 'child' }
    throw new Error(`Unexpected dependency ${name}`)
  })
  return component.QualityAssetPanel({ model: { header: {}, lanes: statuses.map((status) => ({ status })) } })
}
function notice(tree) {
  return tree.props.children.find((node) => node?.props?.['data-testid'] === 'quality-draft-notice')
}
for (const status of ['draft', 'ready_for_review']) {
  for (const locale of ['en', 'zh']) test(`${locale} ${status} does not present generation as approval or verified coverage`, () => {
    const note = notice(render([status], locale))
    assert.equal(note.props.role, 'note')
    assert.match(note.props.children, locale === 'zh' ? /尚未经过批准.*独立审阅.*执行证据/ : /not approved assets.*Independent review.*execution evidence/)
  })
}
test('known terminal lanes and empty inventories do not invent pending review', () => {
  assert.equal(notice(render(['approved', 'completed', 'blocked'])), undefined)
  assert.equal(notice(render([])), undefined)
})
test('Chinese generation inventories and release blockers preserve actual values and unknown IDs', () => {
  const tx = messages.translateDynamicZhCN
  assert.equal(tx('Generated 7 structured test cases.'), '已生成 7 个结构化测试用例草稿。')
  assert.equal(tx('Generated 3 risk-based test scenarios.'), '已生成 3 个基于风险的测试场景草稿。')
  assert.equal(tx('Generated 2 verification priorities and 4 execution allocations.'), '验证计划草稿包含 2 项验证优先级和 4 项执行安排。')
  assert.equal(tx('Generated 1 reviewable Playwright automation script(s).'), '已生成 1 份待审阅的 Playwright 自动化脚本草稿。')
  assert.equal(tx('Generated a traceable change document with 2 source delta(s) and 1 risk item(s).'), '已生成可追溯的变更记录草稿，包含 2 项来源变化和 1 项风险。')
  assert.equal(tx('Required quality assets are not approved: automation_blueprint, case_set, scenario_set, future_kind'),
    '必需的质量资产尚未经过批准：自动化方案、测试用例、测试场景、future_kind')
})
