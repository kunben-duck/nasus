const assert = require('node:assert/strict')
const { execFileSync } = require('node:child_process')
const { createHash } = require('node:crypto')
const path = require('node:path')
const repo = path.resolve(__dirname, '../../..')
const python = (mode, input) => JSON.parse(execFileSync(path.join(repo, '.venv/bin/python'),
  ['-m', 'tests.browser.http-fixture.specimen', ...(mode ? [mode] : [])], { cwd: repo, input: input && JSON.stringify(input), encoding: 'utf8' }))
const sorted = (v) => Array.isArray(v) ? v.map(sorted) : v && typeof v === 'object'
  ? Object.fromEntries(Object.entries(v).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([k, v]) => [k, sorted(v)])) : v
const digest = (v) => 'sha256:' + createHash('sha256').update(JSON.stringify(sorted(v))).digest('hex')
const tools = { grant: 'quality.http_fixture.authorize', execute: 'quality.http_fixture.execute', cancel: 'quality.http_fixture.cancel' }
let state

async function install(page) {
  await page.unrouteAll({ behavior: 'wait' })
  const s = python(), e = s.environment, b = s.binding
  state = { specimen: s, commands: new Map(), grants: new Map(), jobs: new Map(), reads: [], writes: [], confirms: [],
    unexpected: [], errors: [], mutationErrors: [], loseCreate: '', loseConfirm: '', denyResolve: false, revokeEnvironment: false, corruptJob: false }
  const completed = (id, tool, input, result) => ({ id, tool_id: tool, status: 'completed',
    input_payload: { ...input, idempotency_key: id + '-key', confirmed_by_user: true },
    result: { invocation_id: id, status: 'completed', ...result } })
  state.commands.set(e.metadata.invocation_id, completed(e.metadata.invocation_id, 'quality.run_plan.record_environment', e.archive.request,
    { object_refs: ['run_plan_environment:' + e.metadata.record_id], run_plan_environment_record: { metadata: e.metadata, historical_not_live: true } }))
  state.commands.set(b.metadata.invocation_id, completed(b.metadata.invocation_id, 'quality.run_plan.bind_native_build', b.artifact.request,
    { object_refs: ['run_plan_build:' + b.metadata.binding_id] }))
  page.on('pageerror', (error) => state.errors.push(error.message))
  page.on('console', (entry) => { if (entry.text().startsWith('Contract mutation error:')) state.mutationErrors.push(entry.text()) })
  // Every API request is intercepted. There is no backend or target behind this surface.
  await page.route('**/browser-specimen.json', (route) => route.fulfill({ json: s }))
  await page.route('**/v1/**', async (route) => {
    const request = route.request(), url = new URL(request.url()), method = request.method(), id = decodeURIComponent(url.pathname.split('/').at(-1))
    const fulfill = (value, status = 200) => route.fulfill({ status, json: value, headers: { 'Cache-Control': 'private, no-store' } })
    if (method === 'GET') {
      state.reads.push(url.pathname + url.search)
      if (url.pathname === '/v1/tool-invocations/resolve') {
        if (state.denyResolve) return fulfill({ detail: 'Explicit original-command lookup outage' }, 503)
        return fulfill([...state.commands.values()].find((c) => c.tool_id === url.searchParams.get('tool_id') && c.input_payload.idempotency_key === url.searchParams.get('request_key')) ?? null)
      }
      if (url.pathname.startsWith('/v1/tool-invocations/') && state.commands.has(id)) return fulfill(state.commands.get(id))
      if (url.pathname.includes('/run-plan-builds/') && id === b.metadata.binding_id) return fulfill(b)
      if (url.pathname.includes('/native-builds/')) { const value = s.builds.find((v) => v.invocation_id === id); if (value) return fulfill(value) }
      if (url.pathname.includes('/run-plan-environments/') && id === e.metadata.record_id) return fulfill(state.revokeEnvironment ? { detail: 'Explicit source revocation' } : e, state.revokeEnvironment ? 403 : 200)
      if (url.pathname.includes('/http-fixture-grants/') && state.grants.has(id)) return fulfill(state.grants.get(id))
      if (url.pathname.includes('/http-fixture-executions/') && state.jobs.has(id)) {
        const job = structuredClone(state.jobs.get(id)); if (state.corruptJob) job.business_coverage_verified = true
        return fulfill(job)
      }
    }
    if (method === 'POST' && url.pathname === '/v1/tool-invocations') {
      const body = request.postDataJSON(), stage = Object.keys(tools).find((k) => tools[k] === body.tool_id)
      assert.ok(stage, 'Only the three canonical fixture commands may be sent')
      assert.equal([...state.commands.values()].some((c) => c.input_payload.idempotency_key === body.idempotency_key), false)
      const command = { id: `${stage}-command-${state.writes.length}`, tool_id: body.tool_id, status: 'waiting_confirmation',
        input_payload: { ...body.input, idempotency_key: body.idempotency_key }, result: null }
      state.commands.set(command.id, command); state.writes.push({ stage, body, commandId: command.id })
      if (state.loseCreate === stage) { state.loseCreate = ''; return route.abort('failed') }
      return fulfill(command)
    }
    if (method === 'POST' && url.pathname.endsWith('/confirm')) {
      const commandId = decodeURIComponent(url.pathname.split('/').at(-2)), command = state.commands.get(commandId)
      assert.ok(command); assert.equal(command.status, 'waiting_confirmation')
      const stage = Object.keys(tools).find((k) => tools[k] === command.tool_id), now = new Date().toISOString()
      state.confirms.push({ stage, commandId })
      Object.assign(command.input_payload, { confirmed_by_user: true, confirmed_actor_id: 'admin', confirmed_at: now })
      if (stage === 'grant') {
        const input = Object.fromEntries(Object.entries(command.input_payload).filter(([key]) => !['idempotency_key', 'confirmed_by_user', 'confirmed_actor_id', 'confirmed_at'].includes(key)))
        const grant = python('grant', { specimen: s, request: input, command: command.id })
        command.input_payload.confirmed_at = grant.metadata.recorded_at
        command.status = 'completed'; state.grants.set(grant.metadata.record_id, grant)
        command.result = { invocation_id: command.id, status: 'completed', object_refs: ['http_fixture_grant:' + grant.metadata.record_id], http_fixture_grant: grant }
      } else if (stage === 'execute') {
        command.status = 'running'; command.input_payload.fixture_claim_protocol = 'nasus.http-fixture-preparation.v1'
        state.jobs.set(command.id, { schema: 'nasus.http-fixture-job.v2', project_id: 'p', invocation_id: command.id,
          request_digest: digest({ tool_id: command.tool_id, input_payload: command.input_payload }),
          selection: Object.fromEntries(['project_id', 'grant_id', 'grant_digest', 'operation'].map((key) => [key, command.input_payload[key]])),
          status: 'running', phase: 'preparing', preparation_digest: digest(['explicit-preparation', command.id]), intent_digest: null, phases: [],
          target_observation_verified: false, cancellation_requested: false, cancellation_delivered: false,
          execution_authorized: false, canonical_execution_committed: false, business_coverage_verified: false, baseline_restored: false })
      } else {
        const target = state.commands.get(command.input_payload.invocation_id), job = state.jobs.get(target.id)
        target.status = job.status = 'cancelled'; job.phase = 'preparation_cancelled'; job.cancellation_requested = true
        command.status = 'completed'; command.result = { invocation_id: command.id, status: 'completed', object_refs: [] }
      }
      if (state.loseConfirm === stage) { state.loseConfirm = ''; return route.abort('failed') }
      return fulfill(command)
    }
    state.unexpected.push({ method, path: url.pathname }); return fulfill({ detail: 'Unconfigured browser protocol request' }, 503)
  })
  return { scope: 'component contract only', codeSources: s.builds.length, environmentCommand: e.metadata.invocation_id }
}

