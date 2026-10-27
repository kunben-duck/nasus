import assert from 'node:assert/strict'
import http from 'node:http'
import { after, before, test } from 'node:test'

import { executeJob } from '../src/executor.mjs'
import { HTTP_RECEIPT_SCHEMA, requestHash } from '../src/execution-receipt.mjs'
import { validateHttpJob } from '../src/http-job.mjs'
import { pinHttpTarget } from '../src/http-transport.mjs'
import { jsonPointer, strictJson } from '../src/strict-json.mjs'

let target, baseUrl
const visits = [], sockets = new Set()
before(async () => {
  target = http.createServer(async (request, response) => {
    visits.push(request.url)
    const chunks = []
    for await (const chunk of request) chunks.push(chunk)
    if (request.url === '/slow') {
      const timer = setTimeout(() => response.end('late response'), 2000)
      response.on('close', () => clearTimeout(timer))
      return
    }
    if (request.url === '/redirect') { response.writeHead(302, { Location: baseUrl + '/forbidden-redirect' }); response.end('redirect'); return }
    if (request.url === '/oversize') { response.end(Buffer.alloc(1024 * 1024 + 1, 'x')); return }
    if (request.url === '/megabyte') { response.end(Buffer.alloc(1024 * 1024, 'x')); return }
    if (request.url === '/empty') { response.writeHead(204); response.end(); return }
    if (request.url === '/invalid-utf8') { response.end(Buffer.from([0xff])); return }
    if (request.url === '/duplicate') { response.end('{"value":1,"value":1}'); return }
    if (request.url === '/precise') { response.end('{"value":0.10000000000000000001}'); return }
    if (request.url === '/scalar') { response.end('1'); return }
    response.writeHead(request.url === '/failure' ? 500 : 200, { 'Content-Type': 'application/json; charset=utf-8', 'X-Proof': 'observed' })
    response.end(JSON.stringify({ message: 'HTTP fixture', nested: { 'a/b': { '~name': [1, true] } }, body: Buffer.concat(chunks).toString('utf8') }))
  })
  target.on('connection', (socket) => { sockets.add(socket); socket.on('close', () => sockets.delete(socket)) })
  await new Promise((resolve) => target.listen(0, '127.0.0.1', resolve))
  baseUrl = `http://127.0.0.1:${target.address().port}`
  process.env.NASUS_RUNNER_ALLOWED_HOSTS = '127.0.0.1'
})
after(async () => { for (const socket of sockets) socket.destroy(); await new Promise((resolve) => target.close(resolve)) })

const request = (path = '/', request_id = 'original') => ({ action: 'request', request_id, method: 'GET', path,
  headers_json: '{"Accept":"application/json"}', body_json: 'null', source_step_indices: [0] })
const job = (steps, extra = {}) => ({ job_id: 'http-job', project_id: 'http-project', us_id: 'http-case',
  execution_kind: 'http', receipt_protocol: HTTP_RECEIPT_SCHEMA, base_url: baseUrl, timeout_ms: 5000, steps, ...extra })
const assertion = (action, fields = {}) => ({ action, request_id: 'original', source_step_indices: [0], ...fields })

test('executes real HTTP requests and all four oracle kinds with original byte receipts', async () => {
  const raw = job([request(), assertion('assert_status', { value: '200' }),
    assertion('assert_json', { pointer: '/nested/a~1b/~0name/0', value_json: '1.0' }),
    assertion('assert_header', { name: 'X-Proof', value: 'observed' }), assertion('assert_body', { value: 'HTTP fixture' })])
  const wire = Buffer.from(JSON.stringify(raw, null, 2))
  const result = await executeJob(raw, { wireBody: wire })
  assert.equal(result.status, 'passed', result.failure_summary)
  const receipt = result.execution_receipt
  assert.equal(receipt.schema, HTTP_RECEIPT_SCHEMA)
  assert.equal(receipt.request_hash, requestHash(wire))
  assert.equal(receipt.passed_assertion_count, 4)
  assert.deepEqual(receipt.steps.map((step) => step.status), Array(5).fill('passed'))
  assert.equal(receipt.target_build_verified, false)
  assert.equal(receipt.business_coverage_verified, false)
  const body = Buffer.from(result.artifacts.find((item) => item.name === 'http-response-original.bin').content_base64, 'base64')
  const metadata = Buffer.from(result.artifacts.find((item) => item.name === 'http-response-original.json').content_base64, 'base64')
  assert.equal(receipt.requests[0].response_hash, requestHash(body))
  assert.equal(receipt.requests[0].response_byte_count, body.length)
  assert.equal(receipt.requests[0].response_metadata_hash, requestHash(metadata))
  assert.equal(JSON.parse(metadata).headers['x-proof'], 'observed')
})

