import type { ToolInvocation } from '../platform/types'
import type { IterationCreateAttempt, IterationCreateInput, IterationImageBinding } from './types/delivery'

export const deliveryId = (value: unknown): value is string => typeof value === 'string'
  && value.length > 0 && value.length <= 128 && value.trim() === value
  && Array.from(value).every((character) => character.charCodeAt(0) >= 32 && character.charCodeAt(0) !== 127)
export const deliveryHash = (value: unknown): value is string => typeof value === 'string' && /^sha256:[0-9a-f]{64}$/.test(value)

export function validIterationBinding(value: unknown): value is IterationImageBinding {
  if (!value || typeof value !== 'object') return false
  const pin = value as IterationImageBinding
  return deliveryId(pin.publication_id) && deliveryId(pin.image_revision_id) && deliveryHash(pin.image_artifact_hash)
    && deliveryId(pin.expected_head_id) && pin.publication_id === pin.expected_head_id
}

export function verifyIterationInput(value: IterationCreateInput) {
  if (!deliveryId(value.project_id) || typeof value.name !== 'string' || !value.name.trim() || value.name.length > 200
      || !validIterationBinding(value.image_binding)) throw new Error('Iteration creation pin mismatch')
  return value
}

export function verifyIterationInvocation(value: ToolInvocation, attempt: IterationCreateAttempt) {
  verifyIterationInput(attempt.input)
  const input = value.input_payload
  const pin = input?.image_binding as IterationImageBinding | undefined
  if (!deliveryId(value.id) || (attempt.invocation_id && value.id !== attempt.invocation_id)
      || value.tool_id !== 'version.create' || input?.project_id !== attempt.input.project_id || input?.name !== attempt.input.name
      || !validIterationBinding(pin) || Object.keys(attempt.input.image_binding).some((key) =>
        pin[key as keyof IterationImageBinding] !== attempt.input.image_binding[key as keyof IterationImageBinding])
      || (value.result && value.result.invocation_id !== value.id)) throw new Error('Iteration command mismatch')
  return value
}

export function createdIterationId(value: ToolInvocation, attempt: IterationCreateAttempt) {
  verifyIterationInvocation(value, attempt)
  const refs = value.result?.object_refs.filter((ref) => ref.startsWith('version:')) ?? []
  if (value.status !== 'completed' || value.result?.status !== 'completed' || value.result.requires_followup
      || refs.length !== 1 || !deliveryId(refs[0].slice(8))) throw new Error('Iteration creation was not acknowledged')
  return refs[0].slice(8)
}

export const iterationAttemptKey = (projectId: string, actorId: string) => `nasus.iteration-create:${JSON.stringify([actorId, projectId])}`

// Storage is a recovery hint only. Every receipt and pin is reauthorized by the server.
export function readIterationAttempt(storage: Pick<Storage, 'getItem'>, projectId: string, actorId: string): IterationCreateAttempt | null {
  const raw = storage.getItem(iterationAttemptKey(projectId, actorId))
  if (!raw) return null
  const value = JSON.parse(raw) as IterationCreateAttempt
  if (value.actor_id !== actorId || value.input?.project_id !== projectId || !deliveryId(value.idempotency_key)
      || (value.invocation_id !== undefined && !deliveryId(value.invocation_id))) throw new Error('Iteration recovery scope mismatch')
  verifyIterationInput(value.input)
  return value
}
