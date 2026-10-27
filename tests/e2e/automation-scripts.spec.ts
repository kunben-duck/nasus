import { expect, test } from '@playwright/test'
import { mkdirSync, rmSync } from 'node:fs'
import { resolve } from 'node:path'
import { installMappingProtocol, mappingArchiveFixture } from './test-design-mapping-fixtures'
import { generationScopeFixture } from './test-design-generation-fixtures'
import { automationInputFixture } from './automation-input-fixtures'
import { installScriptProtocol } from './automation-script-fixtures'
import { analysisApi, analysisSource } from './source-analysis-fixtures'
import { canonicalDigest } from '../../apps/portal/src/shared/utils/canonicalDigest'
import { zhCN } from '../../apps/portal/src/shared/i18n/messages'

for (const [theme, language, scriptProtocol] of [['light', 'en', 'v1'], ['dark', 'zh', 'v2'],
  ['light', 'zh', 'v3'], ['dark', 'en', 'v3']] as const) {
  const variant = scriptProtocol === 'v3' ? `${theme}-v3` : theme
  test(`script budget, lost acknowledgements and independent review preserve original pins (${variant})`, async ({ page, request }) => {
    test.setTimeout(360_000)
    const exweb = process.env.EXWEB_FIXTURE_ROOT, source = exweb ? resolve(exweb) : analysisSource()
    try {
      const v = await generationScopeFixture(request, source), mapping = await installMappingProtocol(page, v.scope)
      for (const a of mapping.draft.result.proposal.cases[0].assertions) {
        a.oracle_digest = await canonicalDigest(a.oracle)
        mapping.draft.result.proposal.coverage.rows.find((row) => row.row_id === a.row_id)!.oracle_digest = a.oracle_digest
      }
      const head = await mappingArchiveFixture(mapping.draft, { project_id: v.projectId, generation_id: mapping.draft.metadata.generation_id,
        generation_artifact_hash: mapping.draft.metadata.artifact_hash, expected_previous_revision_id: null, decision: 'review',
        mappings: mapping.draft.result.proposal.cases.flatMap((item) => item.assertions.map((a) => ({ case_id: item.case_id,
          row_id: a.row_id, step_index: a.step_index, oracle_digest: a.oracle_digest, decision: 'accept', reason: 'Explicit independent protocol specimen' }))),
        reason: 'Browser transport specimen, not executed coverage', policy_revision: 'nasus.test-design-mapping.v1' }, null)
      mapping.history.push(head)
      const prepared = await automationInputFixture(mapping.draft, head, v.context.context, v.scope)
      const scripts = await installScriptProtocol(page, prepared)
      scripts.admissionStatus = null
      for (let index = 0; index < 11; index++) scripts.history.push({ invocation_id: `ui-script-command-a-${String(index).padStart(3, '0')}`,
        status: 'failed', call_reserved: false, reply_archived: false, provider_outcome_unknown: false, script_revision_id: null, artifact_hash: null })
      expect((await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme, language } })).ok()).toBeTruthy()
      await page.addInitScript(({ token, locale }) => { localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', locale) },
        { token: v.owner.token, locale: language })
      const errors: string[] = []
      page.on('pageerror', (error) => errors.push(error.message))
      const label = (value: keyof typeof zhCN) => language === 'zh' ? zhCN[value] : value
      await page.goto(`/projects/${v.projectId}/knowledge`)
      await page.getByRole('button', { name: label('Inspect published context'), exact: true }).click()
      await page.getByRole('button').filter({ hasText: v.contextId }).click()
      await page.getByRole('button', { name: label('Inspect test-design scope'), exact: true }).click()
      await page.getByRole('button', { name: label('Inspect draft generation'), exact: true }).click()
      await page.getByRole('button', { name: label('Inspect assertion mapping'), exact: true }).click()
      const panel = page.getByRole('region', { name: label('Pinned automation script drafts'), exact: true })
      await expect(panel).toBeVisible(); expect(scripts.historyReads).toBe(0); expect(scripts.writes).toEqual([])
      await panel.getByRole('button', { name: label('Inspect script drafts'), exact: true }).click()
      await panel.getByRole('combobox', { name: label('Tested chat model'), exact: true }).selectOption('ui-tested-model')
      for (const [name, value] of [['Maximum input tokens', '24576'], ['Maximum output tokens', '1024'],
        ['Total token reservation ceiling', '65536'], ['Maximum reserved spend', '1']] as const) await panel.getByLabel(label(name), { exact: true }).fill(value)
      const prepare = panel.getByRole('button', { name: label('Preview complete script budget'), exact: true })
      await expect(prepare).toBeDisabled()
      await panel.getByRole('button', { name: label('Load more script history'), exact: true }).click()
      await expect(prepare).toBeDisabled()
      await expect(panel.getByRole('status')).toContainText(label('Independently approve these exact cases before generating scripts. Mapping acceptance alone is not case admission.'))
      expect(scripts.previews).toBe(0); expect(scripts.writes).toEqual([])
      scripts.admissionStatus = 'approved'
      await panel.getByRole('button', { name: label('Reload script access and history'), exact: true }).click()
      await expect(prepare).toBeEnabled(); await prepare.click()
      const consent = panel.getByRole('checkbox', { name: label('I confirm this exact script input, model destination, source inventory and single-call token/spend ceiling. Execution is not authorized.'), exact: true })
      await consent.check()
      await panel.getByLabel(label('Maximum reserved spend'), { exact: true }).fill('2')
      await expect(consent).toHaveCount(0); expect(scripts.writes).toEqual([])
      await prepare.click(); await consent.check()
      const protocol = panel.getByRole('combobox', { name: label('HTTP script protocol'), exact: true })
      await expect(protocol).toHaveValue('v1'); await protocol.selectOption('v2')
      await expect(consent).toHaveCount(0); expect(scripts.writes).toEqual([])
      await prepare.click(); await consent.check()
      if (scriptProtocol !== 'v2') {
        await protocol.selectOption(scriptProtocol); await expect(consent).toHaveCount(0)
        await prepare.click(); await consent.check()
      }
      scripts.admissionStatus = 'withdrawn'
      await panel.getByRole('button', { name: label('Reload script access and history'), exact: true }).click()
      await expect(consent).toHaveCount(0); await expect(prepare).toBeDisabled(); expect(scripts.writes).toEqual([])
      scripts.admissionStatus = 'approved'
      await panel.getByRole('button', { name: label('Reload script access and history'), exact: true }).click()
      await expect(prepare).toBeEnabled(); await prepare.click(); await consent.check()
      scripts.loseGenerationAck = true
      await panel.getByRole('button', { name: label('Generate script drafts'), exact: true }).click()
      await expect(panel.getByRole('alert')).toContainText(label('Script generation was not acknowledged. Inspect the original command history before a new confirmation. Unknown calls are never automatically resent.'))
      expect(scripts.writes).toHaveLength(1); expect(scripts.confirmed).toHaveLength(1)
      await panel.getByRole('button', { name: label('Reload script access and history'), exact: true }).click()
      const original = scripts.confirmed[0]
      await panel.getByRole('combobox', { name: label('Script generation history'), exact: true }).selectOption(original)
      const archived = panel.getByTestId('automation-script-draft')
      await expect(archived).toBeVisible(); expect(scripts.writes).toHaveLength(1)
      expect(scripts.drafts.size).toBe(1)
      const draft = [...scripts.drafts.values()][0]
      expect(draft.result.prepared.generation_pin).toEqual(head.generation_pin)
      expect(draft.result.prepared.mapping_pin.revision_id).toBe(head.revision.revision_id)
      expect(draft.result.proposal.passed_count).toBe(0); expect(draft.result.proposal.execution_authorized).toBe(false)
      expect(draft.result.request.case_approval_revision_id).toBe(scripts.admission.revision_id)
      expect(draft.result.request.case_approval_artifact_hash).toBe(scripts.admission.artifact_hash)
      expect(draft.result.proposal.schema).toBe('nasus.automation-script-proposal.' + scriptProtocol)
      expect(draft.result.request.http_protocol).toBe(scriptProtocol === 'v1' ? undefined : 'nasus.runner-http-execution.' + scriptProtocol)
      if (scriptProtocol === 'v3') for (const script of draft.result.proposal.scripts) {
        expect(script.actions[0]).toEqual({ action: 'use_fixture_binding', binding_id: 'session', source_step_indices: [0] })
        expect(script.actions.filter((action) => action.action === 'capture_json')).toHaveLength(0)
        expect(script.actions.find((action) => action.action === 'request')!.path).toBe('/sessions/{{session}}')
        expect(script.assertions.map((a) => a.oracle)).toEqual(prepared.cases.find((item) => item.case_id === script.case_id)!.assertions.map((a) => a.oracle))
      }
      const review = panel.getByRole('region', { name: label('Independent script review'), exact: true })
      expect(scripts.reviewReads).toBe(0)
      await review.getByRole('button', { name: label('Inspect script review'), exact: true }).click()
      await review.getByRole('button', { name: label('Review script actions and oracles'), exact: true }).click()
      const editor = review.getByRole('group', { name: label('New independent script decision'), exact: true })
      await editor.locator('details > summary').click()
      const decisions = editor.getByRole('combobox', { name: label('Review decision'), exact: true }), reasons = editor.getByRole('textbox', { name: label('Review reason'), exact: true })
      await expect(decisions).toHaveCount(draft.result.proposal.scripts[0].actions.length + draft.result.proposal.scripts[0].assertions.length)
      await expect(reasons).toHaveCount(await decisions.count() + 1)
      for (let index = 0; index < await decisions.count(); index++) {
        await expect(decisions.nth(index)).toHaveValue('defer'); await expect(reasons.nth(index)).toHaveValue('')
        await decisions.nth(index).selectOption('accept'); await reasons.nth(index).fill('Explicit individual equivalence review; no target execution')
      }
      await reasons.last().fill('Independent complete protocol review')
      const reviewConsent = editor.getByRole('checkbox')
      await reviewConsent.check(); await reasons.last().fill('Updated complete protocol review')
      await expect(reviewConsent).not.toBeChecked()
      const record = editor.getByRole('button', { name: label('Record script decision'), exact: true })
      await expect(record).toBeDisabled(); await reviewConsent.check()
      mkdirSync(resolve('output/playwright'), { recursive: true })
      await editor.scrollIntoViewIfNeeded(); await page.screenshot({ path: resolve(`output/playwright/automation-scripts-${variant}-desktop.png`) })
      await page.setViewportSize({ width: 390, height: 844 })
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
      const mobileReasonWidths = await reasons.evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().width))
      expect(Math.min(...mobileReasonWidths)).toBeGreaterThanOrEqual(220)
      const bannerButtons = await page.locator('.terms-bar > button').evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().height))
      expect(bannerButtons.length).toBe(2)
      expect(Math.max(...bannerButtons)).toBeLessThanOrEqual(36)
      await editor.scrollIntoViewIfNeeded(); await page.screenshot({ path: resolve(`output/playwright/automation-scripts-${variant}-mobile.png`) })
      scripts.loseReviewAck = true; await record.click()
      await expect(review.getByRole('alert')).toContainText(label('Script decision was not acknowledged. Reload the original history before another confirmation; no retry was sent.'))
      expect(scripts.reviews).toHaveLength(1); expect(scripts.reviews[0].assessment?.review_complete).toBe(true)
      await review.getByRole('button', { name: label('Reload script review'), exact: true }).click()
      await expect(review).toContainText(scripts.reviews[0].revision.revision_id)
      expect(scripts.writes).toHaveLength(2); expect(scripts.confirmed).toHaveLength(2)
      await review.getByRole('button', { name: label('Withdraw script review'), exact: true }).click()
      await editor.getByRole('textbox', { name: label('Review reason'), exact: true }).fill('Explicit withdrawal without editing the original oracle')
      await editor.getByRole('checkbox').check(); await record.click()
      await expect(review).toContainText(label('Withdrawn script review'))
      expect(scripts.reviews).toHaveLength(2); expect(scripts.reviews[1].assessment).toBeNull()
      await review.getByRole('combobox', { name: label('Script review history'), exact: true }).selectOption(scripts.reviews[0].revision.revision_id)
      await expect(review).toContainText(label('Recorded script review; execution not authorized'))
      const writes = scripts.writes.length
      scripts.failReview = true
      await review.getByRole('button', { name: label('Reload script review'), exact: true }).click()
      await expect(archived).toHaveCount(0)
      await page.waitForTimeout(300)
      expect(scripts.writes).toHaveLength(writes); expect(mapping.writes).toEqual([]); expect(mapping.generationWrites).toBe(0); expect(errors).toEqual([])
    } finally { if (!exweb) rmSync(source, { recursive: true, force: true }) }
  })
}
