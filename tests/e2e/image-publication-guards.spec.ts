import { expect, test } from '@playwright/test'
import { rmSync } from 'node:fs'
import { analysisApi, analysisSource, captureAnalysis } from './source-analysis-fixtures'
import { frozenRevisions, openImageRevisions, selectImageRevision } from './image-revision-fixtures'

test('concurrent publication review requires reload and renewed explicit consent', async ({ page, request }) => {
  const source = analysisSource()
  try {
    const v = await captureAnalysis(request, source)
    const image = (await frozenRevisions(request, v.projectId, v.owner.headers))[0]
    const dialog = await openImageRevisions(page, v.projectId, v.owner.token)
    await selectImageRevision(page, image.image_revision_id)
    const panel = dialog.getByRole('region', { name: 'Image publication', exact: true })
    await panel.getByRole('button', { name: 'Inspect image publication', exact: true }).click()
    const previewResponse = page.waitForResponse((r) => r.url().includes('/publications/preview'))
    await panel.getByRole('combobox', { name: 'Publication target baseline', exact: true }).selectOption(image.baseline_id)
    const preview = await (await previewResponse).json()
    await expect(panel).toContainText('No published knowledge head')
    await panel.getByRole('textbox', { name: 'Review reason', exact: true }).fill('My outdated review')
    const consent = panel.getByRole('checkbox', { name: 'I confirm this exact image, target baseline, current head and review decision.', exact: true })
    await consent.check()
    const pending = await request.post(`${analysisApi}/v1/tool-invocations`, { headers: v.owner.headers, data: {
      tool_id: 'system_image.revisions.review_publication', input: { ...preview.target,
        expected_preview_digest: preview.preview_digest, expected_review_id: null, decision: 'reject', reason: 'Concurrent fixture rejection' },
    } })
    const other = await pending.json()
    expect(other.status).toBe('waiting_confirmation')
    expect((await (await request.post(`${analysisApi}/v1/tool-invocations/${other.id}/confirm`, { headers: v.owner.headers })).json()).status).toBe('completed')
    let writes = 0
    page.on('request', (r) => { if (r.method() === 'POST' && r.url().endsWith('/v1/tool-invocations')) writes++ })
    await panel.getByRole('button', { name: 'Record publication review', exact: true }).click()
    await expect(panel.getByRole('alert')).toHaveText('Publication inputs changed. Reload and review again.')
    await expect(panel.getByRole('button', { name: 'Record publication review', exact: true })).toBeDisabled()
    await panel.getByRole('button', { name: 'Reload publication', exact: true }).click()
    await expect(panel).toContainText('Concurrent fixture rejection')
    await expect(consent).not.toBeChecked()
    await expect(panel.getByRole('button', { name: 'Record publication review', exact: true })).toBeDisabled()
    expect(writes).toBe(1)
    const history = await request.get(`${analysisApi}/v1/projects/${v.projectId}/system-image/publications`,
      { headers: v.owner.headers, params: { baseline_id: image.baseline_id } })
    expect((await history.json()).head).toBeNull()
  } finally { rmSync(source, { recursive: true, force: true }) }
})

test('publication authorization failure hides previously visible image and disables writes', async ({ page, request }) => {
  const source = analysisSource()
  try {
    const v = await captureAnalysis(request, source)
    const image = (await frozenRevisions(request, v.projectId, v.owner.headers))[0]
    const dialog = await openImageRevisions(page, v.projectId, v.owner.token)
    await selectImageRevision(page, image.image_revision_id)
    const panel = dialog.getByRole('region', { name: 'Image publication', exact: true })
    await panel.getByRole('button', { name: 'Inspect image publication', exact: true }).click()
    await panel.getByRole('combobox', { name: 'Publication target baseline', exact: true }).selectOption(image.baseline_id)
    await expect(panel).toContainText('No published knowledge head')
    let writes = 0
    page.on('request', (r) => { if (r.method() === 'POST' && r.url().endsWith('/v1/tool-invocations')) writes++ })
    await page.route('**/system-image/publications/preview?*', (route) => route.fulfill({ status: 403,
      json: { detail: { error: { code: 'source_access_denied', message: 'Revoked fixture source' } } } }))
    await panel.getByRole('button', { name: 'Reload publication', exact: true }).click()
    await expect(dialog.getByRole('alert')).toContainText('Previous content is hidden')
    await expect(dialog.getByRole('list', { name: 'Frozen image records' })).not.toBeVisible()
    await expect(panel).not.toBeVisible()
    expect(writes).toBe(0)
  } finally { rmSync(source, { recursive: true, force: true }) }
})
