import { expect, test, type Locator } from '@playwright/test'
import { mkdirSync, rmSync } from 'node:fs'
import { resolve } from 'node:path'
import { execFileSync } from 'node:child_process'
import { analysisApi, analysisSource } from './source-analysis-fixtures'
import { scopeFixture } from './test-design-scope-fixtures'
import { scopeContractValid } from '../../apps/portal/src/domains/quality-loop/testDesignScopeDraft'
import { verifyScopeArchive } from '../../apps/portal/src/domains/quality-loop/testDesignScopeValidation'
import type { TestDesignContract } from '../../apps/portal/src/domains/quality-loop/types/testDesignScope'

async function fillOracle(group: Locator) {
  for (const [label, value] of Object.entries({ 'Oracle preconditions': 'Isolated synthetic fixture', 'Action under test': 'Send fixture request',
    'Observable output': 'Recorded response', 'Required result': 'Expected fixture boundary, not a production assertion' })) await group.getByRole('textbox', { name: label, exact: true }).fill(value)
}
for (const theme of ['light', 'dark']) {
test(`review scope through confirmed tools, retain blockers and replay withdrawals (${theme})`, async ({ page, request }) => {
  const exweb = process.env.EXWEB_FIXTURE_ROOT
  test.setTimeout(exweb ? 360_000 : 240_000)
  const source = exweb ? resolve(exweb) : analysisSource(), errors: string[] = [], writes: string[] = []
  if (exweb) expect(execFileSync('git', ['--no-optional-locks', '-C', source, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim())
    .toBe('fe5827f6b76f77ef34918d8b452ee823142332dc')
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('request', (req) => { if (req.method() === 'POST' && req.url().endsWith('/v1/tool-invocations') && req.postDataJSON()?.tool_id === 'quality.test_design_scope.review') writes.push(req.postData()!) })
  try {
    const v = await scopeFixture(request, source)
    expect((await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme } })).ok()).toBeTruthy()
    await page.addInitScript((token) => { localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en') }, v.owner.token)
    const readScopeAfter = async (action: () => Promise<unknown>, revisionId = '') => {
      const response = page.waitForResponse((res) => res.request().method() === 'GET'
        && new URL(res.url()).pathname === `/v1/projects/${v.projectId}/quality/test-design-scopes${revisionId ? `/${revisionId}` : ''}`, { timeout: 60_000 })
      await action()
      expect((await response).ok()).toBeTruthy()
    }
    const recordAfter = async (button: Locator) => readScopeAfter(async () => {
      const response = page.waitForResponse((res) => res.request().method() === 'POST' && res.url().endsWith('/confirm'), { timeout: 60_000 })
      await button.click()
      expect((await (await response).json()).status).toBe('completed')
    })
    const open = async () => {
      await page.getByRole('button', { name: 'Inspect published context', exact: true }).click()
      await page.getByRole('button').filter({ hasText: v.contextId }).click()
      await readScopeAfter(() => page.getByRole('button', { name: 'Inspect test-design scope', exact: true }).click())
    }
    await page.goto(`/projects/${v.projectId}/knowledge`); await open()
    const panel = page.getByRole('region', { name: 'Reviewed test-design scope', exact: true })
    await expect(panel).toContainText('No reviewed scope for this context.')
    await panel.getByRole('button', { name: 'Review scope', exact: true }).click()
    let form = panel.getByRole('group', { name: 'New scope decision', exact: true })
    const save = form.getByRole('button', { name: 'Record scope decision', exact: true })
    await expect(save).toBeDisabled()
    for (const [title, fields] of Object.entries({
      'Risk boundaries': { 'Risk boundary': 'Streaming response content type' },
      'Permission boundaries': { 'Acting role': 'Unauthenticated fixture caller', Operation: 'POST', 'Target resource': '/api/v1/finance/chat/stream' },
      'State transitions': { 'From state': 'idle', 'Triggering event': 'fixture request', 'To state': 'responded' },
      'Historical invariants': { 'Invariant statement': 'Retain both original constraints in scope' },
    })) {
      await form.locator('summary').filter({ hasText: title }).click()
      const dimension = form.getByRole('group', { name: title, exact: true })
      await dimension.getByRole('combobox', { name: 'Applicability', exact: true }).selectOption('applicable')
      await dimension.getByRole('textbox', { name: 'Assessment rationale', exact: true }).fill('Explicit synthetic browser review')
      await dimension.getByRole('button', { name: 'Add obligation', exact: true }).click()
      for (const [label, value] of Object.entries(fields)) await dimension.getByRole('textbox', { name: label, exact: true }).fill(value)
      if (title === 'Permission boundaries') await dimension.getByRole('combobox', { name: 'Permission result', exact: true }).selectOption('denied')
      const constraintChecks = dimension.getByRole('group', { name: 'Required constraints', exact: true })
      if (title === 'Historical invariants') {
        for (const check of await constraintChecks.getByRole('checkbox').all()) await check.check()
      } else await constraintChecks.getByRole('checkbox', { name: title === 'Permission boundaries' ? /BR-EXWEB-1/ : /AC-EXWEB-1/ }).check()
      await fillOracle(dimension.getByRole('group', { name: 'Observable obligation', exact: true }))
      await form.locator('summary').filter({ hasText: title }).click()
    }
    await form.locator('summary').filter({ hasText: 'Explicit gaps and conflicts' }).click()
    await form.getByRole('button', { name: 'Add gap', exact: true }).click()
    await form.getByRole('textbox', { name: 'Gap description', exact: true }).fill('Negative partition still needs a business decision')
    const gap = form.getByRole('group', { name: 'Gap 1', exact: true })
    for (const check of await gap.getByRole('checkbox').all()) await check.check()
    await form.getByRole('button', { name: 'Add conflict', exact: true }).click()
    const conflict = form.getByRole('group', { name: 'Conflict 1', exact: true })
    await conflict.getByRole('textbox', { name: 'Conflict description', exact: true }).fill('Fixture behavior must not be mistaken for deployed behavior')
    await conflict.getByRole('checkbox').first().check()
    await form.locator('summary').filter({ hasText: 'Positive and negative examples' }).click()
    const examples = form.locator('.scope-example')
    await expect(examples).toHaveCount(2)
    for (let index = 0; index < 2; index++) {
      const example = examples.nth(index)
      await example.locator(':scope > summary').click()
      await example.getByRole('combobox', { name: 'Negative example assessment', exact: true }).selectOption('gap')
      await example.getByRole('combobox', { name: 'Blocking gap', exact: true }).selectOption({ index: 1 })
    }
    await form.locator('summary').filter({ hasText: 'Test reuse and conflict assessment' }).click()
    await form.getByRole('textbox', { name: 'Reuse assessment', exact: true }).fill('No runtime reuse claimed')
    await form.getByRole('textbox', { name: 'Conflict assessment', exact: true }).fill('One explicit conflict remains unresolved')
    await form.getByRole('textbox', { name: 'Review reason', exact: true }).fill('Reviewed browser fixture with explicit gaps')
    await page.setViewportSize({ width: 1280, height: 1600 })
    await form.locator('summary').filter({ hasText: 'Risk boundaries' }).click()
    mkdirSync(resolve('output/playwright'), { recursive: true })
    await form.locator('.scope-dimension').first().screenshot({ path: resolve(`output/playwright/test-design-scope${exweb ? '-exweb' : ''}-${theme}-form.png`) })
    await form.locator('summary').filter({ hasText: 'Risk boundaries' }).click()
    await page.setViewportSize({ width: 1280, height: 720 })
    const consent = form.getByRole('checkbox', { name: 'I independently confirm these exact scope obligations, examples and gaps, not inferred code behavior.', exact: true })
    await consent.check(); await expect(save).toBeEnabled()
    await form.getByRole('textbox', { name: 'Review reason', exact: true }).fill('Revised browser fixture review')
    await expect(consent).not.toBeChecked(); await expect(save).toBeDisabled(); await consent.check()
    await recordAfter(save)
    await expect(panel).toContainText('Current reviewed scope')
    await expect(panel).toContainText('2 explicit scope blockers')
    expect(writes).toHaveLength(1)
    const url = `${analysisApi}/v1/projects/${v.projectId}/quality/test-design-scopes`
    const view = await (await request.get(url, { headers: v.owner.headers, params: { context_id: v.contextId } })).json()
    expect(view.head.current_use).toEqual({ scope_current: true, scope_complete: false, generation_authorized: false })
    expect(view.head.assessment.constraint_ids).toHaveLength(2)
    expect(view.head.assessment.obligation_ids).toHaveLength(4)
    expect(scopeContractValid(view.head.request.contract, v.context.context)).toBe(true)
    for (const tamper of [
      (c: TestDesignContract) => { c.examples.pop() },
      (c: TestDesignContract) => { c.risks.applicability = 'not_applicable' },
      (c: TestDesignContract) => { c.transitions.rationale = '' },
      (c: TestDesignContract) => { c.gaps = [] },
      (c: TestDesignContract) => { c.reused_case_ids = ['foreign-test'] },
      (c: TestDesignContract) => { c.permissions.items[0].evidence_ids = ['foreign-evidence'] },
      (c: TestDesignContract) => { c.invariants.items[0].oracle.expected_result = '' },
    ]) {
      const changed = structuredClone(view.head.request.contract)
      tamper(changed)
      expect(scopeContractValid(changed, v.context.context)).toBe(false)
    }
    expect(verifyScopeArchive(view.head, v.context, view.head.revision.revision_id)).toEqual(view.head)
    const invalid = structuredClone(view.head)
    invalid.assessment.generation_authorized = true
    expect(() => verifyScopeArchive(invalid, v.context, view.head.revision.revision_id)).toThrow('Scope assessment mismatch')
    await page.reload(); await open(); await expect(panel).toContainText(view.head.revision.revision_id)
    await panel.getByRole('button', { name: 'Withdraw scope', exact: true }).click()
    form = panel.getByRole('group', { name: 'New scope decision', exact: true })
    await form.getByRole('textbox', { name: 'Review reason', exact: true }).fill('Withdraw explicit fixture review')
    await form.getByRole('checkbox', { name: 'I confirm withdrawal of this exact scope head.', exact: true }).check()
    await recordAfter(form.getByRole('button', { name: 'Record scope decision', exact: true }))
    await expect(panel).toContainText('Withdrawn scope')
    expect(writes).toHaveLength(2)
    await readScopeAfter(() => panel.getByRole('combobox', { name: 'Scope history', exact: true }).selectOption(view.head.revision.revision_id), view.head.revision.revision_id)
    await expect(panel).toContainText('Historical scope; not current')
    await expect(panel).toContainText('Revised browser fixture review')
    await page.setViewportSize({ width: 390, height: 844 }); await panel.scrollIntoViewIfNeeded()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    mkdirSync(resolve('output/playwright'), { recursive: true })
    await page.screenshot({ path: resolve(`output/playwright/test-design-scope${exweb ? '-exweb' : ''}-${theme}-mobile.png`) })
    // Corruption only; all writes and reads above use the real disposable PG API.
    await page.route('**/quality/test-design-scopes?*', async (route) => {
      const response = await route.fetch(), value = await response.json()
      value.context_artifact_hash = `sha256:${'0'.repeat(64)}`
      await route.fulfill({ response, json: value })
    })
    await readScopeAfter(() => panel.getByRole('button', { name: 'Reload scope history', exact: true }).click())
    await expect(page.getByRole('alert')).toContainText('Published context could not be verified.')
    await expect(panel).toHaveCount(0)
    expect(errors).toEqual([])
  } finally { if (!exweb) rmSync(source, { recursive: true, force: true }) }
})
}
