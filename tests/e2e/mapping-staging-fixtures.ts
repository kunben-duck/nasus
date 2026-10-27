import { expect, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { canonicalDigest } from '../../apps/portal/src/shared/utils/canonicalDigest'
import { assessmentFromDecisions } from '../../apps/portal/src/domains/quality-loop/testDesignMappingAssessment'
import { mappingDigestChain, mappingGenerationPin, prepareMappingPlan } from '../../apps/portal/src/domains/quality-loop/testDesignMappingPartitions'
import { mappingQuery, originalPart } from '../../apps/portal/src/domains/quality-loop/mappingStagingValidation'
import { resignPartitionedArchive } from './test-design-mapping-partition-fixtures'
import type { GenerationArchive } from '../../apps/portal/src/domains/quality-loop/types/testDesignGeneration'
import type { MappingFinalize, PartitionedMappingArchive, RecordedMappingArchive } from '../../apps/portal/src/domains/quality-loop/types/testDesignMapping'
import type { MappingWorkspace, MappingPartStage, StagedPartArchive, StagedPartHead } from '../../apps/portal/src/domains/quality-loop/types/mappingStaging'

export async function stagingWorkspaceFixture(draft: GenerationArchive, actorId = 'explicit-independent-staging-reviewer') {
  return { ...await prepareMappingPlan(draft, null), actorId, scopeCurrent: true }
}
export async function stagedArchiveFixture(workspace: MappingWorkspace, input: MappingPartStage, previous: StagedPartArchive | null, invocation_id = randomUUID()): Promise<StagedPartArchive> {
  const recorded_at = new Date().toISOString()
  const body = { schema: 'nasus.test-design-mapping-staged-part.v1', project_id: input.project_id, request: input, plan: workspace.plan,
    authority_actor: workspace.actorId, invocation_id, recorded_at, assertion_mapped: false, execution_authorized: false }
  const { decisions: _decisions, policy_revision: _policy, ...pins } = input
  return { revision: { ...pins, part_revision_id: randomUUID(), revision_sequence: (previous?.revision.revision_sequence ?? 0) + 1,
    artifact_hash: await canonicalDigest(body), request_hash: await canonicalDigest(input), authority_actor: workspace.actorId,
    invocation_id, recorded_at, assertion_mapped: false, execution_authorized: false }, request: input, plan: workspace.plan,
    historical_not_live: true, current_use: { scope_current: true, part_current: true, assertion_mapped: false, review_authorized: false, execution_authorized: false } }
}
export function stagingRequest(workspace: MappingWorkspace, part: ReturnType<typeof originalPart>, previous: string | null = null): MappingPartStage {
  return { ...mappingQuery(workspace), plan_digest: part.plan_digest, sequence: part.sequence, part_digest: part.part_digest,
    expected_previous_revision_id: workspace.plan.expected_previous_revision_id, expected_previous_part_revision_id: previous,
    decisions: part.assertions.map((v) => ({ ...v, decision: 'accept', reason: 'Explicit synthetic saved decision; not product-owner gold' })),
    policy_revision: 'nasus.test-design-mapping-staging.v1' }
}
export function stagedHeadFixture(workspace: MappingWorkspace, sequence: number, history: StagedPartArchive[]): StagedPartHead {
  return { ...mappingQuery(workspace), plan_digest: workspace.plan.plan_digest, sequence, authority_actor: workspace.actorId,
    head: history.at(-1)?.revision ?? null, history: history.slice(-5).map((a) => a.revision), history_count: history.length,
    history_truncated: history.length > 5, scope_current: true, assertion_mapped: false, review_authorized: false, execution_authorized: false }
}
export async function stagedCommitment(workspace: MappingWorkspace, heads: StagedPartArchive[]) {
  const members = heads.map(({ revision: r }) => ({ sequence: r.sequence, part_revision_id: r.part_revision_id,
    artifact_hash: r.artifact_hash, request_hash: r.request_hash, part_digest: r.part_digest }))
  const body = { schema: 'nasus.test-design-mapping-part-set.v1' as const, plan_digest: workspace.plan.plan_digest,
    authority_actor: workspace.actorId, part_count: workspace.plan.part_count, assertion_count: workspace.plan.assertion_count,
    members_digest: await mappingDigestChain(await Promise.all(members.map(canonicalDigest))) }
  return { ...body, part_set_digest: await canonicalDigest(body), members }
}
// Explicit browser protocol fixture. No backend final authority, real model or target execution is claimed.
export async function installStagingProtocol(page: Page, draft: GenerationArchive, actorId: string, mappingHistory: RecordedMappingArchive[]) {
  const workspace = await stagingWorkspaceFixture(draft, actorId), histories = new Map<number, StagedPartArchive[]>()
  const state = { workspace, histories, writes: [] as (MappingPartStage | MappingFinalize)[], plans: 0, previews: 0,
    failRead: false, corruptPart: false, loseAck: false, staleFinal: false }
  const pending = new Map<string, { tool: string; input: MappingPartStage | MappingFinalize }>()
  const tail = (sequence: number) => histories.get(sequence)?.at(-1) ?? null
  await page.route(`**/test-design-results/${draft.metadata.generation_id}/mapping-plan?*`, async (route) => {
    state.plans++
    if (state.failRead) return route.fulfill({ status: 403, json: { detail: 'Explicit source revocation fixture' } })
    await route.fulfill({ json: { ...mappingQuery(workspace), plan: workspace.plan, part: null, scope_current: true,
      historical_not_live: true, review_authorized: false, execution_authorized: false } })
  })
  await page.route(`**/test-design-results/${draft.metadata.generation_id}/mapping-parts/*?*`, async (route) => {
    const sequence = Number(new URL(route.request().url()).pathname.split('/').at(-1)), part = originalPart(draft, workspace, sequence)
    if (state.failRead) return route.fulfill({ status: 403, json: { detail: 'Explicit source revocation fixture' } })
    if (state.corruptPart) part.assertions[0].oracle_digest = 'sha256:' + '0'.repeat(64)
    await route.fulfill({ json: { ...mappingQuery(workspace), plan: workspace.plan, part, scope_current: true,
      historical_not_live: true, review_authorized: false, execution_authorized: false } })
  })
  await page.route(`**/test-design-results/${draft.metadata.generation_id}/mapping-parts/*/staged?*`, async (route) => {
    const sequence = Number(new URL(route.request().url()).pathname.split('/').at(-2))
    await route.fulfill({ json: stagedHeadFixture(workspace, sequence, histories.get(sequence) ?? []) })
  })
  await page.route('**/quality/test-design-mapping-parts/*', async (route) => {
    const id = new URL(route.request().url()).pathname.split('/').at(-1)
    const value = [...histories.values()].flat().find((a) => a.revision.part_revision_id === id)!
    const current = value.revision.part_revision_id === tail(value.revision.sequence)?.revision.part_revision_id
    await route.fulfill({ json: { ...value, current_use: { ...value.current_use, part_current: current } } })
  })
  await page.route(`**/test-design-results/${draft.metadata.generation_id}/mapping-finalization?*`, async (route) => {
    state.previews++
    if (mappingHistory.length) return route.fulfill({ status: 409, json: { detail: 'Mapping head changed fixture' } })
    const heads = Array.from({ length: workspace.plan.part_count }, (_, i) => tail(i)).filter((a): a is StagedPartArchive => !!a)
    const ready = heads.length === workspace.plan.part_count, set = ready ? await stagedCommitment(workspace, heads) : null
    const { members: _members, ...commitment } = set ?? { members: [] }
    await route.fulfill({ json: { ...mappingQuery(workspace), plan_digest: workspace.plan.plan_digest, expected_previous_revision_id: null,
      authority_actor: actorId, part_count: workspace.plan.part_count, saved_part_count: heads.length, assertion_count: workspace.plan.assertion_count,
      part_set: ready ? commitment : null, ready_for_confirmation: ready, scope_current: true, review_authorized: false, execution_authorized: false } })
  })
  await page.route('**/v1/tool-invocations', async (route) => {
    const body = route.request().method() === 'POST' ? route.request().postDataJSON() : null
    if (!['quality.test_design_mapping.stage_part', 'quality.test_design_mapping.finalize'].includes(body?.tool_id)) return route.fallback()
    expect(body.input.project_id).toBe(draft.metadata.project_id)
    const id = randomUUID(), input = structuredClone(body.input)
    state.writes.push(input); pending.set(id, { tool: body.tool_id, input })
    await route.fulfill({ json: { id, tool_id: body.tool_id, status: 'waiting_confirmation', input_payload: input } })
  })
  await page.route('**/v1/tool-invocations/*/confirm', async (route) => {
    const id = new URL(route.request().url()).pathname.split('/').at(-2)!, command = pending.get(id)
    if (!command) return route.fallback()
    pending.delete(id)
    const { input, tool } = command
    if (tool.endsWith('finalize') && state.staleFinal) return route.fulfill({ json: { id, tool_id: tool, status: 'failed', input_payload: input,
      result: { followup_reason: 'test_design_mapping_changed' } } })
    let ref: string
    if ('decisions' in input) {
      expect(input.expected_previous_part_revision_id).toBe(tail(input.sequence)?.revision.part_revision_id ?? null)
      const value = await stagedArchiveFixture(workspace, input, tail(input.sequence), id)
      histories.set(input.sequence, [...histories.get(input.sequence) ?? [], value]); ref = 'test_design_mapping_part:' + value.revision.part_revision_id
    } else {
      const heads = Array.from({ length: workspace.plan.part_count }, (_, i) => tail(i)!)
      const set = await stagedCommitment(workspace, heads)
      expect(input.part_set_digest).toBe(set.part_set_digest)
      const value: PartitionedMappingArchive = { revision: { ...mappingQuery(workspace), revision_id: randomUUID(), previous_revision_id: null,
        sequence: 1, status: 'reviewed', artifact_hash: '', request_hash: '', authority_actor: actorId, invocation_id: id,
        recorded_at: new Date().toISOString(), mapping_schema: 'nasus.test-design-mapping-review.v2', plan_digest: workspace.plan.plan_digest, part_set_digest: set.part_set_digest },
        request: input, generation_pin: await mappingGenerationPin(draft), plan: workspace.plan, part_set: set,
        assessment: assessmentFromDecisions(draft, heads.flatMap((a) => a.request.decisions)), historical_not_live: true,
        current_use: { scope_current: true, mapping_current: true, mapping_complete: true, execution_authorized: false } }
      await resignPartitionedArchive(value); mappingHistory.push(value); ref = 'test_design_mapping:' + value.revision.revision_id
    }
    const lost = state.loseAck; state.loseAck = false
    await route.fulfill({ json: { id, tool_id: tool, status: lost ? 'failed' : 'completed', input_payload: { ...input, confirmed_by_user: true },
      result: lost ? { object_refs: [] } : { object_refs: [ref] } } })
  })
  return state
}
