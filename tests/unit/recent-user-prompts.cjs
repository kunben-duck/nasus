const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const { resolve } = require('node:path')
const test = require('node:test')
const { runInNewContext } = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

const source = readFileSync(resolve(__dirname, '../../apps/portal/src/domains/agent/recentUserPrompts.ts'), 'utf8')
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
const loaded = {}
runInNewContext(code, { exports: loaded })
const recent = (messages) => Array.from(loaded.recentUserPrompts(messages))
const message = (role, text) => ({ role, blocks: [{ type: 'text', text }] })

test('Only the last five nonempty user queries enter history in chronological order', () => {
  const messages = [message('system', 'Policy'), message('user', 'Discarded'), message('user', 'A'),
    message('assistant', 'Reply'), message('user', 'B'), message('tool', 'Tool output'),
    message('user', 'B'), message('user', 'C'), message('user', 'D'), message('user', ' \n ')]
  assert.deepEqual(recent(messages), ['A', 'B', 'B', 'C', 'D'])
  assert.equal(messages.length, 10)
})

test('Full multiline queries survive reload while cards and other conversations are excluded', () => {
  const saved = [{ role: 'user', blocks: [{ type: 'text', text: 'First line' },
    { type: 'structured_card', text: 'Not a query' }, { type: 'text', text: 'Second line' }] }]
  assert.deepEqual(recent(JSON.parse(JSON.stringify(saved))), ['First line\nSecond line'])
  assert.deepEqual(recent(), [])
  assert.deepEqual(recent([message('user', 'Other conversation')]), ['Other conversation'])
})

test('Build gives each conversation a separate composer cursor without sibling key collisions', () => {
  const exports = {}
  const hero = readFileSync(resolve(__dirname, '../../apps/portal/src/routes/build/BuildHero.tsx'), 'utf8')
  const component = (name) => ({ [name]: () => null })
  const imports = {
    'react/jsx-runtime': require('../../apps/portal/node_modules/react/jsx-runtime'),
    '../../shared/ui/BuildComposer': component('BuildComposer'),
    './components/BuildConversation': component('BuildConversation'),
    './components/BuildAgentFeedback': component('BuildAgentFeedback'),
    './components/BuildSidebarToggle': component('BuildSidebarToggle'),
    '../../shared/i18n/I18nProvider': { useI18n: () => ({ t: (key) => key }) },
    '../../domains/agent/recentUserPrompts': loaded,
  }
  runInNewContext(ts.transpileModule(hero, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText, { exports, require: (name) => {
    assert.ok(imports[name], `Unexpected import: ${name}`)
    return imports[name]
  } })
  const keys = []
  for (const id of ['first', 'second']) {
    const view = exports.BuildHero({ conversation: { id, messages: [message('user', id)] } })
    const children = view.props.children.filter(Boolean)
    const siblingKeys = children.map((child) => child.key).filter((key) => key !== null)
    assert.equal(new Set(siblingKeys).size, siblingKeys.length)
    const composer = children.find((child) => child.type === imports['../../shared/ui/BuildComposer'].BuildComposer)
    assert.deepEqual(Array.from(composer.props.promptHistory), [id])
    keys.push(composer.key)
  }
  assert.notEqual(keys[0], keys[1])
})
