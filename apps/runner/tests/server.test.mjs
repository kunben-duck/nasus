import assert from 'node:assert/strict'
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
  if (runnerProcess && !runnerProcess.killed) runnerProcess.kill('SIGTERM')
  await new Promise((resolve) => targetServer.close(resolve))
})

test('requires service authentication and executes jobs over HTTP', async () => {
  const unauthorized = await fetch(`${runnerUrl}/v1/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  })
  assert.equal(unauthorized.status, 401)

  const response = await fetch(`${runnerUrl}/v1/jobs`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${serviceToken}`,
      'Content-Type': 'application/json',
      'X-Request-ID': 'request:runner-integration',
    },
    body: JSON.stringify({
      job_id: 'runner_http_integration',
      project_id: 'proj_runner',
      us_id: 'us_runner',
      base_url: targetUrl,
      timeout_ms: 20_000,
      steps: [
        { action: 'goto', path: '/' },
        { action: 'assert_text', selector: 'h1', text: 'Runner integration target' },
      ],
    }),
  })
  const result = await response.json()

  assert.equal(response.status, 200)
  assert.equal(response.headers.get('x-request-id'), 'request:runner-integration')
  assert.equal(result.status, 'passed')
  assert.ok(result.artifacts.some((artifact) => artifact.artifact_type === 'screenshot'))
  assert.ok(result.artifacts.some((artifact) => artifact.artifact_type === 'trace'))
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
