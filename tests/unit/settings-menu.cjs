const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const { resolve } = require('node:path')
const test = require('node:test')
const { runInNewContext } = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

const source = readFileSync(resolve(__dirname, '../../apps/portal/src/app/shells/settings/settingsMenuModel.ts'), 'utf8')
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
const model = { exports: {}, require: (name) => {
  assert.equal(name, '../../../domains/platform/settings/modelProfiles')
  return { modelRouteLabel: (route) => route }
} }
runInNewContext(code, model)

for (const hasProject of [false, true]) {
  test(`settings menu omits legal and billing entries (project: ${hasProject})`, () => {
    const items = model.exports.buildSettingsMenuItems(undefined, 'chat', hasProject, (text) => text)
    assert.deepEqual(Array.from(items, (item) => item.label), [
      'Theme', 'Language', 'Model configuration', 'Applet notifications', 'Account status',
      ...(hasProject ? ['Project members'] : []),
      'View status', 'Send feedback',
    ])
  })
}
