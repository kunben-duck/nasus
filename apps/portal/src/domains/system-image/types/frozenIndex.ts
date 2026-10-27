import type { SystemImageData } from './data'

export type PublicationPin = NonNullable<NonNullable<SystemImageData['read_state']>['pin']>
export interface IndexSelection {
  project_id: string
  publication_id: string
  model_config_id: string
  method_version: 'nasus.frozen-evidence-index.v1'
}
export interface IndexBuildRequest extends IndexSelection {
  input_digest: string
  model_config_digest: string
}
export interface IndexModelBinding {
  config_id: string
  provider: 'openai' | 'openai_compatible'
  model_name: string
  base_url: string
  config_digest: string
}
export interface IndexPreview {
  request: IndexBuildRequest
  publication_pin: PublicationPin
  model: IndexModelBinding
  source_binding_ids: string[]
  document_count: number
  input_bytes: number
  max_model_calls: number
  batch_size: 32
  timeout_per_call_seconds: 60
  cost_estimate_available: false
  query_egress: string
  rerank_egress_authorized: false
  quality_generation_authorized: false
}
export interface IndexGeneration {
  project_id: string
  generation_id: string
  request: IndexBuildRequest
  publication_pin: PublicationPin
  model: IndexModelBinding
  document_count: number
  dimensions: number
  artifact_hash: string
  quality_generation_authorized: false
}
export interface FrozenIndexStatus {
  project_id: string
  publication_pin: PublicationPin
  state: 'not_built' | 'ready' | 'rebuild_required'
  generation: IndexGeneration | null
  can_build: boolean
  quality_generation_authorized: false
}
