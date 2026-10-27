const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

const context = { exports: {} }
const file = path.resolve(__dirname, '../../apps/portal/src/domains/system-image/imageRecordPosition.ts')
vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, context)
const { imageRecordOffset } = context.exports

for (const [position, total, expected] of [['1', 730, 0], ['730', 730, 729], [' 26 ', 730, 25], ['026', 730, 25], ['1', 1, 0]]) {
  test(`record ${position} in ${total} uses its exact zero-based offset`, () => {
    assert.equal(imageRecordOffset(position, total), expected)
  })
}

for (const position of ['', ' ', '0', '-1', '731', '1.5', '1e2', '+2', 'Infinity', 'NaN', '0x10', '26junk', '9007199254740993']) {
  test(`invalid record position ${JSON.stringify(position)} cannot trigger navigation`, () => {
    assert.equal(imageRecordOffset(position, 730), null)
  })
}

for (const total of [0, -1, 1.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
  test(`unverified record count ${total} cannot admit a position`, () => {
    assert.equal(imageRecordOffset('1', total), null)
  })
}
