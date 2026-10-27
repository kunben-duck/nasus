import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdirSync, rmSync } from 'node:fs'
import { resolve } from 'node:path'
import { analysisApi, analysisSource, captureAnalysis } from './source-analysis-fixtures'
import { frozenRevisions, openImageRevisions, selectImageRevision } from './image-revision-fixtures'

for (const theme of ['light', 'dark']) {
test(`context packs preserve confirmed requirements and expose stale history (${theme})`, async ({ page, request }) => {
  test.setTimeout(240_000)
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => { if (message.type() === 'error' && /same key|unique.*key/i.test(message.text())) errors.push(message.text()) })
  const exweb = process.env.EXWEB_FIXTURE_ROOT
  const source = exweb ? resolve(exweb) : analysisSource()
  if (exweb) expect(execFileSync('git', ['--no-optional-locks', '-C', source, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim())
    .toBe('fe5827f6b76f77ef34918d8b452ee823142332dc')
  try {
    const v = await captureAnalysis(request, source)
    await v.invoke('system_image.sources.register', { source_specs: [
      { source_type: 'us_doc', source_uri: resolve('tests/fixtures/system-image/exweb-context-requirements.md') },
      { source_type: 'test_asset', source_uri: resolve('tests/fixtures/system-image/exweb-test-cases.csv') },
    ] })
    await v.invoke('system_image.sources.ingest'); await v.invoke('system_image.context.materialize')
    const image = await (await request.get(`${analysisApi}/v1/projects/${v.projectId}/system-image`, { headers: v.owner.headers })).json()
    const target = image.objects.find((item: { type: string }) => item.type === 'SourceAcceptanceCriterion')
    const candidate = (await frozenRevisions(request, v.projectId, v.owner.headers)).find((item) => item.manifest_id === image.source_manifest.manifest_id)!
    const authorityUrl = `${analysisApi}/v1/projects/${v.projectId}/quality/acceptance-specifications`
    const params = { image_revision_id: candidate.image_revision_id, image_artifact_hash: candidate.artifact_hash, object_id: target.id }
    const authority = await (await request.get(authorityUrl, { headers: v.owner.headers, params })).json()
    const oracle = { preconditions: 'Isolated fixture environment', action: 'POST the documented finance chat request',
      observation: 'HTTP Content-Type', expected_result: 'Content-Type includes text/event-stream' }
    const decision = { ...params, basis_digest: authority.basis_digest, expected_previous_revision_id: null,
      policy_revision: authority.policy_revision, decision: 'approve', oracle, authority_basis: 'user_confirmed_requirement', reason: 'Explicit companion fixture, not exweb maintainer approval' }
    const pending = await v.invoke('quality.acceptance_specification.review', decision, 'waiting_confirmation')
    const approved = await (await request.post(`${analysisApi}/v1/tool-invocations/${pending.id}/confirm`, { headers: v.owner.headers })).json()
    expect(approved.status).toBe('completed')
    await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme } })
    let dialog = await openImageRevisions(page, v.projectId, v.owner.token)
    await selectImageRevision(page, candidate.image_revision_id)
    let panel = dialog.getByRole('region', { name: 'Test-design context packs', exact: true })
    const previewContext = async () => {
      const response = page.waitForResponse((r) => r.request().method() === 'GET' && r.url().includes('/context-packs/preview?'), { timeout: 60_000 })
      await panel.getByRole('button', { name: 'Preview context', exact: true }).click()
      expect((await response).ok()).toBeTruthy()
    }
    const readContext = async () => {
      // Confirmation and historical replay are separate HTTP operations. Bound
      // each operation, rather than starting the read deadline before it exists.
      await page.waitForRequest((r) => r.method() === 'GET' && /\/context-packs\/[a-f0-9-]+$/.test(r.url()), { timeout: 60_000 })
      return page.waitForResponse((r) => r.request().method() === 'GET' && /\/context-packs\/[a-f0-9-]+$/.test(r.url()), { timeout: 60_000 })
    }
    await panel.getByRole('button', { name: 'Inspect test-design context' }).click()
    await expect(panel).toContainText('No archived context for this image.')
    await previewContext()
    await expect(panel.getByRole('list', { name: 'Mandatory context constraints' })).toContainText(oracle.expected_result)
    const save = panel.getByRole('button', { name: 'Archive context', exact: true })
    await expect(save).toBeDisabled()
    await panel.getByRole('checkbox').check()
    await expect(save).toBeEnabled()
    await panel.getByRole('spinbutton', { name: 'Context budget ceiling' }).fill('6000')
    await expect(save).toHaveCount(0)
    await previewContext()
    await expect(panel.getByText(/budgeted subpacks; every subpack inherits/)).toBeVisible()
    await expect(save).toBeDisabled()
    await panel.getByRole('checkbox').check()
    let writes = 0
    page.on('request', (req) => { if (req.method() === 'POST' && req.url().endsWith('/v1/tool-invocations') && req.postDataJSON()?.tool_id === 'system_image.context.compile') writes++ })
    const archivedResponse = readContext()
    await save.click()
    const archived = await archivedResponse
    expect(archived.ok()).toBeTruthy()
    await expect(panel.getByRole('region', { name: 'Archived context', exact: true })).toContainText('Inputs unchanged. This draft still does not authorize generation.')
    expect(writes).toBe(1)
    const packsUrl = `${analysisApi}/v1/projects/${v.projectId}/system-image/context-packs`
    const list = await (await request.get(packsUrl, { headers: v.owner.headers, params: { image_revision_id: candidate.image_revision_id, image_artifact_hash: candidate.artifact_hash } })).json()
    expect(list.items).toHaveLength(1)
    const contextId = list.items[0].context_id
    const before = await archived.json()
    expect(before.metadata.context_id).toBe(contextId)
    expect(before.context.schema_version).toBe('nasus.context-bundle.v1')
    expect(before.context.parts.length).toBeGreaterThan(1)
    expect(before.context.required_constraints).toHaveLength(8)
    expect(before.context.parts.flatMap((part: { context: { partition: { target_object_ids: string[] } } }) => part.context.partition.target_object_ids)).toHaveLength(6)
    for (const part of before.context.parts) {
      expect(part.context.partition.global_constraint_ids).toHaveLength(2)
      expect(part.context.budget.used_upper_bound).toBeLessThanOrEqual(6000)
    }
    expect(before.context.required_constraints.find((c: { object_id: string }) => c.object_id === target.id).oracle).toEqual(oracle)
    await panel.getByRole('button', { name: 'Requirement evidence 1', exact: true }).first().click()
    await expect(panel.getByRole('region', { name: 'Archived reference evidence' })).toBeVisible()
    await page.reload()
    await page.getByRole('button', { name: 'Image revisions', exact: true }).click()
    dialog = page.getByRole('dialog', { name: 'Image revisions', exact: true })
    await selectImageRevision(page, candidate.image_revision_id)
    panel = dialog.getByRole('region', { name: 'Test-design context packs', exact: true })
    await panel.getByRole('button', { name: 'Inspect test-design context' }).click()
    const reopenedResponse = readContext()
    await panel.getByRole('button').filter({ hasText: contextId }).click()
    expect((await reopenedResponse).ok()).toBeTruthy()
    await expect(panel.getByRole('region', { name: 'Archived context', exact: true })).toContainText(oracle.expected_result)
    const head = await (await request.get(authorityUrl, { headers: v.owner.headers, params })).json()
    const withdraw = await v.invoke('quality.acceptance_specification.review', { ...decision, expected_previous_revision_id: head.head.revision_id,
      decision: 'withdraw', oracle: null, authority_basis: null, reason: 'Withdraw fixture oracle after archiving' }, 'waiting_confirmation')
    expect((await (await request.post(`${analysisApi}/v1/tool-invocations/${withdraw.id}/confirm`, { headers: v.owner.headers })).json()).status).toBe('completed')
    const staleResponse = readContext()
    await panel.getByRole('button', { name: 'Reload context history' }).click()
    const stale = await staleResponse
    expect(stale.ok()).toBeTruthy()
    await expect(panel).toContainText('Inputs have changed. This historical pack cannot authorize current generation.')
    const after = await stale.json()
    expect(after.context).toEqual(before.context)
    expect(after.current_use.generation_authorized).toBe(false)
    await page.setViewportSize({ width: 390, height: 844 })
    await panel.getByRole('region', { name: 'Archived context', exact: true }).scrollIntoViewIfNeeded()
    await panel.getByRole('region', { name: 'Archived context', exact: true }).locator('.context-partitions > summary').click()
    await expect(panel.getByRole('list', { name: 'Context subpacks' })).toBeVisible()
    expect(await dialog.locator('.evidence-inspector-body').evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true)
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    mkdirSync(resolve('output/playwright'), { recursive: true })
    await page.screenshot({ path: resolve(`output/playwright/context-packs-${theme}-mobile.png`) })
    // Only the final corruption guard mocks a response; all archive and authority
    // commands above use canonical confirmation and the disposable PostgreSQL DB.
    await page.route('**/system-image/context-packs/preview?*', async (route) => {
      const response = await route.fetch(), body = await response.json()
      // A valid top-level scope must not hide a child missing a global rule.
      body.context.parts[0].context.required_constraints = body.context.parts[0].context.required_constraints.filter(
        (item: { kind: string }) => item.kind !== 'business_rule')
      await route.fulfill({ response, json: body })
    })
    await previewContext()
    await expect(dialog.getByRole('alert')).toContainText('Previous content is hidden; reload to check access.')
    await expect(panel).toHaveCount(0)
    expect(errors).toEqual([])
  } finally { if (!exweb) rmSync(source, { recursive: true, force: true }) }
})
}
