import { generationDigest } from './testDesignGenerationValidation'
import { scriptId } from './automationScriptValidation'
import { requireRunPlan } from './runPlanValidation'
import type { RunPlanBuildAttempt } from './types/runPlanBuilds'

type StoragePort = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>
export function verifyBuildAttempt(value: unknown): RunPlanBuildAttempt {
  const v = value as RunPlanBuildAttempt
  requireRunPlan(v && ['projectId', 'planId', 'requestKey'].every((key) => scriptId(v[key as keyof typeof v]))
    && generationDigest(v.planHash) && generationDigest(v.requestHash) && (v.commandId === undefined || scriptId(v.commandId))
    && Object.keys(v).every((key) => ['projectId', 'planId', 'planHash', 'requestKey', 'requestHash', 'commandId'].includes(key)))
  return v
}
export function createBuildRecovery(storage: () => StoragePort) {
  const key = (actor: string, project: string, plan: string) => {
    requireRunPlan([actor, project, plan].every(scriptId))
    return 'nasus.run-plan-build.v1:' + JSON.stringify([actor, project, plan])
  }
  const read = (actor: string, project: string, plan: string, hash: string) => {
    const raw = storage().getItem(key(actor, project, plan))
    if (raw === null) return null
    requireRunPlan(raw.length <= 4096)
    const value = verifyBuildAttempt(JSON.parse(raw))
    requireRunPlan(value.projectId === project && value.planId === plan && value.planHash === hash)
    return value
  }
  const write = (actor: string, value: RunPlanBuildAttempt) => {
    verifyBuildAttempt(value)
    const name = key(actor, value.projectId, value.planId), raw = JSON.stringify(value)
    storage().setItem(name, raw); requireRunPlan(storage().getItem(name) === raw)
  }
  return { read,
    save(actor: string, value: RunPlanBuildAttempt) {
      requireRunPlan(!read(actor, value.projectId, value.planId, value.planHash) && !value.commandId); write(actor, value)
    },
    acknowledge(actor: string, value: RunPlanBuildAttempt) {
      const prior = read(actor, value.projectId, value.planId, value.planHash)
      requireRunPlan(prior && prior.requestKey === value.requestKey && prior.requestHash === value.requestHash && value.commandId
        && (!prior.commandId || prior.commandId === value.commandId)); write(actor, value)
    },
    clear(actor: string, value: RunPlanBuildAttempt) {
      const prior = read(actor, value.projectId, value.planId, value.planHash)
      requireRunPlan(prior && prior.requestKey === value.requestKey && prior.requestHash === value.requestHash && prior.commandId === value.commandId)
      const name = key(actor, value.projectId, value.planId); storage().removeItem(name); requireRunPlan(storage().getItem(name) === null)
    },
  }
}
export const buildRecovery = createBuildRecovery(() => window.sessionStorage)
