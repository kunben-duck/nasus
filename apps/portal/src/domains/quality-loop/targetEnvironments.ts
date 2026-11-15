import { request } from '../../shared/api/client'
import { generationDigest } from './testDesignGenerationValidation'
import { scriptId } from './automationScriptValidation'
import { requireRunPlan } from './runPlanValidation'
import type { RunPlanFields } from './types/runPlans'

export interface TargetEnvironmentOption {
  environment_id: string
  profile: 'nasus.java21-pg-redis.v1' | 'nasus.python312-django-pg.v1'
  kind: 'local'
  base_url: 'http://127.0.0.1:8080'
  inventory_hash: string
}
export interface TargetEnvironmentOptions {
  schema: 'nasus.target-environment-options.v1'
  project_id: string
  options: TargetEnvironmentOption[]
  target_verified: false
  execution_authorized: false
}

export function verifyTargetEnvironments(value: TargetEnvironmentOptions, projectId: string) {
  requireRunPlan(value?.schema === 'nasus.target-environment-options.v1' && value.project_id === projectId
    && value.target_verified === false && value.execution_authorized === false
    && Array.isArray(value.options) && value.options.length <= 32
    && new Set(value.options.map((item) => item.environment_id)).size === value.options.length)
  for (const item of value.options) requireRunPlan(scriptId(item.environment_id)
    && ['nasus.java21-pg-redis.v1', 'nasus.python312-django-pg.v1'].includes(item.profile)
    && item.kind === 'local' && item.base_url === 'http://127.0.0.1:8080' && generationDigest(item.inventory_hash)
    && Object.keys(item).sort().join(',') === 'base_url,environment_id,inventory_hash,kind,profile')
  return value
}

export async function readTargetEnvironments(projectId: string, signal: AbortSignal) {
  signal.throwIfAborted()
  const value = await request<TargetEnvironmentOptions>(`/v1/projects/${encodeURIComponent(projectId)}/quality/target-environments`,
    { signal, cache: 'no-store' })
  signal.throwIfAborted()
  return verifyTargetEnvironments(value, projectId)
}

export function registeredEnvironment(fields: RunPlanFields, options?: TargetEnvironmentOptions) {
  return options?.options.some((item) => item.environment_id === fields.environmentId && item.kind === fields.kind
    && item.base_url === fields.origin && item.inventory_hash === fields.inventoryHash) === true
}
