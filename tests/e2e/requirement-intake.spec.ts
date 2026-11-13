import { expect, test } from '@playwright/test'
import { mkdirSync, rmSync } from 'node:fs'
import { resolve } from 'node:path'
import { analysisApi, analysisSource, captureAnalysis } from './source-analysis-fixtures'
import { frozenRevisions } from './image-revision-fixtures'

for (const theme of ['light', 'dark']) test(`requirement intake revisions, refresh and original-command recovery (${theme})`, async ({ page, request }) => {
  test.setTimeout(240_000)
  const source = analysisSource(), errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  try {
    const v = await captureAnalysis(request, source)
    const image = (await frozenRevisions(request, v.projectId, v.owner.headers))[0]
    const publicationRoot = `${analysisApi}/v1/projects/${v.projectId}/system-image/publications`
    const params = { image_revision_id: image.image_revision_id, image_artifact_hash: image.artifact_hash, target_baseline_id: image.baseline_id }
    const preview = await (await request.get(`${publicationRoot}/preview`, { headers: v.owner.headers, params })).json()
    const review = await v.invoke('system_image.revisions.review_publication', {
      ...preview.target, expected_preview_digest: preview.preview_digest, expected_review_id: null,
      decision: 'approve', reason: 'Fixture image review, not requirement approval',
    }, 'waiting_confirmation')
    expect((await (await request.post(`${analysisApi}/v1/tool-invocations/${review.id}/confirm`, { headers: v.owner.headers })).json()).status).toBe('completed')
    const approved = await (await request.get(`${publicationRoot}/preview`, { headers: v.owner.headers, params })).json()
    await v.invoke('baseline.promote', { ...approved.target, expected_preview_digest: approved.preview_digest, approval_id: approved.review.review_id })
    const { head } = await (await request.get(publicationRoot, { headers: v.owner.headers, params: { baseline_id: image.baseline_id } })).json()
    const creation = await v.invoke('version.create', { name: 'Requirement intake sprint', image_binding: {
      publication_id: head.publication_id, image_revision_id: image.image_revision_id,
      image_artifact_hash: image.artifact_hash, expected_head_id: head.publication_id,
    } })
    const version = creation.result.object_refs.find((ref: string) => ref.startsWith('version:')).slice(8)
    await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme } })
    await page.addInitScript((token) => { localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en') }, v.owner.token)
    await page.goto(`/projects/${v.projectId}/versions?version_id=${version}`)
    const panel = page.getByTestId('requirement-intake')
    await expect(panel.getByText('No requirement drafts in this iteration yet.', { exact: true })).toBeVisible()
    await panel.getByRole('textbox', { name: 'Requirement title', exact: true }).fill('US-001 Article editing')
    await panel.getByRole('textbox', { name: 'Requirement description', exact: true }).fill('Support editing articles')
    const writes: unknown[] = []
    await page.route('**/v1/tool-invocations', async (route) => {
      const payload = route.request().postDataJSON()
      if (payload?.tool_id !== 'quality.requirement.revise') return route.continue()
      writes.push(payload)
      if (writes.length !== 1) return route.continue()
      const result = await route.fetch()
      expect((await result.json()).status).toBe('completed')
      await route.abort('failed')
    })
    await panel.getByRole('button', { name: 'Save draft revision', exact: true }).click()
    await expect(panel).toContainText('Retry the same command')
    await page.reload()
    await panel.getByRole('button', { name: 'Retry original save', exact: true }).click()
    await expect(panel.locator('.requirement-draft')).toHaveCount(1)
    expect(writes).toHaveLength(2)
    expect(writes[1]).toEqual(writes[0])
    await panel.getByRole('button', { name: 'Revise requirement', exact: true }).click()
    await panel.getByRole('textbox', { name: 'Requirement description', exact: true }).fill('Only the author may edit an article')
    await panel.getByRole('button', { name: 'Add clarification answer', exact: true }).click()
    await panel.getByRole('textbox', { name: 'Clarification question', exact: true }).fill('Can another user edit it?')
    await panel.getByRole('textbox', { name: 'Your answer', exact: true }).fill('No; reject without changing the article.')
    await panel.getByRole('button', { name: 'Save draft revision', exact: true }).click()
    await expect(panel.locator('.requirement-draft')).toContainText('Only the author may edit an article')
    await page.reload()
    await expect(panel.locator('.requirement-draft')).toContainText('No; reject without changing the article.')
    await expect(panel).toContainText('request independent confirmation')
    await panel.getByRole('button', { name: 'Revision history', exact: true }).click()
    await expect(panel.locator('.requirement-draft')).toHaveCount(2)
    const response = await request.get(`${analysisApi}/v1/projects/${v.projectId}/versions/${version}/requirements`, { headers: v.owner.headers })
    const revision = (await response.json()).items[0]
    expect(revision.sequence).toBe(2)
    expect(revision.original_text).toBe('Support editing articles')
    expect(revision.generation_authorized).toBe(false)
    await page.setViewportSize({ width: 390, height: 844 })
    await panel.scrollIntoViewIfNeeded()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    mkdirSync(resolve('output/playwright'), { recursive: true })
    await page.screenshot({ path: resolve(`output/playwright/requirement-intake-${theme}.png`), fullPage: true })
    await page.route(`**/versions/${version}/requirements?**`, (route) => route.fulfill({ status: 403,
      contentType: 'application/json', body: JSON.stringify({ error: { message: 'Revoked' } }) }))
    await panel.getByRole('button', { name: 'Reload requirements', exact: true }).click()
    await expect(panel).toContainText('Previous content is hidden.')
    await expect(panel.locator('.requirement-draft')).toHaveCount(0)
    await expect(panel.getByRole('textbox')).toHaveCount(0)
    expect(errors).toEqual([])
  } finally { rmSync(source, { recursive: true, force: true }) }
})
