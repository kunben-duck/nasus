import { generationDigest } from './testDesignGenerationValidation'
import { scriptId } from './automationScriptValidation'
import { requireRunPlan } from './runPlanValidation'
import type { EnvironmentRecordAttempt } from './types/environmentRecords'

type StoragePort = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>
export function verifyEnvironmentAttempt(value: unknown): EnvironmentRecordAttempt {
  const v = value as EnvironmentRecordAttempt
  requireRunPlan(v && ['projectId', 'planId', 'bindingId', 'requestKey'].every((key) => scriptId(v[key as keyof typeof v]))
    && [v.planHash, v.bindingHash, v.requestHash].every(generationDigest) && (v.commandId === undefined || scriptId(v.commandId))
    && Object.keys(v).every((key) => ['projectId', 'planId', 'planHash', 'bindingId', 'bindingHash', 'requestKey', 'requestHash', 'commandId'].includes(key)))
  return v
}
export function createEnvironmentRecovery(storage: () => StoragePort, namespace: 'nasus.environment-record.v1:' | 'nasus.health-record.v1:' = 'nasus.environment-record.v1:') {
  const key = (actor: string, project: string, plan: string, binding: string) => {
    requireRunPlan([actor, project, plan, binding].every(scriptId))
    return namespace + JSON.stringify([actor, project, plan, binding])
  }
  const read = (actor: string, project: string, plan: string, planHash: string, binding: string, bindingHash: string) => {
    const raw = storage().getItem(key(actor, project, plan, binding))
    if (raw === null) return null
    requireRunPlan(raw.length <= 4096)
    const value = verifyEnvironmentAttempt(JSON.parse(raw))
    requireRunPlan(value.projectId === project && value.planId === plan && value.planHash === planHash && value.bindingId === binding && value.bindingHash === bindingHash)
    return value
  }
  const prior = (actor: string, v: EnvironmentRecordAttempt) => read(actor, v.projectId, v.planId, v.planHash, v.bindingId, v.bindingHash)
  const write = (actor: string, value: EnvironmentRecordAttempt) => {
    verifyEnvironmentAttempt(value)
    const name = key(actor, value.projectId, value.planId, value.bindingId), raw = JSON.stringify(value)
    storage().setItem(name, raw); requireRunPlan(storage().getItem(name) === raw)
  }
  return { read,
    save(actor: string, value: EnvironmentRecordAttempt) { requireRunPlan(!prior(actor, value) && !value.commandId); write(actor, value) },
    acknowledge(actor: string, value: EnvironmentRecordAttempt) {
      const old = prior(actor, value)
      requireRunPlan(old && old.requestKey === value.requestKey && old.requestHash === value.requestHash && value.commandId
        && (!old.commandId || old.commandId === value.commandId)); write(actor, value)
    },
    clear(actor: string, value: EnvironmentRecordAttempt) {
      const old = prior(actor, value)
      requireRunPlan(old && old.requestKey === value.requestKey && old.requestHash === value.requestHash && old.commandId === value.commandId)
      const name = key(actor, value.projectId, value.planId, value.bindingId)
      storage().removeItem(name); requireRunPlan(storage().getItem(name) === null)
    },
  }
}
export const environmentRecovery = createEnvironmentRecovery(() => window.sessionStorage)
