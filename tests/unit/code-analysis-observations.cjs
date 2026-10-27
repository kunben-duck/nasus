const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')
const root = path.resolve(__dirname, '../../apps/portal/src')
function load(file) {
  const context = { exports: {}, require: (name) => load(path.resolve(path.dirname(file), name) + '.ts') }
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, context)
  return context.exports
}
const { analysisObservationViews } = load(path.join(root, 'routes/project/sections/knowledge/analysis/analysisObservationView.ts'))

for (const status of ['exact', 'ambiguous', 'unresolved']) {
  test(`received ${status} entity is an observation, never an approved identity`, () => {
    const [view] = analysisObservationViews([{ provider_node_id: 'node', name: '<img onerror=alert(1)>',
      qualified_name: 'example.run', entity_kind: 'method', relative_path: 'Example.java',
      language: 'java', start_line: 2, end_line: 5, identity_status: status, location_precision: 'approximate' }])
    assert.equal(view.heading, '<img onerror=alert(1)>')
    assert.equal(view.location, 'Example.java:2-5')
    assert.equal(view.status, status)
    assert.match(view.description, /does not imply admission/)
    assert.equal(view.details.find((item) => item.label === 'Observation node ID').value, 'node')
  })
}
for (const kind of ['belongs_to', 'depends_on', 'calls', 'exposes']) {
  test(`received ${kind} relation keeps endpoint identity and uncalibrated score`, () => {
    const [view] = analysisObservationViews([{ from_provider_node_id: 'a', to_provider_node_id: 'b', relationship_kind: kind, confidence: 0.7 }])
    assert.equal(view.details[0].value, 'a')
    assert.equal(view.details[1].value, 'b')
    assert.equal(view.details[2].label, 'Uncalibrated provider score')
    assert.match(view.description, /does not prove business correctness/)
  })
}
