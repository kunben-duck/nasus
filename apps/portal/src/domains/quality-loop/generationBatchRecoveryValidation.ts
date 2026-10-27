import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { generationDigest, generationEqual } from './testDesignGenerationValidation'
import type { GenerationBatchArchive } from './types/generationBatchResult'

const keys = (value: unknown, names: string[]) => !!value && typeof value === 'object' && !Array.isArray(value)
  && generationEqual(Object.keys(value).sort(), [...names].sort())
function requireValue(value: unknown): asserts value { if (!value) throw new Error('Archived batch recovery provenance could not be verified') }

export async function verifyBatchRecoveryPins(view: GenerationBatchArchive) {
  const result = view.result, request = result.recovery_request, authority = result.recovery_invocation_id
  requireValue(typeof authority === 'string' && authority.length > 0 && authority.length <= 128 && authority.trim() === authority
    && authority !== result.invocation_id && view.metadata.recovery_invocation_id === authority
    && keys(request, ['schema_version', 'project_id', 'invocation_id', 'request_hash', 'reservation_hash', 'plan_digest', 'replies_digest', 'replies'])
    && request?.schema_version === 'nasus.test-design-batch-recovery.v1' && request.project_id === result.project_id
    && request.invocation_id === result.invocation_id && request.plan_digest === result.batch_plan.plan_digest
    && generationDigest(request.replies_digest) && request.request_hash === await canonicalDigest(result.request)
    && request.reservation_hash === await canonicalDigest(result.reservation)
    && Array.isArray(request.replies) && request.replies.length === result.calls.length)
  // The server validates replies_digest against private receipts including
  // storage refs; the public view verifies every visible native call pin.
  for (const [sequence, pin] of request.replies.entries()) {
    const { claim, reply, audit } = result.calls[sequence]
    requireValue(keys(pin, ['sequence', 'batch_digest', 'call_id', 'request_hash', 'reply_artifact_hash', 'response_hash', 'usage_digest', 'audit_digest'])
      && pin.sequence === sequence && pin.batch_digest === claim.batch_digest && pin.call_id === claim.call_id
      && pin.request_hash === claim.request_hash && pin.reply_artifact_hash === reply.artifact_hash && pin.response_hash === reply.response_hash
      && pin.usage_digest === await canonicalDigest(reply.usage) && pin.audit_digest === await canonicalDigest(audit))
  }
}
