const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')
const root = path.resolve(__dirname, '../../apps/portal/src')
function load(relative, overrides = {}, modules = new Map()) {
  const file = path.resolve(root, relative)
  if (modules.has(file)) return modules.get(file)
  const context = { exports: {}, require: (name) => {
    if (Object.hasOwn(overrides, name)) return overrides[name]
    return load(path.relative(root, path.resolve(path.dirname(file), `${name}.ts`)), overrides, modules)
  } }
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText, context)
  modules.set(file, context.exports); return context.exports
}
const loadOptions = (request = () => { throw new Error('unexpected request') }) => load('domains/quality-loop/targetEnvironments.ts', {
  '../../shared/api/client': { request }, './testDesignGenerationValidation': { generationDigest: (v) => /^sha256:[0-9a-f]{64}$/.test(v) },
  './automationScriptValidation': { scriptId: (v) => typeof v === 'string' && v.length > 0 && v.length <= 128 },
  './runPlanValidation': { requireRunPlan: (value) => { assert.ok(value) } },
})
const specimen = () => ({ schema: 'nasus.target-environment-options.v1', project_id: 'project', target_verified: false,
  execution_authorized: false, options: [{ environment_id: 'isolated-target', profile: 'nasus.python312-django-pg.v1',
    kind: 'local', base_url: 'http://127.0.0.1:8080', inventory_hash: 'sha256:' + 'a'.repeat(64) }] })
test('environment discovery is private, abortable and GET-only', async () => {
  const calls = [], api = loadOptions(async (...args) => { calls.push(args); return specimen() })
  const value = await api.readTargetEnvironments('project', new AbortController().signal)
  assert.deepEqual(value, specimen())
  assert.equal(calls[0][0], '/v1/projects/project/quality/target-environments')
  assert.equal(calls[0][1].cache, 'no-store'); assert.equal(calls[0][1].method, undefined)
  await assert.rejects(api.readTargetEnvironments('project', AbortSignal.abort()))
  assert.equal(calls.length, 1)
})
for (const [name, mutate] of Object.entries({
  'cross project': (v) => v.project_id = 'another',
  'arbitrary origin': (v) => v.options[0].base_url = 'http://example.com',
  'execution permission': (v) => v.execution_authorized = true,
  'verification claim': (v) => v.target_verified = true,
  'container disclosure': (v) => v.options[0].container_id = 'secret',
  'duplicate choice': (v) => v.options.push(v.options[0]),
  'unknown profile': (v) => v.options[0].profile = 'custom',
  'unhashed policy': (v) => v.options[0].inventory_hash = 'operator.json',
})) test(`environment options reject ${name}`, () => {
  const value = specimen(); mutate(value)
  assert.throws(() => loadOptions().verifyTargetEnvironments(value, 'project'))
})
test('only an exact currently registered environment can prepare a plan', () => {
  const { registeredEnvironment } = loadOptions(), options = specimen(), item = options.options[0]
  const fields = { environmentId: item.environment_id, kind: item.kind, origin: item.base_url, inventoryHash: item.inventory_hash }
  assert.equal(registeredEnvironment(fields, options), true)
  for (const key of Object.keys(fields)) assert.equal(registeredEnvironment({ ...fields, [key]: 'rebound' }, options), false)
  assert.equal(registeredEnvironment(fields, { ...options, options: [] }), false)
  assert.equal(registeredEnvironment(fields), false)
})