function finishExecution() {
  const command = [...state.commands.values()].find((c) => c.tool_id === tools.execute), old = state.jobs.get(command.id)
  const grant = state.grants.get(old.selection.grant_id).metadata, recipe = state.specimen.recipe.archive.request.manifest
  const phases = grant.operation === 'setup' ? ['setup'] : Object.keys(recipe.cleanup_groups).map((key) => 'cleanup:' + key)
  command.status = 'completed'; command.result = { invocation_id: command.id, status: 'completed', object_refs: [] }
  const { phase, preparation_digest, target_observation_verified, ...job } = old
  Object.assign(job, { schema: 'nasus.http-fixture-job.v1', status: 'completed', intent_digest: digest(['explicit-intent', command.id]),
    phases: phases.map((phase) => ({ phase, claim_id: 'fixture_' + digest(['p', grant.attempt_id, grant.scope.case_id, phase]).slice(7),
      state: 'observed', dispatch_digest: digest(['explicit-dispatch', phase]), result_digest: digest(['explicit-result', phase]), result_status: 'failed' })) })
  state.jobs.set(command.id, job)
}

function unknownExecution() {
  finishExecution()
  const command = [...state.commands.values()].find((c) => c.tool_id === tools.execute), job = state.jobs.get(command.id)
  command.status = job.status = 'running'; command.result = null
  for (const phase of job.phases) {
    phase.state = 'outcome_unknown'; delete phase.result_status; delete phase.result_digest
  }
}

function summary() {
  assert.deepEqual(state.unexpected, []); assert.deepEqual(state.errors, [])
  return { writes: state.writes.map((v) => v.stage), confirms: state.confirms.map((v) => v.stage), reads: state.reads.length,
    originalCommands: state.writes.map((v) => v.commandId), unexpected: state.unexpected, errors: state.errors }
}
module.exports = { install, summary, finishExecution, unknownExecution, configure: (patch) => Object.assign(state, patch), state: () => state }
