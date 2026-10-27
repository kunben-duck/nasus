export interface CodeIndexPin {
  generation_id: string
  project_id: string
  binding_id: string
  source_revision_id: string
  source_manifest_hash: string
  snapshot_hash: string
  provider_fingerprint: string
  invocation_id: string
  content_hash: string
}

export interface CodeIndexSelection { project_id: string; binding_id: string; after_id: string; limit: number }
export interface CodeIndexPage {
  request: CodeIndexSelection
  items: CodeIndexPin[]
  next_after_id: string | null
  scope: 'source_authorized_generation_discovery_not_execution_authorization'
}
export interface CodeIndexStatus {
  pin: CodeIndexPin
  state: 'idle' | 'preparing' | 'ready' | 'degraded' | 'cancel_requested' | 'cancelled' | 'failed'
  epoch: number
  worker_state: 'none' | 'active' | 'expired'
  invocation_status: 'pending' | 'running' | 'waiting_confirmation' | 'waiting_approval' | 'completed' | 'failed' | 'cancelled'
  observed_at: string
  protocol: {
    provider: string; protocol_version: string; server_name: string; server_version: string; cli_version: string
    tools_schema_hash: string; tool_count: number; verified_operations: string[]; gaps: string[]
    schema: 'nasus.code-provider-protocol.v1'
    scope: 'advertised_tool_contract_not_language_or_runtime_completeness'
  } | {
    provider: string; package_name: string; package_version: string; entry_point: 'package_public_entry'
    contract_hash: string; runtime_hash: string; public_operations: string[]; gaps: string[]
    schema: 'nasus.code-provider-sdk-contract.v1'
    scope: 'exercised_public_sdk_projection_not_language_or_runtime_completeness'
  } | null
  projection_hash: string | null
  provider_version: string | null
  entity_count: number | null
  relationship_count: number | null
  scope: 'durable_projection_metadata_not_native_cache_or_business_authority'
}
export interface CodeIndexStatusView {
  request: { project_id: string; generation_id: string }
  status: CodeIndexStatus
  can_cancel: boolean
}
export interface CodeIndexCancelReceipt {
  request: { project_id: string; generation_id: string; expected_generation_hash: string }
  outcome: 'cancel_requested' | 'cancelled' | 'already_committed' | 'already_terminal'
  status: CodeIndexStatus
}
