import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { rmSync } from 'node:fs'
import { resolve } from 'node:path'
import { verifyGenerationJob } from '../../apps/portal/src/domains/quality-loop/testDesignGenerationValidation'
import { analysisApi, analysisSource } from './source-analysis-fixtures'
import { generationScopeFixture } from './test-design-generation-fixtures'
import { batchJobFixture, batchProtocolFixture } from './generation-batch-fixtures'
import { installBatchRecoveryProtocol } from './generation-batch-recovery-protocol'

const consent = 'I confirm recovering this exact complete set of archived batch replies in a new command, without another model request.'
function offeredJob() {
  const v = batchProtocolFixture(undefined, undefined, 'independent-recovery')
  const job = batchJobFixture(v, 3, 0, 'failed')
  job.invocation_id = job.source_invocation_id; job.recovery_request = v.archive.result.recovery_request!
  return { ...v, job }
}

test('complete batch recovery offer is a strict metadata receipt, not execution authority', () => {
  const v = offeredJob()
  expect(verifyGenerationJob(v.job, v.scope, v.job.invocation_id)).toEqual(v.job)
  expect(v.job.execution_authorized).toBe(false)
  expect(JSON.stringify(v.job.recovery_request)).not.toContain('artifact_ref')
})
for (const mutation of ['partial', 'order', 'duplicate-call', 'duplicate-batch', 'extra-secret', 'private-ref', 'schema',
  'plan', 'digest', 'foreign-source', 'unknown', 'unstarted', 'single', 'already-result']) {
  test(`batch recovery job rejects ${mutation}`, () => {
    const v = offeredJob(), r = v.archive.result.recovery_request!, progress = v.job.batch_progress!
    v.job.recovery_request = r
    if (mutation === 'partial') r.replies.pop()
    if (mutation === 'order') r.replies.reverse()
    if (mutation === 'duplicate-call') r.replies[1].call_id = r.replies[0].call_id
    if (mutation === 'duplicate-batch') r.replies[1].batch_digest = r.replies[0].batch_digest
    if (mutation === 'extra-secret') Object.assign(r, { api_key: 'forbidden' })
    if (mutation === 'private-ref') Object.assign(r.replies[0], { artifact_ref: 's3://private' })
    if (mutation === 'schema') Object.assign(r, { schema_version: 'unknown' })
    if (mutation === 'plan') r.plan_digest = r.request_hash
    if (mutation === 'digest') r.replies[0].response_hash = 'invalid'
    if (mutation === 'foreign-source') r.invocation_id = 'foreign-source'
    if (mutation === 'unknown') { progress.archived_calls = 2; progress.unknown_calls = 1 }
    if (mutation === 'unstarted') { progress.archived_calls = progress.claimed_calls = 2; progress.unstarted_calls = 1 }
    if (mutation === 'single') v.job.recovery_request = { project_id: r.project_id, invocation_id: r.invocation_id,
      request_hash: r.request_hash, reply_artifact_hash: r.replies[0].reply_artifact_hash, response_hash: r.replies[0].response_hash }
    if (mutation === 'already-result') v.job.generation_id = v.archive.metadata.generation_id
    expect(() => verifyGenerationJob(v.job, v.scope, v.job.invocation_id)).toThrow()
  })
}

for (const theme of ['light', 'dark'] as const) {
  test(`fixed exweb batch recovery uses fresh canonical confirmation and v4 historical result (${theme})`, async ({ page, request }) => {
    test.setTimeout(420_000)
    const external = process.env.EXWEB_FIXTURE_ROOT, source = external ? resolve(external) : analysisSource()
    if (external) {
      expect(execFileSync('git', ['-C', source, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim()).toBe('fe5827f6b76f77ef34918d8b452ee823142332dc')
      expect(execFileSync('git', ['-C', source, 'status', '--porcelain'], { encoding: 'utf8' }).trim()).toBe('')
    }
    try {
      const v = await generationScopeFixture(request, source, { requirementsPath: 'tests/fixtures/system-image/exweb-batch-requirements.md', constraintCount: 4 })
      const data = batchProtocolFixture(v.context, v.scope, 'z-independent-recovery')
      expect(data.archive.metadata.batch_count).toBeGreaterThanOrEqual(2)
      const protocol = await installBatchRecoveryProtocol(page, data)
      expect((await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme } })).ok()).toBeTruthy()
      await page.addInitScript((token) => { localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en') }, v.owner.token)
      if (theme === 'dark') await page.setViewportSize({ width: 390, height: 844 })
      const panel = page.getByRole('region', { name: 'Pinned draft test generation', exact: true })
      const open = async () => {
        await page.getByRole('button', { name: 'Inspect published context', exact: true }).click()
        await page.getByRole('button').filter({ hasText: v.contextId }).click()
        await page.getByRole('button', { name: 'Inspect test-design scope', exact: true }).click()
        await expect(panel).toBeVisible({ timeout: 60_000 })
        await panel.getByRole('button', { name: 'Inspect draft generation', exact: true }).click()
      }
      const reload = async () => {
        const read = page.waitForResponse((r) => r.request().method() === 'POST' && r.request().postDataJSON()?.tool_id === 'query.quality.test_design_job')
        await panel.getByRole('button', { name: 'Reload generation access and history', exact: true }).click(); await read
      }
      await page.goto(`/projects/${v.projectId}/knowledge`); await open()
      const recover = panel.getByRole('button', { name: 'Recover archived draft', exact: true })
      await expect(recover).toBeDisabled(); expect(protocol.writes).toEqual([])
      protocol.corruptOffer = true; await reload()
      await expect(panel.getByRole('alert')).toContainText('Protected content is hidden')
      await expect(recover).toHaveCount(0); expect(protocol.writes).toEqual([])
      protocol.corruptOffer = false; await reload(); await expect(recover).toBeDisabled()
      await panel.getByRole('checkbox', { name: consent, exact: true }).check(); await expect(recover).toBeEnabled()
      await page.reload(); await open(); await expect(recover).toBeDisabled()
      await panel.getByRole('checkbox', { name: consent, exact: true }).check(); await recover.click()
      await expect.poll(() => protocol.confirmed).toBe(true)
      expect(protocol.writes).toHaveLength(1)
      protocol.completed = true; await reload()
      const draft = panel.locator('[aria-label="Archived draft test cases"]')
      await expect(draft).toBeVisible({ timeout: 60_000 }); await expect(draft).toContainText('counts are all zero')
      await page.reload(); await open(); await expect(draft).toBeVisible({ timeout: 60_000 })
      expect(protocol.writes).toHaveLength(1)
      if (theme === 'dark') expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
      await draft.scrollIntoViewIfNeeded()
      await page.screenshot({ path: `output/playwright/generation-batch-recovery-command-${theme}.png` })
      protocol.denied = true; await reload()
      await expect(panel.getByRole('alert')).toContainText('Protected content is hidden'); await expect(draft).toHaveCount(0)
    } finally { if (!external) rmSync(source, { recursive: true, force: true }) }
  })
}
