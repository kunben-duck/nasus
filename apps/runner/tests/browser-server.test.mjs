import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import http from 'node:http'
import { fileURLToPath } from 'node:url'
import { after, before, test } from 'node:test'

import { command } from './browser-fixtures.mjs'

const serviceToken = 'browser-intake-only-test-service-token'
let child, url, output = ''
const headers = { Authorization: `Bearer ${serviceToken}`, 'Content-Type': 'application/json' }

before(async () => {
  const reservation = http.createServer()
  await new Promise((resolve) => reservation.listen(0, '127.0.0.1', resolve))
  const port = reservation.address().port
  await new Promise((resolve) => reservation.close(resolve))
  url = `http://127.0.0.1:${port}`
  // Isolated new process for intake tests; never attach to or restart a running Runner.
  child = spawn(process.execPath, ['src/server.mjs'], {
    cwd: fileURLToPath(new URL('..', import.meta.url)), stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, NASUS_RUNNER_HOST: '127.0.0.1', NASUS_RUNNER_PORT: String(port),
      NASUS_RUNNER_SERVICE_TOKEN: serviceToken, NASUS_RUNNER_ALLOWED_HOSTS: '127.0.0.1' },
  })
  child.stdout.on('data', (chunk) => { output += chunk })
  child.stderr.on('data', (chunk) => { output += chunk })
  const deadline = Date.now() + 10000
  while (Date.now() < deadline) {
    try { if ((await fetch(url + '/healthz')).ok) return } catch {}
    await new Promise((resolve) => setTimeout(resolve, 20))
  }
  throw new Error('Isolated intake server did not start')
})

after(async () => {
  if (child && child.exitCode === null && child.signalCode === null) {
    const exited = new Promise((resolve) => child.once('exit', resolve))
    child.kill('SIGTERM')
    await exited
  }
})

test('versioned public browser route requires service auth and remains closed without private dispatcher', async () => {
  const unauthorized = await fetch(url + '/v1/browser/jobs', { method: 'POST', body: '{}' })
  assert.equal(unauthorized.status, 401)
  const response = await fetch(url + '/v1/browser/jobs', { method: 'POST', headers: { ...headers,
    'X-Request-ID': 'browser-intake-correlation' }, body: JSON.stringify(command()) })
  assert.equal(response.status, 200)
  assert.equal(response.headers.get('x-request-id'), 'browser-intake-correlation')
  const result = await response.json()
  assert.equal(result.status, 'error')
  assert.equal(result.failure_summary, 'private_dispatch_required')
  assert.equal(result.execution_receipt, undefined)
  assert.deepEqual(result.artifacts, [])
  assert.doesNotMatch(JSON.stringify(result), /registered\.example/)
})

test('formal browser wire rejects duplicate keys and never echoes sensitive raw operands into errors/logs', async () => {
  const raw = JSON.stringify(command())
  for (const body of [raw.replace('"steps":', '"steps":[],"steps":'), '{"secret":"vault://do-not-echo",',
    '{"job_id":"vault://do-not-echo", "receipt_protocol":"future"}']) {
    const response = await fetch(url + '/v1/browser/jobs', { method: 'POST', headers, body })
    const result = await response.json()
    assert.ok([200, 400].includes(response.status))
    assert.equal(result.execution_receipt, undefined)
    assert.doesNotMatch(JSON.stringify(result), /vault|do-not-echo/)
  }
  assert.doesNotMatch(output, /vault|do-not-echo|registered\.example/)
})

test('legacy endpoint still owns HTTP semantics and does not silently accept the formal browser protocol', async () => {
  const legacy = await fetch(url + '/v1/jobs', { method: 'POST', headers, body: JSON.stringify(command()) })
  const result = await legacy.json()
  assert.equal(legacy.status, 200)
  assert.equal(result.status, 'error')
  assert.equal(result.execution_receipt, undefined)
  assert.match(result.failure_summary, /receipt protocol is not supported/)
  const httpDuplicate = await fetch(url + '/v1/jobs', { method: 'POST', headers,
    body: '{"execution_kind":"http","steps":[],"steps":[]}' })
  assert.equal(httpDuplicate.status, 400)
  assert.equal((await httpDuplicate.json()).error, 'invalid_request')
  const unsupported = await fetch(url + '/v2/browser/jobs', { method: 'POST', headers, body: '{}' })
  assert.equal(unsupported.status, 404)
})
