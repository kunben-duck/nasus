import crypto from 'node:crypto'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'

import { chromium } from 'playwright'

const SUPPORTED_ACTIONS = new Set([
  'goto',
  'click',
  'fill',
  'press',
  'assert_text',
  'assert_visible',
  'assert_url',
  'wait_for',
])
const SUPPORTED_WAIT_STATES = new Set(['attached', 'detached', 'visible', 'hidden'])
const MAX_STEPS = 100
const MAX_STRING_LENGTH = 20_000
const DEFAULT_ARTIFACT_LIMIT = 25 * 1024 * 1024

class RunnerTimeoutError extends Error {
  constructor(timeoutMs) {
    super(`Runner job exceeded its ${timeoutMs}ms deadline.`)
    this.name = 'RunnerTimeoutError'
  }
}

function isoNow() {
  return new Date().toISOString()
}

function envInteger(name, fallback, minimum, maximum) {
  const parsed = Number.parseInt(process.env[name] ?? '', 10)
  if (!Number.isFinite(parsed)) return fallback
  return Math.min(Math.max(parsed, minimum), maximum)
}

function allowedHostsFromEnv() {
  return new Set(
    (process.env.NASUS_RUNNER_ALLOWED_HOSTS ?? '')
      .split(',')
      .map((value) => value.trim().toLowerCase())
      .filter(Boolean),
  )
}

function hostMatches(host, allowedHosts) {
  if (allowedHosts.size === 0) {
    return process.env.NASUS_ENV !== 'production' && ['localhost', '127.0.0.1', '::1'].includes(host)
  }
  for (const pattern of allowedHosts) {
    if (pattern.startsWith('*.')) {
      const suffix = pattern.slice(1)
      if (host.endsWith(suffix) && host.length > suffix.length) return true
    } else if (host === pattern) {
      return true
    }
  }
  return false
}

function validatedUrl(rawUrl, allowedHosts, baseUrl = undefined) {
  let parsed
  try {
    parsed = baseUrl ? new URL(rawUrl, baseUrl) : new URL(rawUrl)
  } catch {
    throw new Error(`Runner URL is invalid: ${String(rawUrl).slice(0, 200)}`)
  }
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error(`Runner URL protocol is not allowed: ${parsed.protocol}`)
  }
  if (parsed.username || parsed.password) {
    throw new Error('Runner URLs must not contain credentials.')
  }
  if (!hostMatches(parsed.hostname.toLowerCase(), allowedHosts)) {
    throw new Error(`Runner target host is not allowed: ${parsed.hostname}`)
  }
  return parsed.toString()
}

function requiredString(value, fieldName, { allowEmpty = false } = {}) {
  if (typeof value !== 'string' || (!allowEmpty && !value.trim())) {
    throw new Error(`${fieldName} must be a non-empty string.`)
  }
  if (value.length > MAX_STRING_LENGTH) {
    throw new Error(`${fieldName} exceeds the ${MAX_STRING_LENGTH} character limit.`)
  }
  return value
}

function validateStep(step, index) {
  if (!step || typeof step !== 'object' || Array.isArray(step)) {
    throw new Error(`steps[${index}] must be an object.`)
  }
  const action = requiredString(step.action, `steps[${index}].action`).toLowerCase()
  if (!SUPPORTED_ACTIONS.has(action)) {
    throw new Error(`steps[${index}].action is not supported: ${action}`)
  }
  const normalized = { action }
  if (step.selector !== undefined) {
    normalized.selector = requiredString(step.selector, `steps[${index}].selector`)
  }
  if (step.value !== undefined) {
    normalized.value = requiredString(step.value, `steps[${index}].value`, { allowEmpty: true })
  }
  if (step.text !== undefined) {
    normalized.text = requiredString(step.text, `steps[${index}].text`, { allowEmpty: true })
  }
  if (step.path !== undefined) {
    normalized.path = requiredString(step.path, `steps[${index}].path`)
  }
  if (step.key !== undefined) {
    normalized.key = requiredString(step.key, `steps[${index}].key`)
  }
  if (step.state !== undefined) {
    normalized.state = requiredString(step.state, `steps[${index}].state`)
    if (!SUPPORTED_WAIT_STATES.has(normalized.state)) {
      throw new Error(`steps[${index}].state is not supported: ${normalized.state}`)
    }
  }
  if (step.timeout_ms !== undefined) {
    normalized.timeout_ms = Math.min(Math.max(Number(step.timeout_ms) || 1_000, 100), 30_000)
  }
  return normalized
}