test('preserves exact submitted JSON request bytes and a Unicode request identity', async () => {
  const original = { ...request('/', 'request_\u6d4b\u8bd5'), method: 'POST', body_json: '{ "second": 2, "first": "\\u4e2d" }' }
  const result = await executeJob(job([original, { action: 'assert_json', request_id: original.request_id,
    pointer: '/body', value_json: JSON.stringify(original.body_json) }]))
  assert.equal(result.status, 'passed')
  assert.equal(result.execution_receipt.requests[0].input_hash,
    requestHash(JSON.stringify([original.method, original.path, original.headers_json, original.body_json])))
})

test('a response, including HTTP 500, is not a passed oracle and later requests are not sent', async () => {
  visits.length = 0
  const result = await executeJob(job([request('/failure'), assertion('assert_status', { value: '200' }), request('/must-not-run', 'later')]))
  assert.equal(result.status, 'failed')
  assert.deepEqual(result.execution_receipt.steps.map((step) => step.status), ['passed', 'failed', 'not_executed'])
  assert.equal(result.execution_receipt.requests[0].response_status, 500)
  assert.equal(result.execution_receipt.failed_assertion_count, 1)
  assert.deepEqual(visits, ['/failure'])
})

test('redirects are observed, never followed', async () => {
  visits.length = 0
  const result = await executeJob(job([request('/redirect'), assertion('assert_status', { value: '302' })]))
  assert.equal(result.status, 'passed')
  assert.deepEqual(visits, ['/redirect'])
})

test('empty response bytes remain a verifiable artifact without inventing assertions', async () => {
  const result = await executeJob(job([request('/empty')]))
  assert.equal(result.status, 'passed')
  assert.equal(result.execution_receipt.observed_assertion_count, 0)
  assert.equal(result.execution_receipt.requests[0].response_byte_count, 0)
  assert.equal(result.artifacts.find((item) => item.name === 'http-response-original.bin').content_base64, '')
})

for (const [path, oracle] of [['/duplicate', { pointer: '/value', value_json: '1' }],
  ['/precise', { pointer: '/value', value_json: '0.1' }], ['/scalar', { pointer: '/decimal', value_json: '"1e0"' }],
  ['/', { pointer: '/nested/a~1b/~0name/1', value_json: '1' }], ['/', { pointer: '/absent', value_json: 'null' }]]) {
  test(`ambiguous, missing, rounded or type-incompatible JSON fails: ${path} ${oracle.pointer}`, async () => {
    const result = await executeJob(job([request(path), assertion('assert_json', oracle)]))
    assert.equal(result.status, 'failed')
    assert.equal(result.execution_receipt.passed_assertion_count, 0)
  })
}

test('invalid UTF-8 is not silently replaced for a text oracle', async () => {
  const result = await executeJob(job([request('/invalid-utf8'), assertion('assert_body', { value: '\ufffd' })]))
  assert.equal(result.status, 'failed')
})

for (const [name, alter] of [
  ['protocol', (raw) => { raw.receipt_protocol = 'future' }], ['unknown field', (raw) => { raw.authorized = true }],
  ['credential origin', (raw) => { raw.base_url = 'http://user:secret@127.0.0.1' }],
  ['origin path', (raw) => { raw.base_url += '/business' }], ['deadline bool', (raw) => { raw.timeout_ms = true }],
  ['missing operand', (raw) => { delete raw.steps[0].body_json }], ['external path', (raw) => { raw.steps[0].path = '//unapproved.test/' }],
  ['credential header', (raw) => { raw.steps[0].headers_json = '{"Authorization":"secret"}' }],
  ['duplicate keys', (raw) => { raw.steps[0].headers_json = '{"Accept":"a","\\u0041ccept":"b"}' }],
  ['private malformed key', (raw) => { raw.steps[0].method = 'POST'; raw.steps[0].body_json = '{"private-fixture-\\q":1}' }],
  ['GET body', (raw) => { raw.steps[0].body_json = '{}' }], ['duplicate request ID', (raw) => { raw.steps.push(request()) }],
  ['missing request', (raw) => { raw.steps.unshift(assertion('assert_status', { value: '200' })) }],
  ['invalid oracle', (raw) => { raw.steps.push(assertion('assert_json', { pointer: '/value', value_json: 'NaN' })) }],
  ['unsafe integer', (raw) => { raw.steps.push(assertion('assert_json', { pointer: '', value_json: '9007199254740992' })) }],
  ['oversize numeric spelling', (raw) => { raw.steps.push(assertion('assert_json', { pointer: '', value_json: '0.' + '0'.repeat(256) + '1' })) }],
  ['excessive nesting', (raw) => { raw.steps.push(assertion('assert_json', { pointer: '', value_json: '['.repeat(65) + ']'.repeat(65) })) }],
  ['pointer escape', (raw) => { raw.steps.push(assertion('assert_json', { pointer: '/~2', value_json: 'null' })) }],
  ['unexpected action field', (raw) => { raw.steps[0].shell = 'must never execute' }],
]) {
  test(`the complete job is rejected before any request: ${name}`, async () => {
    visits.length = 0
    const raw = job([request()]); alter(raw)
    assert.throws(() => validateHttpJob(raw))
    const result = await executeJob(raw)
    assert.equal(result.status, 'error')
    assert.equal(result.execution_receipt, undefined)
    assert.ok(!result.failure_summary.includes('private-fixture'))
    assert.deepEqual(visits, [])
  })
}

