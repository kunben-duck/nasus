import { request } from '../../shared/api/client'
import { platformApi } from '../platform/api'
import type { ContextRequest } from '../system-image/types/contextPack'
import { generationEqual } from './testDesignGenerationValidation'

export type ReviewSelection = { project_id: string; version_id: string; revision_id: string }
export type Oracle = { preconditions: string; action: string; observation: string; expected_result: string }
export type Assessment = {
  summary: string; checks: { dimension: string; assessment: string; refs: string[] }[]
  questions: { question: string; blocking: boolean; rationale: string; refs: string[] }[]
  suggestions: string[]; criteria: { title: string; oracle: Oracle; refs: string[] }[]
}
export type ReviewEvent = {
  event_id: string; content_hash: string; actor_id: string; kind: string; recorded_at: string
  payload: { assessment: Assessment; model: { model: string }; projection: { image_revision_id: string; image_artifact_hash: string } | null }
}
export type RequirementReview = ReviewSelection & {
  status: string; current: boolean; can_confirm: boolean; generation_authorized: false
  evaluation: ReviewEvent | null; confirmation: ReviewEvent | null
  test_design_context_request?: ContextRequest | null
  approval_requests: { title: string; input: Record<string, unknown>; current: {
    revision_id: string; authority_actor: string; status: string
  } | null }[]
}
export type RequirementReviewPreview = {
  request: ReviewSelection & { input_digest: string; model_digest: string }
  model: { provider: string; model: string; generation_options?: { thinking_mode?: string } }; omitted_objects: number
  evidence: { ref: string; kind: string; title?: string; text?: string; question?: string; answer?: string }[]
}

const url = (selection: ReviewSelection) => `/v1/projects/${encodeURIComponent(selection.project_id)}/versions/${encodeURIComponent(selection.version_id)}/requirements/${encodeURIComponent(selection.revision_id)}/review`

export function requirementTestDesignSelection(review: RequirementReview): ContextRequest | null {
  const selection = review.test_design_context_request, projection = review.confirmation?.payload.projection
  if (!review.current || review.status !== 'confirmed' || !review.confirmation || !projection || !selection
    || review.generation_authorized !== false || selection.purpose !== 'test_design'
    || selection.project_id !== review.project_id || selection.image_revision_id !== projection.image_revision_id
    || selection.image_artifact_hash !== projection.image_artifact_hash || selection.policy_revision !== 'nasus.test-design-context.v6'
    || selection.iteration?.version_id !== review.version_id || selection.iteration.requirement_revision_id !== review.revision_id
    || selection.iteration.confirmation_id !== review.confirmation.event_id || selection.iteration.confirmation_hash !== review.confirmation.content_hash) return null
  return selection
}

export const requirementReviewsApi = {
  async read(selection: ReviewSelection, signal?: AbortSignal) {
    const value = await request<RequirementReview>(url(selection), { signal, cache: 'no-store' })
    if (Object.entries(selection).some(([key, field]) => value[key as keyof ReviewSelection] !== field)
        || !Array.isArray(value.approval_requests) || value.generation_authorized !== false) throw new Error('Requirement review scope mismatch')
    return value
  },
  preview: (selection: ReviewSelection) => request<RequirementReviewPreview>(`${url(selection)}?preview=true`, { cache: 'no-store' }),
  async execute(actorId: string, toolId: string, input: Record<string, unknown>) {
    // Preserve the original command on a lost HTTP response, including page reloads.
    const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(input)))))
      .map((item) => item.toString(16).padStart(2, '0')).join('')
    const storageKey = `nasus.review-command:${actorId}:${toolId}:${digest}`
    const key = sessionStorage.getItem(storageKey) || crypto.randomUUID()
    sessionStorage.setItem(storageKey, key)
    let result = await platformApi.invokeTool({ tool_id: toolId, input, idempotency_key: key })
    const originalId = result.id
    const matches = () => result.id === originalId && result.tool_id === toolId && !!result.input_payload
      && Object.entries(input).every(([field, value]) => generationEqual(result.input_payload[field], value))
    if (!matches()) {
      throw new Error('The original review command input does not match the displayed request')
    }
    if (result.status === 'waiting_confirmation') result = await platformApi.confirmToolInvocation(result.id)
    if (!matches() || (result.status === 'completed' && (result.result?.invocation_id !== originalId || result.result.status !== 'completed'))) {
      throw new Error('The confirmed review command does not match the original request')
    }
    if (result.status === 'completed' || result.status === 'failed' || result.status === 'cancelled') sessionStorage.removeItem(storageKey)
    if (result.status !== 'completed') throw new Error(result.summary || 'The original review command has not completed')
    return result
  },
}
