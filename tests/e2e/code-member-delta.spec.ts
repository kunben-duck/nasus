import { expect, test, type APIRequestContext, type Request } from '@playwright/test'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { analysisApi, analysisSource, captureAnalysis } from './source-analysis-fixtures'
import { frozenRevisions, openImageRevisions, selectImageRevision } from './image-revision-fixtures'

async function comparisonFixture(request: APIRequestContext, source: string) {
  const fixture = await captureAnalysis(request, source)
  const [before] = await frozenRevisions(request, fixture.projectId, fixture.owner.headers)
  writeFileSync(join(source, 'Added.java'), 'class Added { public String health() { return "ok"; } }\n')
  await fixture.invoke('system_image.context.materialize')
  const images = await frozenRevisions(request, fixture.projectId, fixture.owner.headers)
  const after = images.find((item) => item.image_revision_id !== before.image_revision_id)!
  const params = new URLSearchParams({ before_image_revision_id: before.image_revision_id, before_image_hash: before.artifact_hash,
    after_image_revision_id: after.image_revision_id, after_image_hash: after.artifact_hash, limit: '20', offset: '0' })
  const response = await request.get(`${analysisApi}/v1/projects/${fixture.projectId}/system-image/code-member-delta?${params}`, { headers: fixture.owner.headers })
  expect(response.ok()).toBeTruthy()
  return { ...fixture, before, after, expected: await response.json() }
}

