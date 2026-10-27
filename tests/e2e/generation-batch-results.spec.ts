import { expect, test } from '@playwright/test'
import { rmSync } from 'node:fs'
import { verifyGenerationArchiveView } from '../../apps/portal/src/domains/quality-loop/generationBatchResultValidation'
import { verifyReviewDraftItem } from '../../apps/portal/src/domains/quality-loop/testDesignReviewValidation'
import { mappingDigest, mappingAssessment, newAssertionReviews } from '../../apps/portal/src/domains/quality-loop/testDesignMappingValidation'
import { analysisAccount, analysisApi, analysisSource } from './source-analysis-fixtures'
import { generationScopeFixture } from './test-design-generation-fixtures'
import { installMappingProtocol } from './test-design-mapping-fixtures'
import { batchProtocolFixture as fixture } from './generation-batch-fixtures'

test('v3 public view preserves three native calls, full obligations and independent mapping', async () => {
  const v = fixture()
  expect(await verifyGenerationArchiveView(v.archive, v.scope, v.job)).toEqual(v.archive)
  expect(v.archive.metadata.batch_count).toBe(3)
  const item = { metadata: v.archive.metadata, context_pin: v.archive.result.context_pin, scope_pin: v.archive.result.scope_pin }
  expect(verifyReviewDraftItem(item, v.job.project_id)).toEqual(item)
  expect(JSON.stringify(v.archive)).not.toContain('artifact_ref')
  expect(await mappingDigest(v.archive.result)).not.toBe(v.archive.metadata.artifact_hash)
  const decisions = newAssertionReviews(v.archive).map((value) => ({ ...value, decision: 'accept' as const, reason: 'Explicit independent protocol review' }))
  const review = mappingAssessment(v.archive, decisions)
  expect(review.coverage.assertion_mapped_count).toBe(v.archive.result.proposal.coverage.obligation_denominator)
  expect(review.coverage.passed_count).toBe(0); expect(review.execution_authorized).toBe(false)
})

for (const mutation of ['missing', 'duplicate', 'foreign', 'call', 'usage', 'private-ref', 'extra-secret', 'lineage', 'oracle', 'passed', 'budget', 'plan', 'view-hash', 'metadata']) {
test(`v3 public view fails closed for ${mutation}`, async () => {
  const v = fixture(), r = v.archive.result
  if (mutation === 'missing') r.calls.pop()
  if (mutation === 'duplicate') r.calls[1] = structuredClone(r.calls[0])
  if (mutation === 'foreign') r.calls[0].claim.project_id = 'foreign'
  if (mutation === 'call') r.calls[0].audit.request_hash = v.archive.metadata.artifact_hash
  if (mutation === 'usage') r.calls[0].audit.input_tokens = true as unknown as number
  if (mutation === 'private-ref') Object.assign(r.calls[0].reply, { artifact_ref: 's3://private/native' })
  if (mutation === 'extra-secret') Object.assign(r.calls[0].audit, { api_key: 'never allowed' })
  if (mutation === 'lineage') r.provenance[0].case_id_map = {}
  if (mutation === 'oracle') r.proposal.cases[0].assertions[0].oracle.expected_result = 'Invented business expectation'
  if (mutation === 'passed') Object.assign(r.proposal.coverage, { passed_count: 1 })
  if (mutation === 'budget') r.reservation.reservation.reserved_tokens--
  if (mutation === 'plan') r.batch_plan.batches.pop()
  if (mutation === 'metadata') v.archive.metadata.call_id = 'fake-aggregate-call' as unknown as null
  if (mutation !== 'view-hash') {
    const { view_hash: old, ...value } = v.archive
    expect(old).toBeTruthy()
    v.archive.view_hash = await mappingDigest(value)
  } else v.archive.view_hash = v.archive.metadata.artifact_hash
  await expect(verifyGenerationArchiveView(v.archive, v.scope, v.job)).rejects.toThrow()
})
}

test('qa reviewer opens v3 draft and separately reviews mappings without administrator model access', async ({ page, request }) => {
  test.setTimeout(300_000)
  const source = analysisSource()
  try {
    const v = await generationScopeFixture(request, source), reviewer = await analysisAccount(request)
    expect((await request.put(`${analysisApi}/v1/projects/${v.projectId}/members/${reviewer.userId}`,
      { headers: v.owner.headers, data: { role: 'qa_lead' } })).ok()).toBeTruthy()
    const data = fixture(v.context, v.scope), state = await installMappingProtocol(page, v.scope, data.archive)
    const item = { metadata: data.archive.metadata, context_pin: data.archive.result.context_pin, scope_pin: data.archive.result.scope_pin }
    const forbidden: string[] = []
    page.on('request', (value) => {
      if (/\/quality\/test-design-jobs|\/settings\/model-configs\?route=chat/.test(value.url())) forbidden.push(value.url())
    })
    await page.route('**/quality/test-design-review-drafts?*', async (route) => {
      const params = new URL(route.request().url()).searchParams
      await route.fulfill({ json: { request: { project_id: v.projectId, after_id: params.get('after_id'), limit: Number(params.get('limit')) },
        items: [item], next_after_id: null, can_review: true, generation_authorized: false, execution_authorized: false } })
    })
    await page.addInitScript((token) => { localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en') }, reviewer.token)
    await page.goto(`/projects/${v.projectId}/knowledge`)
    const queue = page.getByRole('region', { name: 'Draft mapping review queue', exact: true })
    await queue.getByRole('button', { name: 'Review draft cases', exact: true }).click()
    await queue.getByRole('button', { name: /^Inspect draft / }).click()
    await expect(queue.locator('[aria-label="Archived draft test cases"]')).toBeVisible({ timeout: 60_000 })
    const mapping = queue.getByRole('region', { name: 'Independent assertion mapping', exact: true })
    await mapping.getByRole('button', { name: 'Inspect assertion mapping', exact: true }).click()
    await mapping.getByRole('button', { name: 'Review assertion mappings', exact: true }).click()
    const form = mapping.getByRole('group', { name: 'New mapping decision', exact: true })
    const total = newAssertionReviews(data.archive).length
    for (let index = 0; index < total; index++) {
      const row = form.getByRole('group', { name: `Assertion mapping ${index + 1}`, exact: true })
      await row.getByRole('combobox').selectOption('accept')
      await row.getByRole('textbox', { name: 'Assertion review reason', exact: true }).fill('Independent v3 protocol review')
    }
    await form.getByRole('textbox', { name: 'Review reason', exact: true }).fill('Explicit QA mapping, not product approval or executed coverage')
    await form.getByRole('checkbox').check()
    await mapping.getByRole('button', { name: 'Record mapping decision', exact: true }).click()
    const obligations = data.archive.result.proposal.coverage.obligation_denominator
    await expect(mapping).toContainText(`${obligations}/${obligations} obligations have accepted assertions`)
    expect(state.writes).toHaveLength(1); expect(state.generationWrites).toBe(0); expect(forbidden).toEqual([])
    expect(data.archive.result.proposal.coverage.passed_count).toBe(0)
    data.archive.result.proposal.cases[0].title = 'Tampered v3 protected content'
    await queue.getByRole('button', { name: 'Reload review drafts', exact: true }).click()
    await queue.getByRole('button', { name: /^Inspect draft / }).click()
    await expect(queue.getByRole('alert')).toBeVisible({ timeout: 60_000 })
    await expect(queue.locator('[aria-label="Archived draft test cases"]')).toHaveCount(0)
    await expect(queue).not.toContainText('Tampered v3 protected content')
  } finally { rmSync(source, { recursive: true, force: true }) }
})
