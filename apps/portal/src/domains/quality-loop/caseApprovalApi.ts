import { request } from '../../shared/api/client'
import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { platformApi } from '../platform/api'
import { generationEqual } from './testDesignGenerationValidation'
import { requireAdmission, verifyCaseAdmissionPreview } from './caseApprovalValidation'
import type { ToolInvocation } from '../platform/types'
import type { GenerationArchive } from './types/testDesignGeneration'
import type { RecordedMappingArchive } from './types/testDesignMapping'
import type { CaseAdmissionPreview, CaseAdmissionRequest } from './types/caseApprovals'

const tool = 'quality.test_design_cases.review', prefix = 'test_design_case_approval:'
function exact(command: ToolInvocation, input: CaseAdmissionRequest) {
  return command && command.tool_id === tool && typeof command.id === 'string' && !!command.id
    && Object.entries(input).every(([key, value]) => generationEqual(command.input_payload?.[key], value))
}
export const caseApprovalApi = {
  async preview(draft: GenerationArchive, mapping: RecordedMappingArchive, signal: AbortSignal) {
    signal.throwIfAborted()
    const params = new URLSearchParams({ mapping_revision_id: mapping.revision.revision_id, mapping_artifact_hash: mapping.revision.artifact_hash })
    for (const id of mapping.assessment?.accepted_case_ids ?? []) params.append('case_ids', id)
    const value = await request<unknown>(`/v1/projects/${encodeURIComponent(draft.metadata.project_id)}/quality/test-design-case-approvals/preview?${params}`, { signal, cache: 'no-store' })
    const result = await verifyCaseAdmissionPreview(value, draft, mapping)
    signal.throwIfAborted(); return result
  },
  async review(input: CaseAdmissionRequest, preview: CaseAdmissionPreview, attempt: string) {
    requireAdmission(input.expected_input_digest === preview.basis.input_digest
      && input.expected_previous_revision_id === preview.head_revision_id && preview.can_review
      && Object.entries(preview.selection).every(([key, value]) => generationEqual(input[key as keyof CaseAdmissionRequest], value))
      && input.policy_revision === 'nasus.test-design-case-admission.v1' && ['approve', 'withdraw'].includes(input.decision)
      && (input.decision === 'approve' ? preview.input_current : preview.head?.status === 'approved'
        && preview.head.input_digest === preview.basis.input_digest))
    const pending = await platformApi.invokeTool({ tool_id: tool, idempotency_key: attempt, input: { ...input } })
    requireAdmission(exact(pending, input) && pending.status === 'waiting_confirmation')
    const command = await platformApi.confirmToolInvocation(pending.id)
    requireAdmission(command.id === pending.id && exact(command, input) && command.status === 'completed'
      && command.input_payload.confirmed_by_user === true && command.result?.object_refs.length === 1
      && command.result.object_refs[0].startsWith(prefix))
    const id = command.result!.object_refs[0].slice(prefix.length)
    const value = await request<unknown>(`/v1/projects/${encodeURIComponent(input.project_id)}/quality/test-design-case-approvals/${encodeURIComponent(id)}`, { cache: 'no-store' })
    const v = value as { revision?: Record<string, unknown>; basis?: unknown; current_use?: Record<string, unknown>; historical_not_live?: unknown }
    requireAdmission(v?.revision?.revision_id === id && v.revision.project_id === input.project_id
      && v.revision.invocation_id === command.id && v.revision.cohort_id === preview.cohort_id
      && v.revision.generation_id === preview.basis.generation_pin.generation_id && v.revision.mapping_revision_id === input.mapping_revision_id
      && v.revision.input_digest === input.expected_input_digest && v.revision.case_count === input.case_ids.length
      && v.revision.request_hash === await canonicalDigest(input) && generationEqual(v.basis, preview.basis)
      && v.revision.status === (input.decision === 'approve' ? 'approved' : 'withdrawn')
      && v.revision.previous_revision_id === input.expected_previous_revision_id
      && v.revision.sequence === preview.history_count + 1 && v.historical_not_live === true
      && typeof v.current_use?.case_admission_current === 'boolean' && v.current_use.generation_authorized === false
      && v.current_use.execution_authorized === false && v.current_use.business_coverage_verified === false)
    return command.id
  },
}
