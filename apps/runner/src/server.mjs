import crypto from 'node:crypto'
import http from 'node:http'

import { executeJob, runnerBrowserAvailable } from './executor.mjs'

const port = Number.parseInt(process.env.NASUS_RUNNER_PORT ?? '8090', 10)
const host = process.env.NASUS_RUNNER_HOST ?? '0.0.0.0'
const serviceToken = process.env.NASUS_RUNNER_SERVICE_TOKEN ?? ''
const maxBodyBytes = Math.max(
  1_024,
  Math.min(Number.parseInt(process.env.NASUS_RUNNER_MAX_BODY_BYTES ?? '1048576', 10), 10 * 1024 * 1024),
)
const maxConcurrency = Math.max(
  1,
  Math.min(Number.parseInt(process.env.NASUS_RUNNER_MAX_CONCURRENCY ?? '2', 10), 16),
)
let activeJobs = 0
const jobCounts = new Map()
const rejectionCounts = new Map()
const durationBuckets = [0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120]
const durationBucketCounts = new Map(durationBuckets.map((bucket) => [bucket, 0]))
let durationCount = 0
let durationSum = 0

if (serviceToken.length < 24) {
  throw new Error('NASUS_RUNNER_SERVICE_TOKEN must contain at least 24 characters.')
}

function sendJson(response, statusCode, payload) {
  const body = Buffer.from(JSON.stringify(payload))
  response.writeHead(statusCode, {
    'Content-Type': 'application/json',
    'Content-Length': body.byteLength,
    'Cache-Control': 'no-store',
  })
  response.end(body)
}

function requestId(request) {
  const supplied = String(request.headers['x-request-id'] ?? '').trim()
  if (/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(supplied)) return supplied
  return `req_${crypto.randomBytes(16).toString('hex')}`
}

function increment(counter, label) {
  counter.set(label, (counter.get(label) ?? 0) + 1)
}

function observeDuration(durationSeconds) {
  durationCount += 1
  durationSum += durationSeconds
  for (const bucket of durationBuckets) {
    if (durationSeconds <= bucket) {
      durationBucketCounts.set(bucket, (durationBucketCounts.get(bucket) ?? 0) + 1)
    }
  }
}

function metricLabel(value) {
  return String(value).replaceAll('\\', '\\\\').replaceAll('"', '\\"').replaceAll('\n', '\\n')
}

function renderMetrics(browserReady) {
  const lines = [
    '# HELP nasus_runner_active_jobs Playwright jobs currently executing.',
    '# TYPE nasus_runner_active_jobs gauge',
    `nasus_runner_active_jobs ${activeJobs}`,
    '# HELP nasus_runner_max_concurrency Configured Playwright job concurrency.',
    '# TYPE nasus_runner_max_concurrency gauge',
    `nasus_runner_max_concurrency ${maxConcurrency}`,
    '# HELP nasus_runner_browser_ready Whether Chromium can be launched by the runner.',
    '# TYPE nasus_runner_browser_ready gauge',
    `nasus_runner_browser_ready ${browserReady ? 1 : 0}`,
    '# HELP nasus_runner_jobs_total Completed Playwright jobs by result status.',
    '# TYPE nasus_runner_jobs_total counter',
  ]
  for (const [status, count] of [...jobCounts.entries()].sort()) {
    lines.push(`nasus_runner_jobs_total{status="${metricLabel(status)}"} ${count}`)
  }
  lines.push(
    '# HELP nasus_runner_rejections_total Runner requests rejected before execution.',
    '# TYPE nasus_runner_rejections_total counter',
  )
  for (const [reason, count] of [...rejectionCounts.entries()].sort()) {
    lines.push(`nasus_runner_rejections_total{reason="${metricLabel(reason)}"} ${count}`)
  }
  lines.push(
    '# HELP nasus_runner_job_duration_seconds Playwright job execution duration.',
    '# TYPE nasus_runner_job_duration_seconds histogram',
  )
  for (const bucket of durationBuckets) {
    lines.push(`nasus_runner_job_duration_seconds_bucket{le="${bucket}"} ${durationBucketCounts.get(bucket) ?? 0}`)
  }
  lines.push(`nasus_runner_job_duration_seconds_bucket{le="+Inf"} ${durationCount}`)
  lines.push(`nasus_runner_job_duration_seconds_sum ${durationSum}`)
  lines.push(`nasus_runner_job_duration_seconds_count ${durationCount}`)
  return `${lines.join('\n')}\n`
}

