import { randomUUID } from 'node:crypto'
import { generationArchiveFixture, generationBudgetFixture, generationPreviewFixture } from './test-design-generation-fixtures'
import { assessmentFromDecisions } from '../../apps/portal/src/domains/quality-loop/testDesignMappingAssessment'
import { canonicalDigest } from '../../apps/portal/src/shared/utils/canonicalDigest'
import { mappingDigestChain, mappingGenerationPin, prepareMappingPlan } from '../../apps/portal/src/domains/quality-loop/testDesignMappingPartitions'
import type { GenerationArchive, GenerationJob } from '../../apps/portal/src/domains/quality-loop/types/testDesignGeneration'
import type { AssertionReview, PartitionedMappingArchive } from '../../apps/portal/src/domains/quality-loop/types/testDesignMapping'
import type { ScopeArchive } from '../../apps/portal/src/domains/quality-loop/types/testDesignScope'

export async function partitionedDraftFixture(scope: ScopeArchive, caseCount = 1) {
  const prepared = generationPreviewFixture({ project_id: scope.revision.project_id, scope_revision_id: scope.revision.revision_id,
    scope_artifact_hash: scope.revision.artifact_hash, model_config_id: 'ui-partition-protocol-model', budget: generationBudgetFixture })
  const job = { project_id: scope.revision.project_id, invocation_id: 'ui-partition-generation', source_invocation_id: 'ui-partition-generation',
    generation_id: 'ui-partition-draft' } as GenerationJob
  const draft = generationArchiveFixture(scope, job, prepared.request), original = draft.result.proposal.cases[0]
  for (const assertion of original.assertions) {
    assertion.oracle_digest = await canonicalDigest(assertion.oracle)
    draft.result.proposal.coverage.rows.find((row) => row.row_id === assertion.row_id)!.oracle_digest = assertion.oracle_digest
  }
  draft.result.proposal.cases = Array.from({ length: caseCount }, (_, index) => ({ ...structuredClone(original), case_id: `ui-partition-case-${String(index).padStart(5, '0')}` }))
  for (const row of draft.result.proposal.coverage.rows) {
    row.planned_case_ids = draft.result.proposal.cases.map((item) => item.case_id)
    row.proposed_assertion_case_ids = [...row.planned_case_ids]
  }
  draft.metadata.case_count = caseCount
  draft.metadata.artifact_hash = await canonicalDigest(draft.result)
  return draft
}
export function partitionedDecisions(draft: GenerationArchive): AssertionReview[] {
  return draft.result.proposal.cases.flatMap((item) => item.assertions.map((assertion) => ({ case_id: item.case_id,
    row_id: assertion.row_id, step_index: assertion.step_index, oracle_digest: assertion.oracle_digest,
    decision: 'accept' as AssertionReview['decision'], reason: 'Explicit synthetic independent fixture, not product-owner approval' })))
    .map((value, index) => ({ ...value, decision: index === 0 ? 'reject' : index === 1 ? 'defer' : 'accept' }))
}
export async function resignPartitionedArchive(value: PartitionedMappingArchive) {
  const r = value.revision
  r.request_hash = await canonicalDigest(value.request)
  r.artifact_hash = await canonicalDigest({ schema: 'nasus.test-design-mapping-review.v2', project_id: r.project_id,
    request: value.request, generation_pin: value.generation_pin, plan: value.plan, part_set: value.part_set, assessment: value.assessment,
    authority_actor: r.authority_actor, invocation_id: r.invocation_id, recorded_at: r.recorded_at })
}
export async function partitionedArchiveFixture(draft: GenerationArchive, previous: string | null = null, sequence = 1): Promise<PartitionedMappingArchive> {
  const { plan, partDigests } = await prepareMappingPlan(draft, previous), actor = 'ui-independent-final-reviewer'
  const members = await Promise.all(partDigests.map(async (part_digest, index) => ({ sequence: index, part_revision_id: `ui-private-part-${index}`,
    artifact_hash: await canonicalDigest({ explicit_fixture: true, part_digest }),
    request_hash: await canonicalDigest({ explicit_fixture: true, sequence: index }), part_digest })))
  const commitment = { schema: 'nasus.test-design-mapping-part-set.v1' as const, plan_digest: plan.plan_digest,
    authority_actor: actor, part_count: members.length, assertion_count: plan.assertion_count,
    members_digest: await mappingDigestChain(await Promise.all(members.map(canonicalDigest))) }
  const set = { ...commitment, part_set_digest: await canonicalDigest(commitment), members }
  const request = { project_id: draft.metadata.project_id, generation_id: draft.metadata.generation_id,
    generation_artifact_hash: draft.metadata.artifact_hash, plan_digest: plan.plan_digest, expected_previous_revision_id: previous,
    part_set_digest: set.part_set_digest, decision: 'review' as const, reason: 'Complete synthetic partition review, never execution', policy_revision: 'nasus.test-design-mapping.v2' as const }
  const value: PartitionedMappingArchive = { revision: { project_id: request.project_id, generation_id: request.generation_id,
    generation_artifact_hash: request.generation_artifact_hash, revision_id: randomUUID(), previous_revision_id: previous, sequence,
    status: 'reviewed', artifact_hash: '', request_hash: '', authority_actor: actor, invocation_id: randomUUID(), recorded_at: new Date().toISOString(),
    mapping_schema: 'nasus.test-design-mapping-review.v2', plan_digest: plan.plan_digest, part_set_digest: set.part_set_digest },
    request, generation_pin: await mappingGenerationPin(draft), plan, part_set: set,
    assessment: assessmentFromDecisions(draft, partitionedDecisions(draft)), historical_not_live: true,
    current_use: { scope_current: true, mapping_current: true, mapping_complete: false, execution_authorized: false } }
  value.current_use.mapping_complete = value.assessment.mapping_complete
  await resignPartitionedArchive(value)
  return value
}
