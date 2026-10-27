const { chromium } = require('@playwright/test')
const { spawn } = require('node:child_process')
const fsSync = require('node:fs')
const fs = require('node:fs/promises')
const os = require('node:os')
const path = require('node:path')

const portalUrl = process.env.PORTAL_URL || 'http://127.0.0.1:4173'
const apiUrl = process.env.API_URL || 'http://127.0.0.1:8000'
const apiCommand = process.env.SMOKE_API_COMMAND || './.venv/bin/python -m uvicorn apps.api.app.main:app --app-dir . --host 127.0.0.1 --port 8000'
const portalCommand = process.env.SMOKE_PORTAL_COMMAND || 'npm --prefix apps/portal run dev -- --host 127.0.0.1 --port 4173'
const smokeStateDir = process.env.NASUS_SMOKE_STATE_DIR || fsSync.mkdtempSync(path.join(os.tmpdir(), 'nasus-smoke-state-'))
const smokeDatabaseUrl = process.env.NASUS_DATABASE_URL || `sqlite+pysqlite:///${path.join(smokeStateDir, 'nasus.db')}`

async function canReach(url, timeout = 2500) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeout)
  try {
    const response = await fetch(url, { signal: controller.signal })
    return response.ok
  } catch {
    return false
  } finally {
    clearTimeout(timer)
  }
}

async function waitFor(url, label, timeout = 60000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    if (await canReach(url)) return
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  throw new Error(`${label} did not become ready at ${url}`)
}

async function ensureServer({ url, label, command }) {
  if (await canReach(url)) return null

  const child = spawn(command, {
    cwd: process.cwd(),
    shell: true,
    stdio: 'ignore',
    detached: false,
    env: {
      ...process.env,
      NASUS_STATE_DIR: smokeStateDir,
      NASUS_DATABASE_URL: smokeDatabaseUrl,
      NASUS_PORTAL_API_PROXY: apiUrl,
      NASUS_RUNNER_MODE: process.env.NASUS_RUNNER_MODE || 'protocol_stub',
    },
  })

  await waitFor(url, label)
  return child
}

function stopServer(child) {
  if (!child || child.killed) return
  child.kill('SIGTERM')
}

async function expectVisible(locator, label, timeout = 15000) {
  await locator.waitFor({ state: 'visible', timeout })
  console.log(`ok: ${label}`)
}

