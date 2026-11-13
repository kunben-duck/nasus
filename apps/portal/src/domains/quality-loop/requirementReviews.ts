import { request } from '../../shared/api/client'
import { platformApi } from '../platform/api'

export type ReviewSelection = { project_id: string; version_id: string; revision_id: string }
export type Oracle = { preconditions: string; action: string; observation: string; expected_result: string }
export type Assessment = {
  summary: string; checks: { dimension: string; assessment: string; refs: string[] }[]
  questions: { question: string; blocking: boolean; rationale: string; refs: string[] }[]
  suggestions: string[]; criteria: { title: string; oracle: Oracle; refs: string[] }[]
}
export type ReviewEvent = {
  event_id: string; content_hash: string; actor_id: string; kind: string; recorded_at: string
  payload: { assessment: Assessment; model: { model: string }; projection: { image_revision_id: string } | null }
}
export type RequirementReview = ReviewSelection & {
  status: string; current: boolean; can_confirm: boolean; generation_authorized: false
  evaluation: ReviewEvent | null; confirmation: ReviewEvent | null
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
    if (result.tool_id !== toolId || Object.entries(input).some(([field, value]) => JSON.stringify(result.input_payload[field]) !== JSON.stringify(value))) {
      throw new Error('The original review command input does not match the displayed request')
    }
    if (result.status === 'waiting_confirmation') result = await platformApi.confirmToolInvocation(result.id)
    if (result.status === 'completed' || result.status === 'failed' || result.status === 'cancelled') sessionStorage.removeItem(storageKey)
    if (result.status !== 'completed') throw new Error(result.summary || 'The original review command has not completed')
    return result
  },
}
