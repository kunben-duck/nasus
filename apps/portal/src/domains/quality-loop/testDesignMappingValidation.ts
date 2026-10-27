import { generationDigest, generationEqual } from './testDesignGenerationValidation'
import { canonicalDigest as mappingDigest } from '../../shared/utils/canonicalDigest'
import { assessmentFromDecisions } from './testDesignMappingAssessment'
import { verifyPartitionedMappingArchive } from './testDesignMappingPartitionValidation'
export { mappingDigest }
import type { GenerationArchive } from './types/testDesignGeneration'
import type { AssertionReview, MappingArchive, MappingAssessment, MappingRevision, MappingView, RecordedMappingArchive } from './types/testDesignMapping'

function requireValue(value: unknown): asserts value { if (!value) throw new Error('Pinned mapping review could not be verified') }
const id = (value: unknown) => typeof value === 'string' && value.length > 0 && value.length <= 128
const text = (value: unknown) => typeof value === 'string' && !!value.trim() && [...value].length <= 2000
export function newAssertionReviews(draft: GenerationArchive): AssertionReview[] {
  return draft.result.proposal.cases.flatMap((item) => item.assertions.map((a) => ({ case_id: item.case_id,
    row_id: a.row_id, step_index: a.step_index, oracle_digest: a.oracle_digest, decision: 'defer' as const, reason: '' })))
}
export function mappingsValid(values: AssertionReview[], draft: GenerationArchive) {
  const expected = new Map(newAssertionReviews(draft).map((value) => [JSON.stringify([value.case_id, value.row_id]), value]))
  if (!Array.isArray(values) || values.length !== expected.size || values.length > 8192) return false
  const seen = new Set<string>()
  return values.every((value) => {
    const key = JSON.stringify([value.case_id, value.row_id]), assertion = expected.get(key)
    if (!assertion || seen.has(key) || !Number.isInteger(value.step_index) || value.step_index !== assertion.step_index
      || value.oracle_digest !== assertion.oracle_digest || !['accept', 'reject', 'defer'].includes(value.decision) || !text(value.reason)
      || Object.keys(value).length !== 6) return false
    seen.add(key); return true
  })
}
export function mappingAssessment(draft: GenerationArchive, values: AssertionReview[]): MappingAssessment {
  requireValue(mappingsValid(values, draft))
  return assessmentFromDecisions(draft, values)
}
function verifyRevision(revision: MappingRevision, draft: GenerationArchive) {
  const m = draft.metadata
  requireValue(revision && revision.project_id === m.project_id && revision.generation_id === m.generation_id
    && revision.generation_artifact_hash === m.artifact_hash && id(revision.revision_id) && id(revision.invocation_id)
    && id(revision.authority_actor) && generationDigest(revision.artifact_hash) && generationDigest(revision.request_hash)
    && typeof revision.recorded_at === 'string' && Number.isFinite(Date.parse(revision.recorded_at))
    && (revision.mapping_schema === undefined ? Object.keys(revision).length === 12
      : revision.mapping_schema === 'nasus.test-design-mapping-review.v2' && Object.keys(revision).length === 15
        && revision.status === 'reviewed' && generationDigest(revision.plan_digest) && generationDigest(revision.part_set_digest))
    && Number.isInteger(revision.sequence) && revision.sequence >= 1 && revision.sequence <= 1000
    && (revision.previous_revision_id === null || id(revision.previous_revision_id)) && ['reviewed', 'withdrawn'].includes(revision.status))
}
export async function verifyMappingArchive(value: unknown, draft: GenerationArchive, expected: MappingRevision): Promise<RecordedMappingArchive> {
  const v = value as MappingArchive, r = v?.revision, q = v?.request, c = v?.current_use, m = draft.metadata
  verifyRevision(r, draft)
  if (r.mapping_schema === 'nasus.test-design-mapping-review.v2') return verifyPartitionedMappingArchive(value, draft, expected)
  requireValue(generationEqual(r, expected) && q && c && v.historical_not_live === true
    && q.project_id === m.project_id && q.generation_id === m.generation_id && q.generation_artifact_hash === m.artifact_hash
    && q.expected_previous_revision_id === r.previous_revision_id && text(q.reason) && q.policy_revision === 'nasus.test-design-mapping.v1'
    && q.decision === (r.status === 'reviewed' ? 'review' : 'withdraw') && Object.keys(q).length === 8
    && Object.keys(v).length === 6 && Object.keys(c).length === 4
    && typeof c.scope_current === 'boolean' && typeof c.mapping_current === 'boolean' && typeof c.mapping_complete === 'boolean'
    && c.execution_authorized === false && (!c.mapping_current || c.scope_current && r.status === 'reviewed'))
  requireValue(generationEqual(v.generation_pin, { generation_id: m.generation_id, artifact_hash: m.artifact_hash,
    context_pin: draft.result.context_pin, scope_pin: draft.result.scope_pin, input_digest: draft.result.request.input_digest,
    proposal_hash: await mappingDigest(draft.result.proposal) }) && r.request_hash === await mappingDigest(q))
  requireValue(r.artifact_hash === await mappingDigest({ schema: 'nasus.test-design-mapping-review.v1',
    project_id: m.project_id, request: q, generation_pin: v.generation_pin, assessment: v.assessment,
    authority_actor: r.authority_actor, invocation_id: r.invocation_id, recorded_at: r.recorded_at }))
  if (q.decision === 'withdraw') requireValue(q.mappings === null && v.assessment === null && !c.mapping_current && !c.mapping_complete)
  else {
    requireValue(Array.isArray(q.mappings) && mappingsValid(q.mappings, draft))
    const assessment = mappingAssessment(draft, q.mappings)
    requireValue(generationEqual(v.assessment, assessment) && c.mapping_complete === (c.mapping_current && assessment.mapping_complete))
  }
  return v
}
export async function verifyMappingView(value: unknown, draft: GenerationArchive): Promise<MappingView> {
  const v = value as MappingView, m = draft.metadata
  requireValue(v && v.project_id === m.project_id && v.generation_id === m.generation_id && v.generation_artifact_hash === m.artifact_hash
    && typeof v.can_review === 'boolean' && typeof v.scope_current === 'boolean' && Array.isArray(v.history) && v.history.length <= 1000
    && Boolean(v.head) === Boolean(v.history.length) && Object.keys(v).length === 7)
  v.history.forEach((revision, index) => {
    verifyRevision(revision, draft)
    requireValue(revision.sequence === index + 1 && revision.previous_revision_id === (v.history[index - 1]?.revision_id ?? null)
      && (revision.status !== 'withdrawn' || v.history[index - 1]?.status === 'reviewed'))
  })
  if (v.head) {
    await verifyMappingArchive(v.head, draft, v.history.at(-1)!)
    requireValue(v.head.current_use.scope_current === v.scope_current
      && v.head.current_use.mapping_current === (v.scope_current && v.head.revision.status === 'reviewed'))
  }
  return v
}
