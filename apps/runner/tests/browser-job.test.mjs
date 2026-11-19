import assert from 'node:assert/strict'
import { test } from 'node:test'

import { executeBrowserJob } from '../src/browser-executor.mjs'
import { validateBrowserJob } from '../src/browser-job.mjs'
import { command, harness, step } from './browser-fixtures.mjs'

test('accepts only versioned schema operands and the pinned Vue attribute locator subset', () => {
  for (const selector of ['#stable-id', '[data-testid="result"]', 'input[name="email"]', 'textarea[name="body"]',
    'input[placeholder="Enter tags"]', 'input[placeholder="What\'s this article about?"]',
    'textarea[placeholder="Write your article (in markdown)"]', 'button[type="submit"]', 'input[type="password"]']) {
    const job = validateBrowserJob(command([step('fill', { selector, value: '' })]))
    assert.equal(job.steps[0].selector, selector)
    assert.ok(Object.isFrozen(job.command))
    assert.ok(Object.isFrozen(job.steps[0].source_step_indices))
  }
})

test('rejects arbitrary code, CSS, legacy aliases, absolute URLs and unbounded operands before launch', async () => {
  const invalidSteps = [
    step('eval', { code: 'process.exit()' }), step('shell', { command: 'id' }),
    step('goto', { path: '/' }), step('assert_text', { selector: '#result', text: 'ready' }),
    step('assert_text', { selector: '#result', value: '' }), step('goto', { url: 'https://registered.example/' }),
    ...['//foreign.example/', '/\\foreign.example/', '/#fragment', 'javascript:alert(1)', '/\u0000'].map((url) => step('goto', { url })),
    ...['body', 'h1', '*', 'input', '#one, #two', '#one >> nth=0', 'xpath=//input',
      'text=Sign in', 'input[placeholder="Email"] button', '[type="submit"]',
      'input[placeholder="Email\\22"]', 'button[type="unknown"]'].map((selector) => step('click', { selector })),
    step('press', { selector: '#one', key: 'Control+Shift+I' }),
    step('fill', { selector: '#one', value: 'x', credential_ref: 'private-ref' }),
    step('click', { selector: '#one', phase: 'verification' }),
    step('click', { selector: '#one', source_step_indices: [0, 0] }),
    step('click', { selector: '#one', timeout_ms: '1000' }),
  ]
  for (const item of invalidSteps) {
    const h = harness()
    const result = await executeBrowserJob(command([item]), h)
    assert.equal(result.status, 'error', JSON.stringify(item))
    assert.equal(result.execution_receipt, undefined)
    assert.equal(h.launched(), 0)
  }
})

test('strict wire identity rejects duplicate keys, mismatched objects, unknown fields and pins', async () => {
  const raw = command(), wire = JSON.stringify(raw)
  const variants = [
    [raw, wire.replace('"steps":', '"steps":[],"steps":')],
    [raw, wire.replace('browser-job', 'different-job')],
    [{ ...raw, metadata: {} }], [{ ...raw, allowed_origins: ['https://foreign.example'] }],
    [{ ...raw, receipt_protocol: 'nasus.runner-execution.v1' }],
    [{ ...raw, reviewed_pins: { ...raw.reviewed_pins, browser_digest: 'latest' } }],
    [{ ...raw, base_url: 'https://name:secret@registered.example' }],
    [{ ...raw, timeout_ms: 999 }], [{ ...raw, steps: [] }],
  ]
  for (const [job, wireBody] of variants) {
    const h = harness()
    const result = await executeBrowserJob(job, { ...h, wireBody })
    assert.equal(result.status, 'error')
    assert.equal(result.execution_receipt, undefined)
    assert.equal(h.launched(), 0)
    assert.doesNotMatch(JSON.stringify(result), /secret|different-job|latest/)
  }
})

test('public source intake cannot authorize execution or credentials', async () => {
  const h = harness()
  const result = await executeBrowserJob(command(), { launchBrowser: h.launchBrowser })
  assert.equal(result.failure_summary, 'private_dispatch_required')
  assert.equal(result.execution_receipt, undefined)
  assert.deepEqual(result.artifacts, [])
  assert.equal(h.launched(), 0)
})

test('private dispatch must bind exact wire/pins/environment/locator/URL and private evidence', async () => {
  const changes = [
    (g) => { g.request_hash = 'sha256:' + '0'.repeat(64) },
    (g) => { g.reviewed_pins.case_digest = 'sha256:' + '0'.repeat(64) },
    (g) => { g.environment.base_url = 'https://other.example' },
    (g) => { g.environment.allowed_origins = ['https://*.example'] },
    (g) => { g.step_permissions[1].selector = '#not-reviewed' },
    (g) => { g.step_permissions[0].url = 'https://registered.example/unreviewed' },
    (g) => { g.step_permissions[0].requests.push({ method: 'POST', url: 'https://registered.example/' }) },
    (g) => { g.step_permissions[1].requests.push({ method: 'GET', url: 'https://foreign.example/' }) },
    (g) => { g.evidence = {} },
    (g) => { g.evidence.record = async () => false },
  ]
  for (const change of changes) {
    const h = harness({ grant: change })
    const result = await executeBrowserJob(command(), h)
    assert.equal(result.status, 'error')
    assert.equal(result.execution_receipt, undefined)
    assert.equal(h.launched(), 0)
  }
})
