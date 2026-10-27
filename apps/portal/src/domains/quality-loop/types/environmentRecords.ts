export interface EnvironmentRecordRequest {
  project_id: string; run_plan_id: string; run_plan_artifact_hash: string
  build_binding_id: string; build_binding_artifact_hash: string
}
export interface EnvironmentInstance { container_id: string; image_id: string; started_at: string; user: string }
export interface EnvironmentInventory {
  schema: 'nasus.owned-target-environment.v1'; project_id: string; environment_id: string
  operator_policy_digest: string; artifact_hash: string; target: EnvironmentInstance
  dependency_instances: (EnvironmentInstance & { role: 'pg' | 'redis' })[]; network_id: string
  namespace_origin: 'http://127.0.0.1:8080'; native_artifact_attested: true; isolation_attested: true
  host_ports_exposed: false; developer_resources_used: false; model_outbound_permitted: false
  execution_authorized: false; external_egress_denial_verified: false; host_access_denial_verified: false
  dependency_health_verified: false; fixtures_verified: false; locators_verified: false; business_coverage_verified: false
  automated_count: 0; executed_on_target_count: 0; passed_count: 0
}
export interface EnvironmentRecordArchive {
  schema: 'nasus.run-plan-environment-record.v1'; project_id: string; record_id: string
  invocation_id: string; actor_id: string; recorded_at: string; request: EnvironmentRecordRequest
  parents: { plan_digest: string; image_revision_id: string; manifest_id: string; environment_id: string
    operator_policy_digest: string; target_artifact_hash: string }
  observation: { inventory: EnvironmentInventory; inventory_hash: string; observed_at: string }
}
export type EnvironmentRecordMetadata = EnvironmentRecordRequest & EnvironmentRecordArchive['parents'] & {
  schema: EnvironmentRecordArchive['schema']; record_id: string; invocation_id: string; actor_id: string; recorded_at: string
  artifact_hash: string; request_hash: string; inventory_hash: string; observed_at: string; status: 'recorded'
  historical_not_live: true; native_artifact_attested: true; isolation_configuration_attested: true
  durable_native_observation_verified: true; environment_fully_verified: false; execution_authorized: false
  external_egress_denial_verified: false; host_access_denial_verified: false; dependency_health_verified: false
  fixtures_verified: false; locators_verified: false; business_coverage_verified: false
  automated_count: 0; executed_on_target_count: 0; passed_count: 0
}
export interface EnvironmentRecordView { metadata: EnvironmentRecordMetadata; archive: EnvironmentRecordArchive; historical_not_live: true }
export interface EnvironmentRecordAttempt {
  projectId: string; planId: string; planHash: string; bindingId: string; bindingHash: string
  requestKey: string; requestHash: string; commandId?: string
}
