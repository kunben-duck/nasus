import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdirSync, rmSync } from 'node:fs'
import { resolve } from 'node:path'
import { analysisApi, analysisSource, captureAnalysis } from './source-analysis-fixtures'
import { frozenRevisions, openImageRevisions, selectImageRevision } from './image-revision-fixtures'

for (const theme of ['light', 'dark']) {
for (const kind of ['AC', 'business rule']) {
test(`source ${kind} needs independent authority confirmation and supports withdrawal (${theme})`, async ({ page, request }) => {
  const rule = kind === 'business rule'
  const noun = rule ? 'business rule' : 'requirement'
  const title = rule ? 'Business rule' : 'Requirement'
  test.setTimeout(180_000)
  const renderErrors: string[] = []
  page.on('pageerror', (error) => renderErrors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error' && /same key|unique.*key/i.test(message.text())) renderErrors.push(message.text())
  })
  const exweb = process.env.EXWEB_FIXTURE_ROOT
  const source = exweb ? resolve(exweb) : analysisSource()
  if (exweb) expect(execFileSync('git', ['--no-optional-locks', '-C', source, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim())
    .toBe('fe5827f6b76f77ef34918d8b452ee823142332dc')
  try {
    const v = await captureAnalysis(request, source)
    await v.invoke('system_image.sources.register', { source_specs: [
      { source_type: 'us_doc', source_uri: resolve('tests/fixtures/system-image/exweb-requirements.md') },
      { source_type: 'test_asset', source_uri: resolve('tests/fixtures/system-image/exweb-test-cases.csv') },
    ] })
    await v.invoke('system_image.sources.ingest'); await v.invoke('system_image.context.materialize')
    const image = await (await request.get(`${analysisApi}/v1/projects/${v.projectId}/system-image`, { headers: v.owner.headers })).json()
    const target = image.objects.find((item: { type: string }) => item.type === (rule ? 'SourceBusinessRule' : 'SourceAcceptanceCriterion'))
    const candidate = (await frozenRevisions(request, v.projectId, v.owner.headers)).find((item) => item.manifest_id === image.source_manifest.manifest_id)!
    const members: { object_id: string }[] = []
    for (let offset = 0; offset < candidate.object_count; offset += 100) {
      const response = await request.get(`${analysisApi}/v1/projects/${v.projectId}/system-image/revisions/${candidate.image_revision_id}?section=members&offset=${offset}&limit=100`, { headers: v.owner.headers })
      expect(response.ok()).toBeTruthy(); members.push(...(await response.json()).items)
    }
    const index = members.findIndex((item) => item.object_id === target.id)
    expect(index).toBeGreaterThanOrEqual(0)
    await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme } })
    const dialog = await openImageRevisions(page, v.projectId, v.owner.token)
    await selectImageRevision(page, candidate.image_revision_id)
    for (let i = 0; i < Math.floor(index / 25); i++) {
      await dialog.getByRole('group', { name: 'Revision content pages' }).getByRole('button', { name: 'Next page', exact: true }).click()
      await expect(dialog.getByRole('list', { name: 'Frozen image records' })).toBeVisible()
    }
    const row = dialog.locator(`[data-object-id="${target.id}"]`)
    await row.getByRole('button', { name: 'Inspect frozen evidence', exact: true }).click()
    const authority = row.getByRole('region', { name: `${title} authority`, exact: true })
    await authority.getByRole('button', { name: `Inspect ${noun} authority` }).click()
    await expect(authority).toContainText(`Unapproved ${noun}`)
    const save = authority.getByRole('button', { name: 'Record authority decision' })
    await expect(save).toBeDisabled()
    await authority.getByRole('textbox', { name: 'Oracle preconditions', exact: true }).fill(rule ? 'Unauthenticated caller in isolated fixture environment' : 'Isolated authorized test environment')
    await authority.getByRole('textbox', { name: 'Action under test', exact: true }).fill('POST /api/v1/finance/chat/stream')
    await authority.getByRole('textbox', { name: 'Observable output', exact: true }).fill(rule ? 'HTTP response status' : 'HTTP response content type')
    await authority.getByRole('textbox', { name: 'Required result', exact: true }).fill(rule ? '401' : 'text/event-stream')
    await authority.getByRole('textbox', { name: 'Review reason', exact: true }).fill('Companion fixture review, not exweb maintainer approval')
    await expect(save).toBeDisabled()
    await authority.getByRole('checkbox').check()
    await expect(save).toBeEnabled()
    const expectedResult = rule ? 'HTTP status is 401; no chat content is disclosed' : 'Content-Type includes text/event-stream'
    await authority.getByRole('textbox', { name: 'Required result', exact: true }).fill(expectedResult)
    await expect(authority.getByRole('checkbox')).not.toBeChecked()
    await expect(save).toBeDisabled()
    await authority.getByRole('checkbox').check()
    await save.click()
    await expect(authority).toContainText(`${title} authority recorded. Other images do not inherit it.`)
    await expect(authority).toContainText(`Approved ${noun}`)
    await expect(row).toContainText('Pending confirmation. Not an approved business oracle.') // Source projection remains unapproved.
    const apiPath = rule ? 'business-rules' : 'acceptance-specifications'
    const url = `${analysisApi}/v1/projects/${v.projectId}/quality/${apiPath}`
    const params = { image_revision_id: candidate.image_revision_id, image_artifact_hash: candidate.artifact_hash, object_id: target.id }
    const approved = await (await request.get(url, { headers: v.owner.headers, params })).json()
    expect(approved.head.status).toBe('approved')
    expect(approved.head.authority_actor).toBe(v.owner.userId)
    expect(approved.current.oracle.expected_result).toBe(expectedResult)
    expect(approved.current.authority_basis).toBe(rule ? 'user_confirmed_business_rule' : 'user_confirmed_requirement')
    await page.setViewportSize({ width: 390, height: 844 })
    await authority.locator('.semantic-review-head').scrollIntoViewIfNeeded()
    expect(await dialog.locator('.evidence-inspector-body').evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true)
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    mkdirSync(resolve('output/playwright'), { recursive: true })
    await page.screenshot({ path: resolve(`output/playwright/${rule ? 'business-rule' : 'acceptance'}-authority-${theme}-mobile.png`) })
    await authority.getByRole('button', { name: 'Reload authority' }).click()
    await expect(authority.getByRole('combobox')).toBeEnabled()
    await authority.getByRole('combobox').selectOption('withdraw')
    await authority.getByRole('textbox', { name: 'Review reason', exact: true }).fill('Withdraw fixture authority')
    await authority.getByRole('checkbox').check()
    await save.click()
    await expect(authority).toContainText(`Withdrawn ${noun}`)
    const current = await (await request.get(url, { headers: v.owner.headers, params })).json()
    expect(current.current.oracle).toBeNull()
    expect(current.head.previous_revision_id).toBe(approved.head.revision_id)
    const historical = await (await request.get(`${url}/${approved.head.revision_id}`, { headers: v.owner.headers })).json()
    expect(historical.oracle).toEqual(approved.current.oracle)
    // Only this corruption check mocks a response; creation, confirmation,
    // persistence, withdrawal and historical read above use the real API/PG.
    await page.route(`**/quality/${apiPath}?*`, async (route) => {
      const response = await route.fetch(), body = await response.json()
      body.basis.image_revision_id = 'wrong-image'
      await route.fulfill({ response, json: body })
    })
    await authority.getByRole('button', { name: 'Reload authority' }).click()
    await expect(dialog.getByRole('alert')).toContainText('Previous content is hidden; reload to check access.')
    await expect(dialog.getByRole('list', { name: 'Frozen image records' })).toHaveCount(0)
    expect(renderErrors).toEqual([])
  } finally { if (!exweb) rmSync(source, { recursive: true, force: true }) }
})
}
}
