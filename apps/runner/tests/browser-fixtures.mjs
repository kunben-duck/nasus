import { EventEmitter } from 'node:events'

import { BROWSER_DISPATCH_SCHEMA, BROWSER_RECEIPT_SCHEMA, BROWSER_MUTATIONS } from '../src/browser-job.mjs'

export const base = 'https://registered.example'
export const pins = Object.fromEntries(['plan_digest', 'script_digest', 'case_digest', 'environment_digest', 'browser_digest']
  .map((key, index) => [key, `sha256:${String(index + 1).repeat(64)}`]))
export const step = (action, operands = {}) => ({ action, source_step_indices: [0], ...operands })
export const command = (steps = [step('goto', { url: '/' }), step('assert_text', { selector: '#result', value: 'ready' })]) => ({
  job_id: 'browser-job', project_id: 'browser-project', us_id: 'browser-case', execution_kind: 'browser',
  receipt_protocol: BROWSER_RECEIPT_SCHEMA, base_url: base, timeout_ms: 10000, reviewed_pins: { ...pins }, steps,
})

// Browser doubles only: no Chromium, network server, target data, or filesystem artifacts.
export function harness(options = {}) {
  const calls = [], records = [], contexts = [], grants = []
  let launched = 0, closedBrowsers = 0
  function contextDouble() {
    const context = new EventEmitter()
    context.closed = false
    context.setDefaultTimeout = () => {}
    context.setDefaultNavigationTimeout = () => {}
    context.route = async (_pattern, handler) => { context.routeHandler = handler }
    context.routeWebSocket = async (_pattern, handler) => { context.socketHandler = handler }
    context.close = async () => { context.closed = true; await options.onContextClose?.(context) }
    context.request = async (url, method = 'GET', { navigation = false, redirected = false, frame } = {}) => {
      let outcome = 'pending'
      const request = { url: () => url, method: () => method, redirectedFrom: () => redirected ? {} : null,
        isNavigationRequest: () => navigation, frame: () => frame ?? context.page.mainFrame() }
      const route = {
        request: () => request,
        fetch: async (config) => {
          calls.push({ kind: 'fetch', url, method, config })
          const response = await options.fetch?.({ url, method, config, context }) ?? {}
          return { status: () => response.status ?? 200, headers: () => response.headers ?? {}, dispose: async () => {} }
        },
        fulfill: async (reply) => { calls.push({ kind: 'fulfill', url, headers: reply.headers }); outcome = 'fulfilled' },
        abort: async () => { calls.push({ kind: 'abort', url, method }); outcome = 'aborted' },
      }
      await context.routeHandler(route)
      return outcome
    }
    context.newPage = async () => {
      const page = new EventEmitter()
      context.page = page
      let currentUrl = 'about:blank'
      const frame = { url: () => currentUrl }
      page.mainFrame = () => frame
      page.url = () => currentUrl
      page.close = async () => {}
      page.navigateEvent = (url) => { currentUrl = url; page.emit('framenavigated', frame) }
      page.goto = async (url, config) => {
        calls.push({ kind: 'goto', url, config })
        if (await context.request(url, 'GET', { navigation: true }) === 'aborted') throw new Error('private navigation error')
        page.navigateEvent(url)
        await options.onGoto?.({ context, page, url })
      }
      page.screenshot = async () => Buffer.from('private-screen-pixels')
      page.locator = (selector) => {
        const act = async (action, value) => {
          calls.push({ kind: action, selector, value })
          await options.onAction?.({ action, selector, value, context, page })
        }
        return {
          count: async () => options.count?.(selector) ?? 1,
          fill: async (value) => act('fill', value), click: async () => act('click'), press: async (key) => act('press', key),
          waitFor: async () => act('wait_for'),
          isVisible: async () => options.visible?.(selector) ?? true,
          textContent: async () => { await act('textContent'); return options.text?.(selector) ?? 'ready' },
        }
      }
      context.emit('page', page)
      return page
    }
    contexts.push(context)
    return context
  }
  const launchBrowser = async () => {
    launched++
    return { newContext: async (config) => { calls.push({ kind: 'newContext', config }); return contextDouble() },
      close: async () => { closedBrowsers++; await options.onBrowserClose?.() } }
  }
  const privateDispatcher = async ({ command: job, requestHash }) => {
    const grant = { schema: BROWSER_DISPATCH_SCHEMA, request_hash: requestHash, reviewed_pins: { ...job.reviewed_pins },
      environment: { base_url: job.base_url, allowed_origins: [new URL(job.base_url).origin] },
      step_permissions: job.steps.map((item, index) => {
        const url = ['goto', 'assert_url'].includes(item.action) ? new URL(item.url ?? item.value, job.base_url).href : undefined
        return { step_index: index, read_only: !BROWSER_MUTATIONS.has(item.action),
          ...(url === undefined ? {} : { url }), ...(item.selector === undefined ? {} : { selector: item.selector }),
          requests: item.action === 'goto' ? [{ method: 'GET', url }] : [] }
      }),
      evidence: {
        record: async (event) => { records.push(event); return options.record ? await options.record(event, contexts.at(-1)) : true },
        seal: async (receipt) => { records.push({ kind: 'seal', receipt }); return options.seal ? await options.seal(receipt) : true },
      },
    }
    await options.grant?.(grant)
    grants.push(grant)
    return grant
  }
  return { calls, records, contexts, grants, launchBrowser, privateDispatcher,
    launched: () => launched, closedBrowsers: () => closedBrowsers }
}
