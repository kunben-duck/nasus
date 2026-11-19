import assert from 'node:assert/strict'
import { test } from 'node:test'

import { executeBrowserJob, reconcileBrowserReceipt } from '../src/browser-executor.mjs'
import { BROWSER_RECEIPT_SCHEMA } from '../src/browser-job.mjs'
import { createExecutionReceipt, requestHash } from '../src/execution-receipt.mjs'
import { base, command, harness, pins, step } from './browser-fixtures.mjs'

test('adapts schema url/value, creates an isolated context per case, and publishes only bounded receipts', async () => {
  const h = harness()
  const job = command(), wireBody = JSON.stringify(job, null, 2)
  for (let i = 0; i < 2; i++) {
    const result = await executeBrowserJob(job, { ...h, wireBody })
    assert.equal(result.status, 'passed')
    assert.deepEqual(result.artifacts, [])
    assert.equal(result.execution_receipt.schema, BROWSER_RECEIPT_SCHEMA)
    assert.equal(result.execution_receipt.request_hash, requestHash(wireBody))
    assert.equal(result.execution_receipt.passed_assertion_count, 1)
    assert.equal(result.execution_receipt.target_build_verified, false)
    assert.equal(result.execution_receipt.business_coverage_verified, false)
    assert.equal(result.execution_receipt.private_evidence_stored, true)
    assert.equal(result.execution_receipt.write_fence, 'open')
    assert.deepEqual(result.execution_receipt.reviewed_pins, pins)
    assert.doesNotMatch(JSON.stringify(result), /registered\.example|#result|private-screen|content_base64/)
  }
  assert.equal(h.contexts.length, 2)
  assert.notEqual(h.contexts[0], h.contexts[1])
  assert.ok(h.contexts.every((context) => context.closed))
  assert.equal(h.closedBrowsers(), 2)
  for (const call of h.calls.filter((call) => call.kind === 'newContext')) {
    assert.deepEqual(call.config, { acceptDownloads: false, ignoreHTTPSErrors: false, serviceWorkers: 'block' })
  }
  assert.ok(h.records.some((record) => record.kind === 'screenshot' && Buffer.isBuffer(record.body)))
})

test('first failed assertion permanently fences writes but executes explicitly reviewed verification', async () => {
  const h = harness({ text: (selector) => selector === '#failure' ? 'wrong' : 'ready' })
  const result = await executeBrowserJob(command([
    step('goto', { url: '/' }), step('assert_text', { selector: '#failure', value: 'expected' }),
    step('fill', { selector: '#input', value: 'must not write' }), step('click', { selector: '#submit' }),
    step('goto', { url: '/unreviewed-after-failure' }), step('assert_visible', { selector: '#ordinary' }),
    step('goto', { url: '/verify', phase: 'verification' }),
    step('assert_text', { selector: '#result', value: 'ready', phase: 'verification' }),
    step('click', { selector: '#submit' }),
  ]), h)
  assert.equal(result.status, 'failed')
  assert.equal(result.failure_summary, 'assertion_failed')
  assert.equal(result.execution_receipt.first_failed_assertion_index, 1)
  assert.equal(result.execution_receipt.write_fence, 'assertion_failed')
  assert.deepEqual(result.execution_receipt.steps.map((item) => item.status),
    ['passed', 'failed', 'not_executed', 'not_executed', 'not_executed', 'not_executed', 'passed', 'passed', 'not_executed'])
  assert.equal(result.execution_receipt.failed_assertion_count, 1)
  assert.equal(result.execution_receipt.passed_assertion_count, 1)
  assert.equal(h.calls.filter((call) => ['click', 'fill'].includes(call.kind)).length, 0)
  assert.deepEqual(h.calls.filter((call) => call.kind === 'goto').map((call) => call.url), [base + '/', base + '/verify'])
})

test('unknown submit is attempted once, never retried, and verification cannot convert it to passed', async () => {
  const h = harness({ onAction: ({ action }) => { if (action === 'click') throw new Error('private credential_ref/secret submit timeout') } })
  const result = await executeBrowserJob(command([
    step('goto', { url: '/' }), step('click', { selector: '#submit' }), step('click', { selector: '#submit' }),
    step('assert_text', { selector: '#result', value: 'ready', phase: 'verification' }),
  ]), h)
  assert.equal(result.status, 'error')
  assert.equal(result.failure_summary, 'unknown_write')
  assert.equal(h.calls.filter((call) => call.kind === 'click').length, 1)
  assert.deepEqual(result.execution_receipt.unknown_write_step_indices, [1])
  assert.equal(result.execution_receipt.write_fence, 'unknown_write')
  assert.deepEqual(result.execution_receipt.steps.map((item) => item.status), ['passed', 'interrupted', 'not_executed', 'passed'])
  assert.doesNotMatch(JSON.stringify(result), /private credential|secret|submit timeout/)
})

test('late unknown write reconciles even a provisionally passed action without erasing original assertion failures', () => {
  const tracker = createExecutionReceipt({ jobId: 'job', projectId: 'project', usId: 'case',
    steps: [step('click', { selector: '#submit' }), step('assert_text', { selector: '#result', value: 'absent' })] }, requestHash('wire'))
  tracker.start(0); tracker.observe(0, 'passed')
  tracker.start(1); tracker.observe(1, 'failed')
  const observed = tracker.finish('failed')
  const receipt = reconcileBrowserReceipt(observed, { reviewedPins: pins, firstFailed: 1,
    writeFence: 'assertion_failed', unknownWrites: [0], evidenceStored: true })
  assert.equal(receipt.execution_status, 'error')
  assert.equal(receipt.steps[0].status, 'interrupted')
  assert.equal(receipt.steps[1].status, 'failed')
  assert.equal(receipt.first_failed_assertion_index, 1)
  assert.equal(receipt.failed_assertion_count, 1)
  assert.equal(observed.steps[0].status, 'passed')
})

test('credentials resolve only through the private port and never reach public output, including exception paths', async () => {
  const secret = 'resolved-password-sensitive', reference = 'vault://private/credential-reference'
  for (const fails of [false, true]) {
    const h = harness({ grant: (grant) => {
      grant.credential_bindings = [{ step_index: 1, credential_ref: reference }]
      grant.resolve_credential = async ({ credential_ref }) => { assert.equal(credential_ref, reference); return secret }
    }, onAction: ({ action, value }) => {
      if (action === 'fill') { assert.equal(value, secret); if (fails) throw new Error(secret + reference) }
    } })
    const result = await executeBrowserJob(command([step('goto', { url: '/' }),
      step('fill', { selector: 'input[type="password"]', value: '' }),
      step('assert_visible', { selector: '#result', phase: 'verification' })]), h)
    assert.equal(result.status, fails ? 'error' : 'passed')
    assert.equal(h.calls.find((call) => call.kind === 'fill').value, secret)
    assert.ok(!JSON.stringify(result).includes(secret))
    assert.ok(!JSON.stringify(result).includes(reference))
    assert.deepEqual(result.artifacts, [])
    assert.ok(!JSON.stringify(h.records).includes(secret))
    assert.ok(!JSON.stringify(h.records).includes(reference))
  }
})

test('credential resolver rejection and evidence storage failure are fail-closed and sanitized', async () => {
  const missingSecret = harness({ grant: (grant) => {
    grant.credential_bindings = [{ step_index: 0, credential_ref: 'vault://do-not-echo' }]
    grant.resolve_credential = async () => { throw new Error('vault://do-not-echo secret') }
  } })
  const denied = await executeBrowserJob(command([step('fill', { selector: '#password', value: '' })]), missingSecret)
  assert.equal(denied.failure_summary, 'credential_unavailable')
  assert.equal(missingSecret.calls.filter((call) => call.kind === 'fill').length, 0)
  assert.doesNotMatch(JSON.stringify(denied), /vault|do-not-echo|secret/)
  for (const options of [{ seal: () => false }, { record: (event) => event.kind !== 'screenshot' }]) {
    const h = harness(options), result = await executeBrowserJob(command(), h)
    assert.equal(result.status, 'error')
    assert.equal(result.failure_summary, 'private_evidence_unavailable')
    assert.equal(result.execution_receipt.private_evidence_stored, false)
    assert.equal(result.execution_receipt.execution_status, 'error')
    assert.deepEqual(result.artifacts, [])
  }
})

test('non-unique locators fail without a click and absent asserted elements count as a failed oracle', async () => {
  const duplicate = harness({ count: () => 2 })
  const result = await executeBrowserJob(command([step('click', { selector: '#submit' })]), duplicate)
  assert.equal(result.status, 'error')
  assert.equal(duplicate.calls.some((call) => call.kind === 'click'), false)
  const absent = await executeBrowserJob(command([step('assert_visible', { selector: '#missing' }),
    step('click', { selector: '#submit' })]), harness({ count: () => 0 }))
  assert.equal(absent.status, 'failed')
  assert.equal(absent.execution_receipt.failed_assertion_count, 1)
  assert.equal(absent.execution_receipt.steps[1].status, 'not_executed')
})

test('observed assertion failure survives private evidence failure without a contradictory interrupted oracle', async () => {
  const h = harness({ text: () => 'wrong', record: (event) => event.kind !== 'step_observation' })
  const result = await executeBrowserJob(command([step('assert_text', { selector: '#result', value: 'expected' }),
    step('click', { selector: '#submit' })]), h)
  assert.equal(result.status, 'error')
  assert.equal(result.execution_receipt.first_failed_assertion_index, 0)
  assert.equal(result.execution_receipt.failed_assertion_count, 1)
  assert.equal(result.execution_receipt.steps[0].status, 'failed')
  assert.equal(result.execution_receipt.steps[1].status, 'not_executed')
  assert.equal(result.execution_receipt.private_evidence_stored, false)
})

test('job deadline interrupts an active unknown write and closes its isolated context', async () => {
  const h = harness({ onAction: ({ action }) => {
    if (action === 'click') return new Promise((resolve) => setTimeout(resolve, 1100))
  } })
  const job = command([step('click', { selector: '#submit' }), step('click', { selector: '#retry' })])
  job.timeout_ms = 1000
  const result = await executeBrowserJob(job, h)
  assert.equal(result.status, 'timed_out')
  assert.equal(result.failure_summary, 'browser_deadline')
  assert.equal(result.execution_receipt.execution_status, 'timed_out')
  assert.deepEqual(result.execution_receipt.unknown_write_step_indices, [0])
  assert.equal(result.execution_receipt.steps[1].status, 'not_executed')
  assert.ok(h.contexts.every((context) => context.closed))
})

test('caller cancellation interrupts an active write, seals receipt and never runs later steps', async () => {
  const controller = new AbortController()
  const h = harness({ onAction: ({ action }) => {
    if (action === 'click') { controller.abort(); return new Promise(() => {}) }
  } })
  const result = await executeBrowserJob(command([step('click', { selector: '#submit' }),
    step('click', { selector: '#retry' })]), { ...h, signal: controller.signal })
  assert.equal(result.status, 'error')
  assert.equal(result.failure_summary, 'browser_interrupted')
  assert.deepEqual(result.execution_receipt.unknown_write_step_indices, [0])
  assert.deepEqual(result.execution_receipt.steps.map((item) => item.status), ['interrupted', 'not_executed'])
  assert.equal(result.execution_receipt.private_evidence_stored, false)
  assert.ok(h.contexts.every((context) => context.closed))
})

test('late browser launch after cancellation is closed and cannot create a context', async () => {
  const controller = new AbortController(), h = harness()
  let finishLaunch, closed = false
  const result = await executeBrowserJob(command(), { ...h, signal: controller.signal,
    launchBrowser: () => { controller.abort(); return new Promise((resolve) => { finishLaunch = resolve }) } })
  finishLaunch({ close: async () => { closed = true }, newContext: () => assert.fail('must not create context') })
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(result.status, 'error')
  assert.equal(closed, true)
})

test('hung browser cleanup is bounded and cannot produce a passed receipt', async () => {
  const h = harness({ onBrowserClose: () => new Promise(() => {}) })
  const startedAt = Date.now()
  const result = await executeBrowserJob(command(), h)
  assert.equal(result.status, 'error')
  assert.equal(result.failure_summary, 'browser_interrupted')
  assert.equal(result.execution_receipt.execution_status, 'error')
  assert.equal(result.execution_receipt.private_evidence_stored, false)
  assert.ok(Date.now() - startedAt < 5000)
})

test('deadline during private sealing cannot leave a passed job with incomplete evidence', async () => {
  const h = harness({ seal: () => new Promise((resolve) => setTimeout(() => resolve(true), 1100)) })
  const job = command()
  job.timeout_ms = 1000
  const result = await executeBrowserJob(job, h)
  assert.equal(result.status, 'timed_out')
  assert.equal(result.execution_receipt.execution_status, 'timed_out')
  assert.equal(result.execution_receipt.private_evidence_stored, false)
  assert.equal(result.execution_receipt.write_fence, 'interrupted')
})
