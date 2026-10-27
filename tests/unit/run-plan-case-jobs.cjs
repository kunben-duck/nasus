const assert = require('node:assert/strict'), test = require('node:test')
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm')
const { execFileSync } = require('node:child_process'), { webcrypto } = require('node:crypto')
const ts = require('../../apps/portal/node_modules/typescript')
const repo = path.resolve(__dirname, '../..'), root = path.join(repo, 'apps/portal/src')
function load(relative, overrides = {}, modules = new Map()) {
  const file = path.resolve(root, relative)
  if (modules.has(file)) return modules.get(file)
  const context = { exports: {}, crypto: webcrypto, TextEncoder, URLSearchParams, require: (name) => {
    if (Object.hasOwn(overrides, name)) return overrides[name]
    return load(path.relative(root, path.resolve(path.dirname(file), `${name}.ts`)), overrides, modules)
  } }
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, context)
  modules.set(file, context.exports); return context.exports
}
const plain = (v) => JSON.parse(JSON.stringify(v))
const { canonicalDigest: digest } = load('shared/utils/canonicalDigest.ts')
const validation = load('domains/quality-loop/runPlanCaseValidation.ts')
const historyValidation = load('domains/quality-loop/runPlanCaseHistoryValidation.ts')
const { createCaseRecovery, verifyCaseAttempt } = load('domains/quality-loop/runPlanCaseRecovery.ts')
// Full original Python compilation and physical verifier with explicit memory/native
// protocol doubles. Not a PG, target deployment, exweb gold or execution claim.
const specimen = JSON.parse(execFileSync(path.join(repo, '.venv/bin/python'), ['-m', 'apps.api.tests.run_plan_case_portal_specimens'], { cwd: repo, encoding: 'utf8', env: { ...process.env,
  NASUS_DATABASE_URL: 'postgresql+psycopg://contract@127.0.0.1:1/nasus_case_contract', NASUS_AUTO_CREATE_TABLES: 'false' } }))
const fixtureSpecimen = JSON.parse(execFileSync(path.join(repo, '.venv/bin/python'), ['-m', 'apps.api.tests.test_run_plan_fixture_handoff'], { cwd: repo, encoding: 'utf8', env: { ...process.env,
  NASUS_DATABASE_URL: 'postgresql+psycopg://contract@127.0.0.1:1/nasus_case_contract', NASUS_AUTO_CREATE_TABLES: 'false' } }))
