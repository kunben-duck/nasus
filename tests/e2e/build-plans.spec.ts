import { expect, test } from '@playwright/test'
import { mkdirSync, rmSync } from 'node:fs'
import { resolve } from 'node:path'
import { analysisAccount, analysisApi, analysisSource, analysisSourcePolicy, captureAnalysis } from './source-analysis-fixtures'

for (const theme of ['light', 'dark']) {
  test(`investigation drafts persist through the canonical tool and preserve ${theme} layout`, async ({ page, request }) => {
    const source = analysisSource()
    try {
      const { owner, projectId } = await captureAnalysis(request, source)
      await request.patch(`${analysisApi}/v1/settings`, { headers: owner.headers, data: { theme } })
      await page.addInitScript((token) => {
        localStorage.setItem('nasus_api_token', token)
        localStorage.setItem('nasus.locale', 'en')
      }, owner.token)
      await page.goto(`/projects/${projectId}/knowledge`)
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
      await page.getByRole('button', { name: 'Investigation plans', exact: true }).click()
      const dialog = page.getByRole('dialog', { name: 'Investigation plans', exact: true })
      await expect(dialog.getByRole('textbox', { name: 'Investigation objective' })).toHaveCount(0)
      await dialog.getByRole('button', { name: 'Propose investigation', exact: true }).click()
      await expect(dialog.getByRole('button', { name: 'Save investigation draft' })).toBeDisabled()
      const objective = 'Investigate <img src=x onerror=alert(1)> as source data'
      await dialog.getByRole('textbox', { name: 'Investigation objective' }).fill(objective)
      const intentTarget = dialog.getByRole('combobox', { name: 'Build intent target' })
      const baseline = await intentTarget.locator('option').nth(1).getAttribute('value')
      await expect(dialog.getByRole('button', { name: 'Save investigation draft' })).toBeDisabled()
      await intentTarget.selectOption(baseline!)
      await expect(dialog.getByRole('button', { name: 'Save investigation draft' })).toBeEnabled()
      await dialog.getByRole('combobox', { name: 'Investigation mode' }).selectOption('enrich')
      await dialog.getByRole('combobox', { name: 'Investigation purpose' }).selectOption('traceability')
      await dialog.getByRole('spinbutton', { name: 'Proposed cost ceiling (USD, optional)' }).fill('1.25')
      const sent = page.waitForResponse((response) => response.url().endsWith('/v1/tool-invocations') && response.request().method() === 'POST')
      await dialog.getByRole('button', { name: 'Save investigation draft', exact: true }).click()
      const result = await (await sent).json()
      expect(result.tool_id).toBe('system_image.build.plan')
      expect(result.status).toBe('completed')
      expect(result.result.requires_followup).toBe(true)
      const planId = result.result.object_refs[0].slice('build_plan:'.length)
      const detail = dialog.getByRole('region', { name: 'Investigation draft', exact: true })
      await expect(detail).toContainText(objective)
      await expect(detail.locator('img,script')).toHaveCount(0)
      await expect(detail).toContainText('Confirmed work and resulting candidates are recorded separately.')
      await expect(detail).toContainText('Expected publication head')
      await expect(detail).toContainText('Pinned target version')
      const stored = await request.get(`${analysisApi}/v1/projects/${projectId}/system-image/build-plans/${planId}`, { headers: owner.headers })
      expect(stored.ok()).toBeTruthy()
      const savedPlan = await stored.json()
      expect(savedPlan.proposal.policy_version).toBe('nasus.image-investigation-plan.v3')
      expect(savedPlan.proposal.intent).toMatchObject({ objective, mode: 'enrich', purpose: 'traceability',
        target: { project_id: projectId, target_baseline_id: baseline, expected_head_id: null, expected_head_hash: null },
        expected_head_status: 'resolved', budget: { max_cost_microusd: 1_250_000 } })
      expect(savedPlan.proposal.intent.scope_binding_ids).toEqual(savedPlan.proposal.intent.sources.map((item: { binding_id: string }) => item.binding_id))
      mkdirSync(resolve('output/playwright'), { recursive: true })
      await dialog.getByRole('heading', { name: objective }).scrollIntoViewIfNeeded()
      await page.screenshot({ path: resolve(`output/playwright/build-plan-${theme}.png`) })
      await page.setViewportSize({ width: 390, height: 844 })
      const bounds = await dialog.boundingBox()
      expect(bounds!.x).toBeGreaterThanOrEqual(0)
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390)
      const body = dialog.locator('.evidence-inspector-body')
      expect(await body.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
      expect(await body.evaluate((element) => getComputedStyle(element).scrollbarWidth)).toBe('none')
      await page.screenshot({ path: resolve(`output/playwright/build-plan-${theme}-mobile.png`) })
      await page.keyboard.press('Escape')
      await expect(dialog).toHaveCount(0)
      await expect(page.getByRole('button', { name: 'Investigation plans', exact: true })).toBeFocused()
      await page.getByRole('button', { name: 'Investigation plans', exact: true }).click()
      await dialog.getByRole('combobox', { name: 'Saved investigation plan' }).selectOption(planId)
      await expect(detail).toContainText(objective)

      const targets = dialog.getByRole('combobox', { name: 'Candidate target baseline' })
      await expect(targets).toHaveValue(baseline!)
      await expect(targets).toBeDisabled()
      await dialog.getByRole('button', { name: 'Prepare structural build', exact: true }).click()
      await expect(dialog.getByRole('button', { name: 'Confirm structural build', exact: true })).toBeEnabled()
      const refreshed = page.waitForResponse((response) => response.url().endsWith(`/build-plans/${planId}`) && response.request().method() === 'GET')
      await page.evaluate(() => window.dispatchEvent(new Event('visibilitychange')))
      await refreshed
      await expect(targets).toHaveValue(baseline!)
      await expect(dialog.getByRole('button', { name: 'Confirm structural build', exact: true })).toBeEnabled()
      const built = page.waitForResponse((response) => response.url().endsWith('/confirm') && response.request().method() === 'POST')
      await dialog.getByRole('button', { name: 'Confirm structural build', exact: true }).click()
      const builtResult = await (await built).json()
      expect(builtResult.status).toBe('completed')
      expect(builtResult.tool_id).toBe('system_image.build.structure')
      await expect(dialog.getByRole('region', { name: 'Recent structural candidates' })).toContainText('Candidate only')
      await dialog.getByRole('button', { name: 'Reload plans' }).click()
      await dialog.getByRole('combobox', { name: 'Saved investigation plan' }).selectOption(planId)
      await expect(dialog.getByRole('region', { name: 'Recent structural candidates' })).toContainText(builtResult.result.object_refs[1].slice('image_revision:'.length))

      const member = await analysisAccount(request)
      await request.put(`${analysisApi}/v1/projects/${projectId}/members/${member.userId}`, { headers: owner.headers, data: { role: 'viewer' } })
      await page.evaluate((token) => localStorage.setItem('nasus_api_token', token), member.token)
      await page.reload()
      await page.getByRole('button', { name: 'Investigation plans', exact: true }).click()
      await dialog.getByRole('combobox', { name: 'Saved investigation plan' }).selectOption(planId)
      await expect(detail).toContainText(objective)
      analysisSourcePolicy(projectId, [])
      await dialog.getByRole('button', { name: 'Reload plans', exact: true }).click()
      await expect(detail).toHaveCount(0)
      await expect(dialog).not.toContainText(objective)
    } finally { rmSync(source, { recursive: true, force: true }) }
  })
}

