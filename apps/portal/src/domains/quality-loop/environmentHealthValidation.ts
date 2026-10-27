import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { strictJson } from '../../shared/utils/strictJson'
import { generationEqual } from './testDesignGenerationValidation'
import { requireRunPlan } from './runPlanValidation'
import { environmentRequest, exactKeys, identity, originalObservationIdentity, utc, verifyEnvironmentInventory } from './environmentRecordValidation'
import type { RunPlanArchive } from './types/runPlans'
import type { RunPlanBuildArchive } from './types/runPlanBuilds'
import type { EnvironmentInstance } from './types/environmentRecords'
import type { HealthCheck, HealthRecordArchive, HealthRecordMetadata, HealthRecordView } from './types/environmentHealthRecords'

const probes = { pg: 'postgres_select_one', redis: 'redis_ping', target: 'target_actuator_health' } as const
export const healthRecordIdentity = (command: string) => originalObservationIdentity(command, 'nasus:run-plan-health:')

export async function healthCheckResult(check: HealthCheck): Promise<boolean> {
  exactKeys(check, ['role', 'probe', 'container_id', 'image_id', 'started_at', 'response_base64', 'response_hash', 'byte_count'])
  requireRunPlan(Object.hasOwn(probes, check.role) && check.probe === probes[check.role] && typeof check.response_base64 === 'string'
    && check.response_base64.length <= 4 * Math.ceil(16384 / 3) && Number.isInteger(check.byte_count) && check.byte_count > 0 && check.byte_count <= 16384)
  let decoded: string
  try { decoded = atob(check.response_base64) } catch { throw new Error('Invalid original health response bytes') }
  requireRunPlan(btoa(decoded) === check.response_base64 && decoded.length === check.byte_count)
  const bytes = Uint8Array.from(decoded, (char) => char.charCodeAt(0)), digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))
  requireRunPlan(check.response_hash === 'sha256:' + Array.from(digest, (byte) => byte.toString(16).padStart(2, '0')).join(''))
  if (check.role === 'pg') return decoded === '1\n'
  if (check.role === 'redis') return decoded === 'PONG\n'
  const body = new TextDecoder('utf-8', { fatal: true }).decode(bytes), split = body.lastIndexOf('\n')
  requireRunPlan(split >= 0 && /^[1-5][0-9]{2}$/.test(body.slice(split + 1)))
  const parsed = strictJson(body.slice(0, split))
  requireRunPlan(parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed))
  return body.slice(split + 1) === '200' && (parsed as Record<string, unknown>).status === 'UP'
}
export async function expectedHealthMetadata(archive: HealthRecordArchive): Promise<HealthRecordMetadata> {
  const checks = [] as HealthRecordMetadata['health_checks']
  for (const check of archive.observation.checks) checks.push({ role: check.role, probe: check.probe, response_hash: check.response_hash,
    byte_count: check.byte_count, healthy: await healthCheckResult(check) })
  return { schema: archive.schema, record_id: archive.record_id, invocation_id: archive.invocation_id, actor_id: archive.actor_id,
    recorded_at: archive.recorded_at, ...archive.request, ...archive.parents, artifact_hash: await canonicalDigest(archive),
    request_hash: await canonicalDigest(archive.request), inventory_hash: archive.observation.inventory_hash,
    health_hash: await canonicalDigest(archive.observation), observed_at: archive.observation.observed_at, status: 'recorded',
    historical_not_live: true, native_artifact_attested: true, isolation_configuration_attested: true, durable_native_observation_verified: true,
    dependency_health_verified: checks.slice(0, 2).every((check) => check.healthy), target_health_verified: checks[2]?.healthy,
    health_checks: checks, environment_fully_verified: false, execution_authorized: false, external_egress_denial_verified: false,
    host_access_denial_verified: false, fixtures_verified: false, locators_verified: false, business_coverage_verified: false,
    automated_count: 0, executed_on_target_count: 0, passed_count: 0 }
}
export async function verifyHealthRecord(value: unknown, plan: RunPlanArchive, binding: RunPlanBuildArchive, command: string, recordId: string): Promise<HealthRecordView> {
  const v = value as HealthRecordView, a = v?.archive, p = plan.metadata, request = environmentRequest(plan, binding)
  exactKeys(v, ['metadata', 'archive', 'historical_not_live'])
  exactKeys(a, ['schema', 'project_id', 'record_id', 'invocation_id', 'actor_id', 'recorded_at', 'request', 'parents', 'observation'])
  exactKeys(a.observation, ['schema', 'inventory', 'inventory_hash', 'checks', 'observed_at'])
  const declaration = plan.artifact.plan.selection.environment, observation = a.observation
  requireRunPlan(new TextEncoder().encode(JSON.stringify(v)).length <= 256 * 1024
    && a.schema === 'nasus.run-plan-health-record.v1' && a.project_id === p.project_id && a.invocation_id === command
    && a.record_id === recordId && recordId === await healthRecordIdentity(command) && identity(a.actor_id) && utc(a.recorded_at)
    && generationEqual(a.request, request) && v.historical_not_live === true
    && declaration.kind === 'local' && declaration.base_url === 'http://127.0.0.1:8080'
    && generationEqual(a.parents, { plan_digest: p.plan_digest, image_revision_id: p.image_revision_id, manifest_id: p.manifest_id,
      environment_id: declaration.environment_id, operator_policy_digest: declaration.inventory_hash, target_artifact_hash: binding.metadata.target_artifact_hash })
    && observation.schema === 'nasus.owned-target-health.v1' && Array.isArray(observation.checks)
    && generationEqual(observation.checks.map((check) => check?.role), ['pg', 'redis', 'target']))
  await verifyEnvironmentInventory(observation.inventory, observation.inventory_hash, observation.observed_at)
  const inventory = observation.inventory
  requireRunPlan(inventory.project_id === p.project_id && inventory.environment_id === declaration.environment_id
    && inventory.operator_policy_digest === declaration.inventory_hash && inventory.artifact_hash === binding.metadata.target_artifact_hash)
  const members = { target: inventory.target, ...Object.fromEntries(inventory.dependency_instances.map((item) => [item.role, item])) } as Record<HealthCheck['role'], EnvironmentInstance>
  for (const check of observation.checks) requireRunPlan(['container_id', 'image_id', 'started_at'].every((key) =>
    check[key as keyof HealthCheck] === members[check.role][key as 'container_id' | 'image_id' | 'started_at']))
  requireRunPlan(generationEqual(v.metadata, await expectedHealthMetadata(a)))
  return v
}
