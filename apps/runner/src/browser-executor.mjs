import { chromium } from 'playwright'

import { createExecutionReceipt, requestHash } from './execution-receipt.mjs'
import { BROWSER_ASSERTIONS, BROWSER_MUTATIONS, BROWSER_RECEIPT_SCHEMA, BrowserPolicyError,
  browserFailureCode, requireBrowser, stepUrl, validateBrowserDispatch, validateBrowserJob } from './browser-job.mjs'
import { installBrowserNetwork } from './browser-network.mjs'

const now = () => new Date().toISOString()

async function closeResource(resource) {
  if (!resource) return true
  let timer
  try {
    return await Promise.race([
      Promise.resolve().then(() => resource.close()).then(() => true, () => false),
      new Promise((resolve) => { timer = setTimeout(() => resolve(false), 1000) }),
    ])
  } finally { clearTimeout(timer) }
}

export function reconcileBrowserReceipt(observed, { reviewedPins, firstFailed, writeFence, unknownWrites, evidenceStored }) {
  const unknown = new Set(unknownWrites)
  return { ...observed,
    execution_status: unknown.size && ['passed', 'failed'].includes(observed.execution_status) ? 'error' : observed.execution_status,
    steps: observed.steps.map((step) => unknown.has(step.step_index) ? { ...step, status: 'interrupted' } : { ...step }),
    reviewed_pins: structuredClone(reviewedPins), first_failed_assertion_index: firstFailed,
    write_fence: unknown.size ? 'unknown_write' : writeFence,
    unknown_write_step_indices: [...unknown].sort((a, b) => a - b), private_evidence_stored: evidenceStored }
}

function result(job, startedAt, status, code, receipt) {
  return { runner_job_id: job?.jobId ?? 'invalid_browser_job', status,
    summary: `Formal browser execution completed with status ${status}.`, failure_summary: code,
    started_at: startedAt, completed_at: now(), timeline: [], artifacts: [],
    failure_fingerprint: status === 'passed' ? null : requestHash(JSON.stringify([job?.inputHash ?? null, code])),
    ...(receipt ? { execution_receipt: receipt } : {}) }
}

async function runStep(page, step, job, value, timeout, started) {
  let locator
  if (step.selector !== undefined) {
    locator = page.locator(step.selector)
    // Never pick first/nth, expand selectors, or infer a locator from page text.
    if (step.action === 'wait_for') await locator.waitFor({ state: 'visible', timeout })
    const count = await locator.count()
    if (count === 0 && BROWSER_ASSERTIONS.has(step.action)) return false
    requireBrowser(count === 1, 'browser_execution_error')
  }
  started()
  switch (step.action) {
    case 'goto': await page.goto(stepUrl(step, job.base), { waitUntil: 'domcontentloaded', timeout }); return true
    case 'fill': await locator.fill(value, { timeout }); return true
    case 'click': await locator.click({ timeout }); return true
    case 'press': await locator.press(step.key, { timeout }); return true
    case 'wait_for': return true
    case 'assert_visible': return await locator.isVisible()
    case 'assert_text': return ((await locator.textContent({ timeout })) ?? '').includes(step.value)
    case 'assert_url': return page.url() === stepUrl(step, job.base)
    default: throw new BrowserPolicyError('invalid_browser_job')
  }
}

