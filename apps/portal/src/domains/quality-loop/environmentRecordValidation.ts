import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { generationDigest, generationEqual } from './testDesignGenerationValidation'
import { scriptId } from './automationScriptValidation'
import { requireRunPlan } from './runPlanValidation'
import type { RunPlanArchive } from './types/runPlans'
import type { RunPlanBuildArchive } from './types/runPlanBuilds'
import type { EnvironmentInventory, EnvironmentRecordArchive, EnvironmentRecordMetadata, EnvironmentRecordRequest, EnvironmentRecordView } from './types/environmentRecords'

export const environmentRequestKeys = ['project_id', 'run_plan_id', 'run_plan_artifact_hash', 'build_binding_id', 'build_binding_artifact_hash'] as const
export const environmentFalseAuthorities = ['environment_fully_verified', 'execution_authorized', 'external_egress_denial_verified',
  'host_access_denial_verified', 'dependency_health_verified', 'fixtures_verified', 'locators_verified', 'business_coverage_verified'] as const
export const environmentZeroCounts = ['automated_count', 'executed_on_target_count', 'passed_count'] as const
const inventoryFalseFields = ['host_ports_exposed', 'developer_resources_used', 'model_outbound_permitted', ...environmentFalseAuthorities.filter((k) => k !== 'environment_fully_verified')]
export function exactKeys(value: unknown, keys: readonly string[]) {
  requireRunPlan(value && typeof value === 'object' && !Array.isArray(value) && generationEqual(Object.keys(value).sort(), [...keys].sort()))
}
export const identity = (value: unknown): value is string => scriptId(value) && value.trim() === value && !Array.from(value).some((char) => char.charCodeAt(0) <= 32)
export const utc = (value: unknown) => typeof value === 'string' && value.length <= 64 && /(?:Z|\+00:00)$/.test(value) && Number.isFinite(Date.parse(value))