for (const theme of ['light', 'dark']) {
  test(`a failed target read cannot save or silently choose another target in ${theme}`, async ({ page, request }) => {
    const source = analysisSource()
    try {
      const { owner, projectId } = await captureAnalysis(request, source)
      await request.patch(`${analysisApi}/v1/settings`, { headers: owner.headers, data: { theme } })
      await page.addInitScript((token) => {
        localStorage.setItem('nasus_api_token', token)
        localStorage.setItem('nasus.locale', 'en')
      }, owner.token)
      let deny = true, targetReads = 0, planWrites = 0
      await page.route('**/system-image/build-targets/*', async (route) => {
        targetReads++
        if (deny) await route.fulfill({ status: 503, json: { error: { code: 'fixture_unavailable', message: 'Unavailable' } } })
        else await route.continue()
      })
      page.on('request', (request) => {
        if (request.method() === 'POST' && request.url().endsWith('/v1/tool-invocations') && request.postDataJSON()?.tool_id === 'system_image.build.plan') planWrites++
      })
      await page.goto(`/projects/${projectId}/knowledge`)
      await page.getByRole('button', { name: 'Investigation plans', exact: true }).click()
      const dialog = page.getByRole('dialog', { name: 'Investigation plans', exact: true })
      await dialog.getByRole('button', { name: 'Propose investigation', exact: true }).click()
      await dialog.getByRole('textbox', { name: 'Investigation objective' }).fill('Build from the explicitly displayed target')
      const target = dialog.getByRole('combobox', { name: 'Build intent target' })
      await expect(target).toHaveValue('')
      const baseline = await target.locator('option').nth(1).getAttribute('value')
      await target.selectOption(baseline!)
      await expect(dialog.getByRole('alert')).toContainText('Build target could not be verified')
      await expect(dialog.getByRole('button', { name: 'Save investigation draft' })).toBeDisabled()
      expect(targetReads).toBe(1)
      expect(planWrites).toBe(0)
      deny = false
      await dialog.getByRole('button', { name: 'Reload build target' }).click()
      await expect(dialog.getByRole('button', { name: 'Save investigation draft' })).toBeEnabled()
      await expect(target).toHaveValue(baseline!)
      expect(planWrites).toBe(0)
      await page.setViewportSize({ width: 390, height: 844 })
      await page.screenshot({ path: resolve(`output/playwright/build-intent-target-${theme}-mobile.png`) })
      await dialog.getByRole('button', { name: 'Save investigation draft' }).click()
      const detail = dialog.getByRole('region', { name: 'Investigation draft', exact: true })
      await expect(detail).toContainText(baseline!)
      await expect(dialog.getByRole('combobox', { name: 'Candidate target baseline' })).toBeDisabled()
      expect(planWrites).toBe(1)
    } finally { rmSync(source, { recursive: true, force: true }) }
  })
}