function fixture() {
  const v = structuredClone(specimen)
  v.fields = { runId: v.input.run_id, environmentCommandId: 'original-environment-command', locatorCommandId: 'original-locator-command',
    timeoutMs: v.input.timeout_ms, setups: v.input.fixture_setups.map((item) => ({ caseId: item.case_id, commandId: item.invocation_id })) }
  v.attempt = { projectId: v.input.project_id, planId: v.input.run_plan_id, planHash: v.input.run_plan_artifact_hash,
    fields: v.fields, input: v.input, execute: { requestKey: 'case-browser-key', requestHash: '', commandId: v.command.id } }
  return v
}
test('all seven original jobs match independent Python compilation and immutable history', async () => {
  const v = fixture(), before = structuredClone(v)
  assert.equal(v.input.fixture_setups.length, 7)
  for (let i = 0; i < 7; i++) assert.deepEqual(plain(await validation.caseJob(v.plan, v.input, i)), v.jobs[i])
  assert.equal(await historyValidation.verifyCaseHistory(v.view, v.command, v.input, v.plan), v.view)
  assert.equal(v.view.history.state.passed_count, 0)
  assert.deepEqual(v, before)
})
test('v3 original setup pins and complete Node observations match Python without adding coverage', async () => {
  const v = structuredClone(fixtureSpecimen), before = structuredClone(v)
  assert.equal(v.view.history.state.schema, 'nasus.run-plan-case-state.v2')
  assert.equal(v.view.history.state.fixture_input_pins.length, v.input.fixture_setups.length)
  assert.equal(await historyValidation.verifyCaseHistory(v.view, v.command, v.input, v.plan), v.view)
  assert.deepEqual(v, before)
  assert.equal(v.view.history.state.passed_count, 0)
  assert.ok(v.view.history.observations.every((o) => o.status === 'failed'))
})
for (const fault of ['state_schema', 'omitted_pin', 'reorder_pin', 'extra_pin', 'wrong_scope', 'input_digest', 'capture_digest',
  'command_digest', 'observation_schema', 'observation_input', 'observation_capture', 'receipt_schema', 'receipt_input', 'receipt_capture', 'oracle']) {
  test('v3 history rejects ' + fault + ' even when the observation hash is recomputed', async () => {
    const v = structuredClone(fixtureSpecimen), s = v.view.history.state, o = v.view.history.observations[0]
    if (fault === 'state_schema') s.schema = 'nasus.run-plan-case-state.v1'
    if (fault === 'omitted_pin') s.fixture_input_pins.pop()
    if (fault === 'reorder_pin') s.fixture_input_pins.reverse()
    if (fault === 'extra_pin') s.fixture_input_pins[0].value = 'invented_resource'
    if (fault === 'wrong_scope') s.fixture_scope_digest = s.scope_digest
    if (fault === 'input_digest') s.fixture_input_pins[0].fixture_input_digest = s.scope_digest
    if (fault === 'capture_digest') s.fixture_input_pins[0].capture_set_digest = s.scope_digest
    if (fault === 'command_digest') s.cases[0].command_digest = s.scope_digest
    if (fault === 'observation_schema') o.schema = 'nasus.run-plan-case-observation.v1'
    if (fault === 'observation_input') o.fixture_input_digest = s.scope_digest
    if (fault === 'observation_capture') o.fixture_capture_digest = s.scope_digest
    if (fault === 'receipt_schema') o.runner_receipt.schema = 'nasus.runner-http-execution.v2'
    if (fault === 'receipt_input') o.runner_receipt.fixture_input_hash = s.scope_digest
    if (fault === 'receipt_capture') o.runner_receipt.fixture_capture_digest = s.scope_digest
    if (fault === 'oracle') o.oracles[0].oracle_digest = s.scope_digest
    const { observation_digest, ...payload } = o
    o.observation_digest = s.cases[0].observation_digest = await digest(payload)
    await assert.rejects(() => historyValidation.verifyCaseHistory(v.view, v.command, v.input, v.plan))
  })
}
for (const fault of ['extra', 'missing_case', 'reorder', 'duplicate_case', 'duplicate_setup', 'timeout_bool', 'timeout_low', 'timeout_high', 'id_length', 'id_unicode', 'digest']) {
  test('selection rejects ' + fault + ' without shrinking the original roster', () => {
    const v = fixture(), input = v.input
    if (fault === 'extra') input.execution_authorized = true
    if (fault === 'missing_case') input.fixture_setups.pop()
    if (fault === 'reorder') input.fixture_setups.reverse()
    if (fault === 'duplicate_case') input.fixture_setups[1].case_id = input.fixture_setups[0].case_id
    if (fault === 'duplicate_setup') input.fixture_setups[1].invocation_id = input.fixture_setups[0].invocation_id
    if (fault === 'timeout_bool') input.timeout_ms = true
    if (fault === 'timeout_low') input.timeout_ms = 999
    if (fault === 'timeout_high') input.timeout_ms = 120001
    if (fault === 'id_length') input.run_id = 'x'.repeat(129)
    if (fault === 'id_unicode') input.run_id = '\ud800'
    if (fault === 'digest') input.plan_digest = 'verified'
    assert.throws(() => validation.requireCaseParent(input, v.plan))
  })
}
for (const fault of ['authority', 'count', 'count_bool', 'omitted', 'reorder', 'case_digest', 'command_digest', 'claim', 'observation', 'oracle', 'action', 'partial_completed', 'unknown_completed', 'wrong_run']) {
  test('history rejects ' + fault + ' instead of presenting false coverage or completion', async () => {
    const v = fixture(), s = v.view.history.state
    if (fault === 'authority') s.business_coverage_verified = true
    if (fault === 'count') s.case_count++
    if (fault === 'count_bool') s.observed_case_count = true
    if (fault === 'omitted') s.cases.pop()
    if (fault === 'reorder') s.cases.reverse()
    if (fault === 'case_digest') s.cases[0].case_digest = s.cases[1].case_digest
    if (fault === 'command_digest') s.cases[0].command_digest = s.cases[1].command_digest
    if (fault === 'claim') s.cases[0].claim_id = 'another-original-claim'
    if (fault === 'observation') v.view.history.observations[0].status = 'error'
    if (fault === 'oracle') v.view.history.observations[0].oracles[0].oracle_digest = s.cases[0].case_digest
    if (fault === 'action') v.view.history.observations[0].actions[0].source_step_indices = [999]
    if (fault === 'partial_completed' || fault === 'unknown_completed') {
      s.cases[0].status = fault === 'partial_completed' ? 'not_dispatched' : 'outcome_unknown'; s.cases[0].observation_digest = null
      s.observed_case_count--; s[fault === 'partial_completed' ? 'not_dispatched_case_count' : 'outcome_unknown_case_count']++
      s.state = fault === 'partial_completed' ? 'partially_observed' : 'outcome_unknown'; v.view.history.observations.shift()
    }
    if (fault === 'wrong_run') v.view.run_id = 'another-run'
    await assert.rejects(() => historyValidation.verifyCaseHistory(v.view, v.command, v.input, v.plan))
  })
}
test('unknown and cancelled original effects remain readable without a fake observation', async () => {
  const v = fixture(), s = v.view.history.state
  v.command.status = v.view.status = 'cancelled'; v.command.result.status = 'cancelled'; s.cancelled = true
  s.cases[0].status = 'outcome_unknown'; s.cases[0].observation_digest = null
  s.observed_case_count--; s.outcome_unknown_case_count++; s.state = 'outcome_unknown'; v.view.history.observations.shift()
  assert.equal(await historyValidation.verifyCaseHistory(v.view, v.command, v.input, v.plan), v.view)
})
test('unbound failed and cancelled tasks have no invented roster', async () => {
  for (const status of ['failed', 'cancelled']) {
    const v = fixture(); v.command.status = v.view.status = status; v.view.bound = false; v.view.history = null
    assert.equal(await historyValidation.verifyCaseHistory(v.view, v.command, v.input, v.plan), v.view)
  }
})
for (const fault of ['id', 'tool', 'key', 'actor', 'unconfirmed', 'marker', 'input', 'extra', 'result']) {
  test('canonical command rejects ' + fault + ' without adopting another request', async () => {
    const v = fixture(); v.attempt.execute.requestHash = await digest(v.input)
    if (fault === 'id') v.command.id = 'other-command'
    if (fault === 'tool') v.command.tool_id = 'run.start'
    if (fault === 'key') v.command.input_payload.idempotency_key = 'another-key'
    if (fault === 'actor') v.command.input_payload.confirmed_actor_id = 'another-actor'
    if (fault === 'unconfirmed') v.command.input_payload.confirmed_by_user = false
    if (fault === 'marker') delete v.command.input_payload.case_claim_protocol
    if (fault === 'input') v.command.input_payload.run_id = 'new-run'
    if (fault === 'extra') v.command.input_payload.scope = {}
    if (fault === 'result') v.command.result.invocation_id = 'other-command'
    await assert.rejects(() => validation.requireCaseCommand(v.command, 'execute', v.attempt.execute, v.input, 'qa-owner'))
  })
}
test('session recovery retains all pins and has no clear or reset shortcut', async () => {
  const values = new Map(), storage = { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) }
  const r = createCaseRecovery(() => storage), v = fixture()
  v.attempt.execute = { requestKey: 'case-browser-key', requestHash: await digest(v.input) }
  r.save('qa-owner', v.attempt)
  const original = r.acknowledge('qa-owner', v.attempt, 'execute', v.command.id)
  assert.deepEqual(plain(r.read('qa-owner', v.attempt.projectId, v.attempt.planId, v.attempt.planHash)), plain(original))
  assert.equal(r.read('other-user', v.attempt.projectId, v.attempt.planId, v.attempt.planHash), null)
  assert.equal(r.clear, undefined)
  assert.throws(() => r.save('qa-owner', v.attempt))
  assert.throws(() => r.acknowledge('qa-owner', original, 'execute', 'replacement-command'))
  const cancel = r.addCancel('qa-owner', original, 'independent-cancel-key', await digest(validation.caseControlInput(v.input, v.command.id)))
  assert.equal(cancel.input.fixture_setups.length, 7)
  assert.throws(() => r.addCancel('qa-owner', cancel, 'another-cancel', cancel.cancel.requestHash))
  assert.throws(() => r.read('qa-owner', v.attempt.projectId, v.attempt.planId, 'sha256:' + '0'.repeat(64)))
  assert.throws(() => verifyCaseAttempt({ ...original, authorized: true }))
})
function transport(v, fault) {
  const writes = [], confirms = [], reads = [], a = { ...v.attempt.execute }
  const pending = structuredClone(v.command); pending.status = 'waiting_confirmation'; delete pending.result
  delete pending.input_payload.confirmed_by_user; delete pending.input_payload.confirmed_actor_id; delete pending.input_payload.confirmed_at; delete pending.input_payload.case_claim_protocol
  const api = load('domains/quality-loop/runPlanCaseApi.ts', {
    '../platform/api': { platformApi: {
      invokeTool: async (body) => { writes.push(plain(body)); if (fault === 'create_ack') throw new Error('lost acknowledgement'); return pending },
      getToolInvocation: async (id) => { reads.push(id); return pending },
      confirmToolInvocation: async (id) => { confirms.push(id); if (fault === 'confirm_ack') throw new Error('lost acknowledgement'); return v.command },
    } },
    '../../shared/api/client': { request: async (url, options) => { reads.push([url, options.cache]); return pending } },
  }).caseExecutionApi
  return { api, writes, confirms, reads, a }
}
test('submit verifies the create acknowledgement before confirming the same original ID', async () => {
  const v = fixture(); v.attempt.execute.requestHash = await digest(v.input); delete v.attempt.execute.commandId
  const t = transport(v), ack = []
  assert.equal((await t.api.submit('execute', v.attempt.execute, v.input, 'qa-owner', (id) => ack.push(id))).id, v.command.id)
  assert.deepEqual(ack, [v.command.id]); assert.deepEqual(t.confirms, [v.command.id])
  assert.equal(t.writes.length, 1); assert.equal(t.writes[0].tool_id, validation.caseTools.execute)
})
for (const fault of ['create_ack', 'confirm_ack']) test('lost ' + fault + ' recovers read-only without a second request', async () => {
  const v = fixture(); v.attempt.execute.requestHash = await digest(v.input); delete v.attempt.execute.commandId
  const t = transport(v, fault); let attempt = v.attempt.execute
  await assert.rejects(() => t.api.submit('execute', attempt, v.input, 'qa-owner', (id) => { attempt = { ...attempt, commandId: id } }))
  const writes = t.writes.length, confirms = t.confirms.length
  await t.api.recover('execute', attempt, v.input, 'qa-owner', new AbortController().signal)
  assert.equal(t.writes.length, writes); assert.equal(t.confirms.length, confirms)
  if (fault === 'create_ack') assert.ok(t.reads.some((v) => Array.isArray(v) && v[0].includes('/resolve?') && v[1] === 'no-store'))
})
test('invalid original payload is rejected before the write transport', async () => {
  const v = fixture(), input = { ...v.input, execution_authorized: true }, t = transport(v)
  const requestHash = await digest(input)
  await assert.rejects(() => t.api.submit('execute', { requestKey: 'key', requestHash }, input, 'qa-owner', () => {}))
  assert.equal(t.writes.length, 0)
})
function references(v, change = () => {}) {
  const reads = [], environment = { metadata: {
    build_binding_id: v.input.build_binding_id, build_binding_artifact_hash: v.input.build_binding_artifact_hash,
    record_id: v.input.environment_record_id, artifact_hash: v.input.environment_record_artifact_hash,
  } }, locators = { metadata: { record_id: v.input.locator_record_id, artifact_hash: v.input.locator_record_artifact_hash },
    archive: { report: { locators: [{ status: 'static_match' }] } } }
  const api = load('domains/quality-loop/runPlanCaseApi.ts', {
    './httpFixtureEnvironmentApi': { readFixtureEnvironment: async (plan, id, signal) => {
      assert.equal(plan, v.plan); assert.equal(id, v.fields.environmentCommandId); assert.ok(signal); reads.push(['environment', id]); return environment
    } },
    './runPlanLocatorRecordApi': { locatorRecordApi: { read: async (command, plan, signal) => {
      assert.equal(command.id, v.fields.locatorCommandId); assert.equal(plan, v.plan); assert.ok(signal); reads.push(['locator', command.id]); return locators
    } } },
    '../platform/api': { platformApi: { getToolInvocation: async (id) => ({ id }) } },
    '../../shared/api/client': { request: async (url, options) => {
      assert.equal(options.cache, 'no-store'); assert.ok(options.signal)
      const id = decodeURIComponent(url.split('/').at(-1)), selected = v.fields.setups.find((row) => row.commandId === id)
      assert.ok(selected); reads.push(['setup', id])
      const item = { project_id: v.input.project_id, invocation_id: id, tool_id: 'quality.http_fixture.execute',
        stage: 'execute', status: 'completed', request_digest: v.input.plan_digest, recipe_id: 'recipe-original',
        recipe_artifact_hash: v.input.plan_digest, run_plan_id: v.input.run_plan_id, run_plan_artifact_hash: v.input.run_plan_artifact_hash,
        case_id: selected.caseId, attempt_id: 'fixture-original', operation: 'setup', original_execution_id: id,
        grant_id: 'original-fixture-grant', grant_digest: v.input.plan_digest,
        observation: 'original_command_metadata_not_target_observation', execution_authorized: false,
        canonical_execution_committed: false, business_coverage_verified: false, baseline_restored: false }
      change(item, reads); return item
    } },
  }).caseExecutionApi
  return { api, reads, locators, environment }
}
test('preparation reads every original setup in order and derives pins from verified read ports', async () => {
  const v = fixture(), t = references(v), signal = new AbortController().signal, before = structuredClone(v)
  assert.deepEqual(plain(await t.api.prepare(v.plan, v.fields, signal)), v.input)
  assert.deepEqual(t.reads, [['environment', v.fields.environmentCommandId], ['locator', v.fields.locatorCommandId],
    ...v.fields.setups.map((row) => ['setup', row.commandId])])
  assert.deepEqual(v, before)
})
for (const fault of ['project', 'id', 'case', 'plan', 'hash', 'operation', 'stage', 'status', 'authority', 'locator', 'missing', 'order', 'aborted']) {
  test('preparation rejects ' + fault + ' rather than skipping unverified original cases', async () => {
    const v = fixture(), controller = new AbortController(), t = references(v, (item) => {
      if (fault === 'project') item.project_id = 'other-project'
      if (fault === 'id') item.invocation_id = item.original_execution_id = 'other-command'
      if (fault === 'case') item.case_id = 'other-case'
      if (fault === 'plan') item.run_plan_id = 'other-plan'
      if (fault === 'hash') item.run_plan_artifact_hash = 'sha256:' + '0'.repeat(64)
      if (fault === 'operation') item.operation = 'cleanup'
      if (fault === 'stage') { item.stage = 'cancel'; item.tool_id = 'quality.http_fixture.cancel' }
      if (fault === 'status') item.status = 'running'
      if (fault === 'authority') item.execution_authorized = true
    })
    if (fault === 'locator') t.locators.archive.report.locators[0].status = 'unresolved'
    if (fault === 'missing') v.fields.setups.pop()
    if (fault === 'order') v.fields.setups.reverse()
    if (fault === 'aborted') controller.abort()
    await assert.rejects(() => t.api.prepare(v.plan, v.fields, controller.signal))
    if (['missing', 'order', 'aborted'].includes(fault)) assert.equal(t.reads.length, 0)
    if (fault === 'locator') assert.equal(t.reads.filter((item) => item[0] === 'setup').length, 0)
  })
}
function historyTransport(v, statuses, view = v.view) {
  const reads = [], api = load('domains/quality-loop/runPlanCaseApi.ts', {
    '../platform/api': { platformApi: { getToolInvocation: async (id) => {
      reads.push(['command', id]); const command = structuredClone(v.command), status = statuses.shift() ?? v.command.status
      command.status = status; if (command.result) command.result.status = status; return command
    } } },
    '../../shared/api/client': { request: async (url, options) => { reads.push(['history', url, options.cache]); return view } },
  }).caseExecutionApi
  return { api, reads }
}
test('read follows a status race using only the same command and private history', async () => {
  const v = fixture(); v.attempt.execute.requestHash = await digest(v.input)
  const t = historyTransport(v, ['running', 'completed'])
  const result = await t.api.read(v.attempt.execute, v.input, v.plan, 'qa-owner', new AbortController().signal)
  assert.equal(result.history, v.view); assert.equal(t.reads.length, 4)
  assert.ok(t.reads.every((row) => row[0] === 'command' ? row[1] === v.command.id : row[1].endsWith('/' + v.command.id) && row[2] === 'no-store'))
})
test('persistent status disagreement fails closed after three read-only attempts', async () => {
  const v = fixture(); v.attempt.execute.requestHash = await digest(v.input)
  const t = historyTransport(v, ['running', 'running', 'running'])
  await assert.rejects(() => t.api.read(v.attempt.execute, v.input, v.plan, 'qa-owner', new AbortController().signal))
  assert.equal(t.reads.length, 6)
})
test('waiting confirmation does not read execution history or confirm on refresh', async () => {
  const v = fixture(); v.attempt.execute.requestHash = await digest(v.input)
  const t = historyTransport(v, ['waiting_confirmation'])
  const result = await t.api.read(v.attempt.execute, v.input, v.plan, 'qa-owner', new AbortController().signal)
  assert.equal(result.history, undefined); assert.equal(t.reads.length, 1)
})
test('cancel has a separate command, payload and confirmation, never another execute', async () => {
  const v = fixture(), input = validation.caseControlInput(v.input, v.command.id), writes = [], confirms = [], ack = []
  const attempt = { requestKey: 'independent-cancel-key', requestHash: await digest(input) }
  const pending = { id: 'original-control', tool_id: validation.caseTools.cancel, status: 'waiting_confirmation',
    input_payload: { ...plain(input), idempotency_key: attempt.requestKey } }
  const done = { ...pending, status: 'completed', input_payload: { ...pending.input_payload, confirmed_by_user: true,
    confirmed_actor_id: 'qa-owner', confirmed_at: v.command.input_payload.confirmed_at } }
  const api = load('domains/quality-loop/runPlanCaseApi.ts', { '../../shared/api/client': { request: async () => { throw new Error('unexpected transport') } }, '../platform/api': { platformApi: {
    invokeTool: async (body) => { writes.push(plain(body)); return pending }, getToolInvocation: async () => pending,
    confirmToolInvocation: async (id) => { confirms.push(id); return done },
  } } }).caseExecutionApi
  assert.equal((await api.submit('cancel', attempt, input, 'qa-owner', (id) => ack.push(id))).id, pending.id)
  assert.deepEqual(writes, [{ tool_id: validation.caseTools.cancel, idempotency_key: attempt.requestKey, input: plain(input) }])
  assert.deepEqual(confirms, [pending.id]); assert.deepEqual(ack, [pending.id]); assert.notEqual(pending.id, v.command.id)
})
test('the route uses the domain hook, full roster, independent consent and no replacement control', () => {
  const panel = fs.readFileSync(path.join(root, 'routes/project/sections/knowledge/scope/RunPlanCaseExecutionPanel.tsx'), 'utf8')
  const hook = fs.readFileSync(path.join(root, 'domains/quality-loop/useRunPlanCaseJob.ts'), 'utf8')
  const route = fs.readFileSync(path.join(root, 'routes/project/sections/knowledge/scope/RunPlanPanel.tsx'), 'utf8')
  assert.match(route, /RunPlanCaseExecutionPanel/); assert.match(panel, /s\.fields\.setups\.map/)
  assert.match(panel, /state\.cases\.map/); assert.match(panel, /s\.mayWrite\(stage\)/)
  assert.match(hook, /submitted\.current = true/); assert.match(hook, /storage\.save/)
  assert.match(hook, /retry: false/); assert.match(hook, /gcTime: 0/)
  assert.doesNotMatch(panel + hook, /dangerouslySetInnerHTML|storage\.clear|slice\(0,|api\.submit\([^)]*reload/)
})
test('case states use shared localization without translating IDs or presenting unknown as failure', () => {
  const { zhCN } = load('shared/i18n/messages.ts')
  assert.equal(zhCN['outcome unknown'], '实际效果尚未确认')
  assert.equal(zhCN['not dispatched'], '尚未派发')
  assert.equal(zhCN.observed, '已记录执行观察')
  const panel = fs.readFileSync(path.join(root, 'routes/project/sections/knowledge/scope/RunPlanCaseExecutionPanel.tsx'), 'utf8')
  assert.match(panel, /tx\(row\.status\)/); assert.match(panel, /tx\(state\.state\)/)
  assert.match(panel, /<code>\{row\.case_id\}<\/code>/)
})
