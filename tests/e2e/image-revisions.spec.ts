import { expect, test } from '@playwright/test'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { analysisAccount, analysisApi, analysisSource, analysisSourcePolicy, captureAnalysis } from './source-analysis-fixtures'
import { frozenRevisions, jumpToFrozenImageRecord, openImageRevisions, selectImageRevision } from './image-revision-fixtures'

for (const theme of ['light', 'dark']) {
  test(`frozen candidates and exact evidence preserve ${theme} desktop and mobile layout`, async ({ page, request }) => {
    const source = analysisSource()
    try {
      const { owner, projectId, revision } = await captureAnalysis(request, source)
      const [candidate] = await frozenRevisions(request, projectId, owner.headers)
      expect((await request.patch(`${analysisApi}/v1/settings`, { headers: owner.headers, data: { theme } })).ok()).toBeTruthy()
      const dialog = await openImageRevisions(page, projectId, owner.token)
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
      const records = dialog.getByRole('list', { name: 'Frozen image records' })
      await expect(records).toHaveCount(0)
      await selectImageRevision(page, candidate.image_revision_id)
      await expect(dialog).toContainText('Candidate · not approved')
      await expect(dialog).toContainText('Inferred relationships are not validated business rules.')
      await expect(dialog).not.toContainText('Official')
      await expect(records.locator(':scope > li')).toHaveCount(25)
      await expect(records.locator('img, script')).toHaveCount(0)
      const firstId = await records.locator(':scope > li').first().getAttribute('data-object-id')
      await dialog.getByRole('button', { name: 'Next page', exact: true }).click()
      await expect(records.locator(':scope > li').first()).not.toHaveAttribute('data-object-id', firstId!)
      await dialog.getByRole('button', { name: 'Previous page', exact: true }).click()
      await expect(records.locator(':scope > li').first()).toHaveAttribute('data-object-id', firstId!)
      await records.getByRole('button', { name: 'Inspect frozen evidence', exact: true }).first().click()
      const code = dialog.getByRole('region', { name: 'Archived source code' })
      await expect(code).toBeVisible()
      const row = records.locator(':scope > li').filter({ has: page.getByRole('region', { name: 'Archived source code' }) })
      const objectId = await row.getAttribute('data-object-id')
      const evidenceId = await row.getByRole('combobox', { name: 'Frozen evidence reference' }).inputValue()
      const endpoint = `${analysisApi}/v1/projects/${projectId}/system-image/revisions/${candidate.image_revision_id}/objects/${objectId}/evidence/${evidenceId}`
      const raw = await request.get(endpoint, { headers: owner.headers })
      expect(raw.ok()).toBeTruthy()
      const expected = await raw.json()
      expect(expected.evidence.source_revision_id).toBe(revision)
      expect(await code.locator('code').allTextContents()).toEqual(expected.content.split('\n')
        .slice(0, expected.end_line - expected.start_line + 1).map((line: string) => line || '\u00a0'))
      await expect(code.locator('img, script')).toHaveCount(0)
      await dialog.getByText('Revision provenance', { exact: true }).click()
      await expect(dialog).toContainText(candidate.artifact_hash)
      await expect(dialog).toContainText(candidate.manifest_id)
      await dialog.getByRole('combobox', { name: 'Frozen candidate revision', exact: true }).scrollIntoViewIfNeeded()
      mkdirSync(resolve('output/playwright'), { recursive: true })
      await page.screenshot({ path: resolve(`output/playwright/image-revision-${theme}.png`) })
      await page.setViewportSize({ width: 390, height: 844 })
      const bounds = await dialog.boundingBox()
      expect(bounds!.x).toBeGreaterThanOrEqual(0)
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390)
      expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(844)
      const body = dialog.locator('.evidence-inspector-body')
      expect(await body.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
      expect(await body.evaluate((element) => getComputedStyle(element).scrollbarWidth)).toBe('none')
      await page.screenshot({ path: resolve(`output/playwright/image-revision-${theme}-mobile.png`) })
      await code.scrollIntoViewIfNeeded()
      expect(await body.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
      await page.screenshot({ path: resolve(`output/playwright/image-revision-${theme}-mobile-evidence.png`) })
      await page.keyboard.press('Escape')
      await expect(dialog).toHaveCount(0)
      await expect(page.getByRole('button', { name: 'Image revisions', exact: true })).toBeFocused()
      await page.getByRole('button', { name: 'Image revisions', exact: true }).click()
      await expect(dialog.getByRole('combobox', { name: 'Frozen candidate revision' })).toHaveValue('')
      await expect(code).toHaveCount(0)
    } finally { rmSync(source, { recursive: true, force: true }) }
  })
}

for (const theme of ['light', 'dark']) {
  test(`record navigation reads exact frozen positions without a write in ${theme}`, async ({ page, request }) => {
    const duplicateKeys: string[] = []
    page.on('console', (message) => { if (message.text().includes('Encountered two children with the same key')) duplicateKeys.push(message.text()) })
    const source = analysisSource()
    try {
      const { owner, projectId } = await captureAnalysis(request, source)
      const [candidate] = await frozenRevisions(request, projectId, owner.headers)
      expect((await request.patch(`${analysisApi}/v1/settings`, { headers: owner.headers, data: { theme } })).ok()).toBeTruthy()
      const dialog = await openImageRevisions(page, projectId, owner.token)
      await selectImageRevision(page, candidate.image_revision_id)
      const records = dialog.getByRole('list', { name: 'Frozen image records', exact: true })
      const first = await records.locator(':scope > li').first().getAttribute('data-object-id')
      let writes = 0, reads = 0
      page.on('request', (sent) => {
        if (['POST', 'PATCH', 'PUT', 'DELETE'].includes(sent.method())) writes += 1
        if (new URL(sent.url()).pathname.endsWith(`/revisions/${candidate.image_revision_id}`)) reads += 1
      })
      const navigation = dialog.getByRole('form', { name: 'Record navigation', exact: true })
      const position = navigation.getByRole('spinbutton', { name: 'Start at record', exact: true })
      const go = navigation.getByRole('button', { name: 'Go to record', exact: true })
      const before = reads
      for (const invalid of ['0', String(candidate.object_count + 1), '1.5']) {
        await position.fill(invalid)
        await expect(go).toBeDisabled()
        await position.press('Enter')
        await expect(records.locator(':scope > li').first()).toHaveAttribute('data-object-id', first!)
      }
      expect(reads).toBe(before)
      const offset = candidate.object_count - 1
      const response = await request.get(`${analysisApi}/v1/projects/${projectId}/system-image/revisions/${candidate.image_revision_id}?section=objects&offset=${offset}&limit=1`, { headers: owner.headers })
      expect(response.ok()).toBeTruthy()
      const last = (await response.json()).items[0].id
      await jumpToFrozenImageRecord(page, projectId, candidate.image_revision_id, offset)
      await expect(records.locator(':scope > li')).toHaveCount(1)
      await expect(records.locator(':scope > li').first()).toHaveAttribute('data-object-id', last)
      await expect(navigation).toContainText(`Records ${offset + 1} to ${offset + 1} of ${candidate.object_count}`)
      await page.setViewportSize({ width: 390, height: 844 })
      await navigation.scrollIntoViewIfNeeded()
      const body = dialog.locator('.evidence-inspector-body')
      expect(await body.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
      expect(await body.evaluate((element) => getComputedStyle(element).scrollbarWidth)).toBe('none')
      mkdirSync(resolve('output/playwright'), { recursive: true })
      await page.screenshot({ path: resolve(`output/playwright/image-record-navigation-${theme}-mobile.png`) })
      await dialog.getByRole('group', { name: 'Revision content pages', exact: true })
        .getByRole('button', { name: 'Previous page', exact: true }).click()
      await expect(records.locator(':scope > li').first()).toHaveAttribute('data-object-id', first!)
      await expect(position).toHaveValue('1')
      await dialog.getByRole('button', { name: 'Frozen reviews', exact: true }).click()
      await expect(dialog).toContainText('No records in this section.')
      await expect(navigation).toHaveCount(0)
      await dialog.getByRole('button', { name: 'Objects', exact: true }).click()
      await expect(position).toHaveValue('1')
      expect(writes).toBe(0)
      expect(duplicateKeys).toEqual([])
    } finally { rmSync(source, { recursive: true, force: true }) }
  })
}

test('new capture does not rewrite a selected historical image and navigation clears it', async ({ page, request }) => {
  const source = analysisSource()
  try {
    const fixture = await captureAnalysis(request, source)
    const [old] = await frozenRevisions(request, fixture.projectId, fixture.owner.headers)
    writeFileSync(join(source, 'Added.java'), 'class AddedRevisionMarker {}\n')
    await fixture.invoke('system_image.context.materialize')
    // Materialization consumes captured snapshots, never an uncaptured local edit.
    expect(await frozenRevisions(request, fixture.projectId, fixture.owner.headers)).toEqual([old])
    await fixture.invoke('system_image.sources.ingest')
    await fixture.invoke('system_image.context.materialize')
    const all = await frozenRevisions(request, fixture.projectId, fixture.owner.headers)
    expect(all).toHaveLength(2)
    const latest = all.find((item) => item.image_revision_id !== old.image_revision_id)!
    // Exercise actual server cursors with two candidates rather than generating
    // 21 large images just to cross the default browser page size.
    await page.route((url) => url.pathname.endsWith(`/projects/${fixture.projectId}/system-image/revisions`), async (route) => {
      const url = new URL(route.request().url())
      url.searchParams.set('limit', '1')
      await route.fulfill({ response: await route.fetch({ url: url.toString() }) })
    })
    const dialog = await openImageRevisions(page, fixture.projectId, fixture.owner.token)
    const choose = dialog.getByRole('combobox', { name: 'Frozen candidate revision' })
    await expect(choose.locator('option')).toHaveCount(2)
    await selectImageRevision(page, all[0].image_revision_id)
    await dialog.getByRole('group', { name: 'Revision list pages' }).getByRole('button', { name: 'Next page' }).click()
    await expect(choose).toHaveValue('')
    await expect(dialog.getByRole('list', { name: 'Frozen image records' })).toHaveCount(0)
    await selectImageRevision(page, all[1].image_revision_id)
    await dialog.getByRole('group', { name: 'Revision list pages' }).getByRole('button', { name: 'Previous page' }).click()
    await expect(choose).toHaveValue('')
    await page.unrouteAll()
    await dialog.getByRole('button', { name: 'Reload revisions', exact: true }).click()
    await selectImageRevision(page, latest.image_revision_id)
    await dialog.getByText('Revision provenance', { exact: true }).click()
    await expect(dialog).toContainText(latest.artifact_hash)
    await selectImageRevision(page, old.image_revision_id)
    await dialog.getByText('Revision provenance', { exact: true }).click()
    await expect(dialog).toContainText(old.artifact_hash)
    await expect(dialog).not.toContainText(latest.artifact_hash)
    await dialog.getByRole('button', { name: 'Input sources', exact: true }).click()
    await dialog.getByText('Frozen record details', { exact: true }).click()
    await expect(dialog).toContainText(fixture.revision)
    await dialog.getByRole('button', { name: 'Relations', exact: true }).click()
    await expect(dialog.getByRole('list', { name: 'Frozen image records' })).toContainText('Inferred relationship')
    await dialog.getByRole('button', { name: 'Frozen membership', exact: true }).click()
    await expect(dialog.getByRole('list', { name: 'Frozen image records' })).toContainText('frozen evidence references')
    const other = await request.post(`${analysisApi}/v1/projects`, { headers: fixture.owner.headers, data: { name: 'Empty image revisions' } })
    expect(other.ok()).toBeTruthy()
    await page.goto(`/projects/${(await other.json()).id}/knowledge`)
    await expect(dialog).toHaveCount(0)
    await page.getByRole('button', { name: 'Image revisions', exact: true }).click()
    await expect(dialog).toContainText('No frozen candidates are available to you.')
    await expect(dialog).not.toContainText(old.image_revision_id)
  } finally { rmSync(source, { recursive: true, force: true }) }
})

for (const revoke of ['source', 'project']) {
  test(`${revoke} revocation during frozen evidence expansion hides the entire candidate`, async ({ page, request }) => {
    const source = analysisSource()
    try {
      const { owner, projectId } = await captureAnalysis(request, source)
      const [candidate] = await frozenRevisions(request, projectId, owner.headers)
      const viewer = await analysisAccount(request)
      const memberUrl = `${analysisApi}/v1/projects/${projectId}/members/${viewer.userId}`
      expect((await request.put(memberUrl, { headers: owner.headers, data: { role: 'viewer' } })).ok()).toBeTruthy()
      if (revoke === 'source') analysisSourcePolicy(projectId, [viewer.userId])
      const dialog = await openImageRevisions(page, projectId, viewer.token)
      await selectImageRevision(page, candidate.image_revision_id)
      let denied: number | null = null
      await page.route((url) => url.pathname.includes(`/revisions/${candidate.image_revision_id}/objects/`), async (route) => {
        if (revoke === 'source') analysisSourcePolicy(projectId, [])
        else expect((await request.delete(memberUrl, { headers: owner.headers })).ok()).toBeTruthy()
        const response = await route.fetch()
        denied = response.status()
        await route.fulfill({ response })
      }, { times: 1 })
      await dialog.getByRole('button', { name: 'Inspect frozen evidence', exact: true }).first().click()
      await expect(dialog.getByRole('alert')).toContainText('Previous content is hidden')
      expect(denied).toBe(403)
      await expect(dialog.getByRole('list', { name: 'Frozen image records' })).toHaveCount(0)
      await expect(dialog.getByRole('combobox', { name: 'Frozen candidate revision' })).toHaveCount(0)
      await expect(dialog.getByRole('region', { name: 'Archived source code' })).toHaveCount(0)
      if (revoke === 'source') analysisSourcePolicy(projectId, [viewer.userId])
      else expect((await request.put(memberUrl, { headers: owner.headers, data: { role: 'viewer' } })).ok()).toBeTruthy()
      await expect(dialog.getByRole('alert')).toBeVisible()
      await dialog.getByRole('button', { name: 'Reload revisions', exact: true }).click()
      await expect(dialog.getByRole('combobox', { name: 'Frozen candidate revision' })).toHaveValue('')
      await expect(dialog.getByRole('list', { name: 'Frozen image records' })).toHaveCount(0)
    } finally { rmSync(source, { recursive: true, force: true }) }
  })
}

test('mismatched frozen membership is hidden and a late response cannot reopen a closed inspector', async ({ page, request }) => {
  const source = analysisSource()
  let release = () => {}
  try {
    const { owner, projectId } = await captureAnalysis(request, source)
    const [candidate] = await frozenRevisions(request, projectId, owner.headers)
    const dialog = await openImageRevisions(page, projectId, owner.token)
    await page.route((url) => url.pathname.endsWith(`/revisions/${candidate.image_revision_id}`)
      && url.searchParams.get('section') === 'members', async (route) => {
      const response = await route.fetch()
      const payload = await response.json()
      payload.items[0].object_id = 'mismatched-object'
      await route.fulfill({ response, json: payload })
    }, { times: 1 })
    await dialog.getByRole('combobox', { name: 'Frozen candidate revision' }).selectOption(candidate.image_revision_id)
    await expect(dialog.getByRole('alert')).toContainText('Previous content is hidden')
    await expect(dialog.getByRole('list', { name: 'Frozen image records' })).toHaveCount(0)
    await dialog.getByRole('button', { name: 'Reload revisions', exact: true }).click()
    await selectImageRevision(page, candidate.image_revision_id)
    let received = () => {}
    const available = new Promise<void>((resolve) => { received = resolve })
    const delayed = new Promise<void>((resolve) => { release = resolve })
    await page.route((url) => url.pathname.includes(`/revisions/${candidate.image_revision_id}/objects/`), async (route) => {
      const response = await route.fetch()
      received()
      await delayed
      await route.fulfill({ response }).catch(() => {}) // Closing the inspector may abort the request.
    }) // StrictMode may abort and remount; hold every matching request.
    await dialog.getByRole('button', { name: 'Inspect frozen evidence', exact: true }).first().click()
    await available
    await expect(dialog).toContainText('Verifying archived source...')
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: 'Image revisions', exact: true }).click()
    release()
    await expect(dialog.getByRole('combobox', { name: 'Frozen candidate revision' })).toHaveValue('')
    await expect(dialog.getByRole('region', { name: 'Archived source code' })).toHaveCount(0)
    await expect(dialog.getByRole('list', { name: 'Frozen image records' })).toHaveCount(0)
  } finally { release(); rmSync(source, { recursive: true, force: true }) }
})
