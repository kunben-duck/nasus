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
