import { expect, test } from '@playwright/test'
import { mkdirSync, rmSync } from 'node:fs'
import { resolve } from 'node:path'
import { analysisApi, analysisSource } from './source-analysis-fixtures'
import { generationScopeFixture, generationArchiveFixture, generationBudgetFixture, generationPreviewFixture } from './test-design-generation-fixtures'
import { installMappingProtocol, mappingArchiveFixture } from './test-design-mapping-fixtures'
import { mappingAssessment, mappingDigest, mappingsValid, newAssertionReviews, verifyMappingArchive, verifyMappingView } from '../../apps/portal/src/domains/quality-loop/testDesignMappingValidation'
import type { ScopeArchive } from '../../apps/portal/src/domains/quality-loop/types/testDesignScope'
import type { GenerationJob } from '../../apps/portal/src/domains/quality-loop/types/testDesignGeneration'
import type { MappingReview } from '../../apps/portal/src/domains/quality-loop/types/testDesignMapping'

test('mapping verifier preserves exact pairs, immutable draft and zero execution under hostile archives', async () => {
  // Minimal pure transport specimen, not source semantics or business gold.
  const hash = 'sha256:' + 'a'.repeat(64), oracle = { preconditions: 'Independent fixture', action: 'Inspect response', observation: 'HTTP status', expected_result: '200' }
  const scope = { revision: { project_id: 'p', revision_id: 'scope', artifact_hash: hash, request_hash: hash },
    context_pin: { context_id: 'c', artifact_hash: hash, input_digest: hash, image_revision_id: 'image', image_artifact_hash: hash },
    assessment: { constraint_ids: ['ac', 'rule'] }, request: { contract: { examples: [{ positive: oracle }, { positive: oracle }] } } } as unknown as ScopeArchive
  const prepared = generationPreviewFixture({ project_id: 'p', scope_revision_id: 'scope', scope_artifact_hash: hash, model_config_id: 'model', budget: generationBudgetFixture })
  const job = { project_id: 'p', invocation_id: 'source', source_invocation_id: 'source', generation_id: 'generation' } as GenerationJob
  const draft = generationArchiveFixture(scope, job, prepared.request), original = structuredClone(draft)
  const values = newAssertionReviews(draft)
  expect(values.every((value) => value.decision === 'defer' && value.reason === '')).toBe(true)
  expect(mappingsValid(values, draft)).toBe(false)
  values.forEach((value) => { value.decision = 'accept'; value.reason = 'Verified fixed step and oracle' })
  const input: MappingReview = { project_id: 'p', generation_id: 'generation', generation_artifact_hash: hash,
    expected_previous_revision_id: null, decision: 'review', mappings: values, reason: 'Independent mapping, not execution', policy_revision: 'nasus.test-design-mapping.v1' }
  const archive = await mappingArchiveFixture(draft, input, null)
  await verifyMappingArchive(archive, draft, archive.revision)
  await verifyMappingView({ project_id: 'p', generation_id: 'generation', generation_artifact_hash: hash,
    head: archive, history: [archive.revision], can_review: true, scope_current: true }, draft)
  expect(archive.assessment!.coverage.assertion_mapped_count).toBe(4)
  expect(archive.assessment!.coverage.automated_count + archive.assessment!.coverage.executed_on_target_count + archive.assessment!.coverage.passed_count).toBe(0)
  expect(draft).toEqual(original)
  for (const field of ['case_id', 'row_id', 'step_index', 'oracle_digest']) {
    const changed = structuredClone(values)
    Object.assign(changed[0], { [field]: field === 'step_index' ? 1 : 'other' })
    expect(mappingsValid(changed, draft)).toBe(false)
  }
  expect(mappingsValid(values.slice(1), draft)).toBe(false)
  expect(mappingsValid([...values, values[0]], draft)).toBe(false)
  expect(mappingsValid(values.map((value) => ({ ...value, step_index: true as unknown as number })), draft)).toBe(false)
  values[0].decision = 'reject'; values[1].decision = 'defer'
  expect(mappingAssessment(draft, values).coverage.assertion_mapped_count).toBe(2)
  for (const corrupt of ['pass', 'oracle', 'scope', 'request', 'artifact', 'authority']) {
    const bad = structuredClone(archive)
    if (corrupt === 'pass') Object.assign(bad.assessment!.coverage, { passed_count: 1 })
    if (corrupt === 'oracle') bad.request.mappings![0].oracle_digest = 'sha256:' + '0'.repeat(64)
    if (corrupt === 'scope') bad.generation_pin.scope_pin.artifact_hash = 'sha256:' + '0'.repeat(64)
    if (corrupt === 'request') bad.request.reason = 'Tampered'
    if (corrupt === 'artifact') bad.revision.artifact_hash = 'sha256:' + '0'.repeat(64)
    if (corrupt === 'authority') bad.revision.authority_actor = 'imposter'
    await expect(verifyMappingArchive(bad, draft, bad.revision)).rejects.toThrow()
  }
  // Python canonical JSON SHA-256: non-ASCII values are not ASCII-escaped.
  expect(await mappingDigest({ a: '中文🦆', z: [true, null, 0] })).toBe('sha256:5751d93a2862f7c436c43a91e91e61745fb6b4a69a7037a25b9e3f124987417a')
})

