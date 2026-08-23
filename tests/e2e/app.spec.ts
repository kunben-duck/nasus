import { expect, test } from '@playwright/test'
import * as path from 'node:path'

const apiPort = process.env.PLAYWRIGHT_API_PORT ?? '8000'
const apiUrl = `http://127.0.0.1:${apiPort}`
const adminToken = process.env.NASUS_E2E_ADMIN_TOKEN ?? 'nasus-e2e-platform-admin-token'

async function createBrowserSession(page: import('@playwright/test').Page) {
  const email = `e2e-${Date.now()}-${Math.random().toString(16).slice(2)}@example.com`
  const response = await fetch(`${apiUrl}/v1/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      email,
      password: 'strong-password-123',
      name: 'E2E Admin',
    }),
  })
  if (!response.ok) {
    throw new Error(`Unable to create E2E auth session: ${response.status} ${await response.text()}`)
  }
  const session = await response.json() as { access_token: string }
  await page.addInitScript((token) => {
    window.localStorage.setItem('nasus_api_token', token)
  }, session.access_token)
}

async function createPlatformAdminBrowserSession(page: import('@playwright/test').Page) {
  await page.addInitScript((token) => {
    window.localStorage.setItem('nasus_api_token', token)
  }, adminToken)
}

test('unauthenticated users register with email before entering build', async ({ page }) => {
  const email = `signup-${Date.now()}-${Math.random().toString(16).slice(2)}@example.com`

  await page.goto('/welcome')
  await expect(page.getByRole('heading', { name: /Build quality project from now/i })).toBeVisible()
  await expect(page.getByText(/Initialize system image from code/i)).toBeVisible()
  await expect(page.getByRole('heading', { name: /Build on a living system image/i })).not.toBeInViewport()
  await page.mouse.wheel(0, 900)
  await expect(page.getByRole('heading', { name: /Build on a living system image/i })).toBeInViewport({ timeout: 5_000 })

  await page.getByRole('link', { name: /Get started/i }).first().click()
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: /Sign in to Nasus Studio/i })).toBeVisible()
  await expect(page.getByRole('link', { name: /^Get started$/i })).toHaveCount(0)

  await page.getByRole('link', { name: /^Create account$/i }).click()
  await expect(page).toHaveURL(/\/register$/)
  await expect(page.getByRole('heading', { name: /Create your Nasus account/i })).toBeVisible()

  await page.getByLabel(/Name/i).fill('Signup Admin')
  await page.getByLabel(/Email/i).fill(email)
  await page.getByLabel(/^Password$/i).fill('strong-password-123')
  await page.getByLabel(/Confirm password/i).fill('strong-password-123')
  await page.getByRole('button', { name: /Create account/i }).click()

  await expect(page).toHaveURL(/\/build$/)
  await expect(page.getByRole('heading', { name: /Build quality projects with Nasus/i })).toBeVisible()
  await expect(page.getByRole('button', { name: new RegExp(email, 'i') })).toBeVisible()
})

test('agent-first build to project workspace path works end-to-end', async ({ page }) => {
  test.setTimeout(45_000)
  const projectName = `E2E Quality Hub ${Date.now()}`
  const fixtureRoot = path.resolve(process.cwd(), 'tests/fixtures/system-image')

  await createBrowserSession(page)
  await page.goto('/build')
  await expect(page.getByRole('heading', { name: /Build quality projects with Nasus/i })).toBeVisible()
  await expect(page.getByTestId('backend-status-pill')).toContainText(/Live/i)

  await page.getByTestId('build-agent-input').fill(`Help me create a new project called ${projectName}`)
  await page.getByTestId('build-agent-submit').click()

  await expect(page).toHaveURL(/\/projects\//, { timeout: 15_000 })
  await expect(page.getByRole('heading', { name: /Build with Agents/i })).toBeVisible()
  await expect(page.getByText(projectName).first()).toBeVisible()

  await page.getByTestId('agent-card-system-image-builder').click()
  await expect(page.getByTestId('agent-goal-panel')).toContainText(/Build Official System Image/i, { timeout: 15_000 })
  await expect(page.getByTestId('agent-loop-trace')).toContainText(/Think · Act · Observe · Decide/i, { timeout: 15_000 })
  await expect(page.getByTestId('agent-current-step')).toBeVisible()
  await expect(page.getByTestId('agent-thinking-card')).toBeVisible()
  await expect(page.getByTestId('agent-memory-context-panel')).toBeVisible()
  await expect(page.getByTestId('agent-confirmation-gate')).toContainText(/Source bindings required/i, { timeout: 15_000 })

  await expect(page.getByTestId('source-binding-panel')).toBeVisible()
  await page.getByTestId('source-code-input').fill(path.join(fixtureRoot, 'code'))
  await page.getByTestId('source-us-input-file').setInputFiles(
    path.join(fixtureRoot, 'us', 'US-101-checkout.md'),
  )
  await expect(page.getByTestId('source-us-input')).toHaveValue(/^(local-object|s3):\/\//)
  await page.getByTestId('source-tests-input-file').setInputFiles(
    path.join(fixtureRoot, 'tests', 'test_checkout_service.py'),
  )
  await expect(page.getByTestId('source-tests-input')).toHaveValue(/^(local-object|s3):\/\//)
  await page.getByTestId('build-system-image-with-sources').click()
  await expect(page.getByTestId('agent-confirmation-gate')).toContainText(/Confirmation required/i, { timeout: 20_000 })

  await page.getByTestId('confirm-agent-goal').click()
  await expect(page.getByTestId('system-image-strip')).toContainText(/ready/i, { timeout: 20_000 })
  await expect(page.getByTestId('system-image-strip')).toContainText(/Official System Image ready/i)
  await expect(page.getByTestId('agent-goal-panel')).toContainText(/completed/i)
  await expect(page.getByText(/Sources indexed/i)).toBeVisible()
  await expect(page.getByText(/Code analysis/i)).toBeVisible()

  await page.getByTestId('project-agent-input').fill('Show me the current system image freshness and baseline status')
  await page.getByTestId('project-agent-submit').click()
  await expect(page.getByText(/source groups are indexed|system image is/i).first()).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('agent-card-quality-loop-agent')).toBeEnabled({ timeout: 15_000 })

  await page.getByTestId('agent-card-quality-loop-agent').click()
  await expect(page.getByTestId('agent-goal-panel')).toContainText(/Advance quality loop/i, { timeout: 15_000 })
  await expect(page.getByTestId('agent-goal-panel')).toContainText(/completed/i, { timeout: 20_000 })
  await expect(page.getByTestId('quality-asset-panel')).toContainText(/Release Assessment/i, { timeout: 20_000 })
  await expect(page.getByTestId('quality-asset-panel')).toContainText(/ready for review/i)
  await expect(page.getByTestId('quality-loop-state')).toContainText(/in progress/i)

  await page.getByTestId('project-agent-input').fill(
    'Continue the quality loop against http://example.test and assess release readiness',
  )
  await page.getByTestId('project-agent-submit').click()
  await expect(page.getByTestId('agent-goal-panel')).toContainText(/completed/i, { timeout: 20_000 })
  await expect(page.getByTestId('quality-asset-panel')).toContainText(/completed/i)
  await expect(page.getByTestId('quality-loop-state')).toContainText(/ready for release/i, { timeout: 20_000 })
  await expect(page.getByTestId('quality-loop-state')).toContainText(/Release score/i)
  await expect(page.getByTestId('quality-asset-panel')).toContainText(/Latest run/i)

  const releaseAssessRequests: string[] = []
  page.on('request', (request) => {
    if (request.method() !== 'POST' || !request.url().endsWith('/v1/tool-invocations')) return
    const body = request.postData() ?? ''
    if (body.includes('"tool_id":"release.assess"')) {
      releaseAssessRequests.push(body)
    }
  })

  await page.getByTestId('tool-release-gate').dblclick()
  await expect(page.getByTestId('tool-invocation-rail')).toContainText(/release\.assess/i, { timeout: 15_000 })
  await expect(page.getByTestId('tool-invocation-rail')).toContainText(/completed/i, { timeout: 15_000 })
  await expect.poll(() => releaseAssessRequests.length, { timeout: 1_000 }).toBe(1)
  await page.waitForTimeout(300)
  expect(releaseAssessRequests).toHaveLength(1)
})

test('studio routes are deep-linkable', async ({ page }) => {
  await createPlatformAdminBrowserSession(page)
  await page.goto('/dashboard')
  await expect(page.getByRole('heading', { name: /Global quality cockpit/i })).toBeVisible()
  await expect(page.getByTestId('backend-status-pill')).toContainText(/Live/i)
  await expect(page).toHaveURL(/\/dashboard$/)

  await page.goto('/documentation')
  await expect(page.getByRole('heading', { name: /How Nasus works/i })).toBeVisible()
  await expect(page.getByTestId('backend-status-pill')).toContainText(/Live/i)
  await expect(page).toHaveURL(/\/documentation$/)

  await page.goto('/projects/proj_payment')
  await expect(page.getByTestId('agent-workspace')).toBeVisible()
  await expect(page.getByText(/Payment System/i).first()).toBeVisible()
  await expect(page.getByRole('heading', { name: /Build with Agents/i })).toBeVisible()
  await expect(page).toHaveURL(/\/projects\/proj_payment$/)

  const projectDeepLinks = [
    {
      path: '/projects/proj_payment/versions',
      testId: 'project-versions-route',
      heading: /Version Space/i,
    },
    {
      path: '/projects/proj_payment/versions/create',
      testId: 'project-version-create-route',
      heading: /Create Version Branch/i,
    },
    {
      path: '/projects/proj_payment/workspaces/us_123',
      testId: 'project-workspace-route',
      heading: /Saved cards checkout flow/i,
    },
    {
      path: '/projects/proj_payment/knowledge',
      testId: 'project-knowledge-route',
      heading: /System Image Knowledge/i,
    },
    {
      path: '/projects/proj_payment/runs',
      testId: 'project-runs-route',
      heading: /Runs/i,
    },
    {
      path: '/projects/proj_payment/governance',
      testId: 'project-governance-route',
      heading: /Governance/i,
    },
    {
      path: '/projects/proj_payment/release-readiness',
      testId: 'project-release-readiness-route',
      heading: /Release Readiness/i,
    },
  ]

  for (const route of projectDeepLinks) {
    await page.goto(route.path)
    await expect(page.getByTestId(route.testId)).toBeVisible()
    await expect(page.getByRole('heading', { name: route.heading })).toBeVisible()
    await expect(page).toHaveURL(new RegExp(`${route.path}$`))
  }
})

test('unknown project deep link disables project-scoped agent actions', async ({ page }) => {
  await createBrowserSession(page)
  await page.goto('/projects/does-not-exist')
  await expect(page.getByTestId('project-not-found')).toBeVisible()
  await expect(page.getByRole('heading', { name: /This project is not available/i })).toBeVisible()
  await expect(page.getByText(/cannot accidentally operate on another project/i)).toBeVisible()
  await expect(page.getByTestId('agent-workspace')).toHaveCount(0)
  await expect(page.getByText(/Payment System/i)).toHaveCount(0)
})
