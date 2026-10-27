import { expect, test, type Request } from '@playwright/test'
import { rmSync } from 'node:fs'
import { analysisApi, analysisSource, captureAnalysis } from './source-analysis-fixtures'
import { frozenRevisions, openImageRevisions, selectImageRevision } from './image-revision-fixtures'

const tooLarge = { detail: { error: { code: 'image_page_too_large', message: 'Request fewer items; page exceeds 64 KiB.' } } }

test('access revalidation hides frozen content but preserves the selected page until denied', async ({ page, request }) => {
  const source = analysisSource()
  let releaseList: (() => void) | undefined
  try {
    const { owner, projectId } = await captureAnalysis(request, source)
    const [candidate] = await frozenRevisions(request, projectId, owner.headers)
    const dialog = await openImageRevisions(page, projectId, owner.token)
    await selectImageRevision(page, candidate.image_revision_id)
    const records = dialog.getByRole('list', { name: 'Frozen image records' })
    const pager = dialog.getByRole('group', { name: 'Revision content pages' })
    await pager.getByRole('button', { name: 'Next page' }).click()
    await expect(pager).toContainText('Page 2')
    const ids = () => records.locator(':scope > li').evaluateAll((elements) => elements.map((el) => el.getAttribute('data-object-id')))
    const pageTwo = await ids()
    expect(pageTwo.length).toBeGreaterThan(0)
    let denied = false
    let requests = 0
    const listGate = new Promise<void>((resolve) => { releaseList = resolve })
    await page.route((url) => url.pathname === `/v1/projects/${projectId}/system-image/revisions`, async (route) => {
      requests += 1
      await listGate
      if (denied) await route.fulfill({ status: 403, json: { detail: { error: { code: 'source_access_denied', message: 'Revoked' } } } })
      else await route.fulfill({ response: await route.fetch() })
    })
    const refocus = () => page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
      window.dispatchEvent(new Event('visibilitychange'))
      Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
      window.dispatchEvent(new Event('visibilitychange'))
      Reflect.deleteProperty(document, 'visibilityState')
    })
    await refocus()
    await expect.poll(() => requests).toBe(1)
    await expect(dialog.getByRole('status').filter({ hasText: 'Checking source access' })).toBeVisible()
    await expect(records).toBeHidden()
    await expect(pager).toBeHidden()
    releaseList!()
    await expect(pager).toContainText('Page 2')
    await expect.poll(ids).toEqual(pageTwo)
    denied = true
    await refocus()
    await expect(dialog.getByRole('alert')).toContainText('Previous content is hidden')
    await expect(records).toHaveCount(0)
    await expect(dialog.getByRole('combobox', { name: 'Frozen candidate revision', exact: true })).toHaveCount(0)
    expect(requests).toBe(2)
  } finally {
    releaseList?.()
    await page.unrouteAll({ behavior: 'ignoreErrors' })
    rmSync(source, { recursive: true, force: true })
  }
})

test('bounded frozen reads shrink both joined windows and preserve variable page history', async ({ page, request }) => {
  const source = analysisSource()
  try {
    const { owner, projectId } = await captureAnalysis(request, source)
    const [candidate] = await frozenRevisions(request, projectId, owner.headers)
    const path = `/v1/projects/${projectId}/system-image/revisions/${candidate.image_revision_id}`
    const response = await request.get(`${analysisApi}${path}?section=objects&limit=25`, { headers: owner.headers })
    expect(response.ok()).toBeTruthy()
    const expected = (await response.json()).items.map((item: { id: string }) => item.id)
    const reads: { section: string; offset: number; limit: number; request: Request }[] = []
    const aborted = new Set<Request>()
    page.on('requestfailed', (sent) => {
      if (sent.failure()?.errorText === 'net::ERR_ABORTED') aborted.add(sent)
    })
    const activeReads = () => reads.filter((item) => !aborted.has(item.request))
      .map(({ section, offset, limit }) => ({ section, offset, limit }))
    let rejectAll = false
    let revalidatedDuringRead = false
    // Use real frozen objects/members, with a smaller transport budget fixture.
    await page.route((url) => url.pathname === path, async (route) => {
      const url = new URL(route.request().url())
      const section = url.searchParams.get('section')!
      const offset = Number(url.searchParams.get('offset'))
      const limit = Number(url.searchParams.get('limit'))
      reads.push({ section, offset, limit, request: route.request() })
      if (section === 'members' && limit === 12 && !revalidatedDuringRead) {
        revalidatedDuringRead = true
        const freshList = page.waitForResponse((r) => new URL(r.url()).pathname === path.slice(0, path.lastIndexOf('/')))
        // Reproduce an access-list refresh during a smaller joined read. Keep
        // focus revalidation enabled; it must hide, not destroy, the read owner.
        await page.evaluate(() => {
          Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
          window.dispatchEvent(new Event('visibilitychange'))
          Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
          window.dispatchEvent(new Event('visibilitychange'))
          Reflect.deleteProperty(document, 'visibilityState')
        })
        expect((await freshList).ok()).toBeTruthy()
      }
      const maximum = offset === 0 ? 3 : offset === 3 ? 6 : 1
      if (section === 'members' && (rejectAll || limit > maximum)) {
        await route.fulfill({ status: 413, json: tooLarge })
      } else await route.fulfill({ response: await route.fetch() })
    })
    const dialog = await openImageRevisions(page, projectId, owner.token)
    await selectImageRevision(page, candidate.image_revision_id)
    const records = dialog.getByRole('list', { name: 'Frozen image records' }).locator(':scope > li')
    const pager = dialog.getByRole('group', { name: 'Revision content pages' })
    const ids = () => records.evaluateAll((elements) => elements.map((el) => el.getAttribute('data-object-id')))
    await expect.poll(ids).toEqual(expected.slice(0, 3))
    await expect(pager).toContainText('Page 1')
    expect(revalidatedDuringRead).toBe(true)
    // Discard only observed transport cancellations from StrictMode's initial
    // mount; duplicate fulfilled reads must still fail this exact sequence.
    expect(activeReads().filter((item) => item.section === 'members').map((item) => item.limit)).toEqual([25, 12, 6, 3])
    for (const limit of [25, 12, 6, 3]) expect(activeReads()).toContainEqual({ section: 'objects', offset: 0, limit })
    await pager.getByRole('button', { name: 'Next page' }).click()
    await expect.poll(ids).toEqual(expected.slice(3, 9))
    await expect(pager).toContainText('Page 2')
    await pager.getByRole('button', { name: 'Next page' }).click()
    await expect.poll(ids).toEqual(expected.slice(9, 10))
    await expect(pager).toContainText('Page 3')
    await pager.getByRole('button', { name: 'Previous page' }).click()
    await expect.poll(ids).toEqual(expected.slice(3, 9))
    await expect(pager).toContainText('Page 2')
    await pager.getByRole('button', { name: 'Previous page' }).click()
    await expect.poll(ids).toEqual(expected.slice(0, 3))
    await expect(pager).toContainText('Page 1')
    await expect(pager.getByRole('button', { name: 'Previous page' })).toBeDisabled()
    await dialog.getByRole('button', { name: 'Frozen membership', exact: true }).click()
    await expect.poll(ids).toEqual(expected.slice(0, 3))
    await pager.getByRole('button', { name: 'Next page' }).click()
    await expect.poll(ids).toEqual(expected.slice(3, 9))
    await dialog.getByRole('button', { name: 'Objects', exact: true }).click()
    await expect.poll(ids).toEqual(expected.slice(0, 3))
    rejectAll = true
    reads.length = 0
    await pager.getByRole('button', { name: 'Next page' }).click()
    await expect(dialog.getByRole('alert')).toContainText('Previous content is hidden')
    expect(activeReads().filter((item) => item.section === 'members').map((item) => item.limit)).toEqual([25, 12, 6, 3, 1])
    await expect(records).toHaveCount(0)
  } finally { rmSync(source, { recursive: true, force: true }) }
})

