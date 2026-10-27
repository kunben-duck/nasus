const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')
const jsx = require('../../apps/portal/node_modules/react/jsx-runtime')

function fixture() {
  const state = [], reads = []
  let index = 0, mode = 'ready'
  const context = { exports: {}, require: (name) => {
    if (name === 'react') return { useState: (initial) => {
      const slot = index++
      if (state[slot] === undefined) state[slot] = initial
      return [state[slot], (value) => { state[slot] = value }]
    } }
    if (name === 'react/jsx-runtime') return jsx
    if (name.endsWith('I18nProvider')) return { useI18n: () => ({ t: (value) => value }) }
    if (name.endsWith('AnalysisPagination')) return { AnalysisPagination: 'Pagination' }
    if (name.endsWith('ReferenceDecisionEditor')) return { ReferenceDecisionEditor: 'DecisionEditor' }
    if (name.endsWith('useReferenceReviews')) return { useReferencePage: (scope, revision, proposal, section, offset, pin) => {
      reads.push({ scope, revision, proposal, section, offset, pin })
      const next = section === 'gaps' ? null : ({ 0: 5, 5: 7, 7: null })[offset]
      return { isError: mode === 'error', isFetching: mode === 'fetching', isPending: false, data: {
        assertion_count: 8, gap_count: 0, image_artifact_hash: 'hash', next_offset: next,
        items: section === 'gaps' ? [] : [{ assertion_id: `assertion-${offset}`, reference_id: 'US-1' }],
      } }
    } }
    throw new Error(`Unexpected dependency ${name}`)
  } }
  const source = fs.readFileSync(path.resolve(__dirname,
    '../../apps/portal/src/routes/project/sections/knowledge/revisions/ReferenceCandidates.tsx'), 'utf8')
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText, context)
  const scope = { projectId: 'project', sessionId: 'session' }
  const pin = { imageArtifactHash: 'sha256:' + 'a'.repeat(64), proposalDigest: 'sha256:' + 'b'.repeat(64) }
  function render() {
    index = 0
    const nodes = []
    function walk(value) {
      if (Array.isArray(value)) return value.forEach(walk)
      if (!value || typeof value !== 'object') return
      nodes.push(value)
      walk(value.props?.children)
    }
    walk(context.exports.ReferenceCandidates({ scope, revisionId: 'image', proposalId: 'proposal', pin }))
    return { nodes, pagination: nodes.find((node) => node.type === 'Pagination'),
      button: (label) => nodes.find((node) => node.type === 'button' && node.props.children === label) }
  }
  return { state, reads, pin, render, mode: (value) => { mode = value } }
}

test('all reference pages and their editor use the selected report and image pins', () => {
  const v = fixture()
  v.render().pagination.props.next()
  v.render().button('Inspect reference').props.onClick()
  const view = v.render()
  const editor = view.nodes.find((node) => node.type === 'DecisionEditor')
  assert.ok(v.reads.every((read) => read.pin === v.pin))
  assert.equal(editor.props.parentArtifactHash, v.pin.imageArtifactHash)
  assert.equal(editor.props.proposalDigest, v.pin.proposalDigest)
})

test('reference navigation follows actual unequal page cursors in both directions', () => {
  const v = fixture()
  let view = v.render()
  assert.equal(view.pagination.props.page, 1)
  assert.equal(view.pagination.props.previous, undefined)
  view.pagination.props.next()
  view = v.render()
  assert.equal(v.reads.at(-1).offset, 5)
  assert.equal(view.pagination.props.page, 2)
  view.pagination.props.next()
  view = v.render()
  assert.equal(v.reads.at(-1).offset, 7)
  assert.equal(view.pagination.props.page, 3)
  assert.equal(view.pagination.props.next, undefined)
  view.pagination.props.previous()
  view = v.render()
  assert.equal(v.reads.at(-1).offset, 5)
  assert.equal(view.pagination.props.page, 2)
  view.pagination.props.previous()
  view = v.render()
  assert.equal(v.reads.at(-1).offset, 0)
  assert.equal(view.pagination.props.page, 1)
  assert.equal(view.pagination.props.previous, undefined)
})

test('moving a reference page clears the previously selected assertion and decision form', () => {
  const v = fixture()
  v.render().button('Inspect reference').props.onClick()
  let view = v.render()
  assert.equal(view.nodes.filter((node) => node.type === 'DecisionEditor').length, 1)
  view.pagination.props.next()
  view = v.render()
  assert.equal(view.nodes.filter((node) => node.type === 'DecisionEditor').length, 0)
  assert.equal(v.reads.at(-1).offset, 5)
})

test('switching to the empty gaps section resets cursors without approving or hiding a missing page', () => {
  const v = fixture()
  v.render().pagination.props.next()
  v.render().button('Inspect reference').props.onClick()
  v.render().button('Reference gaps').props.onClick()
  const view = v.render()
  assert.equal(v.reads.at(-1).section, 'gaps')
  assert.equal(v.reads.at(-1).offset, 0)
  assert.equal(view.pagination.props.page, 1)
  assert.equal(view.pagination.props.previous, undefined)
  assert.equal(view.pagination.props.next, undefined)
  assert.equal(view.nodes.filter((node) => node.type === 'DecisionEditor').length, 0)
})

for (const mode of ['error', 'fetching']) {
  test(`a ${mode} read cannot display the old reference rows or review form`, () => {
    const v = fixture()
    v.render().button('Inspect reference').props.onClick()
    v.mode(mode)
    const view = v.render()
    assert.equal(view.pagination, undefined)
    assert.equal(view.button('Inspect reference'), undefined)
    assert.equal(view.nodes.filter((node) => node.type === 'DecisionEditor').length, 0)
  })
}
