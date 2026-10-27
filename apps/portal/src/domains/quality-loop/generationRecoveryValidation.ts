import type { GenerationBatchRecovery } from './types/generationBatchResult'
import type { GenerationBatchProgress } from './types/testDesignGeneration'

const digest = (value: unknown) => typeof value === 'string' && /^sha256:[a-f0-9]{64}$/.test(value)
const identity = (value: unknown): value is string => typeof value === 'string' && value.length > 0 && value.length <= 128 && value.trim() === value
const keys = (value: unknown, names: string[]) => !!value && typeof value === 'object' && !Array.isArray(value)
  && Object.keys(value).length === names.length && names.every((key) => Object.hasOwn(value, key))
function requireValue(value: unknown): asserts value { if (!value) throw new Error('Complete archived recovery offer could not be verified') }

export function verifyBatchRecoveryOffer(value: unknown, projectId: string, sourceId: string, progress: GenerationBatchProgress) {
  const v = value as GenerationBatchRecovery
  requireValue(keys(v, ['schema_version', 'project_id', 'invocation_id', 'request_hash', 'reservation_hash', 'plan_digest', 'replies_digest', 'replies'])
    && v.schema_version === 'nasus.test-design-batch-recovery.v1' && v.project_id === projectId && v.invocation_id === sourceId
    && [v.request_hash, v.reservation_hash, v.plan_digest, v.replies_digest].every(digest) && v.plan_digest === progress.plan_digest
    && progress.archived_calls === progress.call_count && progress.unknown_calls === 0 && progress.unstarted_calls === 0
    && Array.isArray(v.replies) && v.replies.length === progress.call_count)
  for (const [sequence, pin] of v.replies.entries()) requireValue(
    keys(pin, ['sequence', 'batch_digest', 'call_id', 'request_hash', 'reply_artifact_hash', 'response_hash', 'usage_digest', 'audit_digest'])
    && pin.sequence === sequence && identity(pin.call_id)
    && [pin.batch_digest, pin.request_hash, pin.reply_artifact_hash, pin.response_hash, pin.usage_digest, pin.audit_digest].every(digest))
  requireValue(new Set(v.replies.map((pin) => pin.call_id)).size === v.replies.length
    && new Set(v.replies.map((pin) => pin.batch_digest)).size === v.replies.length)
  return v
}
