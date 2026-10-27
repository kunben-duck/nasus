import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdirSync, rmSync } from 'node:fs'
import { resolve } from 'node:path'
import { analysisApi, analysisSource } from './source-analysis-fixtures'
import { generationScopeFixture } from './test-design-generation-fixtures'
import { batchProtocolFixture } from './generation-batch-fixtures'
import { installBatchProtocol } from './generation-batch-protocol'

const consent = 'I confirm this exact complete batch plan, model destination, source inventory and cumulative token/spend ceilings.'
const stopConsent = 'I confirm stopping this exact job; charged or unknown calls are not refunded or resent.'
for (const [theme, outcome] of [['light', 'complete'], ['dark', 'complete'], ['dark', 'unknown'], ['light', 'cancel']] as const) {
  test(`complete multi-batch confirmation and ${outcome} lifecycle (${theme})`, async ({ page, request }) => {
    test.setTimeout(480_000)
    const exweb = process.env.EXWEB_FIXTURE_ROOT, source = exweb ? resolve(exweb) : analysisSource(), errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    if (exweb) expect(execFileSync('git', ['-C', source, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim())
      .toBe('fe5827f6b76f77ef34918d8b452ee823142332dc')
    try {
      const v = await generationScopeFixture(request, source, { requirementsPath: 'tests/fixtures/system-image/exweb-batch-requirements.md', constraintCount: 4 })
      const data = batchProtocolFixture(v.context, v.scope), protocol = await installBatchProtocol(page, data)
      const batchCount = data.archive.result.calls.length
      expect(batchCount).toBeGreaterThanOrEqual(2)
      expect(data.preview.call_count).toBe(batchCount)
      expect(new Set(data.archive.result.batch_plan.batches.flatMap((batch) => batch.local_constraint_ids)).size).toBe(3)
      expect((await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme } })).ok()).toBeTruthy()
      await page.addInitScript((token) => { localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en') }, v.owner.token)
      const panel = page.getByRole('region', { name: 'Pinned draft test generation', exact: true })
      const open = async () => {
        await page.getByRole('button', { name: 'Inspect published context', exact: true }).click()
        await page.getByRole('button').filter({ hasText: v.contextId }).click()
        await page.getByRole('button', { name: 'Inspect test-design scope', exact: true }).click()
        await expect(panel).toBeVisible({ timeout: 60_000 })
        await panel.getByRole('button', { name: 'Inspect draft generation', exact: true }).click()
      }
      const reload = async () => {
        const read = page.waitForResponse((r) => r.request().method() === 'POST' && r.request().postDataJSON()?.tool_id === 'query.quality.test_design_job')
        await panel.getByRole('button', { name: 'Reload generation access and history', exact: true }).click()
        await read
      }
      await page.goto(`/projects/${v.projectId}/knowledge`); await open()
      await expect(page.getByTestId('project-knowledge-route')).toHaveClass(/(?:^|\s)knowledge-workspace(?:\s|$)/)
      await panel.getByRole('combobox', { name: 'Tested chat model', exact: true }).selectOption(data.preview.request.model_config_id)
      const budget = data.preview.request.execution.budget
      for (const [name, value] of Object.entries({ 'Maximum model calls': budget.max_calls,
        'Maximum input tokens': budget.max_input_tokens_per_call, 'Maximum output tokens': budget.max_output_tokens_per_call,
        'Total token reservation ceiling': budget.max_reserved_tokens, 'Maximum reserved spend': budget.max_reserved_cost_nanos / 1e9 })) {
        await panel.getByRole('spinbutton', { name, exact: true }).fill(String(value))
      }
      const preview = panel.getByRole('button', { name: 'Preview complete generation budget', exact: true })
      protocol.corruptPreview = true; await preview.click()
      await expect(panel.getByRole('alert')).toContainText('Generation preview unavailable')
      await expect(panel.getByRole('checkbox', { name: consent, exact: true })).toHaveCount(0)
      expect(protocol.writes).toEqual([])
      protocol.corruptPreview = false; await preview.click()
      await expect(panel).toContainText('Complete batch preview; no source sent')
      const start = panel.getByRole('button', { name: 'Generate draft cases', exact: true }), confirmation = panel.getByRole('checkbox', { name: consent, exact: true })
      await expect(start).toBeDisabled(); await confirmation.check(); await expect(start).toBeEnabled()
      const calls = panel.getByRole('spinbutton', { name: 'Maximum model calls', exact: true })
      await calls.fill('63'); await expect(confirmation).toHaveCount(0)
      await calls.fill(String(budget.max_calls)); await preview.click()
      if (outcome === 'complete') {
        mkdirSync(resolve('output/playwright'), { recursive: true })
        await page.setViewportSize({ width: 390, height: 844 })
        expect((await panel.boundingBox())?.width).toBeGreaterThanOrEqual(240)
        expect((await calls.boundingBox())?.width).toBeGreaterThanOrEqual(220)
        const previewRecord = panel.locator('.scope-record').filter({ hasText: 'Complete batch preview; no source sent' })
        expect(await previewRecord.locator('dl').evaluate((node) => getComputedStyle(node).gridTemplateColumns.split(' ').length)).toBe(1)
        await previewRecord.scrollIntoViewIfNeeded()
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
        await page.screenshot({ path: resolve(`output/playwright/generation-batch-${theme}-mobile-preview.png`) })
        await page.setViewportSize({ width: 1280, height: 844 })
      }
      await confirmation.check(); await start.click()
      const status = panel.locator('[aria-label="Generation task status"]'), draft = panel.locator('[aria-label="Archived draft test cases"]')
      await expect(status).toContainText('Archived batches are retained')
      await expect(status).not.toContainText('Provider outcome is unknown')
      await expect(draft).toHaveCount(0); expect(protocol.writes).toHaveLength(1)
      await page.reload(); await open(); await expect(status).toContainText('Archived batches are retained')
      protocol.corruptProgress = true; await reload()
      await expect(panel.getByRole('alert')).toContainText('Protected content is hidden')
      await expect(status).toHaveCount(0)
      protocol.corruptProgress = false; await reload(); await expect(status).toBeVisible()
      if (outcome === 'complete') {
        protocol.archived = batchCount; protocol.status = 'completed'; await reload()
        await expect(draft).toBeVisible({ timeout: 60_000 })
        await expect(draft).toContainText(`${data.archive.result.proposal.coverage.obligation_denominator}/${data.archive.result.proposal.coverage.obligation_denominator} obligations planned`)
        await expect(draft).toContainText('counts are all zero')
        await page.reload(); await open(); await expect(draft).toBeVisible({ timeout: 60_000 })
        mkdirSync(resolve('output/playwright'), { recursive: true })
        await page.setViewportSize({ width: 1280, height: 2400 }); await panel.scrollIntoViewIfNeeded()
        await panel.screenshot({ path: resolve(`output/playwright/generation-batch-${theme}-desktop.png`) })
        await page.setViewportSize({ width: 390, height: 844 }); await draft.scrollIntoViewIfNeeded()
        expect((await draft.boundingBox())?.width).toBeGreaterThanOrEqual(240)
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
        await page.screenshot({ path: resolve(`output/playwright/generation-batch-${theme}-mobile.png`) })
      } else if (outcome === 'unknown') {
        protocol.unknown = 1; protocol.status = 'failed'; await reload()
        await expect(status).toContainText('Provider outcome is unknown')
        await expect(panel.getByRole('button', { name: 'Recover archived draft', exact: true })).toHaveCount(0)
        await expect(draft).toHaveCount(0)
      } else {
        await panel.getByRole('checkbox', { name: stopConsent, exact: true }).check()
        await panel.getByRole('button', { name: 'Stop generation', exact: true }).click()
        await expect(status).toContainText('cancelled'); await expect(draft).toHaveCount(0)
        expect(protocol.writes.filter((row) => row.tool_id === 'quality.test_design.cancel')).toHaveLength(1)
      }
      protocol.denied = true; await reload()
      await expect(panel.getByRole('alert')).toContainText('Protected content is hidden'); await expect(draft).toHaveCount(0)
      expect(protocol.writes.filter((row) => row.tool_id === 'quality.test_design.generate')).toHaveLength(1)
      expect(errors).toEqual([])
    } finally { if (!exweb) rmSync(source, { recursive: true, force: true }) }
  })
}
