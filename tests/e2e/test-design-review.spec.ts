import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdirSync, rmSync } from 'node:fs'
import { resolve } from 'node:path'
import { analysisAccount, analysisApi, analysisSource } from './source-analysis-fixtures'
import { generationScopeFixture } from './test-design-generation-fixtures'
import { installMappingProtocol } from './test-design-mapping-fixtures'
import { mappingDigest } from '../../apps/portal/src/domains/quality-loop/testDesignMappingValidation'
import { verifyReviewDraftPage } from '../../apps/portal/src/domains/quality-loop/testDesignReviewValidation'
import type { ReviewDraftItem, ReviewDraftPage } from '../../apps/portal/src/domains/quality-loop/types/testDesignReview'

test('review discovery validates exact scope, ordering, cursor and non-execution authority', () => {
  const hash = 'sha256:' + 'a'.repeat(64)
  const item: ReviewDraftItem = { metadata: { project_id: 'p', generation_id: 'g', scope_revision_id: 's', invocation_id: 'i',
    call_id: 'call', status: 'draft', artifact_hash: hash, case_count: 1, gap_count: 0 },
    context_pin: { context_id: 'c', artifact_hash: hash, input_digest: hash, image_revision_id: 'image', image_artifact_hash: hash },
    scope_pin: { revision_id: 's', artifact_hash: hash, request_hash: hash } }
  const request = { project_id: 'p', after_id: '', limit: 1 }
  const page: ReviewDraftPage = { request, items: [item], next_after_id: 'g', can_review: true,
    generation_authorized: false, execution_authorized: false }
  expect(verifyReviewDraftPage(page, request)).toEqual(page)
  for (const kind of ['project', 'cursor', 'duplicate', 'authority', 'scope', 'hash', 'extra', 'count', 'request']) {
    const bad = structuredClone(page)
    if (kind === 'project') bad.items[0].metadata.project_id = 'foreign'
    if (kind === 'cursor') bad.next_after_id = 'other'
    if (kind === 'duplicate') bad.items.push(item)
    if (kind === 'authority') Object.assign(bad, { execution_authorized: true })
    if (kind === 'scope') bad.items[0].scope_pin.revision_id = 'foreign'
    if (kind === 'hash') bad.items[0].context_pin.artifact_hash = 'unverified'
    if (kind === 'extra') Object.assign(bad.items[0], { raw_output: 'protected text' })
    if (kind === 'count') bad.items[0].metadata.case_count = true as unknown as number
    if (kind === 'request') bad.request.limit = 2
    expect(() => verifyReviewDraftPage(bad, request)).toThrow()
  }
  const reversed = { ...page, request: { ...request, limit: 2 }, items: [item, { ...item, metadata: { ...item.metadata, generation_id: 'a' } }], next_after_id: null }
  expect(() => verifyReviewDraftPage(reversed, reversed.request)).toThrow()
})