test('deadline aborts the original request and seals never-run oracle states', async () => {
  visits.length = 0
  const result = await executeJob(job([request('/slow'), assertion('assert_status', { value: '200' })], { timeout_ms: 1000 }))
  assert.equal(result.status, 'timed_out')
  assert.deepEqual(result.execution_receipt.steps.map((step) => step.status), ['interrupted', 'not_executed'])
  assert.equal(result.execution_receipt.requests.length, 0)
  assert.equal(result.execution_receipt.observed_assertion_count, 0)
  const fixed = JSON.stringify(result)
  await new Promise((resolve) => setTimeout(resolve, 1100))
  assert.equal(JSON.stringify(result), fixed)
  assert.deepEqual(visits, ['/slow'])
})

test('caller cancellation aborts active sockets and does not run a later request', async () => {
  visits.length = 0
  const controller = new AbortController()
  const running = executeJob(job([request('/slow'), request('/later', 'later')]), { signal: controller.signal })
  while (!visits.length) await new Promise((resolve) => setTimeout(resolve, 5))
  controller.abort()
  const result = await running
  assert.equal(result.status, 'error')
  assert.deepEqual(result.execution_receipt.steps.map((step) => step.status), ['interrupted', 'not_executed'])
  assert.deepEqual(visits, ['/slow'])
})

test('oversized or incomplete response cannot become a passed request', async () => {
  const result = await executeJob(job([request('/oversize'), assertion('assert_status', { value: '200' })]))
  assert.equal(result.status, 'error')
  assert.equal(result.execution_receipt.requests.length, 0)
  assert.deepEqual(result.execution_receipt.steps.map((step) => step.status), ['interrupted', 'not_executed'])
})

test('the aggregate byte budget preserves the original complete responses and stops overflow', async () => {
  const result = await executeJob(job(Array.from({ length: 17 }, (_value, index) => request('/megabyte', 'response_' + index))))
  assert.equal(result.status, 'error')
  assert.equal(result.execution_receipt.requests.length, 16)
  assert.equal(result.execution_receipt.steps[16].status, 'interrupted')
  assert.equal(result.execution_receipt.requests.reduce((sum, item) => sum + item.response_byte_count, 0), 16 * 1024 * 1024)
})

test('exact operator hosts are required and metadata, link-local and mapped IPs stay blocked', async () => {
  const savedHosts = process.env.NASUS_RUNNER_ALLOWED_HOSTS, savedEnv = process.env.NASUS_ENV
  try {
    process.env.NASUS_ENV = 'production'; delete process.env.NASUS_RUNNER_ALLOWED_HOSTS
    await assert.rejects(pinHttpTarget(new URL(baseUrl), AbortSignal.timeout(1000)))
    for (const host of ['169.254.169.254', '100.100.100.200', '[::ffff:127.0.0.1]', '[fe80::1]', '[fd00:ec2::254]', '224.0.0.1', '0.0.0.0']) {
      process.env.NASUS_RUNNER_ALLOWED_HOSTS = host.replace(/^\[|\]$/g, '')
      await assert.rejects(pinHttpTarget(new URL('http://' + host), AbortSignal.timeout(1000)))
    }
    process.env.NASUS_RUNNER_ALLOWED_HOSTS = '*.example.test'
    await assert.rejects(pinHttpTarget(new URL('https://app.example.test'), AbortSignal.timeout(1000)))
    process.env.NASUS_RUNNER_ALLOWED_HOSTS = 'localhost'
    const pinned = await pinHttpTarget(new URL('http://localhost'), AbortSignal.timeout(1000))
    assert.ok(['127.0.0.1', '::1'].includes(pinned.address.address))
  } finally {
    process.env.NASUS_RUNNER_ALLOWED_HOSTS = savedHosts
    if (savedEnv === undefined) delete process.env.NASUS_ENV; else process.env.NASUS_ENV = savedEnv
  }
})

test('strict JSON supports root/escaped pointers and rejects aliases of scalar numbers', () => {
  assert.deepEqual(jsonPointer(strictJson('{"a/b":{"~key": [1]}}'), '/a~1b/~0key/0'), 1)
  assert.equal(jsonPointer(strictJson('true'), ''), true)
  assert.throws(() => jsonPointer(strictJson('[1]'), '/00'))
  assert.throws(() => jsonPointer(strictJson('{"x":1}'), '/toString'))
  assert.throws(() => strictJson('{"x":{"a":1,"a":2}}'))
  assert.throws(() => strictJson('1e999'))
  assert.doesNotThrow(() => validateHttpJob(job([request(), assertion('assert_json', { pointer: '', value_json: 'null' })])))
})