function logEvent(event, details) {
  process.stdout.write(`${JSON.stringify({ event, ...details })}\n`)
}

function tokenMatches(authorization) {
  const candidate = authorization?.startsWith('Bearer ') ? authorization.slice(7) : ''
  const expectedBuffer = Buffer.from(serviceToken)
  const candidateBuffer = Buffer.from(candidate)
  return (
    expectedBuffer.byteLength === candidateBuffer.byteLength &&
    crypto.timingSafeEqual(expectedBuffer, candidateBuffer)
  )
}

async function readJson(request) {
  const chunks = []
  let total = 0
  for await (const chunk of request) {
    total += chunk.byteLength
    if (total > maxBodyBytes) {
      throw new Error(`Runner request exceeds the ${maxBodyBytes} byte limit.`)
    }
    chunks.push(chunk)
  }
  const raw = Buffer.concat(chunks).toString('utf8')
  return JSON.parse(raw)
}

const server = http.createServer(async (request, response) => {
  const correlationId = requestId(request)
  response.setHeader('X-Request-ID', correlationId)
  if (request.method === 'GET' && request.url === '/healthz') {
    sendJson(response, 200, { status: 'ok' })
    return
  }
  if (request.method === 'GET' && request.url === '/readyz') {
    const browserAvailable = await runnerBrowserAvailable()
    sendJson(response, browserAvailable ? 200 : 503, {
      status: browserAvailable ? 'ready' : 'not_ready',
      browser: browserAvailable ? 'chromium' : 'unavailable',
      active_jobs: activeJobs,
      max_concurrency: maxConcurrency,
    })
    return
  }
  if (request.method === 'GET' && request.url === '/metrics') {
    if (!tokenMatches(request.headers.authorization)) {
      increment(rejectionCounts, 'unauthorized')
      sendJson(response, 401, { error: 'unauthorized' })
      return
    }
    const browserAvailable = await runnerBrowserAvailable()
    const body = Buffer.from(renderMetrics(browserAvailable))
    response.writeHead(200, {
      'Content-Type': 'text/plain; version=0.0.4; charset=utf-8',
      'Content-Length': body.byteLength,
      'Cache-Control': 'no-store',
    })
    response.end(body)
    return
  }
  if (request.method !== 'POST' || request.url !== '/v1/jobs') {
    sendJson(response, 404, { error: 'not_found' })
    return
  }
  if (!tokenMatches(request.headers.authorization)) {
    increment(rejectionCounts, 'unauthorized')
    sendJson(response, 401, { error: 'unauthorized' })
    return
  }
  if (activeJobs >= maxConcurrency) {
    increment(rejectionCounts, 'capacity')
    response.setHeader('Retry-After', '2')
    sendJson(response, 429, { error: 'runner_capacity_exhausted' })
    return
  }

  activeJobs += 1
  const startedAt = performance.now()
  try {
    const job = await readJson(request)
    const result = await executeJob(job)
    increment(jobCounts, String(result.status ?? 'error'))
    logEvent('runner.job.completed', {
      request_id: correlationId,
      job_id: String(result.runner_job_id ?? job.job_id ?? ''),
      status: String(result.status ?? 'error'),
      duration_ms: Math.round((performance.now() - startedAt) * 1000) / 1000,
    })
    sendJson(response, 200, result)
  } catch (error) {
    increment(rejectionCounts, 'invalid_request')
    logEvent('runner.job.rejected', {
      request_id: correlationId,
      reason: 'invalid_request',
      error_type: String(error?.name ?? 'Error'),
    })
    sendJson(response, 400, {
      error: 'invalid_request',
      message: String(error?.message ?? error).slice(0, 500),
    })
  } finally {
    observeDuration((performance.now() - startedAt) / 1000)
    activeJobs -= 1
  }
})

server.listen(port, host, () => {
  process.stdout.write(`Nasus Playwright runner listening on http://${host}:${port}\n`)
})

function shutdown() {
  server.close(() => process.exit(0))
  setTimeout(() => process.exit(1), 10_000).unref()
}

process.on('SIGINT', shutdown)
process.on('SIGTERM', shutdown)
