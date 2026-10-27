import { expect, test } from '@playwright/test'
import { mkdirSync, rmSync } from 'node:fs'
import { resolve } from 'node:path'
import { analysisAccount, analysisApi, analysisSource, analysisSourcePolicy, captureAnalysis, openAnalysis } from './source-analysis-fixtures'
import { registerBrowserIndex } from './code-index-fixtures'

for (const theme of ['light', 'dark']) {
  test(`public SDK receipt fixture renders without MCP fields in ${theme}`, async ({ page, request }) => {
    const source = analysisSource()
    try {
      const fixture = await captureAnalysis(request, source)
      const pin = registerBrowserIndex(fixture.projectId, fixture.revision, true)
      await request.patch(`${analysisApi}/v1/settings`, { headers: fixture.owner.headers, data: { theme } })
      const dialog = await openAnalysis(page, fixture.projectId, fixture.owner.token)
      await dialog.getByRole('combobox', { name: 'Captured code revision', exact: true }).selectOption(fixture.revision)
      const panel = dialog.getByTestId('code-index-inspector')
      await panel.locator('summary').click()
      await panel.getByRole('combobox', { name: 'Code index generation', exact: true }).selectOption(pin.generation_id)
      const status = panel.getByTestId('code-index-status')
      await expect(status).toContainText('1.6.2')
      await expect(status).toContainText('sdk_projection_subset_not_complete_native_graph')
      await expect(status).toContainText('os_sandbox_not_verified')
      await expect(status).not.toContainText('Unknown')
      await expect(dialog.getByRole('alert')).toHaveCount(0)
      await page.setViewportSize({ width: 390, height: 844 })
      await status.scrollIntoViewIfNeeded()
      const body = dialog.locator('.evidence-inspector-body')
      expect(await body.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
      expect(await body.evaluate((element) => getComputedStyle(element).scrollbarWidth)).toBe('none')
      mkdirSync(resolve('output/playwright'), { recursive: true })
      await page.screenshot({ path: resolve(`output/playwright/code-index-sdk-${theme}-mobile-20261008.png`) })
      await panel.getByRole('button', { name: 'Refresh index status', exact: true }).click()
      await expect(status).toContainText('os_sandbox_not_verified')
    } finally { rmSync(source, { recursive: true, force: true }) }
  })
}

for (const theme of ['light', 'dark']) {
  test(`durable code index status and explicit cancellation preserve ${theme} layout`, async ({ page, request }) => {
    const source = analysisSource()
    try {
      const fixture = await captureAnalysis(request, source)
      const pin = registerBrowserIndex(fixture.projectId, fixture.revision)
      await request.patch(`${analysisApi}/v1/settings`, { headers: fixture.owner.headers, data: { theme } })
      const dialog = await openAnalysis(page, fixture.projectId, fixture.owner.token)
      await dialog.getByRole('combobox', { name: 'Captured code revision', exact: true }).selectOption(fixture.revision)
      const panel = dialog.getByTestId('code-index-inspector')
      await expect(panel).toBeVisible()
      await expect(panel.getByRole('combobox', { name: 'Code index generation' })).toHaveCount(0)
      await panel.locator('summary').click()
      await panel.getByRole('combobox', { name: 'Code index generation', exact: true }).selectOption(pin.generation_id)
      const status = panel.getByTestId('code-index-status')
      await expect(status).toContainText(pin.invocation_id)
      await expect(status).toContainText('Unknown')
      const consent = panel.getByRole('checkbox')
      const cancel = panel.getByRole('button', { name: 'Cancel index build', exact: true })
      await expect(cancel).toBeDisabled()
      await consent.check()
      await expect(cancel).toBeEnabled()
      await panel.getByRole('button', { name: 'Refresh index status', exact: true }).click()
      await expect(consent).not.toBeChecked()
      await expect(cancel).toBeDisabled()

      await page.setViewportSize({ width: 390, height: 844 })
      await status.scrollIntoViewIfNeeded()
      const body = dialog.locator('.evidence-inspector-body')
      expect(await body.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
      expect(await body.evaluate((element) => getComputedStyle(element).scrollbarWidth)).toBe('none')
      mkdirSync(resolve('output/playwright'), { recursive: true })
      await page.screenshot({ path: resolve(`output/playwright/code-index-${theme}-mobile-20261007.png`) })

      await consent.check()
      const acknowledged = page.waitForResponse((response) => response.url().endsWith('/confirm') && response.request().method() === 'POST')
      await cancel.click()
      const result = await (await acknowledged).json()
      expect(result.tool_id).toBe('system_image.code_indexes.cancel')
      expect(result.status).toBe('completed')
      expect(result.result.code_index.outcome).toBe('cancelled')
      expect(result.result.code_index.status.pin.content_hash).toBe(pin.content_hash)
      await expect(cancel).toHaveCount(0)
      await expect(status).toContainText('Cancelled')
      const persisted = await request.get(`${analysisApi}/v1/projects/${fixture.projectId}/system-image/code-indexes/${pin.generation_id}`, { headers: fixture.owner.headers })
      expect((await persisted.json()).status.state).toBe('cancelled')
      await page.reload()
      await page.getByRole('button', { name: 'Source analyses', exact: true }).click()
      await dialog.getByRole('combobox', { name: 'Captured code revision', exact: true }).selectOption(fixture.revision)
      await panel.locator('summary').click()
      await panel.getByRole('combobox', { name: 'Code index generation', exact: true }).selectOption(pin.generation_id)
      await expect(status).toContainText('Cancelled')
    } finally { rmSync(source, { recursive: true, force: true }) }
  })
}

test('code index source revocation hides existing selections and reviewer controls', async ({ page, request }) => {
  const source = analysisSource()
  try {
    const fixture = await captureAnalysis(request, source)
    const pin = registerBrowserIndex(fixture.projectId, fixture.revision)
    const member = await analysisAccount(request)
    await request.put(`${analysisApi}/v1/projects/${fixture.projectId}/members/${member.userId}`, {
      headers: fixture.owner.headers, data: { role: 'viewer' } })
    const dialog = await openAnalysis(page, fixture.projectId, member.token)
    await dialog.getByRole('combobox', { name: 'Captured code revision', exact: true }).selectOption(fixture.revision)
    const panel = dialog.getByTestId('code-index-inspector')
    await panel.locator('summary').click()
    await panel.getByRole('combobox', { name: 'Code index generation', exact: true }).selectOption(pin.generation_id)
    await expect(panel.getByTestId('code-index-status')).toContainText(pin.invocation_id)
    await expect(panel.getByRole('checkbox')).toHaveCount(0)
    await expect(panel.getByRole('button', { name: 'Cancel index build' })).toHaveCount(0)
    analysisSourcePolicy(fixture.projectId, [])
    await panel.getByRole('button', { name: 'Refresh index status', exact: true }).click()
    await expect(dialog.getByRole('alert')).toBeVisible()
    await expect(dialog.getByTestId('code-index-status')).toHaveCount(0)
    await expect(dialog).not.toContainText(pin.invocation_id)
    await expect(dialog).not.toContainText(pin.generation_id)
  } finally { rmSync(source, { recursive: true, force: true }) }
})

test('code index revalidation hides details and clears an earlier cancellation consent', async ({ page, request }) => {
  const source = analysisSource()
  let release: (() => void) | undefined
  try {
    const fixture = await captureAnalysis(request, source)
    const pin = registerBrowserIndex(fixture.projectId, fixture.revision)
    const dialog = await openAnalysis(page, fixture.projectId, fixture.owner.token)
    await dialog.getByRole('combobox', { name: 'Captured code revision', exact: true }).selectOption(fixture.revision)
    const panel = dialog.getByTestId('code-index-inspector')
    await panel.locator('summary').click()
    await panel.getByRole('combobox', { name: 'Code index generation', exact: true }).selectOption(pin.generation_id)
    const status = panel.getByTestId('code-index-status')
    await expect(status).toContainText(pin.invocation_id)
    await panel.getByRole('checkbox').check()
    let entered: (() => void) | undefined
    const reached = new Promise<void>((resolve) => { entered = resolve })
    const held = new Promise<void>((resolve) => { release = resolve })
    const route = `**/system-image/code-indexes/${pin.generation_id}`
    await page.route(route, async (request) => { entered!(); await held; await request.continue() })
    await panel.getByRole('button', { name: 'Refresh index status', exact: true }).click()
    await reached
    await expect(status).toHaveCount(0)
    await expect(panel.getByRole('button', { name: 'Cancel index build' })).toHaveCount(0)
    await expect(panel.getByRole('combobox', { name: 'Code index generation' })).toHaveValue(pin.generation_id)
    release!()
    await expect(status).toContainText(pin.invocation_id)
    await expect(panel.getByRole('checkbox')).not.toBeChecked()
    await expect(panel.getByRole('button', { name: 'Cancel index build' })).toBeDisabled()
    await page.unroute(route)
  } finally { release?.(); rmSync(source, { recursive: true, force: true }) }
})
