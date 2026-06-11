const { chromium } = require('@playwright/test')
const { spawn } = require('node:child_process')

const portalUrl = process.env.PORTAL_URL || 'http://127.0.0.1:4173'
const apiUrl = process.env.API_URL || 'http://127.0.0.1:8000'

async function canReach(url) {
  try {
    const response = await fetch(url)
    return response.ok
  } catch {
    return false
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

async function main() {
  const apiServer = await ensureServer({
    url: `${apiUrl}/healthz`,
    label: 'API server',
    command: './.venv/bin/python -m uvicorn apps.api.app.main:app --app-dir . --host 127.0.0.1 --port 8000',
  })
  const portalServer = await ensureServer({
    url: portalUrl,
    label: 'Portal server',
    command: 'npm --prefix apps/portal run dev -- --host 127.0.0.1 --port 4173',
  })
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage()
  const projectName = `Smoke Quality Hub ${Date.now()}`

  try {
    await page.goto(portalUrl, { waitUntil: 'domcontentloaded' })
    await expectVisible(page.getByRole('heading', { name: /Build quality projects with agents/i }), 'build shell loaded')

    await page.getByTestId('build-agent-input').fill(`Help me create a new project called ${projectName}`)
    await page.getByTestId('build-agent-submit').click()
    await expectVisible(page.getByTestId('agent-workspace'), 'project workspace opened')
    await expectVisible(page.getByText(projectName).first(), 'created project visible')

    await page.getByTestId('agent-card-system-image-builder').click()
    await expectVisible(page.getByTestId('system-image-strip').getByText(/ready/i).first(), 'system image initialized')

    await page.getByTestId('project-agent-input').fill('Show me the current system image freshness and baseline status')
    await page.getByTestId('project-agent-submit').click()
    await expectVisible(page.getByText(/source groups are indexed|system image is/i).first(), 'agent answered system image query')

    await page.getByTestId('agent-card-quality-loop-agent').click()
    await expectVisible(page.getByText(/imported US work item/i).first(), 'quality loop requires imported US')

    console.log('smoke: success')
  } finally {
    await browser.close()
    stopServer(portalServer)
    stopServer(apiServer)
  }
}

main().catch((error) => {
  console.error('smoke: failed')
  console.error(error)
  process.exit(1)
})
