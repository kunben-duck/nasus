import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { generationDigest, generationEqual } from './testDesignGenerationValidation'
import { verifyAutomationInput } from './automationInputValidation'
import type { AutomationInputPreview } from './types/automationInput'
import type { GenerationArchive } from './types/testDesignGeneration'
import type { RecordedMappingArchive } from './types/testDesignMapping'
import type { CaseAdmissionBasis, CaseAdmissionPreview } from './types/caseApprovals'

export function requireAdmission(value: unknown): asserts value {
  if (!value) throw new Error('Fixed case admission could not be verified')
}
export async function caseAdmissionBasis(v: AutomationInputPreview): Promise<CaseAdmissionBasis> {
  return { project_id: v.project_id, input_digest: v.input_digest, context_pin: v.context_pin, scope_pin: v.scope_pin,
    generation_pin: v.generation_pin, mapping_pin: v.mapping_pin,
    case_pins: await Promise.all(v.cases.map(async (item) => ({ case_id: item.case_id, case_digest: await canonicalDigest(item) }))),
    obligation_pins: v.obligations.map(({ row_id, oracle_digest, selected_case_ids }) => ({ row_id, oracle_digest, selected_case_ids })),
    constraint_denominator: v.constraint_denominator, obligation_denominator: v.obligation_denominator,
    constraints_digest: await canonicalDigest(v.required_constraints), scope_contract_digest: await canonicalDigest(v.scope_contract) }
}
export async function caseAdmissionCohort(basis: CaseAdmissionBasis) {
  const identity = await canonicalDigest({ project_id: basis.project_id, generation_id: basis.generation_pin.generation_id,
    case_ids: basis.case_pins.map((item) => item.case_id) })
  const namespace = Uint8Array.from('6ba7b8119dad11d180b400c04fd430c8'.match(/../g)!, (part) => parseInt(part, 16))
  const name = new TextEncoder().encode(`nasus.test-design-case-admission.v1:${identity}`)
  const bytes = new Uint8Array(namespace.length + name.length); bytes.set(namespace); bytes.set(name, namespace.length)
  const id = new Uint8Array(await crypto.subtle.digest('SHA-1', bytes)).slice(0, 16)
  id[6] = (id[6] & 15) | 80; id[8] = (id[8] & 63) | 128
  const hex = Array.from(id, (byte) => byte.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}
export async function verifyCaseAdmissionPreview(value: unknown, draft: GenerationArchive, mapping: RecordedMappingArchive) {
  const v = value as CaseAdmissionPreview
  requireAdmission(v && typeof v.input_current === 'boolean' && typeof v.can_review === 'boolean'
    && v.execution_authorized === false && v.business_coverage_verified === false
    && typeof v.cohort_id === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(v.cohort_id)
    && Number.isSafeInteger(v.history_count) && v.history_count >= 0 && v.history_count <= 1000)
  const prepared = await verifyAutomationInput(v.prepared, draft, mapping, { historical: true })
  requireAdmission(generationEqual(v.selection, { project_id: prepared.project_id, mapping_revision_id: mapping.revision.revision_id,
    mapping_artifact_hash: mapping.revision.artifact_hash, case_ids: mapping.assessment!.accepted_case_ids })
    && generationEqual(v.basis, await caseAdmissionBasis(prepared)) && v.cohort_id === await caseAdmissionCohort(v.basis))
  if (v.head === null) requireAdmission(v.history_count === 0 && v.head_revision_id === null)
  else {
    const h = v.head
    requireAdmission(h && h.revision_id === v.head_revision_id && typeof h.revision_id === 'string' && h.revision_id
      && h.sequence === v.history_count && h.sequence > 0 && h.project_id === prepared.project_id
      && h.generation_id === prepared.generation_pin.generation_id && h.cohort_id === v.cohort_id
      && h.case_count === prepared.cases.length && ['approved', 'withdrawn'].includes(h.status)
      && generationDigest(h.artifact_hash) && generationDigest(h.input_digest) && generationDigest(h.request_hash)
      && typeof h.mapping_revision_id === 'string' && h.mapping_revision_id
      && typeof h.invocation_id === 'string' && h.invocation_id && typeof h.authority_actor === 'string' && h.authority_actor
      && typeof h.recorded_at === 'string' && Number.isFinite(Date.parse(h.recorded_at))
      && (h.sequence === 1 ? h.previous_revision_id === null && h.status === 'approved'
        : typeof h.previous_revision_id === 'string' && !!h.previous_revision_id))
  }
  return v
}
