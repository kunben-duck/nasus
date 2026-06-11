import { expect, test } from '@playwright/test'

test('build to workspace vertical slice works end-to-end', async ({ page }) => {
  await page.goto('/build')

  await expect(page.locator('.input-textarea')).toBeVisible()
  await page.locator('.input-textarea').fill('Help me create a new project called Loyalty Hub')
  await page.locator('.send-btn').click()

  await expect(page.getByText(/I created the draft project.*Loyalty Hub/i).first()).toBeVisible()

  await page.goto('/dashboard')
  await expect(page.locator('.collection-card').first()).toBeVisible()
  await expect(page.getByText('Loyalty Hub', { exact: true }).first()).toBeVisible()

  await page.locator('[data-action="open_project"][data-project="proj_payment"]').click()
  await expect(page.getByText(/Payment System/i).first()).toBeVisible()

  await page.goto('/projects/proj_payment/versions')
  await page.locator('[data-action="open_us_workspace"][data-us-id="us_123"]').first().click()
  await expect(page.getByText(/US quality closure snapshot/i).first()).toBeVisible()

  await page.locator('[data-action="generate_scenarios"]').first().click()

  await expect(page.getByText(/Scenario generation is complete/i).first()).toBeVisible({ timeout: 10_000 })
  await expect(page.getByText(/Quality Asset Pack lanes/i).first()).toBeVisible()
  await expect(page.getByText(/8\/8 done/i).first()).toBeVisible()
})
