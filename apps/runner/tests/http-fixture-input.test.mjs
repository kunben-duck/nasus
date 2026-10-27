import assert from 'node:assert/strict'
import http from 'node:http'
import { randomUUID } from 'node:crypto'
import { after, before, test } from 'node:test'
import { executeHttpJob } from '../src/http-executor.mjs'
import { HTTP_BINDING_RECEIPT_SCHEMA, HTTP_FIXTURE_RECEIPT_SCHEMA, requestHash } from '../src/execution-receipt.mjs'
import { fixtureInputHash } from '../src/http-fixture-input.mjs'
import { validateHttpJob } from '../src/http-job.mjs'

let server, base, original, resource, active = true
const visits = [], sockets = new Set()
const digest = (value) => fixtureInputHash(value)
const request = (request_id, path, method = 'GET') => ({ action: 'request', request_id, path, method,
  headers_json: '{}', body_json: method === 'GET' ? 'null' : '{}' })
const assertion = (request_id, value = 'ACTIVE') => ({ action: 'assert_json', request_id, pointer: '/status', value_json: JSON.stringify(value) })

before(async () => {
  server = http.createServer((request, response) => {
    visits.push([request.method, request.url])
    request.resume()
    if (request.method === 'POST' && request.url === '/sessions') resource = 'fixture_' + randomUUID()
    const found = request.url === '/sessions' && request.method === 'POST' || request.url === `/sessions/${resource}`
    response.writeHead(found ? 200 : 404, { 'Content-Type': 'application/json' })
    response.end(JSON.stringify(found ? { sessionId: resource, status: active ? 'ACTIVE' : 'CLOSED' } : { error: 'not_found' }))
  })
  server.on('connection', (socket) => { sockets.add(socket); socket.on('close', () => sockets.delete(socket)) })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  base = `http://127.0.0.1:${server.address().port}`
  process.env.NASUS_RUNNER_ALLOWED_HOSTS = '127.0.0.1'
  const scope = { project_id: 'fixture-project', attempt_id: 'setup-attempt', case_id: 'fixture-case',
    parent_digest: digest('plan'), data_manifest_hash: digest('manifest'), environment_id: 'fixture-environment',
    artifact_hash: digest('target'), inventory_hash: digest('inventory'), timeout_ms: 5000 }
  const source = { job_id: 'http-fixture-' + digest([digest(scope), 'setup']).slice(7), project_id: scope.project_id,
    us_id: scope.case_id, base_url: base, timeout_ms: scope.timeout_ms, execution_kind: 'http',
    metadata: { fixture_scope: scope, fixture_phase: 'setup', business_coverage_verified: false },
    receipt_protocol: HTTP_BINDING_RECEIPT_SCHEMA, steps: [request('create', '/sessions', 'POST'),
      { action: 'capture_json', request_id: 'create', pointer: '/sessionId', binding_id: 'session' },
      { action: 'assert_status', request_id: 'create', value: '200' }, assertion('create')] }
  const requestBody = Buffer.from(JSON.stringify(source)), result = await executeHttpJob(source, { wireBody: requestBody })
  assert.equal(result.status, 'passed')
  const resultBody = Buffer.from(JSON.stringify(result))
  const capsule = { schema: 'nasus.run-plan-case-fixture-captures.v1', scope_digest: digest('case-scope'),
    project_id: scope.project_id, run_plan_id: 'plan-id', run_plan_artifact_hash: digest('plan-artifact'), plan_digest: scope.parent_digest,
    case_id: scope.case_id, setup_invocation_id: 'setup-command', setup_history_digest: digest('history'),
    fixture_attempt_id: scope.attempt_id, data_manifest_hash: scope.data_manifest_hash, environment_id: scope.environment_id,
    target_artifact_hash: scope.artifact_hash, inventory_hash: scope.inventory_hash, environment_record_id: 'environment-record',
    environment_record_artifact_hash: digest('environment-record'), operator_policy_digest: digest('operator-policy'),
    setup_request_hash: requestHash(requestBody), setup_result_hash: requestHash(resultBody), captures: result.execution_receipt.bindings }
  original = { schema: 'nasus.runner-http-fixture-input.v1', capture_set: capsule, capture_set_digest: digest(capsule),
    source_request_body_base64: requestBody.toString('base64'), source_result_body_base64: resultBody.toString('base64') }
})
after(async () => { for (const socket of sockets) socket.destroy(); await new Promise((resolve) => server.close(resolve)) })

