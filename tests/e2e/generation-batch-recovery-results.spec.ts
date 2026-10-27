import { expect, test } from '@playwright/test'
import { rmSync } from 'node:fs'
import { verifyGenerationArchiveView } from '../../apps/portal/src/domains/quality-loop/generationBatchResultValidation'
import { verifyReviewDraftItem } from '../../apps/portal/src/domains/quality-loop/testDesignReviewValidation'
import { mappingDigest } from '../../apps/portal/src/domains/quality-loop/testDesignMappingValidation'
import { batchProtocolFixture } from './generation-batch-fixtures'
import { analysisAccount, analysisApi, analysisSource } from './source-analysis-fixtures'
import { generationScopeFixture } from './test-design-generation-fixtures'
import { installMappingProtocol } from './test-design-mapping-fixtures'

const fixture = () => batchProtocolFixture(undefined, undefined, 'independent-recovery')

test('v4 public recovered draft preserves all native pins without private storage locations', async () => {
  const v = fixture()
  expect(await verifyGenerationArchiveView(v.archive, v.scope, v.job)).toEqual(v.archive)
  expect(v.archive.metadata.batch_count).toBe(3)
  expect(v.archive.result.recovery_request?.replies).toHaveLength(3)
  expect(v.archive.metadata.recovery_invocation_id).not.toBe(v.archive.metadata.invocation_id)
  expect(verifyReviewDraftItem({ metadata: v.archive.metadata, context_pin: v.archive.result.context_pin,
    scope_pin: v.archive.result.scope_pin }, v.job.project_id).metadata).toEqual(v.archive.metadata)
  expect(JSON.stringify(v.archive)).not.toContain('artifact_ref')
  expect(v.archive.result.proposal.coverage.passed_count).toBe(0)
})

for (const mutation of ['source-authority', 'foreign-authority', 'missing-request', 'request-hash', 'reservation-hash', 'plan',
  'partial', 'reorder', 'call', 'response', 'usage', 'audit', 'extra-secret', 'private-ref', 'view-version', 'v3-authority']) {
  test(`v4 public recovery fails closed for ${mutation}`, async () => {
    const v = fixture(), r = v.archive.result, request = r.recovery_request!
    if (mutation === 'source-authority') r.recovery_invocation_id = v.archive.metadata.recovery_invocation_id = r.invocation_id
    if (mutation === 'foreign-authority') r.recovery_invocation_id = 'foreign-authority'
    if (mutation === 'missing-request') delete r.recovery_request
    if (mutation === 'request-hash') request.request_hash = v.archive.metadata.artifact_hash
    if (mutation === 'reservation-hash') request.reservation_hash = v.archive.metadata.artifact_hash
    if (mutation === 'plan') request.plan_digest = v.archive.metadata.artifact_hash
    if (mutation === 'partial') request.replies.pop()
    if (mutation === 'reorder') request.replies.reverse()
    if (mutation === 'call') request.replies[0].call_id = 'foreign-call'
    if (mutation === 'response') request.replies[0].response_hash = v.archive.metadata.artifact_hash
    if (mutation === 'usage') request.replies[0].usage_digest = v.archive.metadata.artifact_hash
    if (mutation === 'audit') request.replies[0].audit_digest = v.archive.metadata.artifact_hash
    if (mutation === 'extra-secret') Object.assign(request, { api_key: 'forbidden' })
    if (mutation === 'private-ref') Object.assign(request.replies[0], { artifact_ref: 's3://private/native' })
    if (mutation === 'view-version') v.archive.view_schema = 'nasus.test-design-result-view.v3'
    if (mutation === 'v3-authority') r.schema = v.archive.metadata.schema = 'nasus.test-design-result.v3'
    const { view_hash: old, ...view } = v.archive
    expect(old).toBeTruthy()
    v.archive.view_hash = await mappingDigest(view)
    await expect(verifyGenerationArchiveView(v.archive, v.scope, v.job)).rejects.toThrow()
  })
}

for (const theme of ['light', 'dark'] as const) {
  test(`qa reviewer can inspect v4 recovered draft without generation access in ${theme}`, async ({ page, request }) => {
    test.setTimeout(300_000)
    const source = analysisSource()
    try {
      const v = await generationScopeFixture(request, source), reviewer = await analysisAccount(request)
      expect((await request.put(`${analysisApi}/v1/projects/${v.projectId}/members/${reviewer.userId}`,
        { headers: v.owner.headers, data: { role: 'qa_lead' } })).ok()).toBeTruthy()
      const data = batchProtocolFixture(v.context, v.scope, 'independent-recovery')
      const state = await installMappingProtocol(page, v.scope, data.archive)
      const item = { metadata: data.archive.metadata, context_pin: data.archive.result.context_pin, scope_pin: data.archive.result.scope_pin }
      const forbidden: string[] = []
      page.on('request', (value) => { if (/\/quality\/test-design-jobs|\/settings\/model-configs\?route=chat/.test(value.url())) forbidden.push(value.url()) })
      await page.route('**/quality/test-design-review-drafts?*', async (route) => {
        const params = new URL(route.request().url()).searchParams
        await route.fulfill({ json: { request: { project_id: v.projectId, after_id: params.get('after_id'), limit: Number(params.get('limit')) },
          items: [item], next_after_id: null, can_review: true, generation_authorized: false, execution_authorized: false } })
      })
      if (theme === 'dark') await page.setViewportSize({ width: 390, height: 844 })
      await page.addInitScript(({ token, mode }) => {
        localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en'); localStorage.setItem('nasus.theme', mode)
      }, { token: reviewer.token, mode: theme })
      await page.goto(`/projects/${v.projectId}/knowledge`)
      const queue = page.getByRole('region', { name: 'Draft mapping review queue', exact: true })
      await queue.getByRole('button', { name: 'Review draft cases', exact: true }).click()
      await queue.getByRole('button', { name: /^Inspect draft / }).click()
      await expect(queue.locator('[aria-label="Archived draft test cases"]')).toBeVisible({ timeout: 60_000 })
      await expect(queue).toContainText(data.archive.result.proposal.cases[0].title)
      expect(forbidden).toEqual([]); expect(state.generationWrites).toBe(0); expect(state.writes).toEqual([])
      if (theme === 'dark') expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
      await page.screenshot({ path: `output/playwright/generation-batch-recovery-v4-${theme}.png`, fullPage: true })
    } finally { rmSync(source, { recursive: true, force: true }) }
  })
}
