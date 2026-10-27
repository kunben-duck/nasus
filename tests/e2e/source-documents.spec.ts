import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdirSync, rmSync } from 'node:fs'
import { resolve } from 'node:path'
import { analysisApi, analysisSource, captureAnalysis } from './source-analysis-fixtures'
import { frozenRevisions, jumpToFrozenImageRecord, openImageRevisions, selectImageRevision } from './image-revision-fixtures'

const temporarySources = new Set<string>()
test.afterEach(() => {
  for (const source of temporarySources) rmSync(source, { recursive: true, force: true })
  temporarySources.clear()
})

for (const theme of ['light', 'dark']) {
test(`source-pinned requirement and test projections render with verified evidence beside exweb code (${theme})`, async ({ page, request }) => {
  test.setTimeout(180_000)
  const exweb = process.env.EXWEB_FIXTURE_ROOT
  const source = exweb ? resolve(exweb) : analysisSource()
  if (!exweb) temporarySources.add(source)
  if (exweb) {
    expect(execFileSync('git', ['--no-optional-locks', '-c', 'core.fsmonitor=false', '-C', source, 'rev-parse', 'HEAD'],
      { encoding: 'utf8' }).trim()).toBe('fe5827f6b76f77ef34918d8b452ee823142332dc')
    expect(execFileSync('git', ['--no-optional-locks', '-c', 'core.fsmonitor=false', '-C', source, 'status', '--porcelain', '--untracked-files=all'],
      { encoding: 'utf8' }).trim()).toBe('')
  }
  // The documents are explicitly labelled verification fixtures, not exweb-owned specifications.
  const v = await captureAnalysis(request, source)
  await v.invoke('system_image.sources.register', { source_specs: [
    { source_type: 'us_doc', source_uri: resolve('tests/fixtures/system-image/exweb-requirements.md') },
    { source_type: 'test_asset', source_uri: resolve('tests/fixtures/system-image/exweb-test-cases.csv') },
  ] })
  await v.invoke('system_image.sources.ingest')
  await v.invoke('system_image.context.materialize')
  const imageResponse = await request.get(`${analysisApi}/v1/projects/${v.projectId}/system-image`, { headers: v.owner.headers })
  expect(imageResponse.ok()).toBeTruthy()
  const manifestId = (await imageResponse.json()).source_manifest.manifest_id
  const revisions = await frozenRevisions(request, v.projectId, v.owner.headers)
  expect(revisions).toHaveLength(2)
  const candidate = revisions.find((item) => item.manifest_id === manifestId)!
  expect(candidate).toBeDefined()
  const root = `${analysisApi}/v1/projects/${v.projectId}/system-image/revisions/${candidate.image_revision_id}`
  const inputsResponse = await request.get(`${root}?section=source_members`, { headers: v.owner.headers })
  expect(inputsResponse.ok()).toBeTruthy()
  const inputs = (await inputsResponse.json()).items
  expect(inputs.map((item: { source_type: string }) => item.source_type).sort()).toEqual(['code', 'test_asset', 'us_doc'])
  const allMembers: { kind: string; object_id: string; document_revision_id?: string }[] = []
  for (let offset = 0; offset < candidate.object_count; offset += 100) {
    const response = await request.get(`${root}?section=members&offset=${offset}&limit=100`, { headers: v.owner.headers })
    expect(response.ok()).toBeTruthy()
    allMembers.push(...(await response.json()).items)
  }
  const members = allMembers.filter((item) => item.kind === 'source_document')
  expect(members).toHaveLength(4)
  const references = await v.invoke('system_image.links.propose_references', { image_revision_id: candidate.image_revision_id })
  const referenceId = references.result.object_refs.find((item: string) => item.startsWith('image_reference_proposal:'))!.split(':')[1]
  const referenceQuery = await v.invoke('query.system_image.references.read', { proposal_id: referenceId })
  expect(referenceQuery.result.image_query.operation).toBe('references')
  expect(JSON.stringify(referenceQuery)).not.toContain('US-EXWEB-CHAT')
  const referencePage = await request.get(`${analysisApi}/v1/tool-invocations/${referenceQuery.id}/image-query`, { headers: v.owner.headers })
  expect(referencePage.ok()).toBeTruthy()
  const referenceBody = await referencePage.json()
  expect(referenceBody.image_revision_id).toBe(candidate.image_revision_id)
  expect(referenceBody.assertion_count).toBe(1)
  expect(referenceBody.gap_count).toBe(0)
  expect(referenceBody.items[0]).toMatchObject({ predicate: 'references', status: 'proposed', reference_id: 'US-EXWEB-CHAT' })
  expect(referenceBody.publication).toBe('not_in_image_membership')
  expect((await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme } })).ok()).toBeTruthy()
  await openImageRevisions(page, v.projectId, v.owner.token)
  await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
  const dialog = await selectImageRevision(page, candidate.image_revision_id)
  if (exweb) await expect(dialog).toContainText('725 code entities')
  let visibleOffset = 0
  const desktopViewport = page.viewportSize()!
  for (const member of members) {
    const targetIndex = allMembers.findIndex((item) => item.object_id === member.object_id)
    expect(targetIndex).toBeGreaterThanOrEqual(0)
    if (targetIndex < visibleOffset || targetIndex >= visibleOffset + 25) {
      visibleOffset = Math.floor(targetIndex / 25) * 25
      await jumpToFrozenImageRecord(page, v.projectId, candidate.image_revision_id, visibleOffset)
      await expect(dialog).not.toContainText('Verifying frozen image...')
    }
    const row = dialog.locator(`[data-object-id="${member.object_id}"]`)
    await row.getByRole('button', { name: 'Inspect frozen evidence', exact: true }).click()
    const document = row.getByRole('region', { name: 'Source document projection', exact: true })
    await expect(document).toBeVisible()
    await expect(document).toContainText('Source projection only. References do not prove coverage or acceptance.')
    const apiDocument = await request.get(`${root}/objects/${member.object_id}/document`, { headers: v.owner.headers })
    expect(apiDocument.ok()).toBeTruthy()
    const body = await apiDocument.json()
    expect(body.document.document_revision_id).toBe(member.document_revision_id)
    expect(body.projection.semantic_status).toBe('source_projection_not_approved_specification')
    if (body.projection.parent) {
      await expect(document).toContainText('US-EXWEB-CHAT')
      await expect(document).toContainText('Pending confirmation. Not an approved business oracle.')
      await expect(document).toContainText(body.document.parent_document_revision_id)
      expect(members.some((item) => item.document_revision_id === body.document.parent_document_revision_id)).toBe(true)
    } else {
      await expect(document).toContainText('POST /api/v1/finance/chat/stream')
    }
    const query = await request.post(`${analysisApi}/v1/tool-invocations`, { headers: v.owner.headers, data: {
      conversation_id: v.conversationId, tool_id: 'query.system_image.revisions.document',
      input: { project_id: v.projectId, image_revision_id: candidate.image_revision_id, object_id: member.object_id },
    } })
    expect(query.ok()).toBeTruthy()
    const invocation = await query.json()
    expect(invocation.status).toBe('completed')
    expect(invocation.result.image_query.document_revision_id).toBe(member.document_revision_id)
    expect(JSON.stringify(invocation)).not.toContain('POST /api/v1/finance/chat/stream')
    const expanded = await request.get(`${analysisApi}/v1/tool-invocations/${invocation.id}/image-query`, { headers: v.owner.headers })
    expect(expanded.ok()).toBeTruthy()
    expect(await expanded.json()).toEqual(body)
    if (body.projection.kind === 'test_case') {
      expect(body.projection.references).toEqual(['US-EXWEB-CHAT'])
      await expect(document).toContainText('this fixture has not been executed')
    }
    if (body.projection.kind === 'acceptance_criterion') {
      const recall = document.getByRole('region', { name: 'Related code and test candidates', exact: true })
      await recall.getByRole('button', { name: 'Find related code', exact: true }).click()
      await expect(recall).toContainText('Lexical and explicit-reference recall. Vector and structural recall have not run.', { timeout: 30_000 })
      if (exweb) await expect(recall).toContainText('ChatController')
      const toolResponse = page.waitForResponse((response) => response.request().method() === 'POST'
        && response.url().endsWith('/v1/tool-invocations') && response.request().postDataJSON()?.tool_id === 'query.system_image.links.screened_candidates')
      await recall.getByRole('button', { name: 'Find related tests', exact: true }).click()
      const invoked = await (await toolResponse).json()
      expect(invoked.status).toBe('completed')
      expect(invoked.result.image_query).toMatchObject({ operation: 'screened_link_candidates', semantic_status: 'retrieved_not_asserted',
        review_scope: 'pinned_query_heads_not_live', review_heads: [], excluded_by_review: 0,
        request: { image_revision_id: candidate.image_revision_id, target_object_id: member.object_id, relation: 'asserts', method_version: 'nasus.link-recall.reviewed.v2' } })
      expect(JSON.stringify(invoked)).not.toContain('Chat stream contract fixture')
      await expect(recall.getByRole('list', { name: 'Retrieved candidates', exact: true })).toContainText('Chat stream contract fixture')
      await expect(recall).toContainText('Not asserted')
      await expect(recall).toContainText('Review status is fixed at query time. Find candidates again to refresh; model evaluation checks current reviews.')
      await recall.getByRole('combobox', { name: 'Candidate evidence', exact: true }).selectOption({ index: 2 })
      await expect(recall.getByRole('region', { name: 'Archived reference evidence', exact: true })).toContainText('this fixture has not been executed')
      await recall.scrollIntoViewIfNeeded()
      mkdirSync(resolve('output/playwright'), { recursive: true })
      await page.screenshot({ path: resolve(`output/playwright/exweb-link-candidates-${theme}.png`) })
    }
    if (body.projection.kind === 'business_rule') {
      await expect(document.getByRole('button', { name: 'Find related code', exact: true })).toBeVisible()
      await expect(document.getByRole('button', { name: 'Find related tests', exact: true })).toHaveCount(0)
    }
    await expect(row).toContainText('Verified against archived file and snippet hashes')
    await document.scrollIntoViewIfNeeded()
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    mkdirSync(resolve('output/playwright'), { recursive: true })
    await page.screenshot({ path: resolve(`output/playwright/exweb-${body.projection.kind}-projection-${theme}.png`) })
    await page.setViewportSize({ width: 390, height: 844 })
    await document.scrollIntoViewIfNeeded()
    const bounds = await dialog.boundingBox()
    expect(bounds!.x).toBeGreaterThanOrEqual(0)
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390)
    expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(844)
    const scrollBody = dialog.locator('.evidence-inspector-body')
    expect(await scrollBody.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
    expect(await scrollBody.evaluate((element) => getComputedStyle(element).scrollbarWidth)).toBe('none')
    await page.screenshot({ path: resolve(`output/playwright/exweb-${body.projection.kind}-projection-${theme}-mobile.png`) })
    await page.setViewportSize(desktopViewport)
  }
  const reviews = dialog.locator('.image-reference-reviews')
  await reviews.getByRole('button', { name: 'Find explicit references', exact: true }).click()
  await reviews.getByRole('combobox', { name: 'Reference proposal', exact: true }).selectOption(referenceId)
  await reviews.getByRole('button', { name: 'Inspect reference', exact: true }).click()
  const editor = reviews.locator('.reference-decision-editor')
  await expect(editor).toContainText('Review history: 0 decisions')
  await editor.getByRole('combobox', { name: 'Frozen evidence reference', exact: true }).selectOption({ index: 1 })
  await expect(editor.getByRole('region', { name: 'Archived reference evidence', exact: true })).toContainText('US-EXWEB-CHAT')
  await expect(editor.getByRole('button', { name: 'Record review', exact: true })).toBeDisabled()
  await editor.getByRole('combobox', { name: 'Review decision', exact: true }).selectOption('reject')
  await editor.getByRole('textbox', { name: 'Review reason', exact: true }).fill('Companion fixture only; not approved business coverage.')
  await expect(editor.getByRole('button', { name: 'Record review', exact: true })).toBeDisabled()
  await editor.getByRole('checkbox', { name: 'Confirm this decision for these exact revisions. This does not approve coverage or publication.', exact: true }).check()
  await editor.getByRole('button', { name: 'Record review', exact: true }).click()
  await expect(editor).toContainText('Rejected reference')
  const decisionUrl = `${analysisApi}/v1/projects/${v.projectId}/system-image/reference-proposals/${referenceId}/assertions/${referenceBody.items[0].assertion_id}/decisions`
  const first = await request.get(decisionUrl, { headers: v.owner.headers })
  expect(first.ok()).toBeTruthy()
  const firstBody = await first.json()
  expect(firstBody.total).toBe(1)
  expect(firstBody.items[0].decision).toBe('reject')
  const reviewQuery = await v.invoke('query.system_image.links.decisions', { proposal_id: referenceId, assertion_id: referenceBody.items[0].assertion_id })
  expect(reviewQuery.result.image_query.head_decision_id).toBe(firstBody.head_decision_id)
  expect(JSON.stringify(reviewQuery.result)).not.toContain('Companion fixture')
  const freezeForm = editor.locator('.freeze-reference-review')
  await expect(freezeForm.getByRole('button', { name: 'Freeze as new candidate', exact: true })).toBeDisabled()
  await freezeForm.getByRole('checkbox').check()
  await freezeForm.getByRole('button', { name: 'Freeze as new candidate', exact: true }).click()
  await expect(freezeForm.getByRole('status')).toContainText('Candidate frozen.')
  const frozenRevisionId = await freezeForm.getByRole('status').locator('code').innerText()
  const frozenReviewUrl = `${analysisApi}/v1/projects/${v.projectId}/system-image/revisions/${frozenRevisionId}?section=assertion_members`
  const frozenReviewResponse = await request.get(frozenReviewUrl, { headers: v.owner.headers })
  expect(frozenReviewResponse.ok()).toBeTruthy()
  const frozenReview = await frozenReviewResponse.json()
  expect(frozenReview.revision.parent_revision_id).toBe(candidate.image_revision_id)
  expect(frozenReview.items[0]).toMatchObject({ decision: 'reject', decision_id: firstBody.head_decision_id, predicate: 'references' })
  await editor.getByRole('combobox', { name: 'Review decision', exact: true }).selectOption('defer')
  await editor.getByRole('textbox', { name: 'Review reason', exact: true }).fill('Await real requirement owner review.')
  await editor.getByRole('checkbox', { name: 'Confirm this decision for these exact revisions. This does not approve coverage or publication.', exact: true }).check()
  await editor.getByRole('button', { name: 'Record review', exact: true }).click()
  await expect(editor).toContainText('Review history: 2 decisions')
  await expect(editor).toContainText('Rejected reference')
  await expect(editor).toContainText('Deferred reference')
  const historical = await request.get(`${analysisApi}/v1/tool-invocations/${reviewQuery.id}/image-query`, { headers: v.owner.headers })
  expect(await historical.json()).toEqual(firstBody)
  const frozen = await request.get(`${analysisApi}/v1/tool-invocations/${referenceQuery.id}/image-query`, { headers: v.owner.headers })
  expect(await frozen.json()).toEqual(referenceBody)
  expect(await (await request.get(frozenReviewUrl, { headers: v.owner.headers })).json()).toEqual(frozenReview)
  await editor.scrollIntoViewIfNeeded()
  await page.screenshot({ path: resolve(`output/playwright/exweb-reference-review-${theme}.png`) })
  await page.setViewportSize({ width: 390, height: 844 })
  await editor.scrollIntoViewIfNeeded()
  expect(await dialog.locator('.evidence-inspector-body').evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
  await page.screenshot({ path: resolve(`output/playwright/exweb-reference-review-${theme}-mobile.png`) })
  await page.setViewportSize(desktopViewport)
  await page.reload()
  await page.getByRole('button', { name: 'Image revisions', exact: true }).click()
  await selectImageRevision(page, candidate.image_revision_id)
  await reviews.getByRole('combobox', { name: 'Reference proposal', exact: true }).selectOption(referenceId)
  await reviews.getByRole('button', { name: 'Inspect reference', exact: true }).click()
  await expect(editor).toContainText('Review history: 2 decisions')
  await expect(editor).toContainText('Rejected reference')
  await expect(editor).toContainText('Deferred reference')
  await selectImageRevision(page, frozenRevisionId)
  await dialog.getByRole('button', { name: 'Frozen reviews', exact: true }).click()
  await expect(dialog.getByRole('list', { name: 'Frozen image records' })).toContainText('Rejected reference')
  await expect(dialog.getByRole('list', { name: 'Frozen image records' })).not.toContainText('Deferred reference')
  await page.screenshot({ path: resolve(`output/playwright/exweb-frozen-review-${theme}.png`) })
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await dialog.locator('.evidence-inspector-body').evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
  await page.screenshot({ path: resolve(`output/playwright/exweb-frozen-review-${theme}-mobile.png`) })
})
}
