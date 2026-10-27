import { expect, test } from '@playwright/test'
import type { APIRequestContext, Page } from '@playwright/test'

import type { DashboardData } from '../../apps/portal/src/domains/platform/types'

const apiUrl = `http://127.0.0.1:${process.env.PLAYWRIGHT_API_PORT ?? '8000'}`
const adminToken = process.env.NASUS_E2E_ADMIN_TOKEN ?? 'nasus-e2e-platform-admin-token'
const headers = { Authorization: `Bearer ${adminToken}` }

async function dashboard(request: APIRequestContext) {
  const response = await request.get(`${apiUrl}/v1/dashboard`, { headers })
  expect(response.ok()).toBeTruthy()
  const data = await response.json() as DashboardData
  expect(data.projects.length).toBeGreaterThan(0)
  return data
}

async function expectSelected(page: Page, label: string) {
  const selected = page.locator('.studio-sidebar .nav-button[aria-current="page"]')
  await expect(selected).toHaveCount(1)
  await expect(selected).toHaveAccessibleName(label)
  await expect(selected).toHaveClass(/active/)
}

test.beforeEach(async ({ page, request }) => {
  const settings = await request.patch(`${apiUrl}/v1/settings`, { headers, data: { language: 'en' } })
  expect(settings.ok()).toBeTruthy()
  await page.addInitScript((token) => {
    localStorage.setItem('nasus_api_token', token)
    if (!localStorage.getItem('nasus.locale')) localStorage.setItem('nasus.locale', 'en')
  }, adminToken)
})

const features = [
  { path: '/system-image', label: 'System image', section: 'knowledge', heading: 'System Image Knowledge' },
  { path: '/quality-loops', label: 'Quality loops', section: 'versions', heading: 'Version Space' },
  { path: '/runs', label: 'Runs', section: 'runs', heading: 'Runs' },
]

for (const feature of features) {
  test(`home ${feature.label} selects a project and opens its matching section`, async ({ page, request }) => {
    const project = (await dashboard(request)).projects[0]
    const writes: string[] = []
    page.on('request', (request) => {
      if (request.method() === 'POST' && /\/v1\/(tool-invocations|agent-goals)(?:\?|$)/.test(request.url())) {
        writes.push(request.url())
      }
    })
    await page.goto('/build')
    await page.locator('.studio-sidebar').getByRole('button', { name: 'Settings', exact: true }).click()
    await expect(page.locator('.settings-pop')).toBeVisible()
    await page.locator('.studio-sidebar').getByRole('button', { name: 'Settings', exact: true }).click()
    await expect(page.locator('.settings-pop')).not.toBeVisible()
    await page.locator('.studio-sidebar').getByRole('button', { name: feature.label, exact: true }).click()
    await expect(page).toHaveURL(feature.path)
    await expect(page.locator('.settings-pop')).not.toBeVisible()
    await expectSelected(page, feature.label)
    await expect(page.getByRole('heading', { name: feature.label, exact: true })).toBeVisible()
    await expect(page.getByTestId('project-directory')).toBeVisible()
    await page.reload()
    await expectSelected(page, feature.label)
    await page.getByTestId('project-card').filter({ hasText: project.name }).click()
    await expect(page).toHaveURL(`/projects/${encodeURIComponent(project.id)}/${feature.section}`)
    await expect(page.getByRole('heading', { name: feature.heading, exact: true })).toBeVisible()
    await expectSelected(page, feature.label === 'Quality loops' ? 'Quality loop' : feature.label)
    expect(writes).toEqual([])
  })
}

test('keyboard navigation closes an open settings popover', async ({ page }) => {
  await page.goto('/system-image')
  const sidebar = page.locator('.studio-sidebar')
  await sidebar.getByRole('button', { name: 'Settings', exact: true }).click()
  await expect(page.locator('.settings-pop')).toBeVisible()
  const target = sidebar.getByRole('button', { name: 'Runs', exact: true })
  await target.focus()
  await expect(target).toBeFocused()
  await target.press('Enter')
  await expect(page).toHaveURL('/runs')
  await expect(page.locator('.settings-pop')).not.toBeVisible()
  await expectSelected(page, 'Runs')
})

