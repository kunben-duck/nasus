import { expect, test } from '@playwright/test'

test('agent-first build to project workspace path works end-to-end', async ({ page }) => {
  const projectName = `E2E Quality Hub ${Date.now()}`

  await page.goto('/')
  await expect(page.getByRole('heading', { name: /Build quality projects with agents/i })).toBeVisible()

  await page.getByTestId('build-agent-input').fill(`Help me create a new project called ${projectName}`)
  await page.getByTestId('build-agent-submit').click()

  await expect(page.getByTestId('agent-workspace')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText(projectName).first()).toBeVisible()
  await expect(page.getByRole('heading', { name: /Build with Agents/i })).toBeVisible()

  await page.getByTestId('agent-card-system-image-builder').click()
  await expect(page.getByTestId('system-image-strip')).toContainText(/ready/i, { timeout: 15_000 })
  await expect(page.getByText(/Sources indexed/i)).toBeVisible()
  await expect(page.getByText(/Code analysis/i)).toBeVisible()

  await page.getByTestId('project-agent-input').fill('Show me the current system image freshness and baseline status')
  await page.getByTestId('project-agent-submit').click()
  await expect(page.getByText(/source groups are indexed|system image is/i).first()).toBeVisible({ timeout: 15_000 })
})