export function environmentRequest(plan: RunPlanArchive, binding: RunPlanBuildArchive): EnvironmentRecordRequest {
  const p = plan.metadata, b = binding.metadata
  requireRunPlan(b.project_id === p.project_id && b.run_plan_id === p.run_plan_id && b.run_plan_artifact_hash === p.artifact_hash
    && ['plan_digest', 'image_revision_id', 'manifest_id'].every((key) => b[key] === p[key as keyof typeof p]))
  const request = { project_id: p.project_id, run_plan_id: p.run_plan_id, run_plan_artifact_hash: p.artifact_hash,
    build_binding_id: b.binding_id, build_binding_artifact_hash: b.artifact_hash }
  requireRunPlan([request.project_id, request.run_plan_id, request.build_binding_id].every(identity)
    && [request.run_plan_artifact_hash, request.build_binding_artifact_hash].every(generationDigest))
  return request
}
// Match the server's UUIDv5 command-owned record identity, not a caller-selected ID.
export async function environmentRecordIdentity(command: string) {
  return originalObservationIdentity(command, 'nasus:run-plan-environment:')
}
export async function originalObservationIdentity(command: string, prefix: 'nasus:run-plan-environment:' | 'nasus:run-plan-health:' | 'nasus:run-plan-locators:' | 'nasus:http-fixture-recipe:' | 'nasus:http-fixture-grant:') {
  requireRunPlan(identity(command))
  const namespace = Uint8Array.from('6ba7b8119dad11d180b400c04fd430c8'.match(/../g)!, (value) => parseInt(value, 16))
  const name = new TextEncoder().encode(prefix + command), bytes = new Uint8Array(namespace.length + name.length)
  bytes.set(namespace); bytes.set(name, namespace.length)
  const result = new Uint8Array(await crypto.subtle.digest('SHA-1', bytes)).slice(0, 16)
  result[6] = (result[6] & 15) | 80; result[8] = (result[8] & 63) | 128
  const hex = Array.from(result, (value) => value.toString(16).padStart(2, '0')).join('')
  return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join('-')
}
export async function verifyEnvironmentInventory(value: EnvironmentInventory, hash: string, time: string) {
  exactKeys(value, ['schema', 'project_id', 'environment_id', 'operator_policy_digest', 'artifact_hash', 'target', 'dependency_instances',
    'network_id', 'namespace_origin', 'native_artifact_attested', 'isolation_attested', ...inventoryFalseFields, ...environmentZeroCounts])
  requireRunPlan(value.schema === 'nasus.owned-target-environment.v1' && identity(value.project_id) && identity(value.environment_id)
    && generationDigest(value.operator_policy_digest) && generationDigest(value.artifact_hash) && value.namespace_origin === 'http://127.0.0.1:8080'
    && value.native_artifact_attested === true && value.isolation_attested === true
    && inventoryFalseFields.every((key) => (value as unknown as Record<string, unknown>)[key] === false)
    && environmentZeroCounts.every((key) => value[key] === 0) && /^[0-9a-f]{64}$/.test(value.network_id) && utc(time)
    && Array.isArray(value.dependency_instances) && value.dependency_instances.length === 2)
  exactKeys(value.target, ['container_id', 'image_id', 'started_at', 'user'])
  for (const item of value.dependency_instances) exactKeys(item, ['container_id', 'image_id', 'started_at', 'user', 'role'])
  const instances = [value.target, ...value.dependency_instances]
  requireRunPlan(value.target.user === '65534:65534' && generationEqual(value.dependency_instances.map((v) => v.role).sort(), ['pg', 'redis'])
    && instances.every((v) => typeof v.container_id === 'string' && /^[0-9a-f]{64}$/.test(v.container_id) && generationDigest(v.image_id)
      && typeof v.started_at === 'string' && v.started_at.length > 0 && v.started_at.length <= 64
      && typeof v.user === 'string' && /^[1-9][0-9]{0,4}:[1-9][0-9]{0,4}$/.test(v.user) && v.user.split(':').every((part) => Number(part) <= 65535))
    && new Set(instances.map((v) => v.container_id)).size === 3 && instances.every((v) => v.container_id !== value.network_id)
    && await canonicalDigest(value) === hash)
}
export async function expectedEnvironmentMetadata(archive: EnvironmentRecordArchive): Promise<EnvironmentRecordMetadata> {
  return { schema: archive.schema, record_id: archive.record_id, invocation_id: archive.invocation_id,
    actor_id: archive.actor_id, recorded_at: archive.recorded_at, ...archive.request, ...archive.parents,
    artifact_hash: await canonicalDigest(archive), request_hash: await canonicalDigest(archive.request),
    inventory_hash: archive.observation.inventory_hash, observed_at: archive.observation.observed_at, status: 'recorded',
    historical_not_live: true, native_artifact_attested: true, isolation_configuration_attested: true, durable_native_observation_verified: true,
    environment_fully_verified: false, execution_authorized: false, external_egress_denial_verified: false, host_access_denial_verified: false,
    dependency_health_verified: false, fixtures_verified: false, locators_verified: false, business_coverage_verified: false,
    automated_count: 0, executed_on_target_count: 0, passed_count: 0 }
}
export async function verifyEnvironmentRecord(value: unknown, plan: RunPlanArchive, binding: RunPlanBuildArchive, command: string, recordId: string): Promise<EnvironmentRecordView> {
  const v = value as EnvironmentRecordView, a = v?.archive, expectedRequest = environmentRequest(plan, binding)
  exactKeys(v, ['metadata', 'archive', 'historical_not_live'])
  exactKeys(a, ['schema', 'project_id', 'record_id', 'invocation_id', 'actor_id', 'recorded_at', 'request', 'parents', 'observation'])
  exactKeys(a.observation, ['inventory', 'inventory_hash', 'observed_at'])
  const declaration = plan.artifact.plan.selection.environment, p = plan.metadata
  requireRunPlan(new TextEncoder().encode(JSON.stringify(v)).length <= 128 * 1024
    && a.schema === 'nasus.run-plan-environment-record.v1' && a.project_id === p.project_id && a.invocation_id === command
    && a.record_id === recordId && recordId === await environmentRecordIdentity(command) && identity(a.actor_id) && utc(a.recorded_at)
    && generationEqual(a.request, expectedRequest) && v.historical_not_live === true
    && declaration.kind === 'local' && declaration.base_url === 'http://127.0.0.1:8080'
    && generationEqual(a.parents, { plan_digest: p.plan_digest, image_revision_id: p.image_revision_id, manifest_id: p.manifest_id,
      environment_id: declaration.environment_id, operator_policy_digest: declaration.inventory_hash, target_artifact_hash: binding.metadata.target_artifact_hash }))
  await verifyEnvironmentInventory(a.observation.inventory, a.observation.inventory_hash, a.observation.observed_at)
  const inventory = a.observation.inventory
  requireRunPlan(inventory.project_id === p.project_id && inventory.environment_id === declaration.environment_id
    && inventory.operator_policy_digest === declaration.inventory_hash && inventory.artifact_hash === binding.metadata.target_artifact_hash
    && generationEqual(v.metadata, await expectedEnvironmentMetadata(a)))
  return v
}
