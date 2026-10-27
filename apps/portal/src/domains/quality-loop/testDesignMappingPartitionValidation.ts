import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { generationDigest, generationEqual } from './testDesignGenerationValidation'
import { assessmentFromDecisions } from './testDesignMappingAssessment'
import { mappingDigestChain, mappingGenerationPin, mappingInvariant, maxMappingParts, prepareMappingPlan } from './testDesignMappingPartitions'
import type { GenerationArchive } from './types/testDesignGeneration'
import type { AssertionReview, MappingRevision, PartitionedMappingArchive } from './types/testDesignMapping'

const id = (value: unknown) => typeof value === 'string' && !!value.trim() && [...value].length <= 128
function verifyClassifications(value: PartitionedMappingArchive, draft: GenerationArchive) {
  const rows = value.assessment?.coverage?.rows
  mappingInvariant(Array.isArray(rows) && rows.length === draft.result.proposal.coverage.rows.length)
  const cases = new Map(draft.result.proposal.cases.map((item) => [item.case_id, item]))
  const seen = new Set<string>(), decisions: Pick<AssertionReview, 'case_id' | 'row_id' | 'decision'>[] = []
  for (const [index, row] of rows.entries()) {
    mappingInvariant(row.row_id === draft.result.proposal.coverage.rows[index].row_id)
    for (const [decision, field] of [['accept', 'accepted_case_ids'], ['reject', 'rejected_case_ids'], ['defer', 'deferred_case_ids']] as const) {
      mappingInvariant(Array.isArray(row[field]))
      for (const caseId of row[field]) {
        const key = JSON.stringify([caseId, row.row_id])
        mappingInvariant(!seen.has(key) && cases.get(caseId)?.assertions.some((a) => a.row_id === row.row_id))
        seen.add(key); decisions.push({ case_id: caseId, row_id: row.row_id, decision })
      }
    }
  }
  mappingInvariant(decisions.length === draft.result.proposal.cases.reduce((sum, item) => sum + item.assertions.length, 0))
  const assessment = assessmentFromDecisions(draft, decisions)
  mappingInvariant(generationEqual(value.assessment, assessment))
  return assessment
}
export async function verifyPartitionedMappingArchive(value: unknown, draft: GenerationArchive, expected: MappingRevision): Promise<PartitionedMappingArchive> {
  const v = value as PartitionedMappingArchive, r = v?.revision, q = v?.request, c = v?.current_use, m = draft.metadata
  mappingInvariant(v && q && c && generationEqual(r, expected) && Object.keys(v).length === 8 && Object.keys(q).length === 9
    && q.project_id === m.project_id && q.generation_id === m.generation_id && q.generation_artifact_hash === m.artifact_hash
    && q.expected_previous_revision_id === r.previous_revision_id && q.decision === 'review'
    && q.policy_revision === 'nasus.test-design-mapping.v2' && typeof q.reason === 'string' && !!q.reason.trim() && [...q.reason].length <= 2000
    && q.plan_digest === r.plan_digest && q.part_set_digest === r.part_set_digest && v.historical_not_live === true
    && Object.keys(c).length === 4 && typeof c.scope_current === 'boolean' && typeof c.mapping_current === 'boolean'
    && typeof c.mapping_complete === 'boolean' && c.execution_authorized === false && (!c.mapping_current || c.scope_current))
  const { plan, partDigests } = await prepareMappingPlan(draft, r.previous_revision_id)
  mappingInvariant(generationEqual(v.plan, plan) && q.plan_digest === plan.plan_digest)
  const set = v.part_set, members = set?.members
  mappingInvariant(Array.isArray(members) && members.length === plan.part_count && members.length > 0 && members.length <= maxMappingParts)
  const seen = new Set<string>(), hashes: string[] = []
  for (const [index, member] of members.entries()) {
    mappingInvariant(member && Object.keys(member).length === 5 && member.sequence === index && id(member.part_revision_id)
      && !seen.has(member.part_revision_id) && member.part_digest === partDigests[index]
      && generationDigest(member.artifact_hash) && generationDigest(member.request_hash))
    seen.add(member.part_revision_id); hashes.push(await canonicalDigest(member))
  }
  const body = { schema: 'nasus.test-design-mapping-part-set.v1', plan_digest: plan.plan_digest, authority_actor: r.authority_actor,
    part_count: plan.part_count, assertion_count: plan.assertion_count, members_digest: await mappingDigestChain(hashes) }
  mappingInvariant(generationEqual(set, { ...body, part_set_digest: await canonicalDigest(body), members })
    && set.part_set_digest === q.part_set_digest && generationEqual(v.generation_pin, await mappingGenerationPin(draft)))
  const assessment = verifyClassifications(v, draft)
  mappingInvariant(c.mapping_complete === (c.mapping_current && assessment.mapping_complete)
    && r.request_hash === await canonicalDigest(q)
    && r.artifact_hash === await canonicalDigest({ schema: 'nasus.test-design-mapping-review.v2', project_id: m.project_id,
      request: q, generation_pin: v.generation_pin, plan: v.plan, part_set: set, assessment,
      authority_actor: r.authority_actor, invocation_id: r.invocation_id, recorded_at: r.recorded_at }))
  return v
}