async function createAuthSession() {
  const email = `smoke-${Date.now()}-${Math.random().toString(16).slice(2)}@example.com`
  const response = await fetch(`${apiUrl}/v1/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      email,
      password: 'strong-password-123',
      name: 'Smoke Admin',
    }),
  })
  if (!response.ok) {
    throw new Error(`Unable to create smoke auth session: ${response.status} ${await response.text()}`)
  }
  const session = await response.json()
  const settingsResponse = await fetch(`${apiUrl}/v1/settings`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${session.access_token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ language: 'en' }),
  })
  if (!settingsResponse.ok) {
    throw new Error(`Unable to select smoke language: ${settingsResponse.status} ${await settingsResponse.text()}`)
  }
  return session
}

async function createSourceFixture() {
  const fixtureRoot = path.join(process.cwd(), '.nasus', 'smoke-fixtures')
  await fs.mkdir(fixtureRoot, { recursive: true })
  const root = await fs.mkdtemp(path.join(fixtureRoot, 'nasus-smoke-'))
  const codeDir = path.join(root, 'code')
  const usDir = path.join(root, 'us')
  const testDir = path.join(root, 'tests')
  await fs.mkdir(codeDir, { recursive: true })
  await fs.mkdir(usDir, { recursive: true })
  await fs.mkdir(testDir, { recursive: true })
  await fs.writeFile(
    path.join(codeDir, 'checkout_service.py'),
    [
      'class CheckoutService:',
      '    def calculate_total(self, subtotal, discount):',
      '        return subtotal - discount',
      '',
      '    def authorize_payment(self, token):',
      '        return token.startswith("tok_")',
      '',
    ].join('\n'),
  )
  await fs.writeFile(
    path.join(usDir, 'US-101-checkout.md'),
    [
      '# US-101 Checkout payment authorization',
      'As a shopper, I want saved-card checkout to authorize payment safely.',
      '',
      'Acceptance criteria:',
      '- calculate totals with discounts',
      '- authorize payment token before order creation',
      '- show recoverable error states',
      '',
    ].join('\n'),
  )
  await fs.writeFile(
    path.join(testDir, 'test_checkout_service.py'),
    [
      'from checkout_service import CheckoutService',
      '',
      'def test_authorize_payment_token():',
      '    assert CheckoutService().authorize_payment("tok_smoke")',
      '',
    ].join('\n'),
  )
  return { root, codeDir, usDir, testDir }
}

async function main() {
  const apiServer = await ensureServer({
    url: `${apiUrl}/healthz`,
    label: 'API server',
    command: apiCommand,
  })
  const portalServer = await ensureServer({
    url: portalUrl,
    label: 'Portal server',
    command: portalCommand,
  })
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage()
  const systemImageResponses = []
  const pageErrors = []
  const projectName = `Smoke Quality Hub ${Date.now()}`
  const fixture = await createSourceFixture()

  try {
    page.on('pageerror', (error) => {
      pageErrors.push(error.message)
    })
    page.on('response', async (response) => {
      if (!response.url().includes('/system-image') || response.request().method() !== 'GET') return
      const payload = await response.json().catch(() => null)
      systemImageResponses.push({
        at: new Date().toISOString(),
        status: response.status(),
        projectStatus: payload?.project?.system_image_status ?? null,
        buildStatus: payload?.build_state?.status ?? null,
        sourceStatuses: payload?.sources?.map((source) => source.ingestion_status) ?? [],
      })
      if (systemImageResponses.length > 30) systemImageResponses.shift()
    })
    const session = await createAuthSession()
    await page.addInitScript((token) => {
      window.localStorage.setItem('nasus_api_token', token)
      window.localStorage.setItem('nasus.locale', 'en')
      window.__nasusSmokeSseEvents = []
      window.__nasusSmokeSseOpenUrls = []
      const NativeEventSource = window.EventSource
      window.EventSource = class TrackingEventSource extends NativeEventSource {
        constructor(url, options) {
          super(url, options)
          this.addEventListener('open', () => {
            window.__nasusSmokeSseOpenUrls.push(String(url))
          })
          ;[
            'conversation.message.created',
            'agent.step.updated',
            'agent.step.thinking.delta',
            'agent.step.observation.delta',
            'agent.step.decision.delta',
            'agent.swarm.updated',
            'runtime.thinking.delta',
            'runtime.observation.delta',
            'runtime.decision.delta',
            'agent.goal.updated',
            'tool.invocation.updated',
          ].forEach((eventType) => {
            this.addEventListener(eventType, (event) => {
              let payload = null
              try {
                payload = JSON.parse(event.data)
              } catch {
                payload = { raw: event.data }
              }
              window.__nasusSmokeSseEvents.push({ eventType, payload, at: Date.now() })
              if (window.__nasusSmokeSseEvents.length > 1_000) window.__nasusSmokeSseEvents.shift()
            })
          })
        }
      }
    }, session.access_token)
    await page.goto(`${portalUrl}/build`, { waitUntil: 'domcontentloaded' })
    await expectVisible(page.getByRole('heading', { name: /Build quality projects with Nasus/i }), 'build shell loaded')

    const buildSseOpenCount = await page.evaluate(() => window.__nasusSmokeSseOpenUrls.length)
    await page.getByTestId('build-agent-input').fill(`Help me create a new project called ${projectName}`)
    await page.getByTestId('build-agent-submit').click()
    await page.waitForURL(/\/projects\//, { timeout: 15000 })
    await expectVisible(page.getByTestId('agent-workspace'), 'project workspace opened')
    await expectVisible(page.getByText(projectName).first(), 'created project visible')
    await page.waitForFunction(
      (previousCount) => window.__nasusSmokeSseOpenUrls.length > previousCount,
      buildSseOpenCount,
      { timeout: 15_000 },
    )

    await page.getByTestId('agent-card-system-image-builder').click()
    await expectVisible(page.getByTestId('source-binding-panel'), 'required and optional source inputs visible')
    await page.getByTestId('source-code-input').fill(fixture.codeDir)
    await page.getByTestId('source-us-input').fill(fixture.usDir)
    await page.getByTestId('source-tests-input').fill(fixture.testDir)
    await page.getByTestId('build-system-image-with-sources').click()
    await expectVisible(page.getByTestId('agent-goal-panel'), 'system image agent goal visible')
    await expectVisible(page.getByTestId('agent-thinking-card'), 'agent thinking card visible')
    await expectVisible(page.getByTestId('agent-memory-context-panel'), 'agent memory context visible')
    await expectVisible(page.getByTestId('image-build-execution-budget'), 'independent structural budget visible', 20000)
    const projectId = new URL(page.url()).pathname.split('/')[2]
    const authorizedRead = async (relative) => {
      const response = await fetch(`${apiUrl}${relative}`, { headers: { Authorization: `Bearer ${session.access_token}` } })
      if (!response.ok) throw new Error(`Smoke read failed: ${response.status} ${relative}`)
      return response.json()
    }
    const conversation = await authorizedRead(`/v1/conversations?space_type=project&space_id=${projectId}`)
    const conversationId = conversation[0].id
    const before = await authorizedRead(`/v1/conversations/${conversationId}`)
    if (before.agent_goals.length !== 1) throw new Error('The guided entry must create exactly one fixed goal')
    const goal = before.agent_goals[0]
    const planId = goal.target_refs.find((ref) => ref.startsWith('build_plan:')).slice('build_plan:'.length)
    const planUrl = `/v1/projects/${projectId}/system-image/build-plans/${planId}`
    const draft = await authorizedRead(planUrl)
    if (draft.execution_authorizations.length || draft.structural_artifacts.length) {
      throw new Error('Preparing sources or a plan must not grant execution or build a candidate')
    }
    await page.getByTestId('confirm-agent-goal').click()
    try {
      await expectVisible(page.getByTestId('agent-confirmation-gate').getByText('Structural candidate saved', { exact: true }), 'structural candidate saved')
    } catch (error) {
      const diagnostics = await page.evaluate(() => ({
        strip: document.querySelector('[data-testid="system-image-strip"]')?.textContent ?? null,
        events: (window.__nasusSmokeSseEvents ?? []).slice(-25).map(({ eventType, payload, at }) => ({
          eventType,
          at,
          eventId: payload?.event_id ?? null,
          entityVersion: payload?.entity_version ?? null,
          patch: payload?.patch ?? null,
          queryKeys: payload?.query_keys ?? [],
        })),
      }))
      console.error('smoke diagnostics:', JSON.stringify({
        systemImageResponses,
        pageErrors,
        strip: diagnostics.strip,
        events: diagnostics.events,
      }, null, 2))
      throw error
    }
    const built = await authorizedRead(planUrl)
    if (built.structural_artifacts.length !== 1 || built.execution_authorizations.length !== 1
      || built.execution_authorizations[0].goal_id !== goal.id || built.execution_authorizations[0].publication_allowed !== false) {
      throw new Error('The original goal must own one structure-only grant and candidate, without publication')
    }
    const pinned = await authorizedRead(`/v1/conversations/${conversationId}`)
    if (pinned.agent_goals.length !== 1 || pinned.agent_goals[0].id !== goal.id
      || pinned.agent_goals[0].pause_reason !== 'structural_candidate_review') {
      throw new Error('Structural completion must retain the same paused goal')
    }
    await expectVisible(page.getByTestId('system-image-strip').getByText(/Sources indexed\s*3\/3/i).first(), 'source groups indexed')
    const canonicalAgentEvents = await page.evaluate(() => (
      window.__nasusSmokeSseEvents ?? []
    ).filter(({ eventType }) => eventType.startsWith('agent.step.')))
    if (!canonicalAgentEvents.some(({ eventType }) => eventType === 'agent.step.thinking.delta')) {
      throw new Error(`canonical agent thinking event was not observed: ${JSON.stringify(canonicalAgentEvents.map(({ eventType, payload }) => ({ eventType, eventId: payload?.event_id })))}`)
    }
    if (!canonicalAgentEvents.some(({ eventType }) => eventType === 'agent.step.updated')) {
      throw new Error(`canonical agent step update was not observed: ${JSON.stringify(canonicalAgentEvents.map(({ eventType, payload }) => ({ eventType, eventId: payload?.event_id })))}`)
    }

    await page.getByTestId('project-agent-input').fill('Show me the current system image freshness and baseline status')
    await page.getByTestId('project-agent-submit').click()
    await expectVisible(page.getByText(/source groups are indexed|system image is/i).first(), 'agent answered system image query')

    await page.getByTestId('agent-card-quality-loop-agent').click()
    await expectVisible(page.getByTestId('quality-asset-panel'), 'quality loop panel is available')

    console.log('smoke: success')
  } finally {
    await browser.close()
    await fs.rm(fixture.root, { recursive: true, force: true })
    stopServer(portalServer)
    stopServer(apiServer)
  }
}

main().catch((error) => {
  console.error('smoke: failed')
  console.error(error)
  process.exit(1)
})
