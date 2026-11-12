import type { VersionDelivery, DeliveryImagePin, IterationImageBinding } from './types/delivery'
import { deliveryHash, deliveryId } from './iterationCreation'

function validPin(pin: DeliveryImagePin | null) {
  return !!pin && deliveryId(pin.publication_id) && deliveryId(pin.baseline_id)
    && deliveryId(pin.image_revision_id) && deliveryHash(pin.image_artifact_hash)
    && deliveryId(pin.manifest_id) && deliveryHash(pin.manifest_hash) && Number.isSafeInteger(pin.sequence) && pin.sequence > 0
    && pin.quality_generation_authorized === false && pin.release_authorized === false
}

export function verifyVersionDelivery(value: VersionDelivery, projectId: string, versionId: string) {
  if (value.project_id !== projectId || value.version_id !== versionId || typeof value.name !== 'string'
      || typeof value.enabled !== 'boolean' || value.stage !== (value.enabled ? 'image_pinned' : 'legacy')
      || !Array.isArray(value.code_revisions) || !Array.isArray(value.blockers)
      || !Array.isArray(value.pending_confirmations) || !Array.isArray(value.available_actions)
      || (value.enabled && (!validPin(value.baseline) || !validPin(value.iteration_image)))
      || (!value.enabled && (value.baseline !== null || value.iteration_image !== null))) throw new Error('Iteration delivery scope mismatch')
  if ((value.enabled && value.code_revisions.length === 0)
      || value.code_revisions.some((item) => !deliveryId(item.binding_id) || !deliveryId(item.source_id)
        || !deliveryId(item.source_revision_id) || !deliveryId(item.external_revision) || typeof item.repository !== 'string'
        || (item.tracked_ref !== null && typeof item.tracked_ref !== 'string')
        || (item.commit_sha !== null && !/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/.test(item.commit_sha))
        || !deliveryHash(item.content_hash) || !deliveryHash(item.manifest_hash))
      || [...value.blockers, ...value.pending_confirmations].some((item) => typeof item !== 'string' || !item.trim())
      || value.available_actions.some((item) => item !== 'view_pinned_image')) throw new Error('Iteration delivery evidence mismatch')
  return value
}

export function verifyCreatedIteration(value: VersionDelivery, binding: IterationImageBinding) {
  const baseline = value.baseline
  if (!value.enabled || !baseline || baseline.publication_id !== binding.publication_id
      || baseline.image_revision_id !== binding.image_revision_id || baseline.image_artifact_hash !== binding.image_artifact_hash) {
    throw new Error('Created iteration baseline mismatch')
  }
  return value
}