for (const failure of [
  { status: 403, code: 'source_access_denied' },
  { status: 409, code: 'source_access_changed' },
  { status: 502, code: 'image_integrity_failed' },
  { status: 503, code: 'image_artifact_unavailable' },
  { status: 413, code: 'unrelated_size_error' },
]) {
  test(`frozen pagination never shrinks or retries ${failure.code}`, async ({ page, request }) => {
    const source = analysisSource()
    try {
      const { owner, projectId } = await captureAnalysis(request, source)
      const [candidate] = await frozenRevisions(request, projectId, owner.headers)
      const dialog = await openImageRevisions(page, projectId, owner.token)
      await selectImageRevision(page, candidate.image_revision_id)
      const reads: { section: string; limit: number }[] = []
      await page.route((url) => url.pathname.endsWith(`/revisions/${candidate.image_revision_id}`), async (route) => {
        const url = new URL(route.request().url())
        reads.push({ section: url.searchParams.get('section')!, limit: Number(url.searchParams.get('limit')) })
        await route.fulfill({ status: failure.status, json: { detail: { error: { code: failure.code, message: 'Unavailable' } } } })
      })
      await dialog.getByRole('group', { name: 'Revision content pages' }).getByRole('button', { name: 'Next page' }).click()
      await expect(dialog.getByRole('alert')).toContainText('Previous content is hidden')
      await expect(dialog.getByRole('list', { name: 'Frozen image records' })).toHaveCount(0)
      expect(reads.sort((a, b) => a.section.localeCompare(b.section))).toEqual([
        { section: 'members', limit: 25 }, { section: 'objects', limit: 25 },
      ])
    } finally { rmSync(source, { recursive: true, force: true }) }
  })
}

for (const nextOffset of [0, 100000, null]) {
  test(`frozen pagination rejects a non-progressing or incorrect cursor ${nextOffset}`, async ({ page, request }) => {
    const source = analysisSource()
    try {
      const { owner, projectId } = await captureAnalysis(request, source)
      const [candidate] = await frozenRevisions(request, projectId, owner.headers)
      const dialog = await openImageRevisions(page, projectId, owner.token)
      await selectImageRevision(page, candidate.image_revision_id)
      const reads: { section: string; limit: number }[] = []
      await page.route((url) => url.pathname.endsWith(`/revisions/${candidate.image_revision_id}`), async (route) => {
        const url = new URL(route.request().url())
        reads.push({ section: url.searchParams.get('section')!, limit: Number(url.searchParams.get('limit')) })
        const response = await route.fetch()
        await route.fulfill({ response, json: { ...await response.json(), next_offset: nextOffset } })
      })
      await dialog.getByRole('group', { name: 'Revision content pages' }).getByRole('button', { name: 'Next page' }).click()
      await expect(dialog.getByRole('alert')).toContainText('Previous content is hidden')
      await expect(dialog.getByRole('list', { name: 'Frozen image records' })).toHaveCount(0)
      expect(reads.sort((a, b) => a.section.localeCompare(b.section))).toEqual([
        { section: 'members', limit: 25 }, { section: 'objects', limit: 25 },
      ])
    } finally { rmSync(source, { recursive: true, force: true }) }
  })
}
