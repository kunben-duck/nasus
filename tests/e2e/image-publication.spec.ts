import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { analysisApi, analysisSource, captureAnalysis } from './source-analysis-fixtures'
import { frozenRevisions, openImageRevisions, selectImageRevision } from './image-revision-fixtures'

for (const theme of ['light', 'dark']) {
test(`review and publish an exact knowledge snapshot without changing quality authority (${theme})`, async ({ page, request }) => {
  test.setTimeout(240_000)
  const exweb = process.env.EXWEB_FIXTURE_ROOT
  const source = exweb ? resolve(exweb) : analysisSource()
  if (exweb) {
    const git = (...args: string[]) => execFileSync('git', ['--no-optional-locks', '-c', 'core.fsmonitor=false', '-C', source, ...args], { encoding: 'utf8' }).trim()
    expect(git('rev-parse', 'HEAD')).toBe('fe5827f6b76f77ef34918d8b452ee823142332dc')
    expect(git('status', '--porcelain', '--untracked-files=all')).toBe('')
  }
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  try {
    const v = await captureAnalysis(request, source)
    const image = (await frozenRevisions(request, v.projectId, v.owner.headers))[0]
    if (exweb) expect(image.code_member_count).toBe(725)
    expect((await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme } })).ok()).toBeTruthy()
    let dialog = await openImageRevisions(page, v.projectId, v.owner.token)
    await selectImageRevision(page, image.image_revision_id)
    let panel = dialog.getByRole('region', { name: 'Image publication', exact: true })
    await panel.getByRole('button', { name: 'Inspect image publication', exact: true }).click()
    await panel.getByRole('combobox', { name: 'Publication target baseline', exact: true }).selectOption(image.baseline_id)
    await expect(panel).toContainText('No published knowledge head')
    await expect(panel).toContainText('Business expectations, test coverage, generation and release remain separately governed.')
    const record = panel.getByRole('button', { name: 'Record publication review', exact: true })
    const reviewConsent = panel.getByRole('checkbox', { name: 'I confirm this exact image, target baseline, current head and review decision.', exact: true })
    await expect(record).toBeDisabled()
    await panel.getByRole('textbox', { name: 'Review reason', exact: true }).fill('Static code fixture, not exweb maintainer or business approval')
    await reviewConsent.check()
    await expect(record).toBeEnabled()
    await panel.getByRole('textbox', { name: 'Review reason', exact: true }).fill('Explicit static knowledge fixture review, not business acceptance')
    await expect(reviewConsent).not.toBeChecked()
    await expect(record).toBeDisabled()
    await reviewConsent.check()
    const reviewed = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/confirm'), { timeout: 60_000 })
    await record.click()
    expect((await (await reviewed).json()).status).toBe('completed')
    await expect(panel).toContainText('Publication approved')
    const publish = panel.getByRole('button', { name: 'Publish knowledge snapshot', exact: true })
    await expect(publish).toBeDisabled()
    await panel.getByRole('checkbox', { name: 'I confirm moving this baseline head to the reviewed image. This does not approve a release.', exact: true }).check()
    let writes = 0
    page.on('request', (r) => {
      if (r.method() === 'POST' && r.url().endsWith('/v1/tool-invocations') && r.postDataJSON()?.tool_id === 'baseline.promote') writes++
    })
    const published = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/v1/tool-invocations')
      && r.request().postDataJSON()?.tool_id === 'baseline.promote', { timeout: 60_000 })
    await publish.click()
    const result = await (await published).json()
    expect(result.status).toBe('completed')
    expect(result.input_payload).toMatchObject({ image_revision_id: image.image_revision_id, image_artifact_hash: image.artifact_hash,
      target_baseline_id: image.baseline_id, expected_head_id: null, policy_revision: 'nasus.image-publication.v1' })
    await expect(panel).toContainText('This exact image is the published knowledge head, not a quality approval.')
    expect(writes).toBe(1)
    const url = `${analysisApi}/v1/projects/${v.projectId}/system-image/publications`
    const headResponse = await request.get(url, { headers: v.owner.headers, params: { baseline_id: image.baseline_id } })
    expect(headResponse.ok()).toBeTruthy()
    const state = await headResponse.json()
    expect(state.items).toHaveLength(1)
    expect(state.head).toMatchObject({ image_revision_id: image.image_revision_id, image_artifact_hash: image.artifact_hash,
      sequence: 1, previous_publication_id: null, manifest_id: image.manifest_id, manifest_hash: image.manifest_hash,
      quality_generation_authorized: false, release_authorized: false })
    expect(state.items[0]).toEqual(state.head)
    const currentResponse = await request.get(`${analysisApi}/v1/projects/${v.projectId}/system-image`, { headers: v.owner.headers })
    expect(currentResponse.ok()).toBeTruthy()
    const current = await currentResponse.json()
    expect(current.read_state).toMatchObject({ mode: 'published', pin: { publication_id: state.head.publication_id,
      image_revision_id: image.image_revision_id, image_artifact_hash: image.artifact_hash, quality_generation_authorized: false } })
    expect(current.source_manifest.manifest_id).toBe(image.manifest_id)
    expect(current.objects.length).toBe(image.object_count)
    const draftResponse = await request.get(`${analysisApi}/v1/projects/${v.projectId}/system-image?view=working`, { headers: v.owner.headers })
    expect((await draftResponse.json()).read_state.mode).toBe('working_draft')
    expect((await frozenRevisions(request, v.projectId, v.owner.headers))[0]).toEqual(image)
    await page.reload()
    await expect(page.getByTestId('published-image-state')).toContainText(image.image_revision_id)
    await page.getByRole('button', { name: 'Image revisions', exact: true }).click()
    dialog = await selectImageRevision(page, image.image_revision_id)
    panel = dialog.getByRole('region', { name: 'Image publication', exact: true })
    await panel.getByRole('button', { name: 'Inspect image publication', exact: true }).click()
    await panel.getByRole('combobox', { name: 'Publication target baseline', exact: true }).selectOption(image.baseline_id)
    await expect(panel).toContainText('This exact image is the published knowledge head, not a quality approval.')
    await page.setViewportSize({ width: 390, height: 844 })
    await panel.scrollIntoViewIfNeeded()
    expect(await dialog.evaluate((node) => node.scrollWidth <= node.clientWidth + 1)).toBe(true)
    mkdirSync(resolve('output/playwright'), { recursive: true })
    await page.screenshot({ path: resolve(`output/playwright/image-publication-${theme}-mobile.png`) })
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    await page.getByTestId('published-image-state').scrollIntoViewIfNeeded()
    await expect(page.getByTestId('published-image-state')).toContainText(image.artifact_hash)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
    await page.screenshot({ path: resolve(`output/playwright/published-image-read-${theme}-mobile.png`) })
    expect(errors).toEqual([])
    if (exweb) writeFileSync(resolve(`output/playwright/exweb-publication-${theme}.json`), JSON.stringify({
      repository: 'https://github.com/kunben-duck/exweb.git', revision: 'fe5827f6b76f77ef34918d8b452ee823142332dc',
      verified_at: new Date().toISOString(), target_executed: false, external_model_called: false,
      approval_basis: 'explicit_test_reviewer_not_exweb_maintainer', code_member_count: image.code_member_count, head: state.head,
      source_artifact_unchanged: true, page_reload_restored_head: true,
      current_api_uses_published_image: true, explicit_working_draft_available: true, knowledge_page_displays_image_pin: true,
    }, null, 2))
  } finally { if (!exweb) rmSync(source, { recursive: true, force: true }) }
})
}
