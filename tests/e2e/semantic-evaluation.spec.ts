import { expect, test } from '@playwright/test'
import { mkdirSync, rmSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import { analysisApi, analysisSource, captureAnalysis } from './source-analysis-fixtures'
import { frozenRevisions, jumpToFrozenImageRecord, nextFrozenImagePage, openImageRevisions, selectImageRevision } from './image-revision-fixtures'
import { semanticUiFixture } from './semantic-evaluation-fixtures'

for (const theme of ['light', 'dark']) {
test(`semantic consent, private results and no-retry UI on fixed evidence (${theme})`, async ({ page, request }) => {
  test.setTimeout(240_000)
  const duplicateKeys: string[] = []
  page.on('console', (message) => { if (message.text().includes('Encountered two children with the same key')) duplicateKeys.push(message.text()) })
  const exweb = process.env.EXWEB_FIXTURE_ROOT
  const source = exweb ? resolve(exweb) : analysisSource()
  try {
    if (exweb) expect(execFileSync('git', ['--no-optional-locks', '-c', 'core.fsmonitor=false', '-C', source, 'rev-parse', 'HEAD'],
      { encoding: 'utf8' }).trim()).toBe('fe5827f6b76f77ef34918d8b452ee823142332dc')
    if (exweb) expect(execFileSync('git', ['--no-optional-locks', '-c', 'core.fsmonitor=false', '-C', source, 'status', '--porcelain'],
      { encoding: 'utf8' }).trim()).toBe('')
    const v = await captureAnalysis(request, source)
    await v.invoke('system_image.sources.register', { source_specs: [
      { source_type: 'us_doc', source_uri: resolve('tests/fixtures/system-image/exweb-requirements.md') },
      { source_type: 'test_asset', source_uri: resolve('tests/fixtures/system-image/exweb-test-cases.csv') },
    ] })
    await v.invoke('system_image.sources.ingest'); await v.invoke('system_image.context.materialize')
    const image = await (await request.get(`${analysisApi}/v1/projects/${v.projectId}/system-image`, { headers: v.owner.headers })).json()
    const target = image.objects.find((item: { type: string }) => item.type === 'SourceAcceptanceCriterion')
    const candidate = (await frozenRevisions(request, v.projectId, v.owner.headers)).find((item) => item.manifest_id === image.source_manifest.manifest_id)!
    const allObjects: { object_id: string }[] = []
    for (let offset = 0; offset < candidate.object_count; offset += 100) {
      allObjects.push(...(await (await request.get(`${analysisApi}/v1/projects/${v.projectId}/system-image/revisions/${candidate.image_revision_id}?section=members&offset=${offset}&limit=100`,
        { headers: v.owner.headers })).json()).items)
    }
    const targetOffset = allObjects.findIndex((item) => item.object_id === target.id)
    expect(targetOffset).toBeGreaterThanOrEqual(0)
    const targetPage = Math.floor(targetOffset / 25)
    const fixture = await semanticUiFixture(page, request, v.projectId, candidate.image_revision_id, candidate.artifact_hash, v.owner.headers)
    await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme } })
    let firstOpen = true
    async function openTarget() {
      const dialog = await openImageRevisions(page, v.projectId, v.owner.token)
      await selectImageRevision(page, candidate.image_revision_id)
      // Traverse the complete original pagination once; later independent
      // reauthorizations use the actual record-navigation control, not a mock.
      if (firstOpen) {
        for (let index = 0; index < targetPage; index++) {
          await nextFrozenImagePage(page, v.projectId, candidate.image_revision_id, (index + 1) * 25)
        }
      } else if (targetOffset > 0) await jumpToFrozenImageRecord(page, v.projectId, candidate.image_revision_id, targetOffset)
      firstOpen = false
      const row = dialog.locator(`[data-object-id="${target.id}"]`)
      await row.getByRole('button', { name: 'Inspect frozen evidence', exact: true }).click()
      await row.getByRole('button', { name: 'Find related tests', exact: true }).click()
      await expect(row.getByRole('list', { name: 'Retrieved candidates', exact: true })).toContainText('Chat stream contract fixture')
      return { dialog, row, panel: row.getByRole('region', { name: 'Semantic evaluation', exact: true }) }
    }
    let { dialog, row, panel } = await openTarget()
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    await expect(panel.getByRole('button', { name: 'Preview model egress' })).toBeDisabled()
    await row.getByRole('checkbox', { name: /Select candidate:/ }).check()
    const models = panel.getByRole('combobox', { name: 'Evaluation model' })
    await expect(models.locator('option')).toHaveCount(3)
    await models.selectOption('semantic-A')
    await panel.getByRole('button', { name: 'Preview model egress' }).click()
    const consent = panel.getByRole('region', { name: 'Model egress consent' })
    await expect(consent).toContainText('https://semantic.example/v1')
    await expect(consent).toContainText('Provider charges are not estimated.')
    await expect(panel.getByRole('button', { name: 'Confirm and evaluate' })).toBeDisabled()
    mkdirSync(resolve('output/playwright'), { recursive: true })
    await consent.scrollIntoViewIfNeeded()
    await page.screenshot({ path: resolve(`output/playwright/exweb-semantic-consent-${theme}.png`) })
    await page.setViewportSize({ width: 390, height: 844 })
    await consent.scrollIntoViewIfNeeded()
    expect(await dialog.locator('.evidence-inspector-body').evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
    await page.screenshot({ path: resolve(`output/playwright/exweb-semantic-consent-${theme}-mobile.png`) })
    await page.setViewportSize({ width: 1280, height: 900 })
    await consent.getByRole('checkbox').check()
    await models.selectOption('semantic-B')
    await expect(consent).toHaveCount(0)
    expect(fixture.calls).toBe(0)
    await panel.getByRole('button', { name: 'Preview model egress' }).click()
    await expect(consent.getByRole('checkbox')).not.toBeChecked()
    await consent.getByRole('checkbox').check()
    await row.getByRole('checkbox', { name: /Select candidate:/ }).uncheck()
    await expect(consent).toHaveCount(0)
    await expect(panel.getByRole('button', { name: 'Preview model egress' })).toBeDisabled()
    expect(fixture.calls).toBe(0)
    await row.getByRole('checkbox', { name: /Select candidate:/ }).check()
    await panel.getByRole('button', { name: 'Preview model egress' }).click()
    await expect(consent.getByRole('checkbox')).not.toBeChecked()
    await consent.getByRole('checkbox').check()
    await panel.getByRole('button', { name: 'Confirm and evaluate' }).click()
    let result = panel.getByRole('region', { name: 'Archived semantic evaluation' })
    await expect(result).toContainText('Unknown (proposed)')
    await expect(result).toContainText('Human relation decisions are recorded separately')
    await expect(result).toContainText('this fixture has not been executed')
    expect(fixture.calls).toBe(1)
    await expect(panel.getByRole('button', { name: 'Confirm and evaluate' })).toBeDisabled()
    await result.getByRole('button', { name: 'Inspect archived evidence', exact: true }).last().click()
    await expect(result.getByRole('region', { name: 'Archived reference evidence' })).toContainText('US-EXWEB-CHAT')
    await result.scrollIntoViewIfNeeded()
    await page.screenshot({ path: resolve(`output/playwright/exweb-semantic-${theme}.png`) })
    await page.setViewportSize({ width: 390, height: 844 })
    await result.scrollIntoViewIfNeeded()
    expect(await dialog.locator('.evidence-inspector-body').evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
    expect(await dialog.locator('.evidence-inspector-body').evaluate((element) => getComputedStyle(element).scrollbarWidth)).toBe('none')
    await page.screenshot({ path: resolve(`output/playwright/exweb-semantic-${theme}-mobile.png`) })
    await page.setViewportSize({ width: 1280, height: 900 })
    await result.getByRole('button', { name: 'Review relation', exact: true }).click()
    let review = result.getByRole('region', { name: 'Semantic relation review', exact: true })
    await expect(review).toContainText('Not reviewed')
    await expect(review.getByRole('button', { name: 'Record review' })).toBeDisabled()
    await expect(review.locator('option[value="accept"]')).toHaveJSProperty('disabled', true)
    await review.getByRole('combobox', { name: 'Review decision' }).selectOption('reject')
    await review.getByRole('textbox', { name: 'Review reason' }).fill('No independent business oracle; do not treat this fixture as coverage.')
    await review.getByRole('checkbox', { name: /^Confirm this decision/ }).check()
    await review.getByRole('textbox', { name: 'Review reason' }).fill('Human rejection must survive another model evaluation.')
    await expect(review.getByRole('checkbox', { name: /^Confirm this decision/ })).not.toBeChecked()
    await review.getByRole('checkbox', { name: /^Confirm this decision/ }).check()
    await review.getByRole('button', { name: 'Record review' }).click()
    await expect(review).toContainText('Review recorded.')
    await expect(review.locator('.semantic-review-head')).toContainText('Rejected relation')
    expect(fixture.reviewCalls).toBe(1); expect(fixture.calls).toBe(1)
    let frozen = review.getByRole('region', { name: 'Freeze semantic review', exact: true })
    await expect(frozen.getByRole('button')).toBeDisabled()
    await frozen.getByRole('checkbox').check()
    await frozen.getByRole('button').click()
    await expect(frozen).toContainText('Semantic review frozen.')
    await expect(frozen.getByRole('button')).toBeDisabled()
    expect(fixture.freezeCalls).toBe(1); expect(fixture.calls).toBe(1)
    await review.getByRole('button', { name: 'Reload review history' }).click()
    await expect(review.getByRole('checkbox', { name: /^Confirm this decision/ })).not.toBeChecked()
    fixture.staleReview = true
    await review.getByRole('combobox', { name: 'Review decision' }).selectOption('defer')
    await review.getByRole('checkbox', { name: /^Confirm this decision/ }).check()
    await review.getByRole('button', { name: 'Record review' }).click()
    await expect(review.getByRole('alert')).toContainText('Another reviewer changed this claim.')
    await expect(review.getByRole('button', { name: 'Record review' })).toBeDisabled()
    expect(fixture.reviewCalls).toBe(2)
    await review.scrollIntoViewIfNeeded()
    await page.screenshot({ path: resolve(`output/playwright/exweb-semantic-review-${theme}.png`) })
    await page.setViewportSize({ width: 390, height: 844 })
    await review.scrollIntoViewIfNeeded()
    expect(await dialog.locator('.evidence-inspector-body').evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
    await page.screenshot({ path: resolve(`output/playwright/exweb-semantic-review-${theme}-mobile.png`) })
    await page.setViewportSize({ width: 1280, height: 900 })
    // Re-evaluation is blocked until a human explicitly re-reviews the rejection.
    fixture.supported = true
    await panel.getByRole('button', { name: 'Preview model egress' }).click()
    await expect(consent.getByRole('alert')).toContainText('Historical review blocks evaluation.')
    await expect(consent.getByRole('checkbox')).toBeDisabled()
    await expect(panel.getByRole('button', { name: 'Confirm and evaluate' })).toBeDisabled()
    expect(fixture.calls).toBe(1)
    await page.screenshot({ path: resolve(`output/playwright/exweb-semantic-blocked-${theme}.png`) })
    await review.getByRole('button', { name: 'Reload review history' }).click()
    await review.getByRole('combobox', { name: 'Review decision' }).selectOption('defer')
    await review.getByRole('textbox', { name: 'Review reason' }).fill('Explicit human re-review allows a fresh inference, without accepting the relation.')
    await review.getByRole('checkbox', { name: /^Confirm this decision/ }).check()
    await review.getByRole('button', { name: 'Record review' }).click()
    await expect(review).toContainText('Review recorded.')
    await panel.getByRole('button', { name: 'Preview model egress' }).click()
    await expect(consent.getByRole('alert')).toHaveCount(0)
    await consent.getByRole('checkbox').check()
    await panel.getByRole('button', { name: 'Confirm and evaluate' }).click()
    await expect(result).toContainText('Supports (proposed)')
    await result.getByRole('button', { name: 'Review relation', exact: true }).click()
    review = result.getByRole('region', { name: 'Semantic relation review', exact: true })
    await expect(review.locator('.semantic-review-head')).toContainText('Deferred relation')
    await expect(review.locator('option[value="accept"]')).toHaveJSProperty('disabled', false)
    await review.getByRole('combobox', { name: 'Review decision' }).selectOption('accept')
    await review.getByRole('textbox', { name: 'Review reason' }).fill('Explicit fixture-only relation review, not oracle approval.')
    await review.getByRole('checkbox', { name: /^Confirm this decision/ }).check()
    await review.getByRole('button', { name: 'Record review' }).click()
    await expect(review.locator('.semantic-review-head')).toContainText('Accepted relation')
    await expect(review).toContainText('source authority remains pending confirmation')
    expect(fixture.reviewCalls).toBe(4); expect(fixture.calls).toBe(2)
    frozen = review.getByRole('region', { name: 'Freeze semantic review', exact: true })
    fixture.staleFreeze = true
    await expect(frozen.getByRole('checkbox')).not.toBeChecked()
    await frozen.getByRole('checkbox').check()
    await frozen.getByRole('button').click()
    await expect(frozen.getByRole('alert')).toContainText('Another reviewer changed this claim.')
    await expect(frozen.getByRole('button')).toBeDisabled()
    expect(fixture.freezeCalls).toBe(2)
    fixture.supported = false
    fixture.failNext = true
    await panel.getByRole('button', { name: 'Preview model egress' }).click()
    await consent.getByRole('checkbox').check()
    await panel.getByRole('button', { name: 'Confirm and evaluate' }).click()
    await expect(panel.getByRole('alert').filter({ hasText: 'The call did not return a committed result.' })).toContainText('will not be retried automatically')
    await expect(panel).toContainText('The call may be running or interrupted.')
    await expect(panel.getByRole('button', { name: 'Confirm and evaluate' })).toBeDisabled()
    expect(fixture.calls).toBe(3)
    ;({ dialog, row, panel } = await openTarget())
    await panel.getByRole('button', { name: 'Inspect evaluation', exact: true }).first().click()
    result = panel.getByRole('region', { name: 'Archived semantic evaluation' })
    await expect(result).toContainText('Unknown (proposed)')
    expect(fixture.calls).toBe(3)
    await result.getByRole('button', { name: 'Review relation', exact: true }).click()
    review = result.getByRole('region', { name: 'Semantic relation review', exact: true })
    await expect(review.locator('.semantic-review-head')).toContainText('Accepted relation')
    // Acceptance belongs to the supported second evaluation, not this old unknown judgment.
    await expect(review.locator('option[value="accept"]')).toHaveJSProperty('disabled', true)
    fixture.denyReviews = true
    await review.getByRole('button', { name: 'Reload review history' }).click()
    await expect(dialog.getByRole('alert')).toContainText('Previous content is hidden')
    fixture.denyReviews = false
    ;({ dialog, row, panel } = await openTarget())
    await panel.getByRole('button', { name: 'Inspect evaluation', exact: true }).first().click()
    fixture.denyHistory = true
    await panel.getByRole('button', { name: 'Reload evaluation history' }).click()
    await expect(dialog.getByRole('alert')).toContainText('Previous content is hidden')
    await expect(result).toHaveCount(0)
    fixture.denyHistory = false
    for (const malformed of theme === 'light' ? ['revision', 'evidence'] : ['oracle', 'offset']) {
      fixture.corruptResult = malformed
      ;({ dialog, row, panel } = await openTarget())
      await panel.getByRole('button', { name: 'Inspect evaluation', exact: true }).first().click()
      await expect(dialog.getByRole('alert')).toContainText('Previous content is hidden')
      await expect(dialog.getByRole('region', { name: 'Archived semantic evaluation' })).toHaveCount(0)
      expect(fixture.calls).toBe(3)
    }
    fixture.corruptResult = ''
    for (const malformed of theme === 'light' ? ['revision', 'acceptance'] : ['evidence', 'head']) {
      fixture.corruptReview = malformed
      ;({ dialog, row, panel } = await openTarget())
      await panel.getByRole('button', { name: 'Inspect evaluation', exact: true }).first().click()
      await panel.getByRole('button', { name: 'Review relation', exact: true }).click()
      await expect(dialog.getByRole('alert')).toContainText('Previous content is hidden')
      await expect(dialog.getByRole('region', { name: 'Archived semantic evaluation' })).toHaveCount(0)
      expect(fixture.reviewCalls).toBe(4)
    }
    fixture.corruptReview = ''
    dialog = await openImageRevisions(page, v.projectId, v.owner.token)
    await selectImageRevision(page, fixture.frozenRevision)
    await dialog.getByRole('button', { name: 'Frozen semantic reviews', exact: true }).click()
    const frozenRows = dialog.getByRole('list', { name: 'Frozen image records' })
    await expect(frozenRows).toContainText('Reviewed semantic snapshot')
    await expect(frozenRows).toContainText('Rejected relation')
    await frozenRows.getByText('Frozen record details', { exact: true }).click()
    await expect(frozenRows).toContainText('Human rejection must survive another model evaluation.')
    await frozenRows.scrollIntoViewIfNeeded()
    await page.screenshot({ path: resolve(`output/playwright/exweb-frozen-semantic-${theme}.png`) })
    await page.setViewportSize({ width: 390, height: 844 })
    expect(await dialog.locator('.evidence-inspector-body').evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
    await page.screenshot({ path: resolve(`output/playwright/exweb-frozen-semantic-${theme}-mobile.png`) })
    fixture.corruptFrozen = true
    await dialog.getByRole('button', { name: 'Objects', exact: true }).click()
    await expect(frozenRows).toBeVisible()
    await dialog.getByRole('button', { name: 'Frozen semantic reviews', exact: true }).click()
    await expect(dialog.getByRole('alert')).toContainText('Previous content is hidden')
    expect(duplicateKeys).toEqual([])
  } finally { if (!exweb) rmSync(source, { recursive: true, force: true }) }
})
}
