import { BrowserPolicyError, browserUrl, requireBrowser } from './browser-job.mjs'

const readMethods = new Set(['GET', 'HEAD'])

export async function installBrowserNetwork(context, { job, dispatch, state, signal, record }) {
  const pending = new Set()
  let requests = 0, closed = false, mainPage
  const rejectPolicy = (code = 'network_policy_rejected') => { state.policyFailure ??= code }
  const unknown = (index) => {
    state.unknownWrites.add(index)
    state.writeFence = 'unknown_write'
  }
  const handle = async (route) => {
    let response, dispatchedWrite = false, index = state.activeIndex
    try {
      signal.throwIfAborted()
      requireBrowser(!closed && !state.policyFailure, 'network_policy_rejected')
      requireBrowser(++requests <= 512, 'network_policy_rejected')
      const request = route.request(), url = browserUrl(request.url())
      const permission = dispatch.permissions[index]
      const method = request.method(), write = !readMethods.has(method)
      requireBrowser(dispatch.allowedOrigins.has(url.origin) && !url.hash && !request.redirectedFrom(), 'network_policy_rejected')
      requireBrowser(permission?.requests.has(`${method} ${url.href}`), 'network_policy_rejected')
      requireBrowser(!write || !permission.readOnly && state.writeFence === 'open', 'network_policy_rejected')
      if (request.isNavigationRequest()) {
        requireBrowser(request.frame() === mainPage?.mainFrame(), 'network_policy_rejected')
      }
      dispatchedWrite = write
      if (write) state.inflightWrites.add(index)
      // Never continue(): browser-managed redirects bypass per-hop routing. V1 rejects redirects entirely.
      response = await route.fetch({ maxRedirects: 0, maxRetries: 0, timeout: Math.max(1, state.deadlineAt - Date.now()) })
      signal.throwIfAborted()
      const headers = response.headers()
      if (response.status() >= 300 && response.status() < 400 || headers.refresh !== undefined) {
        if (headers.location) {
          requireBrowser(dispatch.allowedOrigins.has(browserUrl(headers.location, url).origin), 'network_policy_rejected')
        }
        throw new BrowserPolicyError('redirect_rejected')
      }
      if (write && response.status() >= 500) throw new BrowserPolicyError('unknown_write')
      await record({ kind: 'network_response', step_index: index, method, url: url.href, status: response.status() })
      signal.throwIfAborted()
      requireBrowser(!closed && !state.policyFailure, 'network_policy_rejected')
      // Additional policy does not replace the target's CSP. Unsupported frames/plugins are disabled.
      const csp = `connect-src ${[...dispatch.allowedOrigins].join(' ')}; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action ${[...dispatch.allowedOrigins].join(' ')}`
      await route.fulfill({ response, headers: { ...headers,
        'content-security-policy': [headers['content-security-policy'], csp].filter(Boolean).join(', ') } })
    } catch (error) {
      if (dispatchedWrite) unknown(index)
      if (!closed && !signal.aborted) {
        if (error instanceof BrowserPolicyError && error.code !== 'unknown_write') rejectPolicy(error.code)
        else if (!dispatchedWrite) rejectPolicy()
      }
      await route.abort('blockedbyclient').catch(() => {})
    } finally {
      if (dispatchedWrite) state.inflightWrites.delete(index)
      await response?.dispose().catch(() => {})
    }
  }
  await context.route('**/*', (route) => {
    const task = handle(route)
    pending.add(task)
    return task.finally(() => pending.delete(task))
  })
  // WebSockets bypass HTTP routing; no socket/worker/popup execution is supported by this slice.
  await context.routeWebSocket('**/*', (socket) => {
    if (!closed) rejectPolicy()
    socket.close({ code: 1008, reason: 'Browser policy' })
  })
  context.on('page', (page) => {
    if (mainPage) {
      rejectPolicy()
      void page.close().catch(() => {})
      return
    }
    mainPage = page
    page.on('worker', () => rejectPolicy())
    page.on('download', (download) => {
      rejectPolicy()
      void download.cancel().catch(() => {})
    })
    page.on('framenavigated', (frame) => {
      try {
        requireBrowser(frame === page.mainFrame(), 'network_policy_rejected')
        const url = browserUrl(frame.url())
        requireBrowser(dispatch.allowedOrigins.has(url.origin)
          && dispatch.permissions[state.activeIndex]?.requests.has(`GET ${url.href}`), 'network_policy_rejected')
      } catch { rejectPolicy() }
    })
  })
  return {
    async drain() { while (pending.size) await Promise.all([...pending]) },
    close() { closed = true },
  }
}
