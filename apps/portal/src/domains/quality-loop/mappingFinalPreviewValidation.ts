import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { generationDigest } from './testDesignGenerationValidation'
import { mappingInvariant } from './testDesignMappingPartitions'
import { mappingQuery } from './mappingStagingValidation'
import type { MappingFinalPreview, MappingWorkspace } from './types/mappingStaging'

export async function verifyFinalPreview(value: unknown, workspace: MappingWorkspace): Promise<MappingFinalPreview> {
  const v = value as MappingFinalPreview, plan = workspace.plan
  mappingInvariant(v && Object.keys(v).length === 14 && Object.entries(mappingQuery(workspace)).every(([k, x]) => v[k as keyof MappingFinalPreview] === x)
    && v.plan_digest === plan.plan_digest && v.expected_previous_revision_id === plan.expected_previous_revision_id
    && v.authority_actor === workspace.actorId && v.part_count === plan.part_count && v.assertion_count === plan.assertion_count
    && Number.isInteger(v.saved_part_count) && v.saved_part_count >= 0 && v.saved_part_count <= plan.part_count
    && typeof v.scope_current === 'boolean' && v.scope_current === workspace.scopeCurrent
    && v.ready_for_confirmation === (v.saved_part_count === plan.part_count && plan.part_count > 0 && v.scope_current)
    && v.review_authorized === false && v.execution_authorized === false)
  if (v.saved_part_count !== plan.part_count || !plan.part_count) mappingInvariant(v.part_set === null)
  else {
    const set = v.part_set
    mappingInvariant(set && Object.keys(set).length === 7 && set.schema === 'nasus.test-design-mapping-part-set.v1'
      && set.plan_digest === plan.plan_digest && set.authority_actor === workspace.actorId
      && set.part_count === plan.part_count && set.assertion_count === plan.assertion_count && generationDigest(set.members_digest))
    const { part_set_digest, ...body } = set
    mappingInvariant(part_set_digest === await canonicalDigest(body))
  }
  return v
}
