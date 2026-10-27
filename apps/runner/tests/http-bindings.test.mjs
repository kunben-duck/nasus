import assert from 'node:assert/strict'
import { randomUUID } from 'node:crypto'
import http from 'node:http'
import { after, before, test } from 'node:test'

import { executeJob } from '../src/executor.mjs'
import { HTTP_BINDING_RECEIPT_SCHEMA, HTTP_RECEIPT_SCHEMA, requestHash } from '../src/execution-receipt.mjs'
import { validateHttpJob } from '../src/http-job.mjs'

let server, baseUrl, identity
const visits = [], sockets = new Set()
before(async () => {
  server = http.createServer(async (request, response) => {
    visits.push([request.method, request.url])
    const parts = []
    for await (const chunk of request) parts.push(chunk)
    let body, status = 200
    if (request.url === '/sessions') {
      identity = 'session_' + randomUUID()
      body = JSON.stringify({ sessionId: identity, status: 'ACTIVE', title: JSON.parse(Buffer.concat(parts).toString()).title })
    } else if (request.url === `/sessions/${identity}`) body = JSON.stringify({ sessionId: identity, status: 'ACTIVE' })
    else if (request.url === `/sessions/${identity}/close`) body = JSON.stringify({ sessionId: identity, status: 'CLOSED' })
    else if (request.url === '/duplicate') body = '{"id":"one","id":"one"}'
    else if (request.url === '/invalid-utf8') body = Buffer.from([0xff])
    else if (request.url.startsWith('/value?')) body = JSON.stringify({ id: JSON.parse(decodeURIComponent(request.url.split('?')[1])) })
    else if (request.url === '/escape-pointer') body = '{"a/b":{"~id":["resource_1"]}}'
    else if (request.url === '/root') body = '"root_resource"'
    else { status = 500; body = '{"id":"not_successful"}' }
    response.writeHead(status, { 'Content-Type': 'application/json' }); response.end(body)
  })
  server.on('connection', (socket) => { sockets.add(socket); socket.on('close', () => sockets.delete(socket)) })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  baseUrl = `http://127.0.0.1:${server.address().port}`
  process.env.NASUS_RUNNER_ALLOWED_HOSTS = '127.0.0.1'
})
after(async () => { for (const socket of sockets) socket.destroy(); await new Promise((resolve) => server.close(resolve)) })

const request = (request_id = 'create', path = '/sessions', method = 'POST') => ({ action: 'request', request_id,
  path, method, headers_json: '{"Content-Type":"application/json"}', body_json: method === 'POST' ? '{"title":"Independent fixture"}' : 'null' })
const capture = (pointer = '/sessionId', binding_id = 'session') => ({ action: 'capture_json', request_id: 'create', pointer, binding_id })
const oracle = (request_id, value) => ({ action: 'assert_json', request_id, pointer: '/status', value_json: JSON.stringify(value) })
const job = (steps, overrides = {}) => ({ job_id: 'binding-job', project_id: 'binding-project', us_id: 'binding-case',
  base_url: baseUrl, timeout_ms: 5000, metadata: {}, receipt_protocol: HTTP_BINDING_RECEIPT_SCHEMA, execution_kind: 'http', steps, ...overrides })

test('one actual HTTP job captures the original ID and creates, reads and closes without external stitching', async () => {
  visits.length = 0
  const steps = [request(), oracle('create', 'ACTIVE'), capture(), request('read', '/sessions/{{session}}', 'GET'),
    oracle('read', 'ACTIVE'), request('close', '/sessions/{{session}}/close'), oracle('close', 'CLOSED')]
  const raw = job(steps), wire = Buffer.from(JSON.stringify(raw))
  const result = await executeJob(raw, { wireBody: wire })
  assert.equal(result.status, 'passed', result.failure_summary)
  const receipt = result.execution_receipt
  assert.equal(receipt.schema, HTTP_BINDING_RECEIPT_SCHEMA)
  assert.equal(receipt.request_hash, requestHash(wire))
  assert.equal(receipt.assertion_count, 3)
  assert.equal(receipt.steps[2].kind, 'action')
  assert.deepEqual(receipt.steps.map((step) => step.status), Array(7).fill('passed'))
  assert.equal(receipt.bindings[0].value, identity)
  assert.equal(receipt.bindings[0].value_hash, requestHash(JSON.stringify(identity)))
  assert.equal(receipt.bindings[0].response_hash, receipt.requests[0].response_hash)
  assert.deepEqual(visits, [['POST', '/sessions'], ['GET', `/sessions/${identity}`], ['POST', `/sessions/${identity}/close`]])
  assert.deepEqual(receipt.requests.map((item) => item.binding_ids), [[], ['session'], ['session']])
  for (const [index, original] of steps.entries()) {
    if (original.action !== 'request') continue
    const actual = receipt.requests.find((item) => item.step_index === index)
    assert.equal(actual.declared_input_hash, requestHash(JSON.stringify([original.method, original.path, original.headers_json, original.body_json])))
    assert.equal(actual.input_hash, requestHash(JSON.stringify([original.method, actual.path, original.headers_json, original.body_json])))
    const metadata = JSON.parse(Buffer.from(result.artifacts.find((item) => item.name === `http-response-${original.request_id}.json`).content_base64, 'base64'))
    assert.equal(metadata.schema, 'nasus.http-response.v2')
    assert.equal(metadata.path, actual.path)
  }
  assert.equal(receipt.target_build_verified, false)
  assert.equal(receipt.business_coverage_verified, false)
})

