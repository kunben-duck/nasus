import { request } from '../../shared/api/client'
import type { ContextRetrievalPlan } from './types/contextRetrievalPlan'
import type { IndexGeneration } from './types/frozenIndex'

const integer = (value: number, max: number) => Number.isInteger(value) && value >= 0 && value <= max
const digest = (value: string) => typeof value === 'string' && /^sha256:[0-9a-f]{64}$/.test(value)

export async function readContextRetrievalPlan(generation: IndexGeneration, signal: AbortSignal) {
  const params = new URLSearchParams({ publication_id: generation.publication_pin.publication_id })
  const root = `/v1/projects/${encodeURIComponent(generation.project_id)}/system-image/indexes/${encodeURIComponent(generation.generation_id)}`
  const plan = await request<ContextRetrievalPlan>(`${root}/context-query-plan?${params}`, { signal, cache: 'no-store' })
  if (!plan || plan.request?.project_id !== generation.project_id || plan.request.generation_id !== generation.generation_id
      || plan.request.publication_id !== generation.publication_pin.publication_id || plan.request.method_version !== 'nasus.context-retrieval-plan.v1'
      || !plan.publication_pin || Object.entries(generation.publication_pin).some(([key, value]) => plan.publication_pin[key as keyof typeof plan.publication_pin] !== value)
      || plan.index_artifact_hash !== generation.artifact_hash || !plan.model
      || Object.entries(generation.model).some(([key, value]) => plan.model[key as keyof typeof plan.model] !== value)
      || !integer(plan.query_count, 256) || !integer(plan.input_bytes, 1048576) || !integer(plan.max_query_bytes, 4096)
      || plan.max_model_calls !== Math.ceil(plan.query_count / 32) || plan.batch_size !== 32 || plan.timeout_per_call_seconds !== 60
      || plan.max_query_count !== 256 || plan.query_byte_limit !== 4096 || plan.total_byte_limit !== 1048576
      || !digest(plan.queries_digest) || !digest(plan.plan_digest) || plan.source_policy !== 'frozen_ac_and_parent_description_only'
      || typeof plan.execution_available !== 'boolean' || plan.model_calls_made !== 0 || plan.cost_estimate_available !== false
      || plan.relationship_authority !== false || plan.quality_generation_authorized !== false || plan.rerank_egress_authorized !== false
      || !Array.isArray(plan.source_binding_ids) || plan.source_binding_ids.some((id) => typeof id !== 'string' || !id)
      || new Set(plan.source_binding_ids).size !== plan.source_binding_ids.length
      || (plan.query_count === 0 ? plan.state !== 'missing_requirements' || plan.input_bytes !== 0 || plan.max_query_bytes !== 0 || plan.source_binding_ids.length !== 0
        : plan.state !== 'prepared' || plan.max_query_bytes === 0 || !plan.source_binding_ids.length
          || plan.input_bytes < plan.max_query_bytes || plan.input_bytes > plan.query_count * plan.max_query_bytes)) {
    throw new Error('Context retrieval plan could not be verified')
  }
  return plan
}