function job() {
  return { job_id: 'business-job', project_id: 'fixture-project', us_id: 'fixture-case', base_url: base,
    timeout_ms: 5000, execution_kind: 'http', receipt_protocol: HTTP_FIXTURE_RECEIPT_SCHEMA,
    metadata: { case_id: 'fixture-case', plan_digest: original.capture_set.plan_digest,
      fixture_scope_digest: original.capture_set.scope_digest, fixture_capture_digest: original.capture_set_digest },
    fixture_input: structuredClone(original), steps: [{ action: 'use_fixture_binding', binding_id: 'session', source_step_indices: [0] },
      { ...request('read', '/sessions/{{session}}'), source_step_indices: [0] }, { ...assertion('read'), source_step_indices: [0] }] }
}
function rehash(value) {
  value.fixture_input.capture_set_digest = digest(value.fixture_input.capture_set)
  value.metadata.fixture_capture_digest = value.fixture_input.capture_set_digest
}

test('two native HTTP jobs bind the original setup ID without repeating setup or rewriting the independent oracle', async () => {
  visits.length = 0
  const raw = job(), immutable = structuredClone(raw), wire = Buffer.from(JSON.stringify(raw))
  const result = await executeHttpJob(raw, { wireBody: wire }), receipt = result.execution_receipt
  assert.equal(result.status, 'passed')
  assert.deepEqual(visits, [['GET', `/sessions/${resource}`]])
  assert.deepEqual(raw, immutable)
  assert.equal(receipt.fixture_input_hash, digest(raw.fixture_input))
  assert.equal(receipt.fixture_capture_digest, original.capture_set_digest)
  assert.deepEqual(receipt.fixture_bindings, [{ step_index: 0, binding_id: 'session', capture_digest: original.capture_set_digest,
    value_hash: requestHash(JSON.stringify(resource)) }])
  assert.deepEqual(receipt.bindings, [])
  assert.equal(receipt.steps[0].kind, 'action')
  assert.equal(receipt.requests[0].path, `/sessions/${resource}`)
  assert.notEqual(receipt.requests[0].input_hash, receipt.requests[0].declared_input_hash)
  assert.equal(receipt.request_hash, requestHash(wire))
  assert.equal(receipt.assertion_count, 1)
  assert.equal(receipt.target_build_verified, false)
  assert.equal(receipt.business_coverage_verified, false)
})

test('an actual mismatching oracle remains failed with its original import and no later request', async () => {
  visits.length = 0; active = false
  try {
    const raw = job(); raw.steps.push(request('later', '/later'))
    const result = await executeHttpJob(raw)
    assert.equal(result.status, 'failed')
    assert.deepEqual(result.execution_receipt.steps.map((item) => item.status), ['passed', 'passed', 'failed', 'not_executed'])
    assert.equal(result.execution_receipt.fixture_bindings.length, 1)
    assert.equal(visits.length, 1)
  } finally { active = true }
})

test('fixture values never interpolate an independent expected-result operand', async () => {
  const raw = job()
  raw.steps[2].pointer = '/sessionId'
  raw.steps[2].value_json = '"{{session}}"'
  const result = await executeHttpJob(raw)
  assert.equal(result.status, 'failed')
  assert.equal(result.execution_receipt.failed_assertion_count, 1)
  assert.equal(raw.steps[2].value_json, '"{{session}}"')
})