test('a failed independent oracle stops the job and preserves only already observed bindings', async () => {
  visits.length = 0
  const result = await executeJob(job([request(), capture(), request('read', '/sessions/{{session}}', 'GET'),
    oracle('read', 'NOT_THE_ACTUAL_STATE'), request('close', '/sessions/{{session}}/close')]))
  assert.equal(result.status, 'failed')
  assert.equal(result.execution_receipt.bindings.length, 1)
  assert.equal(result.execution_receipt.failed_assertion_count, 1)
  assert.deepEqual(result.execution_receipt.steps.map((step) => step.status), ['passed', 'passed', 'passed', 'failed', 'not_executed'])
  assert.equal(visits.length, 2)
})

for (const value of [null, true, 1, {}, [], '', '.', '..', '../escape', 'a/b', 'a\\b', 'a%2fb', 'a?b', 'a#b',
  'https://elsewhere', '\u4e2d\u6587', 'a\n', 'x'.repeat(129)]) {
  test(`unsafe or non-string response ID is rejected without sending subsequent requests: ${JSON.stringify(value)}`, async () => {
    visits.length = 0
    const result = await executeJob(job([request('create', '/value?' + encodeURIComponent(JSON.stringify(value)), 'GET'), capture('/id'),
      request('later', '/sessions/{{session}}', 'GET')]))
    assert.equal(result.status, 'error')
    assert.deepEqual(result.execution_receipt.steps.map((step) => step.status), ['passed', 'interrupted', 'not_executed'])
    assert.deepEqual(result.execution_receipt.bindings, [])
    assert.equal(result.execution_receipt.observed_assertion_count, 0)
    assert.equal(visits.length, 1)
  })
}
for (const [path, pointer] of [['/duplicate', '/id'], ['/invalid-utf8', '/id'], ['/failed', '/id'], ['/root', '/absent']]) {
  test(`captures cannot use ambiguous, invalid, unsuccessful or missing JSON: ${path}`, async () => {
    const result = await executeJob(job([request('create', path, 'GET'), capture(pointer)]))
    assert.equal(result.status, 'error')
    assert.deepEqual(result.execution_receipt.bindings, [])
  })
}
for (const [path, pointer, value] of [['/escape-pointer', '/a~1b/~0id/0', 'resource_1'], ['/root', '', 'root_resource']]) {
  test(`strict JSON pointers preserve explicit root/escaped resource bindings: ${pointer}`, async () => {
    const result = await executeJob(job([request('create', path, 'GET'), capture(pointer)]))
    assert.equal(result.status, 'passed')
    assert.equal(result.execution_receipt.bindings[0].value, value)
    assert.equal(result.execution_receipt.assertion_count, 0)
  })
}

for (const [name, steps] of [
  ['forward reference', [request('create', '/sessions/{{session}}'), capture()]],
  ['unknown response', [capture()]], ['duplicate binding', [request(), capture(), capture()]],
  ['partial segment', [request(), capture(), request('read', '/sessions/prefix{{session}}')]],
  ['query binding', [request(), capture(), request('read', '/sessions?id={{session}}')]],
  ['unknown binding', [request(), capture(), request('read', '/sessions/{{another}}')]],
  ['binding identity', [request(), capture('/sessionId', '../path')]],
  ['extra oracle operand', [request(), { ...capture(), value_json: '"anything"' }]],
  ['bad pointer', [request(), capture('/~2')]],
  ['binding budget', [request(), ...Array.from({ length: 33 }, (_, i) => capture('/sessionId', `binding_${i}`))]],
]) test(`rejects ${name} before transport`, () => assert.throws(() => validateHttpJob(job(steps))))

test('v1 cannot silently gain capture actions or change its receipt shape', async () => {
  assert.throws(() => validateHttpJob(job([request(), capture()], { receipt_protocol: HTTP_RECEIPT_SCHEMA })))
  const result = await executeJob(job([request()], { receipt_protocol: HTTP_RECEIPT_SCHEMA }))
  assert.equal(result.status, 'passed')
  assert.equal(result.execution_receipt.schema, HTTP_RECEIPT_SCHEMA)
  assert.equal(Object.hasOwn(result.execution_receipt, 'bindings'), false)
  assert.equal(Object.hasOwn(result.execution_receipt.requests[0], 'declared_input_hash'), false)
})
