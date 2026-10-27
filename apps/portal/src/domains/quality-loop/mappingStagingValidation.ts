import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { generationEqual, generationDigest } from './testDesignGenerationValidation'
import { compareMappingIds, mappingInvariant } from './testDesignMappingPartitions'
import type { GenerationArchive } from './types/testDesignGeneration'
import type { AssertionReview } from './types/testDesignMapping'
import type { MappingWorkspace, MappingPart, StagedPartRevision, StagedPartHead, StagedPartArchive } from './types/mappingStaging'

export const mappingId = (v: unknown) => typeof v === 'string' && !!v.trim() && v === v.trim() && [...v].length <= 128 && [...v].every((c) => c.codePointAt(0)! >= 32)
export const mappingReason = (v: unknown) => typeof v === 'string' && !!v.trim() && [...v].length <= 2000
export function mappingQuery(workspace: MappingWorkspace) {
  const pin = workspace.plan.generation_pin
  return { project_id: pin.project_id, generation_id: pin.generation_id, generation_artifact_hash: pin.artifact_hash }
}
export function originalPart(draft: GenerationArchive, workspace: MappingWorkspace, sequence: number): MappingPart {
  mappingInvariant(Number.isInteger(sequence) && sequence >= 0 && sequence < workspace.plan.part_count)
  const start = sequence * 128, end = start + 128, assertions: MappingPart['assertions'] = []
  let offset = 0
  for (const item of [...draft.result.proposal.cases].sort((a, b) => compareMappingIds(a.case_id, b.case_id))) {
    for (const a of [...item.assertions].sort((a, b) => compareMappingIds(a.row_id, b.row_id))) {
      if (offset >= start && offset < end) assertions.push({ case_id: item.case_id, row_id: a.row_id, step_index: a.step_index, oracle_digest: a.oracle_digest })
      offset++
    }
    if (offset >= end) break
  }
  return { schema: 'nasus.test-design-mapping-part.v1', sequence, assertions, part_digest: workspace.partDigests[sequence],
    plan_digest: workspace.plan.plan_digest, execution_authorized: false }
}
export function partDecisionsValid(part: MappingPart, values: AssertionReview[]) {
  return Array.isArray(values) && values.length === part.assertions.length && values.length >= 1 && values.length <= 128
    && values.every((v, i) => v && Object.keys(v).length === 6 && mappingReason(v.reason) && ['accept', 'reject', 'defer'].includes(v.decision)
      && generationEqual({ case_id: v.case_id, row_id: v.row_id, step_index: v.step_index, oracle_digest: v.oracle_digest }, part.assertions[i]))
}
export function verifyPartRevision(v: StagedPartRevision, workspace: MappingWorkspace, part: MappingPart) {
  mappingInvariant(v && Object.keys(v).length === 17 && Object.entries(mappingQuery(workspace)).every(([k, x]) => v[k as keyof StagedPartRevision] === x)
    && v.plan_digest === workspace.plan.plan_digest && v.sequence === part.sequence && v.part_digest === part.part_digest
    && v.expected_previous_revision_id === workspace.plan.expected_previous_revision_id && v.authority_actor === workspace.actorId
    && mappingId(v.part_revision_id) && mappingId(v.invocation_id) && generationDigest(v.artifact_hash) && generationDigest(v.request_hash)
    && Number.isInteger(v.revision_sequence) && v.revision_sequence >= 1 && v.revision_sequence <= 1000
    && (v.expected_previous_part_revision_id === null ? v.revision_sequence === 1
      : mappingId(v.expected_previous_part_revision_id) && v.expected_previous_part_revision_id !== v.part_revision_id && v.revision_sequence > 1)
    && typeof v.recorded_at === 'string' && Number.isFinite(Date.parse(v.recorded_at)) && v.assertion_mapped === false && v.execution_authorized === false)
}
export function verifyPartHead(value: unknown, workspace: MappingWorkspace, part: MappingPart): StagedPartHead {
  const v = value as StagedPartHead
  mappingInvariant(v && Object.keys(v).length === 14 && Object.entries(mappingQuery(workspace)).every(([k, x]) => v[k as keyof StagedPartHead] === x)
    && v.plan_digest === workspace.plan.plan_digest && v.sequence === part.sequence && v.authority_actor === workspace.actorId
    && typeof v.scope_current === 'boolean' && v.scope_current === workspace.scopeCurrent && Number.isInteger(v.history_count)
    && v.history_count >= 0 && v.history_count <= 1000 && Array.isArray(v.history) && v.history.length === Math.min(v.history_count, 5)
    && new Set(v.history.map((r) => r.part_revision_id)).size === v.history.length
    && v.history_truncated === (v.history_count > 5) && v.assertion_mapped === false && v.review_authorized === false && v.execution_authorized === false)
  v.history.forEach((r, i) => {
    verifyPartRevision(r, workspace, part)
    mappingInvariant(r.revision_sequence === v.history_count - v.history.length + i + 1
      && (i === 0 || r.expected_previous_part_revision_id === v.history[i - 1].part_revision_id))
  })
  mappingInvariant(v.history_count === 0 ? v.head === null : generationEqual(v.head, v.history.at(-1)))
  return v
}
export async function verifyStagedArchive(value: unknown, workspace: MappingWorkspace, part: MappingPart, expected: StagedPartRevision): Promise<StagedPartArchive> {
  const v = value as StagedPartArchive, q = v?.request, c = v?.current_use
  verifyPartRevision(v?.revision, workspace, part)
  mappingInvariant(q && c && Object.keys(v).length === 5 && Object.keys(q).length === 10 && Object.keys(c).length === 5
    && generationEqual(v.revision, expected) && generationEqual(v.plan, workspace.plan) && v.historical_not_live === true
    && Object.entries(mappingQuery(workspace)).every(([k, x]) => q[k as keyof typeof q] === x)
    && q.plan_digest === part.plan_digest && q.sequence === part.sequence && q.part_digest === part.part_digest
    && q.expected_previous_revision_id === workspace.plan.expected_previous_revision_id
    && q.expected_previous_part_revision_id === expected.expected_previous_part_revision_id
    && q.policy_revision === 'nasus.test-design-mapping-staging.v1' && partDecisionsValid(part, q.decisions)
    && c.scope_current === workspace.scopeCurrent && typeof c.part_current === 'boolean' && (!c.part_current || c.scope_current)
    && c.assertion_mapped === false && c.review_authorized === false && c.execution_authorized === false)
  mappingInvariant(expected.request_hash === await canonicalDigest(q) && expected.artifact_hash === await canonicalDigest({
    schema: 'nasus.test-design-mapping-staged-part.v1', project_id: q.project_id, request: q, plan: v.plan,
    authority_actor: expected.authority_actor, invocation_id: expected.invocation_id, recorded_at: expected.recorded_at,
    assertion_mapped: false, execution_authorized: false }))
  return v
}
