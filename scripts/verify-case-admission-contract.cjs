// Verify a real authorized API specimen against the current Portal contracts.
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { webcrypto } = require('node:crypto')
const ts = require('../apps/portal/node_modules/typescript')
const root = path.resolve(__dirname, '../apps/portal/src'), modules = new Map()
function load(file) {
  if (modules.has(file)) return modules.get(file)
  const context = { exports: {}, crypto: webcrypto, TextEncoder, require: (name) => load(path.resolve(path.dirname(file), `${name}.ts`)) }
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, context)
  modules.set(file, context.exports); return context.exports
}
async function verify() {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'))
  const { verifyCaseAdmissionPreview } = load(path.join(root, 'domains/quality-loop/caseApprovalValidation.ts'))
  const value = await verifyCaseAdmissionPreview(input.preview, input.draft, input.mapping)
  if (value.head === null || value.head.status !== 'approved' || !value.input_current) throw new Error('Current approval was not verified')
  process.stdout.write(JSON.stringify({ verified: true, cases: value.basis.case_pins.length,
    obligations: value.basis.obligation_denominator, target_execution_verified: false }) + '\n')
}
verify().catch(() => { process.stderr.write('Case admission Portal contract verification failed\n'); process.exitCode = 1 })