function validateJob(rawJob) {
  if (!rawJob || typeof rawJob !== 'object' || Array.isArray(rawJob)) {
    throw new Error('Runner job must be a JSON object.')
  }
  const allowedHosts = allowedHostsFromEnv()
  const baseUrl = validatedUrl(requiredString(rawJob.base_url, 'base_url'), allowedHosts)
  if (!Array.isArray(rawJob.steps) || rawJob.steps.length === 0) {
    throw new Error('Runner job must include at least one structured step.')
  }
  if (rawJob.steps.length > MAX_STEPS) {
    throw new Error(`Runner job exceeds the ${MAX_STEPS} step limit.`)
  }
  const timeoutMs = Math.min(Math.max(Number(rawJob.timeout_ms) || 60_000, 1_000), 120_000)
  return {
    jobId: requiredString(rawJob.job_id, 'job_id'),
    projectId: requiredString(rawJob.project_id, 'project_id'),
    usId: requiredString(rawJob.us_id, 'us_id'),
    baseUrl,
    allowedHosts,
    steps: rawJob.steps.map(validateStep),
    timeoutMs,
    metadata: rawJob.metadata && typeof rawJob.metadata === 'object' ? rawJob.metadata : {},
  }
}

function redact(value) {
  return String(value)
    .replace(/(authorization:\s*bearer\s+)[^\s]+/gi, '$1[REDACTED]')
    .replace(/([?&](?:api[_-]?key|token|secret|password)=)[^&\s]+/gi, '$1[REDACTED]')
    .replace(/("(?:api[_-]?key|token|secret|password)"\s*:\s*")[^"]+/gi, '$1[REDACTED]')
    .slice(0, 20_000)
}

function failureFingerprint(jobId, error) {
  const normalized = `${error?.name ?? 'Error'}:${redact(error?.message ?? error)}`
  return `sha256:${crypto.createHash('sha256').update(`${jobId}:${normalized}`).digest('hex')}`
}

async function executeStep(page, step, baseUrl, allowedHosts) {
  const timeout = step.timeout_ms
  switch (step.action) {
    case 'goto': {
      const target = validatedUrl(step.path ?? step.value ?? '/', allowedHosts, baseUrl)
      await page.goto(target, { waitUntil: 'domcontentloaded', timeout })
      return `Navigated to ${new URL(target).pathname || '/'}`
    }
    case 'click':
      await page.locator(requiredString(step.selector, 'click.selector')).click({ timeout })
      return `Clicked ${step.selector}`
    case 'fill':
      await page
        .locator(requiredString(step.selector, 'fill.selector'))
        .fill(requiredString(step.value, 'fill.value', { allowEmpty: true }), { timeout })
      return `Filled ${step.selector}`
    case 'press':
      await page
        .locator(requiredString(step.selector, 'press.selector'))
        .press(requiredString(step.key, 'press.key'), { timeout })
      return `Pressed ${step.key} on ${step.selector}`
    case 'assert_text': {
      const locator = step.selector ? page.locator(step.selector) : page.locator('body')
      const actual = (await locator.textContent({ timeout })) ?? ''
      const expected = requiredString(step.text ?? step.value, 'assert_text.text', { allowEmpty: true })
      if (!actual.includes(expected)) {
        throw new Error(`Expected ${step.selector ?? 'body'} to contain ${JSON.stringify(expected)}.`)
      }
      return `Asserted text in ${step.selector ?? 'body'}`
    }
    case 'assert_visible':
      if (!(await page.locator(requiredString(step.selector, 'assert_visible.selector')).isVisible({ timeout }))) {
        throw new Error(`Expected ${step.selector} to be visible.`)
      }
      return `Asserted ${step.selector} is visible`
    case 'assert_url': {
      const expected = requiredString(step.value ?? step.text, 'assert_url.value')
      if (!page.url().includes(expected)) {
        throw new Error(`Expected current URL to contain ${JSON.stringify(expected)}.`)
      }
      return 'Asserted current URL'
    }
    case 'wait_for':
      await page
        .locator(requiredString(step.selector, 'wait_for.selector'))
        .waitFor({ state: step.state ?? 'visible', timeout })
      return `Waited for ${step.selector}`
    default:
      throw new Error(`Unsupported runner action: ${step.action}`)
  }
}

async function artifactFromFile(artifactType, name, mediaType, filePath, artifactLimit) {
  try {
    const body = await fs.readFile(filePath)
    if (body.byteLength > artifactLimit) return null
    return {
      artifact_type: artifactType,
      name,
      media_type: mediaType,
      content_base64: body.toString('base64'),
    }
  } catch {
    return null
  }
}

function artifactFromText(artifactType, name, mediaType, text) {
  return {
    artifact_type: artifactType,
    name,
    media_type: mediaType,
    content_base64: Buffer.from(text, 'utf8').toString('base64'),
  }
}

