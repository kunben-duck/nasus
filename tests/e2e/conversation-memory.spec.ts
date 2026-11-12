import { expect, test } from '@playwright/test'

const api = `http://127.0.0.1:${process.env.PLAYWRIGHT_API_PORT ?? '8000'}`

test.afterEach(async ({ page }) => {
  // Finish in-flight fixture reads before Playwright tears down the page.
  await page.unrouteAll({ behavior: 'wait' })
})

test('memory budget diagnostics render without exposing summary text and survive reload', async ({ page, request }) => {
  const account = await request.post(`${api}/v1/auth/register`, { data: {
    email: `memory-${Date.now()}@example.com`, password: 'strong-password-123', name: 'Memory browser test',
  } })
  expect(account.ok()).toBeTruthy()
  const { access_token } = await account.json()
  const headers = { Authorization: `Bearer ${access_token}` }
  const projectResponse = await request.post(`${api}/v1/projects`, { headers, data: { name: 'Memory diagnostics' } })
  expect(projectResponse.ok()).toBeTruthy()
  const project = await projectResponse.json()
  await page.addInitScript((token) => {
    localStorage.setItem('nasus_api_token', token)
    localStorage.setItem('nasus.locale', 'en')
  }, access_token)
  // UI contract specimen only; real model and persistence are exercised by separate gates.
  await page.route('**/v1/agent-memory/context?*', async (route) => {
    const response = await route.fetch()
    expect(response.ok()).toBeTruthy()
    const original = await response.json()
    await route.fulfill({ response, json: { ...original, context_budget: {
      input_limit: 16384, estimated_input_tokens: 9000, counting_method: 'utf8_bytes_upper_estimate',
      summary: { format_version: 2, coverage_end: 'message-coverage-26', job_status: 'failed',
        degraded_reason: 'summary_unavailable_originals_fit' },
    } } })
  })
  await page.goto(`/projects/${project.id}`)
  await page.getByTestId('agent-card-system-image-builder').click()
  const budget = page.getByTestId('agent-memory-budget')
  await expect(budget).toContainText('9000 / 16384')
  await expect(budget).toContainText('message-coverage-26')
  await expect(budget).toContainText('utf8_bytes_upper_estimate')
  await expect(budget.getByRole('status')).toHaveText('Original history retained')
  await page.reload()
  await expect(budget).toContainText('9000 / 16384')
  await expect(page.getByTestId('project-agent-input')).toBeEnabled()
})
