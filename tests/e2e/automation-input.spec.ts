import { expect, test } from '@playwright/test'
import { rmSync, mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { automationInputFixture } from './automation-input-fixtures'
import { installMappingProtocol, mappingArchiveFixture } from './test-design-mapping-fixtures'
import { generationScopeFixture } from './test-design-generation-fixtures'
import { analysisApi, analysisSource } from './source-analysis-fixtures'
import { canonicalDigest } from '../../apps/portal/src/shared/utils/canonicalDigest'
import { verifyAutomationInput } from '../../apps/portal/src/domains/quality-loop/automationInputValidation'
import { zhCN } from '../../apps/portal/src/shared/i18n/messages'

for (const [theme, language] of [['light', 'en'], ['dark', 'zh']] as const) {
  test(`automation preparation preserves reviewed pins and refuses invalid or revoked responses (${theme})`, async ({ page, request }) => {
    test.setTimeout(180_000)
    const exweb = process.env.EXWEB_FIXTURE_ROOT, source = exweb ? resolve(exweb) : analysisSource()
    try {
      const v = await generationScopeFixture(request, source), state = await installMappingProtocol(page, v.scope)
      // Unlike the older UI specimen, these assertions use exact canonical oracle digests.
      for (const assertion of state.draft.result.proposal.cases[0].assertions) {
        assertion.oracle_digest = await canonicalDigest(assertion.oracle)
        state.draft.result.proposal.coverage.rows.find((row) => row.row_id === assertion.row_id)!.oracle_digest = assertion.oracle_digest
      }
      const reviews = state.draft.result.proposal.cases.flatMap((item) => item.assertions.map((a) => ({
        case_id: item.case_id, row_id: a.row_id, step_index: a.step_index, oracle_digest: a.oracle_digest,
        decision: 'accept' as const, reason: 'Independent transport review, not target execution' })))
      const head = await mappingArchiveFixture(state.draft, { project_id: v.projectId, generation_id: state.draft.metadata.generation_id,
        generation_artifact_hash: state.draft.metadata.artifact_hash, expected_previous_revision_id: null,
        decision: 'review', mappings: reviews, reason: 'Explicit transport fixture', policy_revision: 'nasus.test-design-mapping.v1' }, null)
      state.history.push(head)
      const valid = await automationInputFixture(state.draft, head, v.context.context, v.scope)
      expect(await verifyAutomationInput(valid, state.draft, head)).toEqual(valid)
      for (const change of ['project', 'context', 'scope', 'mapping', 'cases', 'oracle', 'denominator', 'passed', 'authorized', 'ready', 'digest']) {
        const bad = structuredClone(valid)
        if (change === 'project') bad.project_id = 'foreign'
        else if (change === 'context') bad.context_pin.context_id = 'foreign'
        else if (change === 'scope') bad.scope_pin.revision_id = 'foreign'
        else if (change === 'mapping') bad.mapping_pin.revision_id = 'foreign'
        else if (change === 'cases') bad.cases[0].steps[0] = 'Changed assertion step'
        else if (change === 'oracle') bad.obligations[0].oracle.expected_result = 'Changed independently expected result'
        else if (change === 'denominator') bad.obligation_denominator--
        else if (change === 'passed') Object.assign(bad, { passed_count: 1 })
        else if (change === 'authorized') Object.assign(bad, { execution_authorized: true })
        else if (change === 'ready') Object.assign(bad.readiness, { status: 'ready', reason_codes: [] })
        else bad.input_digest = 'sha256:' + '0'.repeat(64)
        if (change !== 'digest') bad.input_digest = await canonicalDigest(Object.fromEntries(Object.entries(bad).filter(([key]) => key !== 'input_digest')))
        await expect(verifyAutomationInput(bad, state.draft, head)).rejects.toThrow()
      }
      let reads = 0, mode: 'valid' | 'corrupt' | 'revoked' = 'valid'
      await page.route('**/quality/test-design-mapping-reviews/*/automation-input-preview?*', async (route) => {
        reads++
        expect(route.request().method()).toBe('GET')
        const params = new URL(route.request().url()).searchParams
        expect(params.get('artifact_hash')).toBe(head.revision.artifact_hash)
        expect(params.getAll('case_ids')).toEqual(valid.selected_case_ids)
        if (mode === 'revoked') return route.fulfill({ status: 403, json: { detail: 'Explicit source-access revocation fixture' } })
        const reply = structuredClone(valid)
        if (mode === 'corrupt') Object.assign(reply, { execution_authorized: true })
        await route.fulfill({ json: reply, headers: { 'Cache-Control': 'private, no-store' } })
      })
      expect((await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme, language } })).ok()).toBeTruthy()
      await page.addInitScript(({ token, locale }) => { localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', locale) },
        { token: v.owner.token, locale: language })
      const errors: string[] = []
      page.on('pageerror', (error) => errors.push(error.message))
      const label = (text: keyof typeof zhCN) => language === 'zh' ? zhCN[text] : text
      await page.goto(`/projects/${v.projectId}/knowledge`)
      await page.getByRole('button', { name: label('Inspect published context'), exact: true }).click()
      await page.getByRole('button').filter({ hasText: v.contextId }).click()
      // Use fixed translated labels from the same registry as the production controls.
      await page.getByRole('button', { name: label('Inspect test-design scope'), exact: true }).click()
      await page.getByRole('button', { name: label('Inspect draft generation'), exact: true }).click()
      await page.getByRole('button', { name: label('Inspect assertion mapping'), exact: true }).click()
      const panel = page.getByRole('region', { name: label('Automation input check'), exact: true })
      await expect(panel).toBeVisible()
      const scripts = page.getByRole('region', { name: label('Pinned automation script drafts'), exact: true })
      await expect(scripts.getByRole('button', { name: label('Inspect script drafts'), exact: true })).toHaveAttribute('aria-expanded', 'false')
      expect(reads).toBe(0)
      await panel.getByRole('button', { name: label('Inspect automation inputs'), exact: true }).click()
      const preview = panel.getByTestId('automation-input-preview')
      await expect(preview).toContainText(valid.input_digest)
      await expect(preview.locator('ul').first().locator('li')).toHaveCount(5)
      await expect(preview.locator('details')).toHaveCount(valid.cases.length)
      expect(state.writes).toEqual([]); expect(state.generationWrites).toBe(0)
      mode = 'corrupt'; await panel.getByRole('button', { name: label('Recheck automation inputs'), exact: true }).click()
      await expect(panel.getByRole('alert')).toBeVisible(); await expect(preview).toHaveCount(0)
      mode = 'revoked'; await panel.getByRole('button', { name: label('Recheck automation inputs'), exact: true }).click()
      await expect(panel.getByRole('alert')).toBeVisible(); await expect(preview).toHaveCount(0)
      await expect(scripts.getByRole('button', { name: label('Inspect script drafts'), exact: true })).toHaveAttribute('aria-expanded', 'false')
      const observed = reads
      await page.waitForTimeout(300)
      expect(reads).toBe(observed)
      mode = 'valid'; await panel.getByRole('button', { name: label('Recheck automation inputs'), exact: true }).click()
      await expect(preview).toBeVisible()
      await page.setViewportSize({ width: 390, height: 844 })
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
      mkdirSync(resolve('output/playwright'), { recursive: true })
      await panel.scrollIntoViewIfNeeded(); await page.screenshot({ path: resolve(`output/playwright/automation-input-${theme}-mobile.png`) })
      const withdrawn = await mappingArchiveFixture(state.draft, { ...head.request, expected_previous_revision_id: head.revision.revision_id,
        decision: 'withdraw', mappings: null }, head)
      state.history.push(withdrawn)
      await page.getByRole('button', { name: label('Reload mapping history'), exact: true }).click()
      await expect(panel).toHaveCount(0)
      expect(state.writes).toEqual([]); expect(state.generationWrites).toBe(0); expect(errors).toEqual([])
    } finally { if (!exweb) rmSync(source, { recursive: true, force: true }) }
  })
}
