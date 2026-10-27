import { expect, test } from '@playwright/test'
import { rmSync } from 'node:fs'
import { analysisSource, captureAnalysis } from './source-analysis-fixtures'
import { frozenRevisions, nextFrozenImagePage, openImageRevisions, selectImageRevision } from './image-revision-fixtures'

test('content paging keeps image-level panels mounted while old records stay hidden until verification', async ({ page, request }) => {
  const source = analysisSource()
  let release: (() => void) | undefined
  try {
    const fixture = await captureAnalysis(request, source)
    const [image] = await frozenRevisions(request, fixture.projectId, fixture.owner.headers)
    const path = `/v1/projects/${fixture.projectId}/system-image/revisions/${image.image_revision_id}`
    let proposals = 0
    page.on('request', (req) => { if (new URL(req.url()).pathname === `${path}/reference-proposals`) proposals++ })
    const dialog = await openImageRevisions(page, fixture.projectId, fixture.owner.token)
    await selectImageRevision(page, image.image_revision_id)
    const records = dialog.getByRole('list', { name: 'Frozen image records' })
    await expect(records).toBeVisible()
    await expect(dialog.getByRole('combobox', { name: 'Reference proposal', exact: true })).toBeVisible()
    // Development StrictMode may mount twice. Paging must not add any reads.
    const initialProposals = proposals
    expect(initialProposals).toBeGreaterThan(0)
    const first = await records.locator(':scope > li').first().getAttribute('data-object-id')
    let started!: () => void
    const pending = new Promise<void>((resolve) => { started = resolve })
    const gate = new Promise<void>((resolve) => { release = resolve })
    await page.route((url) => url.pathname === path && url.searchParams.get('section') === 'objects'
      && url.searchParams.get('offset') === '25', async (route) => {
      started()
      await gate
      await route.continue()
    })
    const moving = nextFrozenImagePage(page, fixture.projectId, image.image_revision_id, 25)
    await pending
    await expect(records).toBeHidden()
    await expect(dialog.getByRole('status')).toContainText('Verifying frozen image...')
    release()
    await moving
    await expect(records).toBeVisible()
    await expect(records.locator(':scope > li').first()).not.toHaveAttribute('data-object-id', first!)
    await expect(dialog.getByRole('combobox', { name: 'Reference proposal', exact: true })).toBeVisible()
    expect(proposals).toBe(initialProposals)
    await page.unrouteAll()
    await dialog.getByRole('group', { name: 'Revision content pages' }).getByRole('button', { name: 'Previous page' }).click()
    await expect(records.locator(':scope > li').first()).toHaveAttribute('data-object-id', first!)
    expect(proposals).toBe(initialProposals)
  } finally {
    release?.()
    rmSync(source, { recursive: true, force: true })
  }
})
