import { expect, test } from '@playwright/test'
import { createHash } from 'node:crypto'
import { mkdirSync, rmSync } from 'node:fs'
import { resolve } from 'node:path'
import { analysisApi, analysisSource, captureAnalysis } from './source-analysis-fixtures'
import { frozenRevisions, openImageRevisions, selectImageRevision } from './image-revision-fixtures'

for (const theme of ['light', 'dark']) {
test(`screened recall displays fixed exclusion and revalidation states (${theme})`, async ({ page, request }) => {
  test.setTimeout(90_000)
  const source = analysisSource()
  try {
    const v = await captureAnalysis(request, source)
    await v.invoke('system_image.sources.register', { source_specs: [
      { source_type: 'us_doc', source_uri: resolve('tests/fixtures/system-image/exweb-requirements.md') },
      { source_type: 'test_asset', source_uri: resolve('tests/fixtures/system-image/exweb-test-cases.csv') },
    ] })
    await v.invoke('system_image.sources.ingest'); await v.invoke('system_image.context.materialize')
    const image = await (await request.get(`${analysisApi}/v1/projects/${v.projectId}/system-image`, { headers: v.owner.headers })).json()
    const target = image.objects.find((item: { type: string }) => item.type === 'SourceAcceptanceCriterion')
    const candidate = (await frozenRevisions(request, v.projectId, v.owner.headers)).find((item) => item.manifest_id === image.source_manifest.manifest_id)!
    const members: { object_id: string }[] = []
    for (let offset = 0; offset < candidate.object_count; offset += 100) {
      const response = await request.get(`${analysisApi}/v1/projects/${v.projectId}/system-image/revisions/${candidate.image_revision_id}?section=members&offset=${offset}&limit=100`, { headers: v.owner.headers })
      expect(response.ok()).toBeTruthy()
      members.push(...(await response.json()).items)
    }
    const targetIndex = members.findIndex((item) => item.object_id === target.id)
    expect(targetIndex).toBeGreaterThanOrEqual(0)
    await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme } })
    // Source ingestion and canonical queries are real. Historical review states
    // below are transport fixtures; real rejection/persistence is covered in PG tests.
    let mode = 'rejected'
    let corrupt = false
    const queries = new Map<string, string>()
    await page.route('**/v1/tool-invocations', async (route) => {
      if (route.request().method() !== 'POST' || route.request().postDataJSON()?.tool_id !== 'query.system_image.links.screened_candidates') return route.continue()
      const response = await route.fetch()
      const invocation = await response.json()
      expect(invocation.status).toBe('completed')
      queries.set(invocation.id, mode)
      await route.fulfill({ response })
    })
    await page.route(/\/v1\/tool-invocations\/[^/]+\/image-query$/, async (route) => {
      const snapshot = queries.get(route.request().url().split('/').at(-2)!)
      if (!snapshot) return route.continue()
      const response = await route.fetch()
      const body = await response.json()
      expect(body.items).toHaveLength(1)
      body.review_scope_digest = `sha256:${createHash('sha256').update(snapshot).digest('hex')}`
      body.review_screening = [{ subject_object_id: body.items[0].endpoint.object_id,
        head_decision_id: `fixture-${snapshot}`, head_decision_digest: body.review_scope_digest,
        claim_id: 'fixture-claim', source_image_revision_id: candidate.image_revision_id, decision: 'reject',
        status: snapshot === 'rejected' ? 'rejected_same_revisions' : snapshot === 'stale' ? 'stale_requires_review' : 'same_revisions_review_required',
        candidate_action: snapshot === 'rejected' ? 'exclude_from_unreviewed_candidates' : snapshot === 'stale' ? 'revalidate_before_review' : 'review_before_acceptance' }]
      if (snapshot === 'reviewed') body.review_screening[0].decision = 'defer'
      if (snapshot === 'rejected') {
        body.items = []; body.matched_count = 0; body.excluded.historical_review = 1
      } else body.items[0].review_status = snapshot === 'stale' ? 'requires_revalidation' : 'reviewed_not_approved'
      if (corrupt) body.review_scope = 'unverified_live_head'
      await route.fulfill({ response, json: body })
    })
    const dialog = await openImageRevisions(page, v.projectId, v.owner.token)
    await selectImageRevision(page, candidate.image_revision_id)
    for (let index = 0; index < Math.floor(targetIndex / 25); index++) {
      await dialog.getByRole('group', { name: 'Revision content pages' }).getByRole('button', { name: 'Next page', exact: true }).click()
      await expect(dialog.getByRole('list', { name: 'Frozen image records' })).toBeVisible()
    }
    const row = dialog.locator(`[data-object-id="${target.id}"]`)
    await row.getByRole('button', { name: 'Inspect frozen evidence', exact: true }).click()
    const recall = row.getByRole('region', { name: 'Related code and test candidates', exact: true })
    const refresh = recall.getByRole('button', { name: 'Find related tests', exact: true })
    await refresh.click()
    await expect(recall).toContainText('Excluded by historical review before limiting: 1')
    await expect(recall.getByRole('checkbox')).toHaveCount(0)
    mode = 'stale'
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')))
    await expect(recall).toContainText('Excluded by historical review before limiting: 1')
    expect(queries.size).toBe(1)
    await refresh.click()
    await expect(recall).toContainText('Source changed: revalidation required')
    await expect(recall.getByRole('checkbox')).toHaveCount(1)
    expect(queries.size).toBe(2)
    await page.setViewportSize({ width: 390, height: 844 })
    await recall.scrollIntoViewIfNeeded()
    expect(await dialog.locator('.evidence-inspector-body').evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true)
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    mkdirSync(resolve('output/playwright'), { recursive: true })
    await page.screenshot({ path: resolve(`output/playwright/screened-recall-${theme}-mobile.png`) })
    mode = 'reviewed'
    await refresh.click()
    await expect(recall).toContainText('Previously reviewed; approval is not transferred')
    corrupt = true
    await refresh.click()
    await expect(dialog.getByRole('alert')).toContainText('Previous content is hidden; reload to check access.')
    await expect(dialog.getByRole('region', { name: 'Related code and test candidates', exact: true })).toHaveCount(0)
    await expect(dialog.getByRole('list', { name: 'Frozen image records' })).toHaveCount(0)
  } finally { rmSync(source, { recursive: true, force: true }) }
})
}
