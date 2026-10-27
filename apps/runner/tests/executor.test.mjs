import assert from 'node:assert/strict'
import http from 'node:http'
import { after, before, test } from 'node:test'

import { executeJob } from '../src/executor.mjs'

let targetServer
let baseUrl

before(async () => {
  targetServer = http.createServer((request, response) => {
    response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
    response.end(`
      <!doctype html>
      <html>
        <body>
          <label>Name <input id="name" /></label>
          <button id="submit" onclick="document.querySelector('#result').textContent = 'Hello ' + document.querySelector('#name').value">Submit</button>
          <p id="result"></p>
        </body>
      </html>
    `)
  })
  await new Promise((resolve) => targetServer.listen(0, '127.0.0.1', resolve))
  const address = targetServer.address()
  baseUrl = `http://127.0.0.1:${address.port}`
  process.env.NASUS_RUNNER_ALLOWED_HOSTS = '127.0.0.1'
})

after(async () => {
  await new Promise((resolve) => targetServer.close(resolve))
})

test('executes a structured Playwright job and returns real evidence', async () => {
  const result = await executeJob({
    job_id: 'runner_job_success',
    project_id: 'proj_runner',
    us_id: 'us_runner',
    base_url: baseUrl,
    timeout_ms: 20_000,
    steps: [
      { action: 'goto', path: '/' },
      { action: 'fill', selector: '#name', value: 'Nasus' },
      { action: 'click', selector: '#submit' },
      { action: 'assert_text', selector: '#result', text: 'Hello Nasus' },
    ],
  })

  assert.equal(
    result.status,
    'passed',
    result.failure_summary || `Runner timeline: ${JSON.stringify(result.timeline)}`,
  )
  assert.match(result.summary, /4 structured Playwright steps/)
  assert.ok(result.timeline.length >= 4)
  const artifactTypes = new Set(result.artifacts.map((artifact) => artifact.artifact_type))
  assert.ok(artifactTypes.has('script'))
  assert.ok(artifactTypes.has('screenshot'))
  assert.ok(artifactTypes.has('trace'))
  assert.ok(artifactTypes.has('log'))
  assert.ok(result.artifacts.every((artifact) => artifact.content_base64.length > 0))
  assert.deepEqual(result.execution_receipt.steps.map((step) => step.status), ['passed', 'passed', 'passed', 'passed'])
  assert.equal(result.execution_receipt.assertion_count, 1)
  assert.equal(result.execution_receipt.passed_assertion_count, 1)
  assert.equal(result.execution_receipt.business_coverage_verified, false)
})

test('fails closed and captures artifacts when an assertion fails', async () => {
  const result = await executeJob({
    job_id: 'runner_job_failure',
    project_id: 'proj_runner',
    us_id: 'us_runner',
    base_url: baseUrl,
    timeout_ms: 20_000,
    steps: [
      { action: 'goto', path: '/' },
      { action: 'assert_text', selector: '#result', text: 'This text is absent' },
    ],
  })

  assert.equal(result.status, 'failed')
  assert.ok(result.failure_summary)
  assert.match(result.failure_fingerprint, /^sha256:/)
  assert.ok(result.artifacts.some((artifact) => artifact.artifact_type === 'failure_artifact'))
  assert.deepEqual(result.execution_receipt.steps.map((step) => step.status), ['passed', 'failed'])
  assert.equal(result.execution_receipt.failed_assertion_count, 1)
})

test('rejects unapproved targets and empty step lists before launching a browser', async () => {
  const result = await executeJob({
    job_id: 'runner_job_invalid',
    project_id: 'proj_runner',
    us_id: 'us_runner',
    base_url: 'https://unapproved.example.com',
    steps: [],
  })

  assert.equal(result.status, 'error')
  assert.match(result.failure_summary, /not allowed|at least one structured step/i)
  assert.ok(result.artifacts.some((artifact) => artifact.artifact_type === 'failure_artifact'))
})

test('a job deadline preserves interrupted and never-run assertions', async () => {
  const result = await executeJob({ job_id: 'runner_deadline', project_id: 'proj_runner', us_id: 'us_runner',
    base_url: baseUrl, timeout_ms: 1000, steps: [
      { action: 'goto', path: '/' }, { action: 'wait_for', selector: '#never-present', timeout_ms: 30_000 },
      { action: 'assert_text', text: 'not observed' },
    ] })
  assert.equal(result.status, 'timed_out')
  assert.deepEqual(result.execution_receipt.steps.map((step) => step.status), ['passed', 'interrupted', 'not_executed'])
  assert.equal(result.execution_receipt.observed_assertion_count, 0)
  assert.equal(result.execution_receipt.passed_assertion_count, 0)
})

test('navigation-only success is not an assertion pass', async () => {
  const result = await executeJob({ job_id: 'runner_navigation', project_id: 'proj_runner', us_id: 'us_runner',
    base_url: baseUrl, steps: [{ action: 'goto', path: '/' }] })
  assert.equal(result.status, 'passed')
  assert.equal(result.execution_receipt.assertion_count, 0)
  assert.equal(result.execution_receipt.passed_assertion_count, 0)
})

test('empty or missing oracles and unsupported receipt protocols are rejected before execution', async () => {
  for (const step of [{ action: 'assert_text', text: '' }, { action: 'assert_text' }, { action: 'assert_url', value: '' }]) {
    const result = await executeJob({ job_id: 'runner_empty_oracle', project_id: 'proj_runner', us_id: 'us_runner',
      base_url: baseUrl, steps: [{ action: 'goto', path: '/' }, step] })
    assert.equal(result.status, 'error')
    assert.equal(result.execution_receipt, undefined)
  }
  const result = await executeJob({ job_id: 'runner_protocol', project_id: 'proj_runner', us_id: 'us_runner',
    base_url: baseUrl, steps: [{ action: 'goto', path: '/' }], receipt_protocol: 'future' })
  assert.equal(result.status, 'error')
  assert.equal(result.execution_receipt, undefined)
})