for (const theme of ['light', 'dark']) {
  test(`fixed code comparison remains read-only and paginated in ${theme} desktop and mobile`, async ({ page, request }) => {
    const source = analysisSource()
    try {
      const fixture = await comparisonFixture(request, source)
      const { projectId, owner, before, after, expected } = fixture
      expect((await request.patch(`${analysisApi}/v1/settings`, { headers: owner.headers, data: { theme } })).ok()).toBeTruthy()
      const dialog = await openImageRevisions(page, projectId, owner.token)
      await selectImageRevision(page, after.image_revision_id)
      let writes = 0
      const reads: { offset: number; limit: number; request: Request }[] = []
      const aborted = new Set<Request>()
      page.on('requestfailed', (sent) => {
        if (sent.failure()?.errorText === 'net::ERR_ABORTED') aborted.add(sent)
      })
      page.on('request', (sent) => { if (['POST', 'PATCH', 'PUT', 'DELETE'].includes(sent.method())) writes += 1 })
      await page.route((url) => url.pathname.endsWith('/system-image/code-member-delta'), async (route) => {
        const url = new URL(route.request().url())
        expect(url.searchParams.get('before_image_hash')).toBe(before.artifact_hash)
        expect(url.searchParams.get('after_image_hash')).toBe(after.artifact_hash)
        const limit = Number(url.searchParams.get('limit')), offset = Number(url.searchParams.get('offset'))
        reads.push({ limit, offset, request: route.request() })
        if (limit > 10) await route.fulfill({ status: 413, json: { detail: { error: { code: 'image_page_too_large', message: 'Reduce complete page' } } } })
        else await route.continue()
      })
      const toggle = dialog.getByRole('button', { name: 'Compare code versions', exact: true })
      await expect(toggle).toHaveAttribute('aria-expanded', 'false')
      await toggle.click()
      const choose = dialog.getByRole('combobox', { name: 'Compare from image', exact: true })
      const compare = dialog.getByRole('button', { name: 'Compare fixed images', exact: true })
      await expect(compare).toBeDisabled()
      expect(reads).toHaveLength(0)
      await choose.selectOption(before.image_revision_id)
      expect(reads).toHaveLength(0)
      await compare.click()
      const result = dialog.getByTestId('code-member-delta-result')
      await expect(result).toBeVisible()
      const rows = result.getByRole('list', { name: 'Code member changes', exact: true }).locator(':scope > li')
      await expect(rows).toHaveCount(10)
      // Development StrictMode can cancel its initial mount. Count the actual
      // non-aborted read, not the discarded request, as the shrink sequence.
      expect(reads.filter((read) => !aborted.has(read.request)).map(({ offset, limit }) => ({ offset, limit })))
        .toEqual([{ offset: 0, limit: 20 }, { offset: 0, limit: 10 }])
      const first = await rows.first().getAttribute('data-entity-id')
      await result.getByText('Comparison provenance', { exact: true }).click()
      await expect(result).toContainText(before.artifact_hash)
      await expect(result).toContainText(after.artifact_hash)
      await expect(result).toContainText(expected.content_hash)
      await expect(dialog).toContainText('Removal is not proof of source deletion')
      const pages = result.getByRole('group', { name: 'Code comparison pages', exact: true })
      await pages.getByRole('button', { name: 'Next page', exact: true }).click()
      await expect(rows.first()).not.toHaveAttribute('data-entity-id', first!)
      expect(reads.at(-1)?.offset).toBe(10)
      await pages.getByRole('button', { name: 'Previous page', exact: true }).click()
      await expect(rows.first()).toHaveAttribute('data-entity-id', first!)
      await dialog.getByRole('combobox', { name: 'Member change category', exact: true }).selectOption('added_member')
      await expect(rows).toHaveCount(expected.counts.added_member)
      await expect(result).toContainText('Added to image')
      await expect(result.locator('img, script')).toHaveCount(0)
      mkdirSync(resolve('output/playwright'), { recursive: true })
      await result.scrollIntoViewIfNeeded()
      await page.screenshot({ path: resolve(`output/playwright/code-member-delta-${theme}.png`) })
      await page.setViewportSize({ width: 390, height: 844 })
      await result.scrollIntoViewIfNeeded()
      const body = dialog.locator('.evidence-inspector-body')
      expect(await body.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
      expect(await body.evaluate((element) => getComputedStyle(element).scrollbarWidth)).toBe('none')
      await page.screenshot({ path: resolve(`output/playwright/code-member-delta-${theme}-mobile.png`) })
      await choose.selectOption('')
      await expect(result).toHaveCount(0)
      await expect(compare).toBeDisabled()
      await toggle.click()
      await toggle.click()
      await expect(choose).toHaveValue('')
      await expect(result).toHaveCount(0)
      expect(writes).toBe(0)
    } finally { rmSync(source, { recursive: true, force: true }) }
  })
}

for (const failure of ['wrong image hash', 'changed comparison hash', 'source access revoked']) {
  test(`code comparison hides prior results on ${failure} without another mutation`, async ({ page, request }) => {
    const source = analysisSource()
    try {
      const { owner, projectId, before, after } = await comparisonFixture(request, source)
      let fail = false, reads = 0, writes = 0
      await page.route((url) => url.pathname.endsWith('/system-image/code-member-delta'), async (route) => {
        reads += 1
        if (!fail) { await route.continue(); return }
        if (failure === 'source access revoked') { await route.fulfill({ status: 403, json: { detail: { error: { code: 'source_access_denied', message: 'Denied' } } } }); return }
        const response = await route.fetch(), body = await response.json()
        body[failure === 'wrong image hash' ? 'after_image_hash' : 'content_hash'] = `sha256:${'f'.repeat(64)}`
        await route.fulfill({ response, json: body })
      })
      const dialog = await openImageRevisions(page, projectId, owner.token)
      await selectImageRevision(page, after.image_revision_id)
      await dialog.getByRole('button', { name: 'Compare code versions', exact: true }).click()
      await dialog.getByRole('combobox', { name: 'Compare from image', exact: true }).selectOption(before.image_revision_id)
      await dialog.getByRole('button', { name: 'Compare fixed images', exact: true }).click()
      const result = dialog.getByTestId('code-member-delta-result')
      await expect(result).toBeVisible()
      const priorReads = reads
      page.on('request', (sent) => { if (['POST', 'PATCH', 'PUT', 'DELETE'].includes(sent.method())) writes += 1 })
      fail = true
      await result.getByRole('group', { name: 'Code comparison pages', exact: true }).getByRole('button', { name: 'Next page', exact: true }).click()
      await expect(result).toHaveCount(0)
      await expect(dialog.getByRole('alert')).toContainText('Previous content is hidden')
      expect(reads - priorReads).toBe(1)
      expect(writes).toBe(0)
    } finally { rmSync(source, { recursive: true, force: true }) }
  })
}
