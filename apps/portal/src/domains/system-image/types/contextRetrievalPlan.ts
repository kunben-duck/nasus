import type { IndexModelBinding, PublicationPin } from './frozenIndex'

export interface ContextRetrievalPlan {
  request: { project_id: string; publication_id: string; generation_id: string; method_version: 'nasus.context-retrieval-plan.v1' }
  publication_pin: PublicationPin
  index_artifact_hash: string
  model: IndexModelBinding
  source_binding_ids: string[]
  query_count: number
  input_bytes: number
  max_query_bytes: number
  max_model_calls: number
  batch_size: 32
  timeout_per_call_seconds: 60
  max_query_count: 256
  query_byte_limit: 4096
  total_byte_limit: 1048576
  queries_digest: string
  plan_digest: string
  state: 'prepared' | 'missing_requirements'
  source_policy: 'frozen_ac_and_parent_description_only'
  execution_available: boolean
  model_calls_made: 0
  cost_estimate_available: false
  relationship_authority: false
  quality_generation_authorized: false
  rerank_egress_authorized: false
}
