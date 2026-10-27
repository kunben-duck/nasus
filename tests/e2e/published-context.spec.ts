import { expect, test, type APIRequestContext } from '@playwright/test'
import { mkdirSync, rmSync } from 'node:fs'
import { resolve } from 'node:path'
import { analysisApi, analysisSource, captureAnalysis } from './source-analysis-fixtures'
import { frozenRevisions } from './image-revision-fixtures'

async function publish(request: APIRequestContext, v: Awaited<ReturnType<typeof captureAnalysis>>, previous?: string) {
  const image = (await frozenRevisions(request, v.projectId, v.owner.headers))[0]
  const root = `${analysisApi}/v1/projects/${v.projectId}/system-image/publications`
  const response = await request.get(`${root}/preview`, { headers: v.owner.headers, params: {
    image_revision_id: image.image_revision_id, image_artifact_hash: image.artifact_hash, target_baseline_id: image.baseline_id,
    ...(previous ? { expected_head_id: previous } : {}),
  } })
  expect(response.ok()).toBeTruthy()
  const preview = await response.json()
  const pending = await v.invoke('system_image.revisions.review_publication', { ...preview.target,
    expected_preview_digest: preview.preview_digest, expected_review_id: preview.review?.review_id ?? null,
    decision: 'approve', reason: 'Browser fixture knowledge review, never business authority' }, 'waiting_confirmation')
  const approved = await request.post(`${analysisApi}/v1/tool-invocations/${pending.id}/confirm`, { headers: v.owner.headers })
  expect(approved.ok()).toBeTruthy()
  const done = await approved.json()
  expect(done.status).toBe('completed')
  await v.invoke('baseline.promote', { ...preview.target, expected_preview_digest: preview.preview_digest,
    approval_id: done.result.object_refs[0].split(':')[1] })
  const current = await request.get(root, { headers: v.owner.headers, params: { baseline_id: image.baseline_id } })
  expect(current.ok()).toBeTruthy()
  return (await current.json()).head
}

for (const theme of ['light', 'dark']) {
test(`published context pins survive reload, become stale on head change and reject mismatches (${theme})`, async ({ page, request }) => {
  test.setTimeout(180_000)
  const source = analysisSource(), errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  try {
    const v = await captureAnalysis(request, source)
    const head = await publish(request, v)
    expect((await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme } })).ok()).toBeTruthy()
    await page.addInitScript((token) => { localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en') }, v.owner.token)
    await page.goto(`/projects/${v.projectId}/knowledge`)
    const panel = page.getByRole('region', { name: 'Test-design context packs', exact: true })
    await panel.getByRole('button', { name: 'Inspect published context', exact: true }).click()
    await panel.getByRole('button', { name: 'Preview context', exact: true }).click()
    await expect(panel.getByTestId('context-publication-pin')).toContainText(head.publication_id)
    await expect(panel).toContainText('No mandatory requirements are available.')
    await expect(panel).not.toContainText('This image has not been published.')
    const save = panel.getByRole('button', { name: 'Archive context', exact: true })
    await expect(save).toBeDisabled()
    await panel.getByRole('checkbox', { name: 'I confirm archiving these exact inputs and gaps. This is not generation or execution approval.', exact: true }).check()
    const committed = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/confirm'))
    await save.click()
    const result = await (await committed).json()
    expect(result.status).toBe('completed')
    expect(result.input_payload).toMatchObject({ policy_revision: 'nasus.test-design-context.v4', publication_id: head.publication_id })
    const contextId = result.result.object_refs[0].split(':')[1]
    await expect(panel.getByRole('region', { name: 'Archived context', exact: true })).toContainText(contextId)
    // Real empty-requirement v5 archive validates mixed-policy history rendering.
    // Nonempty indexed recall and native provider calls are covered by PG tests.
    const indexedResponse = await request.get(`${analysisApi}/v1/projects/${v.projectId}/system-image/context-packs/preview`, {
      headers: v.owner.headers, params: { image_revision_id: head.image_revision_id, image_artifact_hash: head.image_artifact_hash,
        publication_id: head.publication_id, policy_revision: 'nasus.test-design-context.v5', retrieval_bindings: '{}' },
    })
    expect(indexedResponse.ok()).toBeTruthy()
    const indexedPreview = await indexedResponse.json()
    expect(indexedPreview.context.required_constraints).toEqual([])
    const indexedPending = await v.invoke('system_image.context.compile', {
      ...indexedPreview.request, expected_input_digest: indexedPreview.input_digest,
    }, 'waiting_confirmation')
    const indexedDone = await request.post(`${analysisApi}/v1/tool-invocations/${indexedPending.id}/confirm`, { headers: v.owner.headers })
    const indexedResult = await indexedDone.json()
    expect(indexedResult.status).toBe('completed')
    const indexedId = indexedResult.result.object_refs[0].split(':')[1]
    const next = await publish(request, v, head.publication_id)
    expect(next.publication_id).not.toBe(head.publication_id)
    await page.reload()
    await expect(page.getByTestId('published-image-state')).toContainText(head.image_revision_id)
    await panel.getByRole('button', { name: 'Inspect published context', exact: true }).click()
    await panel.getByRole('button').filter({ hasText: indexedId }).click()
    await expect(panel).toContainText('Candidates replay a bounded saved search; query selection is not a relevance or coverage guarantee.')
    await expect(panel).toContainText('Structural graph expansion has not been applied to this context.')
    await expect(panel).toContainText('Inputs have changed. This historical pack cannot authorize current generation.')
    await panel.getByRole('button').filter({ hasText: contextId }).click()
    await expect(panel).toContainText('Inputs have changed. This historical pack cannot authorize current generation.')
    await expect(panel.getByTestId('context-publication-pin')).toContainText(head.publication_id)
    await page.setViewportSize({ width: 390, height: 844 })
    await panel.scrollIntoViewIfNeeded()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
    mkdirSync(resolve('output/playwright'), { recursive: true })
    await page.screenshot({ path: resolve(`output/playwright/published-context-${theme}-mobile.png`) })
    await page.route('**/system-image/context-packs/preview?**', async (route) => {
      const response = await route.fetch(), body = await response.json()
      body.context.publication_pin.publication_id = 'not-the-requested-publication'
      await route.fulfill({ response, json: body })
    })
    await panel.getByRole('button', { name: 'Preview context', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('Published context could not be verified.')
    await expect(page.getByTestId('context-publication-pin')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Archive context', exact: true })).toHaveCount(0)
    expect(errors).toEqual([])
  } finally { rmSync(source, { recursive: true, force: true }) }
})
}