/** Private dispatcher is infrastructure authority, never a property of the public JSON command. */
export async function executeBrowserJob(raw, { wireBody, signal, privateDispatcher,
  launchBrowser = () => chromium.launch({ headless: true }) } = {}) {
  const startedAt = now()
  let job
  try { job = validateBrowserJob(raw, wireBody) }
  catch (error) { return result(undefined, startedAt, 'error', browserFailureCode(error)) }
  if (typeof privateDispatcher !== 'function') return result(job, startedAt, 'error', 'private_dispatch_required')

  const deadline = AbortSignal.timeout(job.timeoutMs)
  const stop = signal ? AbortSignal.any([deadline, signal]) : deadline
  const state = { activeIndex: -1, deadlineAt: Date.now() + job.timeoutMs, firstFailed: null, writeFence: 'open',
    unknownWrites: new Set(), inflightWrites: new Set(), policyFailure: null }
  let browser, context, network, dispatch, tracker, status = 'error', code = '', evidenceStored = false, evidenceFailed = false
  const abortCode = () => deadline.aborted ? 'browser_deadline' : 'browser_interrupted'
  // Bound every private port and browser operation. A late resource is closed, never reused.
  const bounded = (operation, lateCleanup) => {
    stop.throwIfAborted()
    return new Promise((resolve, reject) => {
      let aborted = false
      const abort = () => { aborted = true; reject(new BrowserPolicyError(abortCode())) }
      stop.addEventListener('abort', abort, { once: true })
      Promise.resolve().then(() => { stop.throwIfAborted(); return operation() }).then((value) => {
        stop.removeEventListener('abort', abort)
        if (aborted) void Promise.resolve(lateCleanup?.(value)).catch(() => {})
        else resolve(value)
      }, (error) => { stop.removeEventListener('abort', abort); reject(error) })
    })
  }
  const record = async (event) => {
    try { requireBrowser(await bounded(() => dispatch.evidence.record(event, { signal: stop })) === true, 'private_evidence_unavailable') }
    catch {
      evidenceFailed = true
      throw new BrowserPolicyError(stop.aborted ? abortCode() : 'private_evidence_unavailable')
    }
  }
  const receipt = () => reconcileBrowserReceipt(tracker.finish(status), { reviewedPins: job.command.reviewed_pins,
    firstFailed: state.firstFailed, writeFence: state.writeFence, unknownWrites: state.unknownWrites, evidenceStored })
  const checkPolicy = () => { if (state.policyFailure) throw new BrowserPolicyError(state.policyFailure) }
  try {
    dispatch = validateBrowserDispatch(await bounded(() => privateDispatcher({ command: job.command,
      requestHash: job.inputHash, signal: stop })), job)
    await record({ kind: 'execution_started', request_hash: job.inputHash, reviewed_pins: job.command.reviewed_pins })
    tracker = createExecutionReceipt(job, job.inputHash, { schema: BROWSER_RECEIPT_SCHEMA, assertions: BROWSER_ASSERTIONS })
    browser = await bounded(launchBrowser, closeResource)
    context = await bounded(() => browser.newContext({ acceptDownloads: false, ignoreHTTPSErrors: false,
      serviceWorkers: 'block' }), closeResource)
    context.setDefaultTimeout(Math.min(30000, job.timeoutMs))
    context.setDefaultNavigationTimeout(Math.min(30000, job.timeoutMs))
    network = await bounded(() => installBrowserNetwork(context, { job, dispatch, state, signal: stop, record }))
    const page = await bounded(() => context.newPage(), closeResource)
    for (let index = 0; index < job.steps.length; index++) {
      stop.throwIfAborted()
      checkPolicy()
      const step = job.steps[index], permission = dispatch.permissions[index]
      if (state.writeFence !== 'open' && !(step.phase === 'verification' && permission.readOnly)) continue
      state.activeIndex = index
      tracker.start(index)
      let attempted = false, value = step.value
      try {
        if (dispatch.credentials.has(index)) {
          try { value = await bounded(() => dispatch.resolveCredential({ credential_ref: dispatch.credentials.get(index), signal: stop })) }
          catch { throw new BrowserPolicyError('credential_unavailable') }
          requireBrowser(typeof value === 'string' && value.length > 0 && value.length <= 20000, 'credential_unavailable')
        }
        const matches = await bounded(() => runStep(page, step, job, value,
          Math.min(step.timeout_ms ?? 30000, Math.max(1, state.deadlineAt - Date.now())), () => { attempted = true }))
        value = undefined
        // Fence immediately on the first mismatch, before any awaited evidence or queued traffic.
        if (!matches) {
          state.firstFailed ??= index
          if (state.writeFence === 'open') state.writeFence = 'assertion_failed'
          tracker.observe(index, 'failed')
        }
        await bounded(() => network.drain())
        checkPolicy()
        if (state.unknownWrites.has(index)) throw new BrowserPolicyError('unknown_write')
        await record({ kind: 'step_observation', step_index: index, action: step.action, status: matches ? 'passed' : 'failed' })
        if (matches) tracker.observe(index, 'passed')
      } catch (error) {
        value = undefined
        if (attempted && (BROWSER_MUTATIONS.has(step.action) || !permission.readOnly)) {
          state.unknownWrites.add(index)
          state.writeFence = 'unknown_write'
        }
        if (stop.aborted) throw error
        checkPolicy()
        if (browserFailureCode(error) === 'credential_unavailable' || browserFailureCode(error) === 'private_evidence_unavailable') throw error
        if (!state.unknownWrites.has(index)) throw error
        // Unknown submit is never retried; only independently reviewed verification can follow.
        tracker.observe(index, 'interrupted')
        await record({ kind: 'step_observation', step_index: index, action: step.action, status: 'interrupted' })
      }
    }
    state.activeIndex = -1
    checkPolicy()
    const screenshot = await bounded(() => page.screenshot({ fullPage: true, timeout: Math.max(1, state.deadlineAt - Date.now()) }))
    requireBrowser(screenshot.byteLength <= 25 * 1024 * 1024, 'private_evidence_unavailable')
    await record({ kind: 'screenshot', media_type: 'image/png', body: screenshot })
    checkPolicy()
    status = state.unknownWrites.size ? 'error' : state.firstFailed === null ? 'passed' : 'failed'
    code = state.unknownWrites.size ? 'unknown_write' : state.firstFailed === null ? '' : 'assertion_failed'
  } catch (error) {
    status = deadline.aborted ? 'timed_out' : 'error'
    code = stop.aborted ? abortCode() : browserFailureCode(error)
    if (code === 'private_evidence_unavailable') evidenceFailed = true
    if (state.writeFence === 'open') state.writeFence = stop.aborted ? 'interrupted' : 'policy_rejected'
  } finally {
    for (const index of state.inflightWrites) state.unknownWrites.add(index)
    if (state.unknownWrites.size) state.writeFence = 'unknown_write'
    // Seal observations before closing a context can trigger late browser callbacks.
    if (tracker) tracker.finish(status)
    network?.close()
    const [, browserClosed] = await Promise.all([closeResource(context), closeResource(browser)])
    if (!browserClosed) {
      if (status !== 'timed_out') { status = 'error'; code = 'browser_interrupted' }
      if (state.writeFence === 'open') state.writeFence = 'interrupted'
      evidenceFailed = true
    }
    dispatch?.credentials.clear()
  }
  if (state.unknownWrites.size && ['passed', 'failed'].includes(status)) { status = 'error'; code = 'unknown_write' }
  if (tracker) {
    try {
      requireBrowser(await bounded(() => dispatch.evidence.seal(receipt(), { signal: stop })) === true, 'private_evidence_unavailable')
      evidenceStored = !evidenceFailed
    } catch {
      status = deadline.aborted ? 'timed_out' : 'error'
      code = stop.aborted ? abortCode() : 'private_evidence_unavailable'
      if (state.writeFence === 'open') state.writeFence = stop.aborted ? 'interrupted' : 'policy_rejected'
    }
  }
  return result(job, startedAt, status, code, tracker ? receipt() : undefined)
}
