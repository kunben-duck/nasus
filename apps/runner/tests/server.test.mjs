import assert from 'node:assert/strict'
import crypto from 'node:crypto'
import { spawn } from 'node:child_process'
import http from 'node:http'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { after, before, test } from 'node:test'

const runnerRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const serviceToken = 'runner-test-service-token-1234567890'
let targetServer
let targetUrl
let runnerProcess
let runnerUrl
let slowHttpStarted = false, slowHttpClosed = false, laterHttpRequests = 0

async function availablePort() {
  const server = http.createServer()
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  const port = server.address().port
  await new Promise((resolve) => server.close(resolve))
  return port
}

async function waitForReady(url) {
  const deadline = Date.now() + 15_000
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url)
      if (response.ok) return
    } catch {
      // The child process may still be loading Chromium metadata.
    }
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  throw new Error(`Runner did not become ready at ${url}`)
}

before(async () => {
  targetServer = http.createServer((request, response) => {
    if (request.url === '/slow-http') {
      slowHttpStarted = true
      const timer = setTimeout(() => response.end('late response'), 5000)
      response.on('close', () => { clearTimeout(timer); slowHttpClosed = true })
      return
    }
    if (request.url === '/later-http') laterHttpRequests++
    response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
    response.end('<main><h1>Runner integration target</h1></main>')
  })
  await new Promise((resolve) => targetServer.listen(0, '127.0.0.1', resolve))
  targetUrl = `http://127.0.0.1:${targetServer.address().port}`

  const runnerPort = await availablePort()
  runnerUrl = `http://127.0.0.1:${runnerPort}`
  runnerProcess = spawn(process.execPath, ['src/server.mjs'], {
    cwd: runnerRoot,
    env: {
      ...process.env,
      NASUS_RUNNER_HOST: '127.0.0.1',
      NASUS_RUNNER_PORT: String(runnerPort),
      NASUS_RUNNER_SERVICE_TOKEN: serviceToken,
      NASUS_RUNNER_ALLOWED_HOSTS: '127.0.0.1',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  await waitForReady(`${runnerUrl}/readyz`)
})

after(async () => {
  if (runnerProcess && runnerProcess.exitCode === null && runnerProcess.signalCode === null) {
    const exited = new Promise((resolve) => runnerProcess.once('exit', resolve))
    runnerProcess.kill('SIGTERM')
    await exited
  }
  await new Promise((resolve) => targetServer.close(resolve))
})

test('requires service authentication and executes jobs over HTTP', async () => {
  const unauthorized = await fetch(`${runnerUrl}/v1/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  })
  assert.equal(unauthorized.status, 401)

  const body = JSON.stringify({
    job_id: 'runner_http_integration', project_id: 'proj_runner', us_id: 'us_runner',
    base_url: targetUrl, timeout_ms: 20_000, metadata: { private_note: 'not receipt authority' },
    receipt_protocol: 'nasus.runner-execution.v1', steps: [
      { action: 'goto', path: '/' },
      { action: 'assert_text', selector: 'h1', text: 'Runner integration target' },
    ],
  }, null, 2)
  const response = await fetch(`${runnerUrl}/v1/jobs`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${serviceToken}`,
      'Content-Type': 'application/json',
      'X-Request-ID': 'request:runner-integration',
    },
    body,
  })
  const result = await response.json()

  assert.equal(response.status, 200)
  assert.equal(response.headers.get('x-request-id'), 'request:runner-integration')
  assert.equal(result.status, 'passed')
  assert.ok(result.artifacts.some((artifact) => artifact.artifact_type === 'screenshot'))
  assert.ok(result.artifacts.some((artifact) => artifact.artifact_type === 'trace'))
  assert.equal(result.execution_receipt.request_hash, `sha256:${crypto.createHash('sha256').update(body).digest('hex')}`)
  assert.equal(result.execution_receipt.passed_assertion_count, 1)
  assert.equal(result.execution_receipt.business_coverage_verified, false)
})

test('protects and exports low-cardinality operational metrics', async () => {
  const anonymous = await fetch(`${runnerUrl}/metrics`)
  assert.equal(anonymous.status, 401)

  const response = await fetch(`${runnerUrl}/metrics`, {
    headers: { Authorization: `Bearer ${serviceToken}` },
  })
  const metrics = await response.text()

  assert.equal(response.status, 200)
  assert.match(response.headers.get('content-type'), /text\/plain/)
  assert.match(metrics, /nasus_runner_active_jobs 0/)
  assert.match(metrics, /nasus_runner_max_concurrency/)
  assert.match(metrics, /nasus_runner_browser_ready 1/)
  assert.match(metrics, /nasus_runner_jobs_total\{status="passed"\} 1/)
  assert.match(metrics, /nasus_runner_rejections_total\{reason="unauthorized"\}/)
  assert.match(metrics, /nasus_runner_job_duration_seconds_count 1/)
})

const httpJob = (steps) => ({ job_id: 'native-http-server', project_id: 'fixture-project', us_id: 'fixture-case',
  execution_kind: 'http', receipt_protocol: 'nasus.runner-http-execution.v1', base_url: targetUrl,
  timeout_ms: 10000, steps })
const httpStep = (path, request_id = 'original') => ({ action: 'request', request_id, method: 'GET', path, headers_json: '{}', body_json: 'null' })

test('HTTP jobs share authentication but use their own exact wire and oracle receipt', async () => {
  const body = JSON.stringify(httpJob([httpStep('/'), { action: 'assert_body', request_id: 'original', value: 'Runner integration target' }]), null, 2)
  const result = await fetch(runnerUrl + '/v1/jobs', { method: 'POST', headers: {
    Authorization: `Bearer ${serviceToken}`, 'Content-Type': 'application/json' }, body })
  const payload = await result.json()
  assert.equal(result.status, 200)
  assert.equal(payload.status, 'passed')
  assert.equal(payload.execution_receipt.request_hash, `sha256:${crypto.createHash('sha256').update(body).digest('hex')}`)
  assert.equal(payload.execution_receipt.passed_assertion_count, 1)
  assert.equal(payload.execution_receipt.business_coverage_verified, false)
})

test('HTTP caller disconnect cancels the active request and releases runner capacity', async () => {
  const body = JSON.stringify(httpJob([httpStep('/slow-http'), httpStep('/later-http', 'later')]))
  const client = http.request(runnerUrl + '/v1/jobs', { method: 'POST', headers: {
    Authorization: `Bearer ${serviceToken}`, 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) } })
  client.on('error', () => {})
  client.end(body)
  const deadline = Date.now() + 10000
  while (!slowHttpStarted) { assert.ok(Date.now() < deadline); await new Promise((resolve) => setTimeout(resolve, 5)) }
  client.destroy()
  while (!slowHttpClosed) { assert.ok(Date.now() < deadline); await new Promise((resolve) => setTimeout(resolve, 5)) }
  let idle = false
  while (!idle) {
    assert.ok(Date.now() < deadline)
    const metrics = await fetch(runnerUrl + '/metrics', { headers: { Authorization: `Bearer ${serviceToken}` } })
    idle = /nasus_runner_active_jobs 0/.test(await metrics.text())
  }
  assert.equal(laterHttpRequests, 0)
})

