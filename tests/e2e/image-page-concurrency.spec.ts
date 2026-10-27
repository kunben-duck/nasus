import { expect, test } from '@playwright/test'
import { rmSync } from 'node:fs'
import { analysisSource, captureAnalysis } from './source-analysis-fixtures'
import { frozenRevisions, openImageRevisions, selectImageRevision } from './image-revision-fixtures'

test('object and membership windows read concurrently but neither can display an incomplete pair', async ({ page, request }) => {
  const source = analysisSource()
  const releases: (() => void)[] = []
  try {
    const fixture = await captureAnalysis(request, source)
    const [image] = await frozenRevisions(request, fixture.projectId, fixture.owner.headers)
    const path = `/v1/projects/${fixture.projectId}/system-image/revisions/${image.image_revision_id}`
    const dialog = await openImageRevisions(page, fixture.projectId, fixture.owner.token)
    await selectImageRevision(page, image.image_revision_id)
    const records = dialog.getByRole('list', { name: 'Frozen image records' })
    const first = await records.locator(':scope > li').first().getAttribute('data-object-id')
    const gates = ['objects', 'members'].map(() => new Promise<void>((resolve) => { releases.push(resolve) }))
    const started: string[] = []
    const completed: string[] = []
    await page.route((url) => url.pathname === path && url.searchParams.get('offset') === '25', async (route) => {
      const section = new URL(route.request().url()).searchParams.get('section')!
      const index = ['objects', 'members'].indexOf(section)
      expect(index).toBeGreaterThanOrEqual(0)
      started.push(section)
      await gates[index]
      await route.fulfill({ response: await route.fetch() })
      completed.push(section)
    })
    await dialog.getByRole('group', { name: 'Revision content pages' }).getByRole('button', { name: 'Next page' }).click()
    await expect.poll(() => [...started].sort()).toEqual(['members', 'objects'])
    await expect(records).toHaveCount(0)
    releases[0]()
    await expect.poll(() => completed).toEqual(['objects'])
    await expect(records).toHaveCount(0)
    await expect(dialog.getByRole('status')).toContainText('Verifying frozen image...')
    releases[1]()
    await expect(records).toBeVisible()
    await expect(records.locator(':scope > li').first()).not.toHaveAttribute('data-object-id', first!)
    expect(started.length).toBe(2)
    expect(completed.sort()).toEqual(['members', 'objects'])
  } finally {
    releases.forEach((release) => release())
    await page.unrouteAll({ behavior: 'ignoreErrors' })
    rmSync(source, { recursive: true, force: true })
  }
})