for (const theme of ['light', 'dark']) {
test(`qa reviewer discovers drafts independently, confirms mapping and hides invalid content (${theme})`, async ({ page, request }) => {
  test.setTimeout(300_000)
  const exweb = process.env.EXWEB_FIXTURE_ROOT, source = exweb ? resolve(exweb) : analysisSource()
  if (exweb) {
    expect(execFileSync('git', ['-C', source, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim()).toBe('fe5827f6b76f77ef34918d8b452ee823142332dc')
    expect(execFileSync('git', ['-C', source, 'remote', 'get-url', 'origin'], { encoding: 'utf8' }).trim()).toBe('https://github.com/kunben-duck/exweb.git')
  }
  const errors: string[] = [], forbiddenReads: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('request', (value) => {
    if (/\/quality\/test-design-jobs|\/settings\/model-configs\?route=chat/.test(value.url())
      || value.method() === 'POST' && value.postDataJSON()?.tool_id === 'query.quality.test_design_job') forbiddenReads.push(value.url())
  })
  try {
    const v = await generationScopeFixture(request, source), reviewer = await analysisAccount(request)
    const memberUrl = `${analysisApi}/v1/projects/${v.projectId}/members/${reviewer.userId}`
    expect((await request.put(memberUrl, { headers: v.owner.headers, data: { role: 'viewer' } })).ok()).toBeTruthy()
    const discoveryUrl = `${analysisApi}/v1/projects/${v.projectId}/quality/test-design-review-drafts`
    expect((await request.get(discoveryUrl, { headers: reviewer.headers })).status()).toBe(403)
    expect((await request.put(memberUrl, { headers: v.owner.headers, data: { role: 'qa_lead' } })).ok()).toBeTruthy()
    const authorized = await request.get(discoveryUrl, { headers: reviewer.headers })
    expect(authorized.ok()).toBeTruthy()
    expect((await authorized.json()).can_review).toBe(true)
    const state = await installMappingProtocol(page, v.scope)
    state.draft.metadata.artifact_hash = await mappingDigest(state.draft.result)
    const base: ReviewDraftItem = { metadata: state.draft.metadata, context_pin: state.draft.result.context_pin, scope_pin: state.draft.result.scope_pin }
    // Only catalog/result/review transport is a protocol fixture. Authentication,
    // qa membership, source capture, publication, context and scope use real PG.
    const entries = [base, ...[1, 2, 3].map((index) => ({ ...structuredClone(base),
      metadata: { ...base.metadata, generation_id: `${base.metadata.generation_id}-${index}` } }))]
    const reads: string[] = [], catalog = { denied: false, corrupt: false }
    await page.route('**/quality/test-design-review-drafts?*', async (route) => {
      const params = new URL(route.request().url()).searchParams, after = params.get('after_id')!, limit = Number(params.get('limit'))
      reads.push(after)
      if (catalog.denied) return route.fulfill({ status: 403, json: { detail: 'Explicit reviewer/source revocation fixture' } })
      const remaining = entries.filter((item) => item.metadata.generation_id > after), items = remaining.slice(0, limit)
      const response: ReviewDraftPage = { request: { project_id: v.projectId, after_id: after, limit }, items,
        next_after_id: remaining.length > limit ? items.at(-1)!.metadata.generation_id : null,
        can_review: true, generation_authorized: false, execution_authorized: false }
      if (catalog.corrupt) response.items = response.items.map((item) => ({ ...item, scope_pin: { ...item.scope_pin, revision_id: 'foreign' } }))
      await route.fulfill({ json: response })
    })
    expect((await request.patch(`${analysisApi}/v1/settings`, { headers: reviewer.headers, data: { theme } })).ok()).toBeTruthy()
    await page.addInitScript((token) => { localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en') }, reviewer.token)
    await page.goto(`/projects/${v.projectId}/knowledge`)
    const queue = page.getByRole('region', { name: 'Draft mapping review queue', exact: true })
    const draft = queue.locator('[aria-label="Archived draft test cases"]')
    const open = queue.getByRole('button', { name: 'Review draft cases', exact: true })
    const reload = queue.getByRole('button', { name: 'Reload review drafts', exact: true })
    const inspect = () => queue.getByRole('button', { name: `Inspect draft ${base.metadata.generation_id} (1 cases)`, exact: true })
    await expect(open).toBeVisible(); expect(reads).toEqual([])
    await expect(open).toHaveCSS('border-radius', '9px')
    await expect(open).toHaveCSS('border-top-width', '1px')
    await expect(open).toHaveCSS('font-size', '12px')
    await expect(open).toHaveCSS('background-color', theme === 'light' ? 'rgb(238, 242, 248)' : 'rgb(36, 37, 38)')
    await open.click(); await expect(queue.getByRole('button', { name: /^Inspect draft / })).toHaveCount(3)
    await queue.getByRole('button', { name: 'Load more review drafts', exact: true }).click()
    await expect(queue.getByRole('button', { name: /^Inspect draft / })).toHaveCount(4)
    expect(reads).toEqual(['', entries[2].metadata.generation_id])
    await inspect().click(); await expect(draft).toBeVisible({ timeout: 60_000 })
    await expect(inspect()).toHaveCSS('border-radius', '9px')
    await expect(inspect()).toHaveCSS('border-top-color', theme === 'light' ? 'rgb(77, 121, 216)' : 'rgb(122, 162, 255)')
    await expect(queue.getByRole('button', { name: 'Generate draft cases', exact: true })).toHaveCount(0)
    const mapping = queue.getByRole('region', { name: 'Independent assertion mapping', exact: true })
    await mapping.getByRole('button', { name: 'Inspect assertion mapping', exact: true }).click()
    await mapping.getByRole('button', { name: 'Review assertion mappings', exact: true }).click()
    const form = mapping.getByRole('group', { name: 'New mapping decision', exact: true })
    const record = mapping.getByRole('button', { name: 'Record mapping decision', exact: true })
    await expect(record).toBeDisabled()
    for (let index = 0; index < 4; index++) {
      const row = form.getByRole('group', { name: `Assertion mapping ${index + 1}`, exact: true })
      await row.getByRole('combobox').selectOption('accept')
      await row.getByRole('textbox', { name: 'Assertion review reason', exact: true }).fill('Explicit independent fixture decision')
    }
    await form.getByRole('textbox', { name: 'Review reason', exact: true }).fill('QA mapping fixture; not product approval or target execution')
    await form.getByRole('checkbox').check(); await expect(record).toBeEnabled()
    await reload.click(); await expect(draft).toHaveCount(0)
    await inspect().click(); await expect(draft).toBeVisible({ timeout: 60_000 })
    await mapping.getByRole('button', { name: 'Inspect assertion mapping', exact: true }).click()
    await mapping.getByRole('button', { name: 'Review assertion mappings', exact: true }).click()
    await expect(form.getByRole('checkbox')).not.toBeChecked(); await expect(record).toBeDisabled()
    for (let index = 0; index < 4; index++) {
      const row = form.getByRole('group', { name: `Assertion mapping ${index + 1}`, exact: true })
      await row.getByRole('combobox').selectOption('accept')
      await row.getByRole('textbox', { name: 'Assertion review reason', exact: true }).fill('New exact fixture confirmation')
    }
    await form.getByRole('textbox', { name: 'Review reason', exact: true }).fill('Independent QA fixture decision')
    await form.getByRole('checkbox').check(); await record.click()
    await expect(mapping).toContainText('4/4 obligations have accepted assertions')
    expect(state.writes).toHaveLength(1); expect(state.generationWrites).toBe(0)
    await page.reload(); await open.click(); await inspect().click(); await expect(draft).toBeVisible({ timeout: 60_000 })
    await mapping.getByRole('button', { name: 'Inspect assertion mapping', exact: true }).click()
    await expect(mapping).toContainText('4/4 obligations have accepted assertions')
    await page.setViewportSize({ width: 390, height: 844 })
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    mkdirSync(resolve('output/playwright'), { recursive: true })
    await open.scrollIntoViewIfNeeded()
    await page.screenshot({ path: resolve(`output/playwright/review-queue-${exweb ? 'exweb-' : ''}${theme}-mobile.png`) })
    state.corruptRead = true
    await mapping.getByRole('button', { name: 'Reload mapping history', exact: true }).click()
    await expect(queue.getByRole('alert')).toBeVisible(); await expect(draft).toHaveCount(0)
    await expect(queue.getByRole('button', { name: /^Inspect draft / })).toHaveCount(0)
    state.corruptRead = false; await reload.click(); await inspect().click(); await expect(draft).toBeVisible({ timeout: 60_000 })
    catalog.denied = true; await reload.click(); await expect(queue.getByRole('alert')).toBeVisible(); await expect(draft).toHaveCount(0)
    catalog.denied = false; catalog.corrupt = true; await reload.click(); await expect(queue.getByRole('alert')).toBeVisible()
    await expect(queue.getByRole('button', { name: /^Inspect draft / })).toHaveCount(0)
    catalog.corrupt = false; await reload.click(); await inspect().click(); await expect(draft).toBeVisible({ timeout: 60_000 })
    state.draft.result.proposal.cases[0].title = 'Tampered protected result'
    await reload.click(); await inspect().click(); await expect(queue.getByRole('alert')).toBeVisible({ timeout: 60_000 }); await expect(draft).toHaveCount(0)
    await expect(queue).not.toContainText('Tampered protected result')
    expect(forbiddenReads).toEqual([]); expect(errors).toEqual([])
  } finally { if (!exweb) rmSync(source, { recursive: true, force: true }) }
})
}
