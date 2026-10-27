import { generationDigest } from './testDesignGenerationValidation'
import type { GenerationArchive } from './types/testDesignGeneration'

export function verifyGenerationMetadata(value: GenerationArchive['metadata']): boolean {
  const id = (v: unknown) => typeof v === 'string' && v.length > 0 && v.length <= 128
  const count = (v: unknown) => Number.isSafeInteger(v) && Number(v) >= 0
  if (!value || ![value.project_id, value.generation_id, value.scope_revision_id, value.invocation_id].every(id)
    || value.status !== 'draft' || !generationDigest(value.artifact_hash) || !count(value.case_count) || !count(value.gap_count)) return false
  if (value.schema === 'nasus.test-design-result.v3' || value.schema === 'nasus.test-design-result.v4') {
    const recovered = value.schema === 'nasus.test-design-result.v4'
    return Object.keys(value).length === (recovered ? 14 : 13) && value.call_id === null
    && (recovered ? id(value.recovery_invocation_id) && value.recovery_invocation_id !== value.invocation_id : value.recovery_invocation_id === undefined)
    && generationDigest(value.plan_digest)
    && Number.isSafeInteger(value.batch_count) && Number(value.batch_count) >= 1 && Number(value.batch_count) <= 64
    && Array.isArray(value.call_ids) && value.call_ids.length === value.batch_count && value.call_ids.every(id)
    && new Set(value.call_ids).size === value.batch_count && value.case_count <= 32768 && value.gap_count <= 32768
  }
  return value.schema === undefined && Object.keys(value).length === (value.recovery_invocation_id === undefined ? 9 : 10)
    && id(value.call_id) && (value.recovery_invocation_id === undefined || id(value.recovery_invocation_id) && value.recovery_invocation_id !== value.invocation_id)
}
