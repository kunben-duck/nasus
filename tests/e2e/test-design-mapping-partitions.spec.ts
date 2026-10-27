import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdirSync, rmSync } from 'node:fs'
import { resolve } from 'node:path'
import { analysisApi, analysisSource } from './source-analysis-fixtures'
import { generationScopeFixture } from './test-design-generation-fixtures'
import { installMappingProtocol } from './test-design-mapping-fixtures'
import { partitionedArchiveFixture, partitionedDecisions, partitionedDraftFixture, resignPartitionedArchive } from './test-design-mapping-partition-fixtures'
import { mappingsValid, verifyMappingArchive, verifyMappingView } from '../../apps/portal/src/domains/quality-loop/testDesignMappingValidation'
import { mappingGenerationPin } from '../../apps/portal/src/domains/quality-loop/testDesignMappingPartitions'
import type { ScopeArchive } from '../../apps/portal/src/domains/quality-loop/types/testDesignScope'

function specimenScope() {
  const hash = 'sha256:' + 'a'.repeat(64), oracle = { preconditions: 'Synthetic source', action: 'Inspect response', observation: 'HTTP status', expected_result: '200' }
  return { revision: { project_id: 'partition-fixture', revision_id: 'scope', artifact_hash: hash, request_hash: hash },
    context_pin: { context_id: 'context', artifact_hash: hash, input_digest: hash, image_revision_id: 'image', image_artifact_hash: hash },
    assessment: { constraint_ids: ['ac', 'rule'] }, request: { contract: { examples: [{ positive: oracle }, { positive: oracle }] } } } as unknown as ScopeArchive
}
test('partitioned archive matches Python commitments, classifications and canonical artifact', async () => {
  const draft = await partitionedDraftFixture(specimenScope(), 2)
  draft.result.proposal.cases[0].case_id = 'case-\ufffd'
  draft.result.proposal.cases[1].case_id = 'case-\ud83e\udd86'
  for (const row of draft.result.proposal.coverage.rows) {
    row.planned_case_ids = draft.result.proposal.cases.map((item) => item.case_id)
    row.proposed_assertion_case_ids = [...row.planned_case_ids]
  }
  const archive = await partitionedArchiveFixture(draft)
  const python = execFileSync(resolve('.venv/bin/python'), ['-c', [
    'import json, sys',
    'from apps.api.app.domain.quality_loop.mapping_partitions import prepare_mapping_partitions',
    'from apps.api.app.domain.quality_loop.mapping_part_sets import part_set_commitment',
    'from apps.api.app.domain.quality_loop.test_design_mapping import assess_mappings',
    'from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest',
    'v = json.load(sys.stdin)',
    'plan, _ = prepare_mapping_partitions(v["proposal"], v["pin"], None)',
    'commitment = part_set_commitment(plan, v["actor"], v["members"])',
    'assessment = assess_mappings(v["proposal"], v["decisions"])',
    'print(json.dumps({"plan": plan, "commitment": commitment, "assessment": assessment, "artifact_hash": acceptance_digest(v["body"])}, ensure_ascii=False))',
  ].join('\n')], { encoding: 'utf8', input: JSON.stringify({ proposal: draft.result.proposal, pin: { project_id: draft.metadata.project_id, ...await mappingGenerationPin(draft) },
    actor: archive.revision.authority_actor, members: archive.part_set.members, decisions: partitionedDecisions(draft),
    body: { schema: 'nasus.test-design-mapping-review.v2', project_id: draft.metadata.project_id, request: archive.request,
      generation_pin: archive.generation_pin, plan: archive.plan, part_set: archive.part_set, assessment: archive.assessment,
      authority_actor: archive.revision.authority_actor, invocation_id: archive.revision.invocation_id, recorded_at: archive.revision.recorded_at } }) })
  const expected = JSON.parse(python), { members: _members, ...commitment } = archive.part_set
  expect(archive.plan).toEqual(expected.plan); expect(commitment).toEqual(expected.commitment)
  expect(archive.assessment).toEqual(expected.assessment); expect(archive.revision.artifact_hash).toBe(expected.artifact_hash)
  await verifyMappingArchive(archive, draft, archive.revision)
})
test('all 9000 original pairs remain verifiable beyond the unchanged v1 limit', async () => {
  test.setTimeout(60_000)
  const draft = await partitionedDraftFixture(specimenScope(), 2250), original = structuredClone(draft)
  const archive = await partitionedArchiveFixture(draft)
  expect(archive.plan.assertion_count).toBe(9000); expect(archive.part_set.members).toHaveLength(71)
  expect(mappingsValid(partitionedDecisions(draft), draft)).toBe(false)
  await verifyMappingArchive(archive, draft, archive.revision)
  expect(archive.assessment.accepted_assertion_count).toBe(8998)
  expect(draft).toEqual(original)
  const missingLast = structuredClone(archive)
  missingLast.part_set.members.pop(); await resignPartitionedArchive(missingLast)
  await expect(verifyMappingArchive(missingLast, draft, missingLast.revision)).rejects.toThrow()
})
test('re-signed missing, duplicated, foreign or unearned authority remains rejected', async () => {
  const draft = await partitionedDraftFixture(specimenScope(), 40), archive = await partitionedArchiveFixture(draft)
  for (const fault of ['last-part', 'part-digest', 'member-key', 'decision-missing', 'decision-duplicate', 'foreign-case', 'passed', 'scope', 'actor', 'policy', 'raw-decision']) {
    const bad = structuredClone(archive), row = bad.assessment.coverage.rows[0]
    if (fault === 'last-part') bad.part_set.members.pop()
    if (fault === 'part-digest') bad.part_set.members.at(-1)!.part_digest = 'sha256:' + '0'.repeat(64)
    if (fault === 'member-key') Object.assign(bad.part_set.members[0], { reason: 'Private draft leak' })
    if (fault === 'decision-missing') row.rejected_case_ids = []
    if (fault === 'decision-duplicate') row.deferred_case_ids.push(row.rejected_case_ids[0])
    if (fault === 'foreign-case') row.accepted_case_ids[0] = 'foreign-case'
    if (fault === 'passed') Object.assign(bad.assessment.coverage, { passed_count: 1 })
    if (fault === 'scope') bad.generation_pin.scope_pin.artifact_hash = 'sha256:' + '0'.repeat(64)
    if (fault === 'actor') bad.revision.authority_actor = 'foreign-authority'
    if (fault === 'policy') Object.assign(bad.request, { policy_revision: 'nasus.test-design-mapping.v1' })
    if (fault === 'raw-decision') Object.assign(bad.request, { mappings: [] })
    await resignPartitionedArchive(bad)
    await expect(verifyMappingArchive(bad, draft, bad.revision), fault).rejects.toThrow()
  }
  const history = { project_id: draft.metadata.project_id, generation_id: draft.metadata.generation_id,
    generation_artifact_hash: draft.metadata.artifact_hash, head: archive, history: [archive.revision], can_review: true, scope_current: true }
  await verifyMappingView(history, draft)
  archive.current_use.mapping_current = false
  await expect(verifyMappingView(history, draft)).rejects.toThrow()
})

