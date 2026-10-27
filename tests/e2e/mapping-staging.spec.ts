import { expect, test, type Locator } from '@playwright/test'
import { mkdirSync, rmSync } from 'node:fs'
import { resolve } from 'node:path'
import { analysisAccount, analysisApi, analysisSource } from './source-analysis-fixtures'
import { generationScopeFixture } from './test-design-generation-fixtures'
import { installMappingProtocol } from './test-design-mapping-fixtures'
import { partitionedDraftFixture } from './test-design-mapping-partition-fixtures'
import { installStagingProtocol, stagedArchiveFixture, stagedCommitment, stagedHeadFixture, stagingRequest, stagingWorkspaceFixture } from './mapping-staging-fixtures'
import { originalPart, partDecisionsValid, verifyPartHead, verifyStagedArchive } from '../../apps/portal/src/domains/quality-loop/mappingStagingValidation'
import { verifyFinalPreview } from '../../apps/portal/src/domains/quality-loop/mappingFinalPreviewValidation'
import { mappingQuery } from '../../apps/portal/src/domains/quality-loop/mappingStagingValidation'
import type { ScopeArchive } from '../../apps/portal/src/domains/quality-loop/types/testDesignScope'

function specimenScope() {
  const hash = 'sha256:' + 'a'.repeat(64), oracle = { preconditions: 'Synthetic source', action: 'Inspect response', observation: 'HTTP status', expected_result: '200' }
  return { revision: { project_id: 'staging-fixture', revision_id: 'scope', artifact_hash: hash, request_hash: hash },
    context_pin: { context_id: 'context', artifact_hash: hash, input_digest: hash, image_revision_id: 'image', image_artifact_hash: hash },
    assessment: { constraint_ids: ['ac', 'rule'] }, request: { contract: { examples: [{ positive: oracle }, { positive: oracle }] } } } as unknown as ScopeArchive
}
test('private part validators bind full original pairs, signer, history and archived hash', async () => {
  const draft = await partitionedDraftFixture(specimenScope(), 33), workspace = await stagingWorkspaceFixture(draft), part = originalPart(draft, workspace, 1)
  expect(workspace.plan.assertion_count).toBe(132); expect(part.assertions).toHaveLength(4)
  const input = stagingRequest(workspace, part), first = await stagedArchiveFixture(workspace, input, null)
  expect(partDecisionsValid(part, input.decisions)).toBe(true)
  await verifyStagedArchive(first, workspace, part, first.revision)
  const second = await stagedArchiveFixture(workspace, { ...input, expected_previous_part_revision_id: first.revision.part_revision_id }, first)
  const head = stagedHeadFixture(workspace, 1, [first, second])
  verifyPartHead(head, workspace, part)
  const self = structuredClone(second)
  self.revision.expected_previous_part_revision_id = self.revision.part_revision_id
  await expect(verifyStagedArchive(self, workspace, part, self.revision)).rejects.toThrow()
  for (const fault of ['actor', 'order', 'missing', 'oracle', 'reason', 'policy', 'approved', 'hash', 'plan']) {
    const bad = structuredClone(first)
    if (fault === 'actor') bad.revision.authority_actor = 'foreign-reviewer'
    if (fault === 'order') bad.request.decisions.reverse()
    if (fault === 'missing') bad.request.decisions.pop()
    if (fault === 'oracle') bad.request.decisions[0].oracle_digest = 'sha256:' + '0'.repeat(64)
    if (fault === 'reason') bad.request.decisions[0].reason = '😀'.repeat(2001)
    if (fault === 'policy') Object.assign(bad.request, { policy_revision: 'nasus.test-design-mapping.v2' })
    if (fault === 'approved') Object.assign(bad.current_use, { review_authorized: true })
    if (fault === 'hash') bad.revision.artifact_hash = 'sha256:' + '0'.repeat(64)
    if (fault === 'plan') bad.plan.expected_previous_revision_id = 'foreign-head'
    await expect(verifyStagedArchive(bad, workspace, part, bad.revision), fault).rejects.toThrow()
  }
  head.history[1].expected_previous_part_revision_id = null
  expect(() => verifyPartHead(head, workspace, part)).toThrow()
  const bounded = structuredClone(input.decisions); bounded[0].reason = '😀'.repeat(2000)
  expect(partDecisionsValid(part, bounded)).toBe(true)
})
test('complete preview requires every part and grants no review or execution authority', async () => {
  const draft = await partitionedDraftFixture(specimenScope(), 33), workspace = await stagingWorkspaceFixture(draft)
  const heads = []
  for (let i = 0; i < workspace.plan.part_count; i++) heads.push(await stagedArchiveFixture(workspace, stagingRequest(workspace, originalPart(draft, workspace, i)), null))
  const { members: _members, ...set } = await stagedCommitment(workspace, heads)
  const complete = { ...mappingQuery(workspace), plan_digest: workspace.plan.plan_digest, expected_previous_revision_id: null,
    authority_actor: workspace.actorId, part_count: 2, saved_part_count: 2, assertion_count: 132, part_set: set,
    ready_for_confirmation: true, scope_current: true, review_authorized: false, execution_authorized: false }
  await verifyFinalPreview(complete, workspace)
  await verifyFinalPreview({ ...complete, saved_part_count: 1, part_set: null, ready_for_confirmation: false }, workspace)
  for (const changes of [{ saved_part_count: 1 }, { assertion_count: 128 }, { authority_actor: 'foreign-reviewer' },
    { expected_previous_revision_id: 'new-head' }, { execution_authorized: true }, { part_set: { ...set, members: [] } },
    { part_set: { ...set, part_set_digest: 'sha256:' + '0'.repeat(64) } }]) {
    await expect(verifyFinalPreview({ ...complete, ...changes }, workspace)).rejects.toThrow()
  }
})
async function decide(form: Locator, count: number, text: string) {
  for (let i = 0; i < count; i++) {
    await form.getByRole('combobox', { name: 'Mapping decision', exact: true }).nth(i).selectOption('accept')
    await form.getByRole('textbox', { name: 'Assertion review reason', exact: true }).nth(i).fill(text + i)
  }
}
for (const theme of ['light', 'dark']) test(`private editing, ack recovery and independent full-set confirmation (${theme})`, async ({ page, request }) => {
  test.setTimeout(300_000)
  const exweb = process.env.EXWEB_FIXTURE_ROOT, source = exweb ? resolve(exweb) : analysisSource(), errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  try {
    const v = await generationScopeFixture(request, source), draft = await partitionedDraftFixture(v.scope, theme === 'dark' ? 33 : 1)
    const base = await installMappingProtocol(page, v.scope, draft), state = await installStagingProtocol(page, draft, v.owner.userId, base.history)
    if (theme === 'dark') {
      const part = originalPart(draft, state.workspace, 0)
      state.histories.set(0, [await stagedArchiveFixture(state.workspace, stagingRequest(state.workspace, part), null)])
    }
    expect((await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme } })).ok()).toBeTruthy()
    await page.addInitScript((token) => { localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en') }, v.owner.token)
    await page.goto(`/projects/${v.projectId}/knowledge`)
    await page.getByRole('button', { name: 'Inspect published context', exact: true }).click()
    await page.getByRole('button').filter({ hasText: v.contextId }).click()
    await page.getByRole('button', { name: 'Inspect test-design scope', exact: true }).click()
    await page.getByRole('region', { name: 'Pinned draft test generation', exact: true }).getByRole('button', { name: 'Inspect draft generation', exact: true }).click()
    const mapping = page.getByRole('region', { name: 'Independent assertion mapping', exact: true })
    await mapping.getByRole('button', { name: 'Inspect assertion mapping', exact: true }).click()
    await expect(mapping.getByRole('button', { name: 'Review mapping in parts', exact: true })).toBeVisible({ timeout: 60_000 })
    expect(state.plans).toBe(0); expect(state.writes).toHaveLength(0)
    await mapping.getByRole('button', { name: 'Review mapping in parts', exact: true }).click()
    const panel = mapping.getByRole('region', { name: 'Partitioned assertion review', exact: true })
    const part = panel.getByRole('group', { name: 'Private mapping part', exact: true })
    await expect(part.getByRole('button', { name: 'Edit this part', exact: true })).toBeEnabled({ timeout: 60_000 })
    const final = panel.getByRole('group', { name: 'Final mapping confirmation', exact: true })
    await final.getByRole('button', { name: 'Inspect complete saved set', exact: true }).click()
    await expect(final).toContainText('No subset can be approved.')
    await expect(final.getByRole('button', { name: 'Finalize complete mapping', exact: true })).toHaveCount(0)
    if (theme === 'dark') {
      await part.getByRole('button', { name: 'Edit this part', exact: true }).click()
      const edit = part.getByRole('group', { name: 'Edit private assertion decisions', exact: true })
      await expect(edit.getByRole('textbox', { name: 'Assertion review reason', exact: true })).toHaveCount(8)
      await edit.getByRole('textbox', { name: 'Assertion review reason', exact: true }).first().fill('Independent edited original part')
      await edit.getByRole('checkbox').check()
      await edit.getByRole('button', { name: 'Save private part', exact: true }).click()
      await expect(part).toContainText('Private part saved', { timeout: 60_000 })
      expect(state.histories.get(0)).toHaveLength(2)
      expect('decisions' in state.writes[0] && state.writes[0].decisions.length).toBe(128)
      await part.getByRole('combobox', { name: 'Private part history', exact: true }).selectOption(state.histories.get(0)![0].revision.part_revision_id)
      await expect(part).toContainText('Historical private part; not current')
      await expect(part.getByRole('combobox', { name: 'Mapping decision', exact: true })).toHaveCount(0)
      await panel.getByRole('button', { name: 'Next part', exact: true }).click()
      await expect(part).toContainText('4 assertion pairs in this part.', { timeout: 60_000 })
    }
    await part.getByRole('button', { name: 'Edit this part', exact: true }).click()
    const edit = part.getByRole('group', { name: 'Edit private assertion decisions', exact: true })
    await expect(edit.getByRole('button', { name: 'Save private part', exact: true })).toBeDisabled()
    await decide(edit, 4, 'Independent synthetic exact review ')
    const consent = edit.getByRole('checkbox')
    await consent.check()
    await edit.getByRole('textbox', { name: 'Assertion review reason', exact: true }).last().fill('Changed after confirmation')
    await expect(consent).not.toBeChecked(); await expect(edit.getByRole('button', { name: 'Save private part', exact: true })).toBeDisabled()
    await consent.check(); state.loseAck = true
    const before = state.writes.length
    await edit.getByRole('button', { name: 'Save private part', exact: true }).click()
    await expect(part.getByRole('alert')).toContainText('no automatic retry', { timeout: 60_000 })
    expect(state.writes).toHaveLength(before + 1)
    await part.getByRole('button', { name: 'Reload private part', exact: true }).click()
    await expect(part).toContainText('Current private part; not final approval', { timeout: 60_000 })
    expect(state.writes).toHaveLength(before + 1)
    await final.getByRole('button', { name: 'Inspect complete saved set', exact: true }).click()
    await expect(final.getByRole('textbox', { name: 'Final review reason', exact: true })).toBeVisible()
    await final.getByRole('textbox', { name: 'Final review reason', exact: true }).fill('Independent final confirmation of all exact saved parts')
    await final.getByRole('checkbox').check()
    if (theme === 'light') {
      await part.getByRole('button', { name: 'Edit this part', exact: true }).click()
      await expect(final.getByRole('checkbox')).toHaveCount(0)
      await part.getByRole('button', { name: 'Reload private part', exact: true }).click()
      await expect(part).toContainText('Current private part; not final approval', { timeout: 60_000 })
      await final.getByRole('button', { name: 'Inspect complete saved set', exact: true }).click()
      await expect(final.getByRole('checkbox')).not.toBeChecked()
      await final.getByRole('textbox', { name: 'Final review reason', exact: true }).fill('Reconfirmed complete set after private editor reload')
      await final.getByRole('checkbox').check()
    }
    mkdirSync(resolve('output/playwright'), { recursive: true })
    await page.setViewportSize({ width: 390, height: 844 })
    await final.evaluate((node) => node.scrollIntoView({ block: 'start' }))
    await page.screenshot({ path: resolve(`output/playwright/mapping-staging-${theme}-mobile.png`) })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await final.getByRole('textbox', { name: 'Final review reason', exact: true }).fill('Updated independent final reason')
    await expect(final.getByRole('checkbox')).not.toBeChecked()
    await final.getByRole('checkbox').check()
    await final.getByRole('button', { name: 'Finalize complete mapping', exact: true }).click()
    await expect(mapping.getByLabel('Verified partitioned mapping', { exact: true })).toBeVisible({ timeout: 60_000 })
    expect(state.writes.filter((q) => q.policy_revision === 'nasus.test-design-mapping.v2')).toHaveLength(1)
    expect(base.history[0].assessment!.coverage.automated_count).toBe(0)
    expect(base.history[0].assessment!.coverage.passed_count).toBe(0)
    expect(base.generationWrites).toBe(0); expect(errors).toEqual([])
  } finally { if (!exweb) rmSync(source, { recursive: true, force: true }) }
})
test('independent QA uses private and final review without administrator model or job access', async ({ page, request }) => {
  test.setTimeout(300_000)
  const exweb = process.env.EXWEB_FIXTURE_ROOT, source = exweb ? resolve(exweb) : analysisSource(), forbidden: string[] = []
  try {
    const v = await generationScopeFixture(request, source), reviewer = await analysisAccount(request)
    const member = `${analysisApi}/v1/projects/${v.projectId}/members/${reviewer.userId}`
    expect((await request.put(member, { headers: v.owner.headers, data: { role: 'viewer' } })).ok()).toBeTruthy()
    const discovery = `${analysisApi}/v1/projects/${v.projectId}/quality/test-design-review-drafts`
    expect((await request.get(discovery, { headers: reviewer.headers })).status()).toBe(403)
    expect((await request.put(member, { headers: v.owner.headers, data: { role: 'qa_lead' } })).ok()).toBeTruthy()
    expect((await request.get(discovery, { headers: reviewer.headers })).ok()).toBeTruthy()
    const draft = await partitionedDraftFixture(v.scope), base = await installMappingProtocol(page, v.scope, draft)
    const state = await installStagingProtocol(page, draft, reviewer.userId, base.history)
    await page.route('**/quality/test-design-review-drafts?*', async (route) => {
      const params = new URL(route.request().url()).searchParams
      await route.fulfill({ json: { request: { project_id: v.projectId, after_id: params.get('after_id')!, limit: Number(params.get('limit')) },
        items: [{ metadata: draft.metadata, context_pin: draft.result.context_pin, scope_pin: draft.result.scope_pin }],
        next_after_id: null, can_review: true, generation_authorized: false, execution_authorized: false } })
    })
    page.on('request', (r) => {
      if (/\/quality\/test-design-jobs|\/settings\/model-configs\?route=chat/.test(r.url())
        || r.method() === 'POST' && r.postDataJSON()?.tool_id === 'query.quality.test_design_job') forbidden.push(r.url())
    })
    await page.addInitScript((token) => { localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en') }, reviewer.token)
    await page.goto(`/projects/${v.projectId}/knowledge`)
    const queue = page.getByRole('region', { name: 'Draft mapping review queue', exact: true })
    await queue.getByRole('button', { name: 'Review draft cases', exact: true }).click()
    await queue.getByRole('button', { name: `Inspect draft ${draft.metadata.generation_id} (1 cases)`, exact: true }).click()
    const mapping = queue.getByRole('region', { name: 'Independent assertion mapping', exact: true })
    await expect(queue.locator('[aria-label="Archived draft test cases"]')).toBeVisible({ timeout: 60_000 })
    await mapping.getByRole('button', { name: 'Inspect assertion mapping', exact: true }).click()
    await mapping.getByRole('button', { name: 'Review mapping in parts', exact: true }).click()
    const part = mapping.getByRole('group', { name: 'Private mapping part', exact: true })
    await part.getByRole('button', { name: 'Edit this part', exact: true }).click()
    const edit = part.getByRole('group', { name: 'Edit private assertion decisions', exact: true })
    await decide(edit, 4, 'Independent QA fixture ')
    await edit.getByRole('checkbox').check()
    await edit.getByRole('button', { name: 'Save private part', exact: true }).click()
    await expect(part).toContainText('Private part saved', { timeout: 60_000 })
    expect(state.histories.get(0)![0].revision.authority_actor).toBe(reviewer.userId)
    const final = mapping.getByRole('group', { name: 'Final mapping confirmation', exact: true })
    await final.getByRole('button', { name: 'Inspect complete saved set', exact: true }).click()
    await final.getByRole('textbox', { name: 'Final review reason', exact: true }).fill('Independent QA final fixture, never target execution')
    await final.getByRole('checkbox').check()
    await final.getByRole('button', { name: 'Finalize complete mapping', exact: true }).click()
    await expect(mapping.getByLabel('Verified partitioned mapping', { exact: true })).toBeVisible({ timeout: 60_000 })
    expect(base.history[0].revision.authority_actor).toBe(reviewer.userId)
    expect(state.writes).toHaveLength(2); expect(forbidden).toEqual([]); expect(base.generationWrites).toBe(0)
    expect(base.history[0].assessment!.coverage.executed_on_target_count).toBe(0)
  } finally { if (!exweb) rmSync(source, { recursive: true, force: true }) }
})
test('corrupt part hides the parent draft without a write or generation request', async ({ page, request }) => {
  test.setTimeout(300_000)
  const exweb = process.env.EXWEB_FIXTURE_ROOT, source = exweb ? resolve(exweb) : analysisSource()
  try {
    const v = await generationScopeFixture(request, source), draft = await partitionedDraftFixture(v.scope)
    const base = await installMappingProtocol(page, v.scope, draft), state = await installStagingProtocol(page, draft, v.owner.userId, base.history)
    state.corruptPart = true
    await page.addInitScript((token) => { localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en') }, v.owner.token)
    await page.goto(`/projects/${v.projectId}/knowledge`)
    await page.getByRole('button', { name: 'Inspect published context', exact: true }).click()
    await page.getByRole('button').filter({ hasText: v.contextId }).click()
    await page.getByRole('button', { name: 'Inspect test-design scope', exact: true }).click()
    await page.getByRole('region', { name: 'Pinned draft test generation', exact: true }).getByRole('button', { name: 'Inspect draft generation', exact: true }).click()
    const mapping = page.getByRole('region', { name: 'Independent assertion mapping', exact: true })
    await mapping.getByRole('button', { name: 'Inspect assertion mapping', exact: true }).click()
    await mapping.getByRole('button', { name: 'Review mapping in parts', exact: true }).click()
    await expect(page.locator('[aria-label="Archived draft test cases"]')).toHaveCount(0, { timeout: 60_000 })
    expect(state.writes).toHaveLength(0); expect(base.generationWrites).toBe(0)
  } finally { if (!exweb) rmSync(source, { recursive: true, force: true }) }
})
