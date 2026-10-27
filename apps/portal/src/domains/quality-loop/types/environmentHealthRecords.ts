import type { EnvironmentInstance, EnvironmentInventory, EnvironmentRecordArchive, EnvironmentRecordMetadata, EnvironmentRecordRequest } from './environmentRecords'

export interface HealthCheck extends Omit<EnvironmentInstance, 'user'> {
  role: 'pg' | 'redis' | 'target'
  probe: 'postgres_select_one' | 'redis_ping' | 'target_actuator_health'
  response_base64: string; response_hash: string; byte_count: number
}
export interface HealthObservation {
  schema: 'nasus.owned-target-health.v1'; inventory: EnvironmentInventory; inventory_hash: string
  checks: HealthCheck[]; observed_at: string
}
export interface HealthRecordArchive extends Omit<EnvironmentRecordArchive, 'schema' | 'observation'> {
  schema: 'nasus.run-plan-health-record.v1'; request: EnvironmentRecordRequest; observation: HealthObservation
}
export type HealthRecordMetadata = Omit<EnvironmentRecordMetadata, 'schema' | 'dependency_health_verified'> & {
  schema: HealthRecordArchive['schema']; health_hash: string; dependency_health_verified: boolean; target_health_verified: boolean
  health_checks: (Pick<HealthCheck, 'role' | 'probe' | 'response_hash' | 'byte_count'> & { healthy: boolean })[]
}
export interface HealthRecordView { metadata: HealthRecordMetadata; archive: HealthRecordArchive; historical_not_live: true }
