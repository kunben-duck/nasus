import assert from 'node:assert/strict'
import { test } from 'node:test'

import { executeBrowserJob } from '../src/browser-executor.mjs'
import { base, command, harness, step } from './browser-fixtures.mjs'

test('every routed subresource/navigation is bound to reviewed origins AND exact per-step URLs', async () => {
  for (const url of ['https://foreign.example/image.png', base + '/unreviewed.js',
    'http://registered.example/other-scheme', 'https://registered.example:444/other-port',
    'https://name:password@registered.example/', 'file:///etc/passwd']) {
    const h = harness({ onGoto: async ({ context }) => {
      assert.equal(await context.request(url), 'aborted')
    } })
    const result = await executeBrowserJob(command(), h)
    assert.equal(result.status, 'error', url)
    assert.ok(!h.calls.some((call) => call.kind === 'fetch' && call.url === url))
    assert.equal(result.execution_receipt.steps[1].status, 'not_executed')
    assert.doesNotMatch(JSON.stringify(result), /foreign|password|passwd|registered\.example/)
  }
})

test('same-origin and foreign redirects/Refresh headers never get followed', async () => {
  for (const headers of [{ location: 'https://foreign.example/steal' }, { location: '/allowed-but-redirected' },
    { location: 'javascript:alert(1)' }, { refresh: '0;url=https://foreign.example/' }]) {
    const h = harness({ fetch: () => ({ status: headers.refresh ? 200 : 302, headers }) })
    const result = await executeBrowserJob(command(), h)
    assert.equal(result.status, 'error')
    const fetches = h.calls.filter((call) => call.kind === 'fetch')
    assert.equal(fetches.length, 1)
    assert.equal(fetches[0].config.maxRedirects, 0)
    assert.equal(fetches[0].config.maxRetries, 0)
    assert.equal(h.calls.filter((call) => call.kind === 'fulfill').length, 0)
  }
})

test('redirected requests are rejected even when destination is explicitly allowlisted', async () => {
  const h = harness({ onGoto: async ({ context }) => {
    assert.equal(await context.request(base + '/', 'GET', { redirected: true }), 'aborted')
  } })
  const result = await executeBrowserJob(command(), h)
  assert.equal(result.status, 'error')
  assert.equal(h.calls.filter((call) => call.kind === 'fetch').length, 1)
})

test('approved secondary origins require both registered environment and request permissions', async () => {
  const api = 'https://api.registered.example/data'
  const h = harness({ grant: (grant) => {
    grant.environment.allowed_origins.push('https://api.registered.example')
    grant.step_permissions[0].requests.push({ method: 'GET', url: api })
  }, onGoto: async ({ context }) => { assert.equal(await context.request(api), 'fulfilled') } })
  const result = await executeBrowserJob(command(), h)
  assert.equal(result.status, 'passed')
  assert.ok(h.calls.some((call) => call.kind === 'fetch' && call.url === api))
})

test('uncertain writes fence later writes for network failure and 5xx, with zero transport retries', async () => {
  for (const failure of ['disconnect', '5xx']) {
    const h = harness({ grant: (grant) => {
      grant.step_permissions[0].requests.push({ method: 'POST', url: base + '/submit' })
    }, onAction: async ({ action, context }) => { if (action === 'click') await context.request(base + '/submit', 'POST') },
    fetch: ({ method }) => {
      if (method === 'POST') {
        if (failure === 'disconnect') throw new Error('uncertain private response')
        return { status: 503 }
      }
    } })
    const result = await executeBrowserJob(command([step('click', { selector: '#submit' }),
      step('click', { selector: '#retry' }), step('assert_visible', { selector: '#result', phase: 'verification' })]), h)
    assert.equal(result.status, 'error')
    assert.equal(result.failure_summary, 'unknown_write')
    assert.deepEqual(result.execution_receipt.unknown_write_step_indices, [0])
    assert.deepEqual(result.execution_receipt.steps.map((item) => item.status), ['interrupted', 'not_executed', 'passed'])
    const writes = h.calls.filter((call) => call.kind === 'fetch' && call.method === 'POST')
    assert.equal(writes.length, 1)
    assert.equal(writes[0].config.maxRetries, 0)
  }
})

test('background writes cannot bypass an assertion fence during evidence recording', async () => {
  let attempted = false
  const h = harness({ text: () => 'wrong', record: async (event, context) => {
    if (event.kind === 'step_observation' && event.status === 'failed') {
      attempted = true
      assert.equal(await context.request(base + '/submit', 'POST'), 'aborted')
    }
    return true
  } })
  const result = await executeBrowserJob(command([step('assert_text', { selector: '#result', value: 'expected' }),
    step('click', { selector: '#submit' })]), h)
  assert.equal(attempted, true)
  assert.equal(result.execution_receipt.first_failed_assertion_index, 0)
  assert.equal(result.execution_receipt.failed_assertion_count, 1)
  assert.equal(result.status, 'error')
  assert.equal(h.calls.some((call) => call.kind === 'fetch' && call.method === 'POST'), false)
})

test('WebSockets, workers, non-HTTP/unreviewed navigation and popup pages fail closed', async () => {
  const attempts = [
    ({ context }) => { let closed = false; context.socketHandler({ close: () => { closed = true } }); assert.equal(closed, true) },
    ({ page }) => page.emit('worker', {}),
    ({ page }) => page.navigateEvent('data:text/html,secret'),
    ({ page }) => page.navigateEvent('https://foreign.example/'),
    ({ page }) => page.navigateEvent(base + '/not-reviewed'),
    ({ context }) => context.emit('page', { close: async () => {} }),
  ]
  for (const attempt of attempts) {
    const h = harness({ onGoto: attempt })
    const result = await executeBrowserJob(command(), h)
    assert.equal(result.status, 'error')
    assert.equal(result.execution_receipt.steps[1].status, 'not_executed')
  }
})
