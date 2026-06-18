import { expect, test } from '@playwright/test'
import * as path from 'node:path'

test('agent-first build to project workspace path works end-to-end', async ({ page }) => {
  const projectName = `E2E Quality Hub ${Date.now()}`
  const fixtureRoot = path.resolve(process.cwd(), 'tests/fixtures/system-image')
  const sourcePrompt = [
    `code path ${path.join(fixtureRoot, 'code')}`,
    `US docs path ${path.join(fixtureRoot, 'us')}`,
    `tests path ${path.join(fixtureRoot, 'tests')}`,
  ].join(', ')

  await page.goto('/')
  await expect(page.getByRole('heading', { name: /Build quality projects with Nasus/i })).toBeVisible()

  await page.getByTestId('build-agent-input').fill(`Help me create a new project called ${projectName}`)
  await page.getByTestId('build-agent-submit').click()

  await expect(page.getByTestId('agent-workspace')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText(projectName).first()).toBeVisible()
  await expect(page.getByRole('heading', { name: /Build with Agents/i })).toBeVisible()

  await page.getByTestId('agent-card-system-image-builder').click()
  await expect(page.getByTestId('agent-goal-panel')).toContainText(/Build Official System Image/i, { timeout: 15_000 })
  await expect(page.getByTestId('agent-confirmation-gate')).toContainText(/Source bindings required/i, { timeout: 15_000 })

  await page.getByTestId('project-agent-input').fill(sourcePrompt)
  await page.getByTestId('project-agent-submit').click()
  await expect(page.getByTestId('agent-confirmation-gate')).toContainText(/Confirmation required/i, { timeout: 20_000 })

  await page.getByTestId('confirm-agent-goal').click()
  await expect(page.getByTestId('system-image-strip')).toContainText(/ready/i, { timeout: 20_000 })
  await expect(page.getByTestId('agent-goal-panel')).toContainText(/completed/i)
  await expect(page.getByText(/Sources indexed/i)).toBeVisible()
  await expect(page.getByText(/Code analysis/i)).toBeVisible()

  await page.getByTestId('project-agent-input').fill('Show me the current system image freshness and baseline status')
  await page.getByTestId('project-agent-submit').click()
  await expect(page.getByText(/source groups are indexed|system image is/i).first()).toBeVisible({ timeout: 15_000 })

  await page.getByTestId('agent-card-quality-loop-agent').click()
  await expect(page.getByText(/imported US work item/i).first()).toBeVisible({ timeout: 15_000 })
})
