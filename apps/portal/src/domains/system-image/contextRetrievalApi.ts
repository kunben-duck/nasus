import { request } from '../../shared/api/client'
import { platformApi } from '../platform/api'
import type { ToolInvocation } from '../platform/types'
import type { ContextRetrievalPlan } from './types/contextRetrievalPlan'

export interface ContextRetrievalResult {
  schema: 'nasus.context-retrieval.v1'
  project_id: string
  invocation_id: string
  generation_id: string
  plan_digest: string
  queries_digest: string
  publication_pin: ContextRetrievalPlan['publication_pin']
  index_artifact_hash: string
  model: ContextRetrievalPlan['model']
  query_count: number
  retrieval_bindings: Record<string, string>
  queries: { target_id: string; query_hash: string; retrieval_id: string; artifact_hash: string }[]
  batches: { ordinal: number; artifact_hash: string; fallback: boolean }[]
  relationship_authority: false
  quality_generation_authorized: false
  rerank_egress_authorized: false
}

const tool = 'system_image.context.retrieve'
const digest = (value: string) => typeof value === 'string' && /^sha256:[0-9a-f]{64}$/.test(value)
const input = (plan: ContextRetrievalPlan) => ({ ...plan.request, expected_plan_digest: plan.plan_digest })
const matches = (item: ToolInvocation, plan: ContextRetrievalPlan) => item.tool_id === tool
  && Object.entries(input(plan)).every(([key, value]) => item.input_payload?.[key] === value)

export const contextRetrievalApi = {
  async latest(plan: ContextRetrievalPlan, signal: AbortSignal) {
    const all = await request<ToolInvocation[]>(`/v1/tool-invocations?tool_id=${tool}`, { signal, cache: 'no-store' })
    if (!Array.isArray(all)) throw new Error('Invalid retrieval history')
    const matching = all.filter((item) => matches(item, plan))
    if (matching.some((item) => !item.id || !['pending', 'running', 'waiting_confirmation', 'waiting_approval', 'completed', 'failed', 'cancelled'].includes(item.status))) {
      throw new Error('Invalid retrieval lifecycle')
    }
    return matching.filter((item) => item.status !== 'waiting_confirmation').at(-1) ?? null
  },
  async start(plan: ContextRetrievalPlan, attempt: string) {
    const pending = await platformApi.invokeTool({ tool_id: tool, idempotency_key: attempt, input: input(plan) })
    if (!matches(pending, plan) || pending.status !== 'waiting_confirmation') throw new Error('Exact query confirmation required')
    const accepted = await platformApi.confirmToolInvocation(pending.id)
    if (accepted.id !== pending.id || !matches(accepted, plan) || !['running', 'completed'].includes(accepted.status)) throw new Error('Query dispatch was not acknowledged')
    return accepted
  },
  async cancel(projectId: string, invocationId: string) {
    const result = await platformApi.invokeTool({ tool_id: 'system_image.context.cancel_retrieval', idempotency_key: crypto.randomUUID(),
      input: { project_id: projectId, invocation_id: invocationId } })
    if (result.status !== 'completed') throw new Error('Cancellation was not acknowledged')
  },
  async result(plan: ContextRetrievalPlan, invocationId: string, signal: AbortSignal) {
    const result = await request<ContextRetrievalResult>(`/v1/projects/${encodeURIComponent(plan.request.project_id)}/system-image/context-retrievals/${encodeURIComponent(invocationId)}`, { signal, cache: 'no-store' })
    if (!result || result.schema !== 'nasus.context-retrieval.v1' || result.project_id !== plan.request.project_id
        || result.invocation_id !== invocationId || result.generation_id !== plan.request.generation_id
        || result.plan_digest !== plan.plan_digest || result.queries_digest !== plan.queries_digest
        || result.index_artifact_hash !== plan.index_artifact_hash || !result.publication_pin || !result.model
        || Object.entries(plan.publication_pin).some(([key, value]) => result.publication_pin[key as keyof typeof result.publication_pin] !== value)
        || Object.entries(plan.model).some(([key, value]) => result.model[key as keyof typeof result.model] !== value)
        || result.query_count !== plan.query_count || !result.retrieval_bindings || !Array.isArray(result.queries)
        || Object.keys(result.retrieval_bindings).length !== plan.query_count || result.queries.length !== plan.query_count
        || new Set(result.queries.map((item) => item.target_id)).size !== plan.query_count
        || new Set(Object.values(result.retrieval_bindings)).size !== plan.query_count
        || result.queries.some((item) => !item.target_id || !item.retrieval_id || result.retrieval_bindings[item.target_id] !== item.retrieval_id
          || !digest(item.artifact_hash) || !digest(item.query_hash))
        || !Array.isArray(result.batches) || result.batches.length !== plan.max_model_calls
        || result.batches.some((batch, ordinal) => batch.ordinal !== ordinal || !digest(batch.artifact_hash) || typeof batch.fallback !== 'boolean')
        || result.relationship_authority !== false || result.quality_generation_authorized !== false || result.rerank_egress_authorized !== false) {
      throw new Error('Completed retrieval mapping could not be verified')
    }
    return result
  },
}
