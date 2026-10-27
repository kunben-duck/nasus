import { expect, test, type Locator } from '@playwright/test'
import { mkdirSync, rmSync } from 'node:fs'
import { resolve } from 'node:path'
import { execFileSync } from 'node:child_process'
import { analysisApi, analysisSource } from './source-analysis-fixtures'
import { generationScopeFixture, installGenerationProtocol } from './test-design-generation-fixtures'
import { verifyGenerationArchive, verifyGenerationJob, verifyGenerationPreview } from '../../apps/portal/src/domains/quality-loop/testDesignGenerationValidation'

const generateConsent = 'I confirm this exact model destination, full source inventory and maximum token/spend reservation for one draft generation call.'
const stopConsent = 'I confirm stopping this exact job; charged or unknown calls are not refunded or resent.'
const recoverConsent = 'I confirm recovering this exact archived reply in a new command, without another model request.'
async function enterBudget(panel: Locator) {
  await panel.getByRole('combobox', { name: 'Tested chat model', exact: true }).selectOption('ui-tested-model')
  for (const [name, value] of Object.entries({ 'Maximum input tokens': '24576', 'Maximum output tokens': '1024',
    'Total token reservation ceiling': '65536', 'Maximum reserved spend': '1' })) {
    await panel.getByRole('spinbutton', { name, exact: true }).fill(value)
  }
}