for (const [name, fault] of [
  ['old protocol imports', (raw) => { raw.receipt_protocol = HTTP_BINDING_RECEIPT_SCHEMA }],
  ['missing source', (raw) => { delete raw.fixture_input }],
  ['caller verified flag', (raw) => { raw.fixture_input.verified = true }],
  ['wrong case', (raw) => { raw.us_id = 'another-case' }],
  ['wrong target origin', (raw) => { raw.base_url = 'http://127.0.0.1:8080' }],
  ['rehashed wrong plan', (raw) => { raw.fixture_input.capture_set.plan_digest = digest('another-plan'); rehash(raw); raw.metadata.plan_digest = raw.fixture_input.capture_set.plan_digest }],
  ['setup bytes', (raw) => { raw.fixture_input.source_result_body_base64 += '\n' }],
  ['oversized original source', (raw) => { raw.fixture_input.source_result_body_base64 = 'A'.repeat(350000) }],
  ['missing capture', (raw) => { raw.fixture_input.capture_set.captures = []; rehash(raw) }],
  ['duplicate capture', (raw) => { raw.fixture_input.capture_set.captures.push(structuredClone(raw.fixture_input.capture_set.captures[0])); rehash(raw) }],
  ['binding used before import', (raw) => { [raw.steps[0], raw.steps[1]] = [raw.steps[1], raw.steps[0]] }],
  ['unknown binding', (raw) => { raw.steps[0].binding_id = 'other' }],
  ['duplicate import', (raw) => { raw.steps.unshift(structuredClone(raw.steps[0])) }],
  ['import with oracle operand', (raw) => { raw.steps[0].value_json = '"ACTIVE"' }],
  ['query substitution', (raw) => { raw.steps[1].path = '/sessions?id={{session}}' }],
  ['partial path substitution', (raw) => { raw.steps[1].path = '/sessions/prefix{{session}}' }],
  ['rehashed wrong capture pointer', (raw) => { raw.fixture_input.capture_set.captures[0].pointer = '/status'; rehash(raw) }],
  ['rehashed unsafe value', (raw) => { raw.fixture_input.capture_set.captures[0].value = '../escape'; rehash(raw) }],
]) test(`rejects ${name} before any business transport`, () => {
  visits.length = 0
  const raw = job(); fault(raw)
  assert.throws(() => validateHttpJob(raw))
  assert.deepEqual(visits, [])
})

test('self-consistent forged receipt and value hashes cannot replace the original source response', () => {
  const raw = job(), input = raw.fixture_input
  const output = JSON.parse(Buffer.from(input.source_result_body_base64, 'base64'))
  const fake = 'forged_resource', capture = output.execution_receipt.bindings[0]
  capture.value = fake; capture.value_hash = requestHash(JSON.stringify(fake))
  output.artifacts.find((item) => item.name === 'http-execution.json').content_base64 = Buffer.from(JSON.stringify(output.execution_receipt)).toString('base64')
  const resultBody = Buffer.from(JSON.stringify(output))
  input.source_result_body_base64 = resultBody.toString('base64')
  input.capture_set.setup_result_hash = requestHash(resultBody)
  input.capture_set.captures = structuredClone(output.execution_receipt.bindings)
  rehash(raw)
  assert.throws(() => validateHttpJob(raw))
})

test('rehashed setup success cannot conceal a source oracle contradicted by its actual response', () => {
  const raw = job(), input = raw.fixture_input
  const source = JSON.parse(Buffer.from(input.source_request_body_base64, 'base64'))
  source.steps[2].value = '404'
  const requestBody = Buffer.from(JSON.stringify(source)), output = JSON.parse(Buffer.from(input.source_result_body_base64, 'base64'))
  output.execution_receipt.request_hash = requestHash(requestBody)
  output.artifacts.find((item) => item.name === 'http-execution.json').content_base64 = Buffer.from(JSON.stringify(output.execution_receipt)).toString('base64')
  const resultBody = Buffer.from(JSON.stringify(output))
  input.source_request_body_base64 = requestBody.toString('base64')
  input.source_result_body_base64 = resultBody.toString('base64')
  input.capture_set.setup_request_hash = requestHash(requestBody)
  input.capture_set.setup_result_hash = requestHash(resultBody)
  rehash(raw)
  assert.throws(() => validateHttpJob(raw))
})