for (const theme of ['light', 'dark']) test(`complete partitioned history, withdrawal, private reasons and revocation (${theme})`, async ({ page, request }) => {
  test.setTimeout(300_000)
  const exweb = process.env.EXWEB_FIXTURE_ROOT, source = exweb ? resolve(exweb) : analysisSource(), errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  try {
    const v = await generationScopeFixture(request, source), draft = await partitionedDraftFixture(v.scope)
    const state = await installMappingProtocol(page, v.scope, draft), archived = await partitionedArchiveFixture(draft)
    state.history.push(archived)
    expect((await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme } })).ok()).toBeTruthy()
    await page.addInitScript((token) => { localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en') }, v.owner.token)
    await page.goto(`/projects/${v.projectId}/knowledge`)
    await page.getByRole('button', { name: 'Inspect published context', exact: true }).click()
    await page.getByRole('button').filter({ hasText: v.contextId }).click()
    await page.getByRole('button', { name: 'Inspect test-design scope', exact: true }).click()
    const generation = page.getByRole('region', { name: 'Pinned draft test generation', exact: true })
    await generation.getByRole('button', { name: 'Inspect draft generation', exact: true }).click()
    await expect(page.locator('[aria-label="Archived draft test cases"]')).toBeVisible({ timeout: 60_000 })
    const mapping = page.getByRole('region', { name: 'Independent assertion mapping', exact: true })
    await mapping.getByRole('button', { name: 'Inspect assertion mapping', exact: true }).click()
    await expect(mapping.getByLabel('Verified partitioned mapping', { exact: true })).toBeVisible({ timeout: 60_000 })
    await expect(mapping).toContainText('1 immutable parts bind all 4 assertion pairs')
    await expect(mapping.getByRole('combobox', { name: 'Mapping decision', exact: true })).toHaveCount(0)
    expect(state.writes).toHaveLength(0)
    mkdirSync(resolve('output/playwright'), { recursive: true })
    await page.setViewportSize({ width: 390, height: 844 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await mapping.getByLabel('Verified partitioned mapping', { exact: true }).evaluate((node) => node.scrollIntoView({ block: 'start' }))
    await page.screenshot({ path: resolve(`output/playwright/partitioned-mapping-${theme}-mobile.png`) })
    await mapping.getByRole('button', { name: 'Withdraw mapping', exact: true }).click()
    const form = mapping.getByRole('group', { name: 'New mapping decision', exact: true })
    await form.getByRole('textbox', { name: 'Review reason', exact: true }).fill('Independent withdrawal of this exact v2 head')
    await form.getByRole('checkbox', { name: 'I confirm withdrawal of this exact mapping head.', exact: true }).check()
    await form.getByRole('button', { name: 'Record mapping decision', exact: true }).click()
    await expect(mapping).toContainText('Withdrawn mapping')
    expect(state.writes).toHaveLength(1); expect(state.writes[0].expected_previous_revision_id).toBe(archived.revision.revision_id)
    await mapping.getByRole('combobox', { name: 'Mapping history', exact: true }).selectOption(archived.revision.revision_id)
    await expect(mapping).toContainText('Historical mapping; not current')
    await expect(mapping.getByLabel('Verified partitioned mapping', { exact: true })).toBeVisible()
    state.failRead = true
    await mapping.getByRole('button', { name: 'Reload mapping history', exact: true }).click()
    await expect(page.locator('[aria-label="Archived draft test cases"]')).toHaveCount(0)
    expect(state.generationWrites).toBe(0); expect(errors).toEqual([])
  } finally { if (!exweb) rmSync(source, { recursive: true, force: true }) }
})