for (const theme of ['light', 'dark']) {
test(`fixed generation confirmation, cancel, unknown outcome and archive-only recovery (${theme})`, async ({ page, request }) => {
  const exweb = process.env.EXWEB_FIXTURE_ROOT, source = exweb ? resolve(exweb) : analysisSource()
  test.setTimeout(exweb ? 420_000 : 240_000)
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  if (exweb) expect(execFileSync('git', ['--no-optional-locks', '-C', source, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim())
    .toBe('fe5827f6b76f77ef34918d8b452ee823142332dc')
  try {
    const v = await generationScopeFixture(request, source), protocol = await installGenerationProtocol(page, v.scope)
    expect((await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme } })).ok()).toBeTruthy()
    await page.addInitScript((token) => { localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en') }, v.owner.token)
    const panel = page.getByRole('region', { name: 'Pinned draft test generation', exact: true })
    const open = async () => {
      await page.getByRole('button', { name: 'Inspect published context', exact: true }).click()
      await page.getByRole('button').filter({ hasText: v.contextId }).click()
      await page.getByRole('button', { name: 'Inspect test-design scope', exact: true }).click()
      await expect(panel).toBeVisible({ timeout: 60_000 })
      await panel.getByRole('button', { name: 'Inspect draft generation', exact: true }).click()
      await expect(panel.getByRole('group', { name: 'Native generation budget', exact: true })).toBeVisible()
    }
    const reload = async () => {
      const response = page.waitForResponse((res) => res.request().method() === 'POST' && res.request().postDataJSON()?.tool_id === 'query.quality.test_design_job')
      await panel.getByRole('button', { name: 'Reload generation access and history', exact: true }).click()
      await response
    }
    const preview = panel.getByRole('button', { name: 'Preview complete generation budget', exact: true })
    const consent = panel.getByRole('checkbox', { name: generateConsent, exact: true })
    const start = panel.getByRole('button', { name: 'Generate draft cases', exact: true })
    const begin = async () => {
      await enterBudget(panel); await expect(preview).toBeEnabled(); await preview.click()
      await expect(start).toBeDisabled(); await consent.check(); await expect(start).toBeEnabled()
      await start.click()
      await expect(panel.getByRole('button', { name: 'Stop generation', exact: true })).toBeVisible()
    }
    await page.goto(`/projects/${v.projectId}/knowledge`)
    expect(protocol.previewCount).toBe(0); expect(protocol.modelCount).toBe(0)
    await open(); await expect(preview).toBeDisabled()
    await expect(panel.getByRole('combobox', { name: 'Tested chat model', exact: true }).locator('option')).toHaveCount(2)
    await enterBudget(panel); await preview.click(); await expect(start).toBeDisabled()
    await consent.check(); await expect(start).toBeEnabled()
    await panel.getByRole('spinbutton', { name: 'Maximum reserved spend', exact: true }).fill('0.5')
    await expect(consent).toHaveCount(0)
    await preview.click(); await expect(start).toBeDisabled(); await consent.check()
    protocol.modelSignature = 'new-ui-tested-signature'
    await panel.getByRole('button', { name: 'Reload generation access and history', exact: true }).click()
    await expect(consent).toHaveCount(0); await expect(preview).toBeEnabled()
    await begin()
    expect(protocol.writes.filter((row) => row.tool_id === 'quality.test_design.generate')).toHaveLength(1)
    await expect(panel.locator('[aria-label="Archived draft test cases"]')).toHaveCount(0)
    const status = panel.locator('[aria-label="Generation task status"]')
    await expect(status).toContainText('Provider outcome is unknown')
    await expect(panel.getByRole('button', { name: 'Stop generation', exact: true })).toBeDisabled()
    await panel.getByRole('checkbox', { name: stopConsent, exact: true }).check()
    // Identical metadata polling must not erase a still-exact cancellation consent.
    const jobsBefore = protocol.jobCount
    await expect.poll(() => protocol.jobCount, { timeout: 10_000 }).toBeGreaterThan(jobsBefore)
    await expect(panel.getByRole('checkbox', { name: stopConsent, exact: true })).toBeChecked()
    await panel.getByRole('button', { name: 'Stop generation', exact: true }).click()
    await expect(status).toContainText('cancelled')
    await expect(preview).toBeEnabled()
    expect(protocol.writes.filter((row) => row.tool_id === 'quality.test_design.cancel')).toHaveLength(1)
    await begin()
    protocol.setMode('unknown'); await reload(); await expect(status).toContainText('failed')
    await expect(status).toContainText('will never be automatically resent')
    await expect(panel.getByRole('button', { name: 'Recover archived draft', exact: true })).toHaveCount(0)
    expect(protocol.writes.filter((row) => row.tool_id === 'quality.test_design.generate')).toHaveLength(2)
    // Explicit failed+archived protocol state exercises a new recovery command,
    // not a model retry or a reopening of the original failed command.
    protocol.setMode('failed-reply'); await reload()
    const recover = panel.getByRole('button', { name: 'Recover archived draft', exact: true })
    await expect(recover).toBeDisabled(); await panel.getByRole('checkbox', { name: recoverConsent, exact: true }).check()
    await recover.click()
    const draft = panel.locator('[aria-label="Archived draft test cases"]')
    await expect(draft).toContainText('1 draft cases; 4/4 obligations planned')
    await expect(draft).toContainText('counts are all zero')
    const original = protocol.history.filter((row) => row.tool_id === 'quality.test_design.generate').at(-1)!
    expect(original.status).toBe('failed')
    expect(protocol.writes.filter((row) => row.tool_id === 'quality.test_design.recover')).toHaveLength(1)
    expect(protocol.writes.filter((row) => row.tool_id === 'quality.test_design.generate')).toHaveLength(2)
    await draft.locator('summary').click(); await expect(draft).toContainText('Content-Type includes text/event-stream')
    mkdirSync(resolve('output/playwright'), { recursive: true })
    await page.setViewportSize({ width: 1280, height: 2400 })
    await panel.evaluate((element) => element.scrollIntoView({ block: 'center' }))
    await panel.screenshot({ path: resolve(`output/playwright/test-design-generation${exweb ? '-exweb' : ''}-${theme}-desktop.png`) })
    await page.reload(); await open(); await expect(draft).toContainText('1 draft cases; 4/4 obligations planned')
    await page.setViewportSize({ width: 390, height: 844 }); await draft.scrollIntoViewIfNeeded()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    await page.screenshot({ path: resolve(`output/playwright/test-design-generation${exweb ? '-exweb' : ''}-${theme}-mobile.png`) })
    protocol.corruptResult = true; await reload()
    await expect(panel.getByRole('alert')).toContainText('could not be verified')
    await expect(draft).toHaveCount(0)
    protocol.corruptResult = false; await reload(); await expect(draft).toBeVisible()
    protocol.failRead = true; await reload(); await expect(panel.getByRole('alert')).toContainText('Protected content is hidden')
    await expect(draft).toHaveCount(0)
    expect(protocol.writes).toHaveLength(4)
    expect(errors).toEqual([])
  } finally { if (!exweb) rmSync(source, { recursive: true, force: true }) }
})
}

test('generation UI rejects corrupted previews and archived coverage without changing the denominator', async ({ page, request }) => {
  test.setTimeout(240_000)
  const source = analysisSource()
  try {
    const v = await generationScopeFixture(request, source), protocol = await installGenerationProtocol(page, v.scope)
    await page.addInitScript((token) => { localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en') }, v.owner.token)
    await page.goto(`/projects/${v.projectId}/knowledge`)
    await page.getByRole('button', { name: 'Inspect published context', exact: true }).click()
    await page.getByRole('button').filter({ hasText: v.contextId }).click()
    await page.getByRole('button', { name: 'Inspect test-design scope', exact: true }).click()
    const panel = page.getByRole('region', { name: 'Pinned draft test generation', exact: true })
    await panel.getByRole('button', { name: 'Inspect draft generation', exact: true }).click()
    await enterBudget(panel)
    protocol.corruptPreview = true
    await panel.getByRole('button', { name: 'Preview complete generation budget', exact: true }).click()
    await expect(panel.getByRole('alert')).toContainText('Generation preview unavailable')
    await expect(panel.getByRole('checkbox', { name: generateConsent, exact: true })).toHaveCount(0)
    expect(protocol.writes).toHaveLength(0)
    protocol.corruptPreview = false
    const responses = page.waitForResponse((res) => res.request().method() === 'POST' && res.request().postDataJSON()?.tool_id === 'query.quality.test_design_execution')
    await panel.getByRole('button', { name: 'Preview complete generation budget', exact: true }).click()
    const preview = (await (await responses).json()).result.test_design_execution_preview
    const selection = { project_id: v.projectId, scope_revision_id: v.scope.revision.revision_id, scope_artifact_hash: v.scope.revision.artifact_hash,
      model_config_id: 'ui-tested-model', budget: preview.request.execution.budget }
    expect(verifyGenerationPreview(preview, selection)).toEqual(preview)
    for (const tamper of [
      (p: typeof preview) => { p.request.execution.source_binding_ids.push('ui-protocol-source') },
      (p: typeof preview) => { p.destination = 'http://untrusted.example' },
      (p: typeof preview) => { p.reservation.reserved_cost_nanos++ },
      (p: typeof preview) => { p.generation_authorized = true },
      (p: typeof preview) => { p.policy.tokenizer_id = { unsafe: 'not a tokenizer label' } },
    ]) { const invalid = structuredClone(preview); tamper(invalid); expect(() => verifyGenerationPreview(invalid, selection)).toThrow() }
    await panel.getByRole('checkbox', { name: generateConsent, exact: true }).check()
    await panel.getByRole('button', { name: 'Generate draft cases', exact: true }).click()
    await expect(panel.getByRole('button', { name: 'Stop generation', exact: true })).toBeVisible()
    protocol.setMode('complete')
    const jobResponse = page.waitForResponse((res) => res.request().method() === 'POST' && res.request().postDataJSON()?.tool_id === 'query.quality.test_design_job'
      && protocol.history[0].status === 'completed')
    const job = (await (await jobResponse).json()).result.test_design_job
    expect(verifyGenerationJob(job, v.scope, job.invocation_id)).toEqual(job)
    const draft = panel.locator('[aria-label="Archived draft test cases"]')
    await expect(draft).toBeVisible()
    await expect(panel.getByRole('button', { name: 'Preview complete generation budget', exact: true })).toBeEnabled()
    const archiveResponse = page.waitForResponse((res) => res.url().endsWith('/quality/test-design-results/ui-generation-draft'))
    await panel.getByRole('button', { name: 'Reload generation access and history', exact: true }).click()
    const archive = await (await archiveResponse).json()
    expect(verifyGenerationArchive(archive, v.scope, job)).toEqual(archive)
    for (const tamper of [
      (a: typeof archive) => { a.result.proposal.coverage.passed_count = 1 },
      (a: typeof archive) => { a.result.proposal.coverage.rows[1].constraint_ids = [...a.result.proposal.coverage.rows[0].constraint_ids] },
      (a: typeof archive) => { a.result.proposal.coverage.rows[0].planned_case_ids = [] },
      (a: typeof archive) => { a.result.proposal.cases[0].assertions.pop() },
      (a: typeof archive) => { a.result.proposal.gaps.push({ gap_id: 'unsafe-gap', row_ids: [], description: { html: '<img>' } }) },
      (a: typeof archive) => { a.result.proposal.coverage.scope_pin.artifact_hash = `sha256:${'0'.repeat(64)}` },
    ]) { const invalid = structuredClone(archive); tamper(invalid); expect(() => verifyGenerationArchive(invalid, v.scope, job)).toThrow() }
    expect(protocol.writes).toHaveLength(1)
  } finally { rmSync(source, { recursive: true, force: true }) }
})

test('generation history stays bounded, detects unloaded running jobs and retains a newly accepted job', async ({ page, request }) => {
  test.setTimeout(240_000)
  const source = analysisSource()
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  try {
    const v = await generationScopeFixture(request, source), protocol = await installGenerationProtocol(page, v.scope)
    protocol.seedHistory(35, 34)
    expect((await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme: 'dark' } })).ok()).toBeTruthy()
    await page.addInitScript((token) => { localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en') }, v.owner.token)
    const panel = page.getByRole('region', { name: 'Pinned draft test generation', exact: true })
    const open = async () => {
      await page.getByRole('button', { name: 'Inspect published context', exact: true }).click()
      await page.getByRole('button').filter({ hasText: v.contextId }).click()
      await page.getByRole('button', { name: 'Inspect test-design scope', exact: true }).click()
      await panel.getByRole('button', { name: 'Inspect draft generation', exact: true }).click()
    }
    const history = panel.getByRole('combobox', { name: 'Generation history', exact: true })
    const preview = panel.getByRole('button', { name: 'Preview complete generation budget', exact: true })
    const more = panel.getByRole('button', { name: 'Load more generation history', exact: true })
    const draft = panel.locator('[aria-label="Archived draft test cases"]')
    await page.goto(`/projects/${v.projectId}/knowledge`); await open()
    await expect(history.locator('option')).toHaveCount(20)
    await expect(panel.getByRole('status')).toContainText('running outside the loaded history')
    await expect(preview).toBeDisabled()
    expect(protocol.historyRequests.every((input) => input.after_id === '')).toBe(true)
    expect(protocol.writes).toHaveLength(0)
    await more.click(); await expect(history.locator('option')).toHaveCount(35)
    await history.selectOption('ui-command-a-034')
    await panel.getByRole('checkbox', { name: stopConsent, exact: true }).check()
    await panel.getByRole('button', { name: 'Stop generation', exact: true }).click()
    await expect(panel.locator('[aria-label="Generation task status"]')).toContainText('cancelled')
    const requested = protocol.historyRequests.length
    await page.reload(); await open()
    await expect(history.locator('option')).toHaveCount(20)
    expect(protocol.historyRequests.slice(requested).every((input) => input.after_id === '')).toBe(true)
    await enterBudget(panel); await expect(preview).toBeEnabled(); await preview.click()
    await panel.getByRole('checkbox', { name: generateConsent, exact: true }).check()
    await panel.getByRole('button', { name: 'Generate draft cases', exact: true }).click()
    const accepted = protocol.writes.find((item) => item.tool_id === 'quality.test_design.generate')!
    await expect(history).toHaveValue(accepted.id)
    await expect(history.locator('option')).toHaveCount(21)
    await expect(panel.getByRole('button', { name: 'Stop generation', exact: true })).toBeVisible()
    expect(protocol.historyRequests.slice(requested).every((input) => input.after_id === '')).toBe(true)
    protocol.setMode('complete')
    await expect(draft).toContainText('1 draft cases; 4/4 obligations planned', { timeout: 15_000 })
    await expect(preview).toBeEnabled()
    await expect(history).toHaveValue(accepted.id)
    protocol.corruptNextPage = true; await more.click()
    await expect(panel.getByRole('alert')).toContainText('Protected content is hidden')
    await expect(history).toHaveCount(0); await expect(draft).toHaveCount(0)
    protocol.corruptNextPage = false
    await panel.getByRole('button', { name: 'Reload generation access and history', exact: true }).click()
    await expect(draft).toBeVisible(); await expect(history.locator('option')).toHaveCount(21)
    await more.click(); await expect(history.locator('option')).toHaveCount(36)
    expect(protocol.historyRequests.every((input) => input.limit === 20)).toBe(true)
    expect(protocol.legacyHistoryReads).toBe(0)
    await page.setViewportSize({ width: 390, height: 844 })
    await history.scrollIntoViewIfNeeded()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
    mkdirSync(resolve('output/playwright'), { recursive: true })
    await page.screenshot({ path: resolve('output/playwright/test-design-generation-history-dark-mobile.png') })
    protocol.failRead = true
    await panel.getByRole('button', { name: 'Reload generation access and history', exact: true }).click()
    await expect(panel.getByRole('alert')).toContainText('Protected content is hidden')
    await expect(history).toHaveCount(0); await expect(draft).toHaveCount(0)
    expect(protocol.writes).toHaveLength(2)
    expect(errors).toEqual([])
  } finally { rmSync(source, { recursive: true, force: true }) }
})
