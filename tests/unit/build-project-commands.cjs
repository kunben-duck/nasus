const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const { resolve } = require('node:path')
const test = require('node:test')
const { runInNewContext } = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

const source = readFileSync(resolve(__dirname, '../../apps/portal/src/domains/platform/buildProjectCommands.ts'), 'utf8')
const command = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText

function load(invokeTool) {
  const exports = {}
  runInNewContext(command, { exports, require: (name) => {
    assert.equal(name, './api')
    return { platformApi: { invokeTool } }
  } })
  return exports.createProjectFromBuild
}

test('Build creates the named project through the canonical tool and keeps the original retry key', async () => {
  const requests = []
  const create = load(async (request) => {
    requests.push(JSON.parse(JSON.stringify(request)))
    if (requests.length === 1) throw new Error('Connection lost')
    return { status: 'completed', result: { object_refs: ['project:exweb-pilot'] } }
  })
  await assert.rejects(create('exweb', 'original'), /Connection lost/)
  assert.equal(await create('exweb', 'original'), 'exweb-pilot')
  assert.deepEqual(requests[0], { tool_id: 'project.create', input: { name: 'exweb' }, idempotency_key: 'original' })
  assert.deepEqual(requests[1], requests[0])
})

test('Build cannot navigate to a project from a blocked or unrelated receipt', async () => {
  const blocked = load(async () => ({ status: 'blocked', summary: 'Permission denied', result: { object_refs: ['project:other'] } }))
  await assert.rejects(blocked('exweb', 'key'), /Permission denied/)
  const unrelated = load(async () => ({ status: 'completed', result: { object_refs: ['version:other'] } }))
  await assert.rejects(unrelated('exweb', 'key'), /did not return a project/)
})