async function executeValidatedJob(job) {
  const startedAt = isoNow()
  const timeline = []
  const logs = [`[runner] started ${job.jobId}`]
  const artifacts = [
    artifactFromText(
      'script',
      'structured-steps.json',
      'application/json',
      JSON.stringify({ base_url: job.baseUrl, steps: job.steps }, null, 2),
    ),
  ]
  const artifactLimit = envInteger(
    'NASUS_RUNNER_MAX_ARTIFACT_BYTES',
    DEFAULT_ARTIFACT_LIMIT,
    1_024,
    100 * 1024 * 1024,
  )
  const workDir = await fs.mkdtemp(path.join(os.tmpdir(), 'nasus-runner-'))
  const tracePath = path.join(workDir, 'trace.zip')
  const screenshotPath = path.join(workDir, 'final.png')
  let browser
  let context
  let status = 'error'
  let failureSummary = ''

  try {
    browser = await chromium.launch({ headless: true })
    context = await browser.newContext({
      acceptDownloads: false,
      ignoreHTTPSErrors: process.env.NASUS_RUNNER_IGNORE_HTTPS_ERRORS === 'true',
      serviceWorkers: 'block',
    })
    context.setDefaultTimeout(Math.min(job.timeoutMs, 30_000))
    context.setDefaultNavigationTimeout(Math.min(job.timeoutMs, 30_000))
    await context.tracing.start({ screenshots: true, snapshots: true, sources: false })
    const page = await context.newPage()
    page.on('console', (message) => logs.push(`[console:${message.type()}] ${redact(message.text())}`))
    page.on('pageerror', (error) => logs.push(`[pageerror] ${redact(error.message)}`))
    page.on('requestfailed', (request) => {
      logs.push(`[requestfailed] ${redact(request.method())} ${redact(request.url())}`)
    })

    const execution = (async () => {
      for (let index = 0; index < job.steps.length; index += 1) {
        const summary = await executeStep(page, job.steps[index], job.baseUrl, job.allowedHosts)
        timeline.push(`Step ${index + 1}/${job.steps.length}: ${summary}`)
        logs.push(`[step:${index + 1}] ${summary}`)
      }
    })()
    let timeoutHandle
    const deadline = new Promise((_, reject) => {
      timeoutHandle = setTimeout(() => reject(new RunnerTimeoutError(job.timeoutMs)), job.timeoutMs)
    })
    try {
      await Promise.race([execution, deadline])
    } finally {
      clearTimeout(timeoutHandle)
    }
    await page.screenshot({ path: screenshotPath, fullPage: true })
    status = 'passed'
  } catch (error) {
    status = error instanceof RunnerTimeoutError ? 'timed_out' : 'failed'
    failureSummary = redact(error?.message ?? error)
    logs.push(`[runner:${status}] ${failureSummary}`)
    if (context) {
      const pages = context.pages()
      if (pages.length > 0) {
        await pages[0].screenshot({ path: screenshotPath, fullPage: true }).catch(() => {})
      }
    }
  } finally {
    if (context) {
      await context.tracing.stop({ path: tracePath }).catch(() => {})
      await context.close().catch(() => {})
    }
    if (browser) await browser.close().catch(() => {})
  }

  const screenshot = await artifactFromFile('screenshot', 'final.png', 'image/png', screenshotPath, artifactLimit)
  if (screenshot) artifacts.push(screenshot)
  const trace = await artifactFromFile('trace', 'trace.zip', 'application/zip', tracePath, artifactLimit)
  if (trace) artifacts.push(trace)
  artifacts.push(
    artifactFromText('log', 'runner.log', 'text/plain; charset=utf-8', logs.map(redact).join('\n')),
  )
  if (status !== 'passed') {
    artifacts.push(
      artifactFromText(
        'failure_artifact',
        'failure.json',
        'application/json',
        JSON.stringify({ status, failure_summary: failureSummary, timeline }, null, 2),
      ),
    )
  }
  await fs.rm(workDir, { recursive: true, force: true })

  return {
    runner_job_id: job.jobId,
    status,
    summary:
      status === 'passed'
        ? `Executed ${job.steps.length} structured Playwright steps successfully.`
        : `Playwright execution completed with status ${status}.`,
    failure_summary: failureSummary,
    started_at: startedAt,
    completed_at: isoNow(),
    timeline,
    artifacts,
    failure_fingerprint: status === 'passed' ? null : failureFingerprint(job.jobId, failureSummary),
  }
}

export async function executeJob(rawJob) {
  const startedAt = isoNow()
  try {
    const job = validateJob(rawJob)
    return await executeValidatedJob(job)
  } catch (error) {
    const jobId =
      rawJob && typeof rawJob === 'object' && typeof rawJob.job_id === 'string'
        ? rawJob.job_id
        : 'invalid_runner_job'
    const failureSummary = redact(error?.message ?? error)
    return {
      runner_job_id: jobId,
      status: 'error',
      summary: 'Runner rejected an invalid or unsafe job before browser execution.',
      failure_summary: failureSummary,
      started_at: startedAt,
      completed_at: isoNow(),
      timeline: ['Runner input validation failed closed.'],
      artifacts: [
        artifactFromText(
          'failure_artifact',
          'validation-failure.json',
          'application/json',
          JSON.stringify({ failure_summary: failureSummary }, null, 2),
        ),
      ],
      failure_fingerprint: failureFingerprint(jobId, failureSummary),
    }
  }
}

export function runnerBrowserAvailable() {
  return fs
    .access(chromium.executablePath())
    .then(() => true)
    .catch(() => false)
}