const consentText = 'I independently confirm every exact step, oracle and mapping decision. This is not evidence of test execution.'
for (const theme of ['light', 'dark']) {
test(`independent mapping review, changed consent, history, withdrawal and fail-closed access (${theme})`, async ({ page, request }) => {
  test.setTimeout(300_000)
  const exweb = process.env.EXWEB_FIXTURE_ROOT, source = exweb ? resolve(exweb) : analysisSource()
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  try {
    const v = await generationScopeFixture(request, source), state = await installMappingProtocol(page, v.scope)
    expect((await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme } })).ok()).toBeTruthy()
    await page.addInitScript((token) => { localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en') }, v.owner.token)
    const generation = page.getByRole('region', { name: 'Pinned draft test generation', exact: true })
    const mapping = page.getByRole('region', { name: 'Independent assertion mapping', exact: true })
    const draft = page.locator('[aria-label="Archived draft test cases"]')
    const open = async () => {
      await page.getByRole('button', { name: 'Inspect published context', exact: true }).click()
      await page.getByRole('button').filter({ hasText: v.contextId }).click()
      await page.getByRole('button', { name: 'Inspect test-design scope', exact: true }).click()
      await generation.getByRole('button', { name: 'Inspect draft generation', exact: true }).click()
      await expect(draft).toBeVisible({ timeout: 60_000 })
    }
    const reloadMapping = mapping.getByRole('button', { name: 'Reload mapping history', exact: true })
    const record = mapping.getByRole('button', { name: 'Record mapping decision', exact: true })
    const form = mapping.getByRole('group', { name: 'New mapping decision', exact: true })
    await page.goto(`/projects/${v.projectId}/knowledge`); await open()
    expect(state.inspections).toBe(0)
    await mapping.getByRole('button', { name: 'Inspect assertion mapping', exact: true }).click()
    await expect(mapping).toContainText('No independent mapping review')
    await mapping.getByRole('button', { name: 'Review assertion mappings', exact: true }).click()
    await expect(form.getByRole('combobox', { name: 'Mapping decision', exact: true })).toHaveCount(4)
    await expect(record).toBeDisabled()
    for (let index = 0; index < 4; index++) {
      const item = form.getByRole('group', { name: `Assertion mapping ${index + 1}`, exact: true })
      await expect(item.getByRole('combobox')).toHaveValue('defer')
      await item.getByRole('combobox').selectOption(index === 0 ? 'reject' : index === 1 ? 'defer' : 'accept')
      await item.getByRole('textbox', { name: 'Assertion review reason', exact: true }).fill(`Independent fixture reason ${index}`)
    }
    await form.getByRole('textbox', { name: 'Review reason', exact: true }).fill('Mixed mapping decisions, never execution')
    const consent = form.getByRole('checkbox', { name: consentText, exact: true })
    await consent.check(); await expect(record).toBeEnabled()
    await form.getByRole('textbox', { name: 'Review reason', exact: true }).fill('Changed exact review reason')
    await expect(consent).not.toBeChecked(); await expect(record).toBeDisabled()
    await consent.check(); await reloadMapping.click(); await expect(record).toBeDisabled()
    await consent.check(); await record.click()
    await expect(mapping).toContainText('2/4 obligations have accepted assertions; 2 accepted, 1 rejected, 1 deferred')
    expect(state.writes).toHaveLength(1)
    expect(state.draft.current_use.mapping_approved).toBe(false)
    await expect(draft).toContainText('counts are all zero')
    await mapping.getByRole('button', { name: 'Review assertion mappings', exact: true }).click()
    for (const select of await form.getByRole('combobox', { name: 'Mapping decision', exact: true }).all()) await select.selectOption('accept')
    await form.getByRole('textbox', { name: 'Review reason', exact: true }).fill('New independent fixture assessment')
    await consent.check(); state.staleNext = true; await record.click()
    await expect(mapping.getByRole('alert')).toContainText('head changed')
    expect(state.history).toHaveLength(1)
    await expect(record).toBeDisabled(); await reloadMapping.click(); await consent.check(); await record.click()
    await expect(mapping).toContainText('4/4 obligations have accepted assertions')
    expect(state.history).toHaveLength(2)
    mkdirSync(resolve('output/playwright'), { recursive: true })
    await page.setViewportSize({ width: 1280, height: 3000 }); await mapping.scrollIntoViewIfNeeded()
    await mapping.screenshot({ path: resolve(`output/playwright/test-design-mapping-${exweb ? 'exweb-' : ''}${theme}-desktop.png`) })
    await page.setViewportSize({ width: 390, height: 844 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    await mapping.getByRole('button', { name: 'Inspect assertion mapping', exact: true }).scrollIntoViewIfNeeded()
    await page.screenshot({ path: resolve(`output/playwright/test-design-mapping-${exweb ? 'exweb-' : ''}${theme}-mobile.png`) })
    await mapping.getByRole('button', { name: 'Withdraw mapping', exact: true }).click()
    await form.getByRole('textbox', { name: 'Review reason', exact: true }).fill('Explicit withdrawal fixture')
    await form.getByRole('checkbox', { name: 'I confirm withdrawal of this exact mapping head.', exact: true }).check(); await record.click()
    await expect(mapping).toContainText('Withdrawn mapping')
    await mapping.getByRole('combobox', { name: 'Mapping history', exact: true }).selectOption(state.history[0].revision.revision_id)
    await expect(mapping).toContainText('Historical mapping; not current')
    await expect(mapping).toContainText('2/4 obligations have accepted assertions')
    await expect(form).toHaveCount(0)
    await page.reload(); await open()
    state.scopeCurrent = false
    await mapping.getByRole('button', { name: 'Inspect assertion mapping', exact: true }).click()
    await expect(mapping.getByRole('button', { name: 'Review assertion mappings', exact: true })).toBeDisabled()
    state.failRead = true; await reloadMapping.click()
    await expect(generation.getByRole('alert')).toContainText('draft and mapping are hidden')
    await expect(draft).toHaveCount(0)
    state.failRead = false; state.scopeCurrent = true
    await generation.getByRole('button', { name: 'Reload generation access and history', exact: true }).click()
    await expect(draft).toBeVisible(); state.corruptRead = true
    await mapping.getByRole('button', { name: 'Inspect assertion mapping', exact: true }).click()
    await expect(draft).toHaveCount(0)
    expect(state.writes).toHaveLength(4)
    expect(state.generationWrites).toBe(0)
    expect(errors).toEqual([])
  } finally { if (!exweb) rmSync(source, { recursive: true, force: true }) }
})
}
