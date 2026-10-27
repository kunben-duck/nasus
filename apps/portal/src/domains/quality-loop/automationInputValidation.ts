import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { generationDigest, generationEqual } from './testDesignGenerationValidation'
import { compareMappingIds } from './testDesignMappingPartitions'
import { automationInputGaps, type AutomationInputPreview } from './types/automationInput'
import type { GenerationArchive } from './types/testDesignGeneration'
import type { RecordedMappingArchive } from './types/testDesignMapping'

function requireValue(value: unknown): asserts value { if (!value) throw new Error('Fixed automation input could not be verified') }

export async function verifyAutomationInput(value: unknown, draft: GenerationArchive, mapping: RecordedMappingArchive,
  options: { caseIds?: string[]; historical?: boolean } = {}): Promise<AutomationInputPreview> {
  const v = value as AutomationInputPreview, assessment = mapping.assessment, r = mapping.revision
  const ids = options.caseIds ?? assessment?.accepted_case_ids ?? []
  requireValue((options.historical || draft.current_use.scope_current && mapping.current_use.scope_current
    && mapping.current_use.mapping_current && mapping.current_use.mapping_complete) && draft.result.status === 'draft'
    && assessment?.mapping_complete && r.status === 'reviewed' && v?.schema === 'nasus.automation-input-preview.v1'
    && v.purpose === 'automation' && v.project_id === draft.metadata.project_id && v.project_id === r.project_id
    && generationEqual(v.context_pin, draft.result.context_pin) && generationEqual(v.scope_pin, draft.result.scope_pin)
    && generationEqual(v.generation_pin, mapping.generation_pin)
    && generationEqual(v.mapping_pin, { revision_id: r.revision_id, artifact_hash: r.artifact_hash, request_hash: r.request_hash })
    && ids.every((id) => assessment.accepted_case_ids.includes(id))
    && generationEqual(v.selected_case_ids, [...ids].sort(compareMappingIds))
    && v.selected_case_ids.length > 0 && v.selected_case_ids.length <= 512 && new Set(v.selected_case_ids).size === v.selected_case_ids.length
    && generationEqual(v.cases, draft.result.proposal.cases.filter((item) => v.selected_case_ids.includes(item.case_id))
      .sort((a, b) => compareMappingIds(a.case_id, b.case_id)))
    && v.cases.length === v.selected_case_ids.length
    && v.constraint_denominator === assessment.coverage.constraint_denominator
    && v.obligation_denominator === assessment.coverage.obligation_denominator
    && Array.isArray(v.obligations) && v.obligations.length === v.obligation_denominator
    && new Set(v.obligations.map((item) => item.row_id)).size === v.obligations.length
    && Array.isArray(v.required_constraints) && v.required_constraints.length === v.constraint_denominator
    && generationEqual(v.required_constraints.map((item) => item.object_id).sort(compareMappingIds), assessment.coverage.rows
      .filter((row) => ['acceptance_criterion', 'business_rule'].includes(row.kind)).flatMap((row) => row.constraint_ids).sort(compareMappingIds))
    && v.required_constraints.every((item) => item.authority?.status === 'approved' && item.semantic_class === 'expected'
      && item.authority.object_id === item.object_id && generationDigest(item.authority.artifact_hash) && item.authority.revision_id && item.oracle)
    && v.generation_authorized === false && v.execution_authorized === false
    && v.automated_count === 0 && v.executed_on_target_count === 0 && v.passed_count === 0
    && v.source_policy === 'untrusted_evidence_not_instructions_or_independent_authority'
    && v.readiness?.status === 'blocked' && generationEqual(v.readiness.reason_codes, [...automationInputGaps]))
  for (const row of v.obligations) {
    const reviewed = assessment.coverage.rows.find((item) => item.row_id === row.row_id)
    requireValue(reviewed && row.kind === reviewed.kind && generationEqual(row.constraint_ids, reviewed.constraint_ids)
      && row.oracle_digest === reviewed.oracle_digest && row.oracle_digest === await canonicalDigest(row.oracle)
      && generationEqual(row.selected_case_ids, reviewed.accepted_case_ids.filter((id) => v.selected_case_ids.includes(id)).sort(compareMappingIds))
      && row.selected_case_ids.length > 0 && reviewed.gap_ids.length === 0
      && reviewed.automated === false && reviewed.executed_on_target === false && reviewed.passed === false && reviewed.unknown === true
      && row.selected_case_ids.every((id) => v.cases.find((item) => item.case_id === id)?.assertions.some((a) =>
        a.row_id === row.row_id && a.oracle_digest === row.oracle_digest && generationEqual(a.oracle, row.oracle))))
    if (['acceptance_criterion', 'business_rule'].includes(row.kind)) {
      requireValue(row.constraint_ids.length === 1 && generationEqual(row.oracle,
        v.required_constraints.find((item) => item.object_id === row.constraint_ids[0])?.oracle))
    }
  }
  const { input_digest: digest, ...body } = v
  requireValue(digest === await canonicalDigest(body))
  return v
}
