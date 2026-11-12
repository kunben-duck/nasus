const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const { resolve } = require('node:path')
const test = require('node:test')
const { runInNewContext } = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')
const jsx = require('../../apps/portal/node_modules/react/jsx-runtime')

function load(file, imports = {}) {
  const source = readFileSync(resolve(__dirname, '../../apps/portal/src/shared/ui', file), 'utf8')
  const code = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText
  const exports = {}
  runInNewContext(code, { exports, requestAnimationFrame: () => 0, require: (name) => {
    if (imports[name]) return imports[name]
    if (name === 'react') return { useRef: (value) => ({ current: value }) }
    if (name === 'react/jsx-runtime') return jsx
    if (name === '../../i18n/I18nProvider') return { useI18n: () => ({ t: (key) => key }) }
    if (name === './promptHistory') return history
    assert.ok(imports[name], `Unexpected import: ${name}`)
    return imports[name]
  } })
  return exports
}

const history = load('build-composer/promptHistory.ts')
const { BuildPromptInput } = load('build-composer/BuildPromptInput.tsx')

function keydown(overrides = {}, props = {}) {
  let submitted = 0
  let prevented = false
  const input = BuildPromptInput({ prompt: 'Build a project', setPrompt() {},
    runPrompt: () => submitted++, busy: false, ...props })
  input.props.onKeyDown({ key: 'Enter', shiftKey: false, repeat: false,
    currentTarget: { selectionStart: 0, selectionEnd: 0 },
    nativeEvent: { isComposing: false, keyCode: 13 },
    preventDefault: () => { prevented = true }, ...overrides })
  return { submitted, prevented }
}

test('Enter sends without inserting a newline and retains Ctrl/Meta shortcuts', () => {
  for (const keys of [{}, { ctrlKey: true }, { metaKey: true }]) {
    assert.deepEqual(keydown(keys), { submitted: 1, prevented: true })
  }
})

test('Shift+Enter preserves the browser newline and ordinary keys keep editing', () => {
  for (const keys of [{ shiftKey: true }, { key: 'a' }]) {
    assert.deepEqual(keydown(keys), { submitted: 0, prevented: false })
  }
})

test('IME confirmation never sends or prevents composition', () => {
  for (const nativeEvent of [{ isComposing: true, keyCode: 13 }, { isComposing: false, keyCode: 229 }]) {
    assert.deepEqual(keydown({ nativeEvent }), { submitted: 0, prevented: false })
  }
})

test('Enter ignores empty drafts, held keys and in-flight turns', () => {
  assert.deepEqual(keydown({}, { prompt: ' \n\t ' }), { submitted: 0, prevented: true })
  assert.deepEqual(keydown({ repeat: true }), { submitted: 0, prevented: true })
  assert.deepEqual(keydown({}, { busy: true }), { submitted: 0, prevented: true })
})

test('Composer blocks keyboard submission while loading or streaming', () => {
  const { BuildComposer } = load('BuildComposer.tsx', {
    './build-composer/BuildPromptInput': { BuildPromptInput },
    './build-composer/BuildComposerActions': { BuildComposerActions: () => null },
    './build-composer/SelectedSkillGrid': { SelectedSkillGrid: () => null },
  })
  for (const [loading, streaming] of [[true, false], [false, true], [false, false]]) {
    const composer = BuildComposer({ prompt: 'Draft', promptHistory: ['Previous'], loading, streaming, selectedSkills: [] })
    const input = composer.props.children.props.children.find((child) => child.type === BuildPromptInput)
    assert.equal(input.props.busy, loading || streaming)
    assert.deepEqual(input.props.promptHistory, ['Previous'])
  }
})

test('Up/Down fills recent prompts without sending and restores the draft', () => {
  const ref = { current: null }
  const { BuildPromptInput: Input } = load('build-composer/BuildPromptInput.tsx', { react: { useRef: () => ref } })
  let value = 'Unsent draft'
  let sent = 0
  const render = () => Input({ prompt: value, promptHistory: ['Older', 'Newest\nsecond line'], busy: false,
    setPrompt: (next) => { value = next }, runPrompt: () => sent++ })
  function press(key, extra = {}) {
    let prevented = false
    render().props.onKeyDown({ key, nativeEvent: {},
      currentTarget: { selectionStart: value.length, selectionEnd: value.length },
      preventDefault: () => { prevented = true }, ...extra })
    return prevented
  }
  assert.equal(press('ArrowUp', { nativeEvent: { isComposing: true } }), false)
  assert.equal(press('ArrowUp', { nativeEvent: { keyCode: 229 } }), false)
  for (const modifier of ['ctrlKey', 'metaKey', 'altKey', 'shiftKey']) {
    assert.equal(press('ArrowUp', { [modifier]: true }), false)
  }
  assert.equal(value, 'Unsent draft')
  assert.equal(press('ArrowUp'), true)
  assert.equal(value, 'Newest\nsecond line')
  press('ArrowUp')
  assert.equal(value, 'Older')
  press('ArrowDown')
  assert.equal(value, 'Newest\nsecond line')
  press('ArrowDown')
  assert.equal(value, 'Unsent draft')
  assert.equal(sent, 0)
  press('ArrowUp')
  render().props.onChange({ target: { value: 'Edited history' } })
  assert.equal(ref.current, null)
  press('ArrowUp')
  press('ArrowDown')
  assert.equal(value, 'Edited history')
})

test('History is capped at five turns without wrapping or removing repeated queries', () => {
  const entries = ['One', 'Two', 'Three', 'Repeated', 'Repeated', 'Six', 'Seven']
  let cursor = null
  let value = 'Draft'
  const recall = (direction, source = entries) => {
    const result = history.recallPrompt(cursor, source, value, direction)
    if (result) ({ cursor, value } = result)
    return result
  }
  assert.equal(recall('newer'), null)
  for (const expected of ['Seven', 'Six', 'Repeated', 'Repeated', 'Three', 'Three']) {
    recall('older')
    assert.equal(value, expected)
  }
  for (let index = 0; index < 5; index++) recall('newer')
  assert.equal(value, 'Draft')
  assert.equal(cursor, null)
  assert.equal(recall('older', []), null)
})

test('Multiline editing and selection stay native outside history browsing', () => {
  const text = 'first\nsecond\nthird'
  assert.equal(history.canRecallPrompt('ArrowUp', text, 3, 3, false), true)
  assert.equal(history.canRecallPrompt('ArrowUp', text, 8, 8, false), false)
  assert.equal(history.canRecallPrompt('ArrowDown', text, 8, 8, false), false)
  assert.equal(history.canRecallPrompt('ArrowDown', text, text.length, text.length, false), true)
  assert.equal(history.canRecallPrompt('ArrowUp', text, text.length, text.length, true), true)
  assert.equal(history.canRecallPrompt('ArrowUp', text, 0, text.length, true), false)
})

test('Changed conversation history or edited text cannot reuse an old cursor', () => {
  const first = history.recallPrompt(null, ['Old query'], 'Old draft', 'older')
  assert.equal(history.recallPrompt(first.cursor, ['New query'], first.value, 'newer'), null)
  assert.equal(history.recallPrompt(first.cursor, ['Old query'], 'Changed text', 'newer'), null)
})