test('duplicate HTTP wire keys are rejected without creating an execution receipt', async () => {
  const body = JSON.stringify(httpJob([httpStep('/')])).replace('"steps":', '"steps":[],"steps":')
  const response = await fetch(runnerUrl + '/v1/jobs', { method: 'POST', headers: {
    Authorization: `Bearer ${serviceToken}`, 'Content-Type': 'application/json' }, body })
  const result = await response.json()
  assert.equal(response.status, 400)
  assert.equal(result.error, 'invalid_request')
  assert.equal(result.execution_receipt, undefined)
})

test('fixture resource imports cannot bypass the owned-target worker through the public job endpoint', async () => {
  const body = JSON.stringify({ ...httpJob([httpStep('/')]), receipt_protocol: 'nasus.runner-http-execution.v3',
    fixture_input: { private_resource: 'must-not-be-echoed' } })
  const response = await fetch(runnerUrl + '/v1/jobs', { method: 'POST', headers: {
    Authorization: `Bearer ${serviceToken}`, 'Content-Type': 'application/json' }, body })
  const result = await response.json()
  assert.equal(response.status, 400)
  assert.equal(result.error, 'invalid_request')
  assert.equal(result.execution_receipt, undefined)
  assert.equal(result.message, 'Fixture imports require the private owned-target worker.')
  assert.equal(JSON.stringify(result).includes('must-not-be-echoed'), false)
})