test('project navigation works across sections, nested routes, reload and browser history', async ({ page, request }) => {
  const project = (await dashboard(request)).projects[0]
  const base = `/projects/${encodeURIComponent(project.id)}`
  await page.goto(base)
  await expectSelected(page, 'Agent workspace')
  const sidebar = page.locator('.studio-sidebar')
  for (const [label, section] of [
    ['System image', 'knowledge'], ['Quality loop', 'versions'], ['Runs', 'runs'],
    ['Governance', 'governance'], ['Release Readiness', 'release-readiness'],
  ]) {
    await sidebar.getByRole('button', { name: label, exact: true }).click()
    await expect(page).toHaveURL(`${base}/${section}`)
    await expectSelected(page, label)
  }
  await page.goBack()
  await expect(page).toHaveURL(`${base}/governance`)
  await expectSelected(page, 'Governance')
  await page.goForward()
  await expectSelected(page, 'Release Readiness')
  await page.reload()
  await expectSelected(page, 'Release Readiness')

  for (const [path, label] of [
    ['knowledge/selected-object', 'System image'],
    ['versions/create', 'Quality loop'],
    ['workspaces/selected-us', 'Quality loop'],
    ['runs/selected-run', 'Runs'],
    ['approvals/selected-approval', 'Governance'],
  ]) {
    await page.goto(`${base}/${path}`)
    await expectSelected(page, label)
  }
  await sidebar.getByRole('button', { name: 'Agent workspace', exact: true }).click()
  await expect(page).toHaveURL(base)
  await expectSelected(page, 'Agent workspace')
  await sidebar.getByRole('button', { name: 'Back to dashboard' }).click()
  await expect(page).toHaveURL('/dashboard')
})

test('project directory includes the ninth project but excludes preview templates', async ({ page, request }) => {
  const data = await dashboard(request)
  const project = data.projects[0]
  const projects = Array.from({ length: 8 }, (_, index) => ({
    ...project, id: `navigation-fixture-${index}`, name: `Navigation project ${index}`,
  }))
  await page.route('**/v1/dashboard', (route) => route.fulfill({
    json: { ...data, projects: [...projects, project, { ...project, id: 'preview', name: 'Preview template', preview_only: true }] },
  }))
  await page.goto('/system-image')
  await expect(page.getByTestId('project-card')).toHaveCount(9)
  await expect(page.getByText('Preview template')).toHaveCount(0)
  await page.getByTestId('project-card').nth(8).click()
  await expect(page).toHaveURL(`/projects/${encodeURIComponent(project.id)}/knowledge`)
})

test('project directory distinguishes loading, empty results and errors and can recover', async ({ page, request }) => {
  const data = await dashboard(request)
  let release: () => void = () => {}
  const ready = new Promise<void>((resolve) => { release = resolve })
  let state: 'loading' | 'empty' | 'error' | 'ready' = 'loading'
  await page.route('**/v1/dashboard', async (route) => {
    if (state === 'loading') await ready
    if (state === 'error') {
      await route.fulfill({ status: 503, json: { detail: 'Unavailable' } })
    } else {
      await route.fulfill({ json: { ...data, projects: state === 'ready' ? data.projects : [] } })
    }
  })
  await page.goto('/runs')
  await expect(page.getByText('Loading projects...')).toBeVisible()
  await expect(page.getByTestId('project-card')).toHaveCount(0)
  state = 'empty'
  release()
  await expect(page.getByText(/No projects available/)).toBeVisible()
  await page.getByRole('button', { name: 'Create a project', exact: true }).click()
  await expect(page).toHaveURL('/build')

  state = 'error'
  await page.goto('/runs')
  await expect(page.getByRole('alert')).toContainText(/Unable to load projects/)
  await expect(page.getByTestId('project-card')).toHaveCount(0)
  await expect(page.getByText(/Payment System/)).toHaveCount(0)
  state = 'ready'
  await page.getByRole('button', { name: 'Reload projects' }).click()
  await expect(page.getByTestId('project-card')).toHaveCount(data.projects.length)
  await expectSelected(page, 'Runs')
})

test('Chinese mobile navigation remains named and usable when sidebar text is hidden', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('nasus.locale', 'zh'))
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/build')
  await page.locator('.studio-sidebar').getByRole('button', { name: '系统画像', exact: true }).click()
  await expect(page).toHaveURL('/system-image')
  await expectSelected(page, '系统画像')
  await expect(page.getByRole('heading', { name: '系统画像', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '收起导航栏', exact: true }).click()
  await expect(page.locator('.nasus-app')).toHaveClass(/sidebar-collapsed/)
  await page.getByRole('button', { name: '展开导航栏', exact: true }).click()
  await page.locator('.studio-sidebar').getByRole('button', { name: '执行记录', exact: true }).click()
  await expect(page).toHaveURL('/runs')
  await expectSelected(page, '执行记录')
})

test('feature directories require authentication', async ({ page }) => {
  await page.addInitScript(() => localStorage.removeItem('nasus_api_token'))
  for (const feature of features) {
    await page.goto(feature.path)
    await expect(page).toHaveURL(/\/login$/)
    await expect(page.getByTestId('project-directory')).toHaveCount(0)
  }
})
