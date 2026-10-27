import assert from 'node:assert/strict'
import { test } from 'node:test'

import { createExecutionReceipt, requestHash } from '../src/execution-receipt.mjs'

const job = { jobId: 'receipt-job', projectId: 'receipt-project', usId: 'receipt-us',
  steps: [{ action: 'goto' }, { action: 'assert_text' }, { action: 'assert_visible' }] }

test('records only actual outcomes and never copies caller coverage authority', () => {
  const tracker = createExecutionReceipt({ ...job, business_coverage_verified: true }, requestHash('actual wire bytes'))
  tracker.start(0)
  tracker.observe(0, 'passed')
  tracker.start(1)
  tracker.observe(1, 'failed')
  const value = tracker.finish('failed')
  assert.deepEqual(value.steps.map((step) => step.status), ['passed', 'failed', 'not_executed'])
  assert.equal(value.assertion_count, 2)
  assert.equal(value.observed_assertion_count, 1)
  assert.equal(value.passed_assertion_count, 0)
  assert.equal(value.failed_assertion_count, 1)
  assert.equal(value.target_build_verified, false)
  assert.equal(value.business_coverage_verified, false)
})

test('a deadline seals observations before late browser callbacks settle', () => {
  const tracker = createExecutionReceipt(job, requestHash('original bytes'))
  assert.equal(tracker.stopped(), false)
  tracker.start(0)
  tracker.observe(0, 'passed')
  tracker.start(1)
  const interrupted = tracker.finish('timed_out')
  assert.equal(tracker.stopped(), true)
  tracker.observe(1, 'passed')
  tracker.start(2)
  tracker.observe(2, 'passed')
  assert.deepEqual(tracker.finish('timed_out'), interrupted)
  assert.deepEqual(interrupted.steps.map((step) => step.status), ['passed', 'interrupted', 'not_executed'])
  assert.equal(interrupted.observed_assertion_count, 0)
})

test('wire hashes preserve exact UTF-8, whitespace and property order', () => {
  assert.notEqual(requestHash('{"a":1,"b":2}'), requestHash('{"b":2,"a":1}'))
  assert.notEqual(requestHash('{"a":1}'), requestHash('{ "a": 1 }'))
  assert.match(requestHash(Buffer.from('中文和 emoji 🦆', 'utf8')), /^sha256:[a-f0-9]{64}$/)
})
