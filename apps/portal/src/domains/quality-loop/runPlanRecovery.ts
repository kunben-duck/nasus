import { generationDigest } from './testDesignGenerationValidation'
import { scriptId } from './automationScriptValidation'
import { requireRunPlan } from './runPlanValidation'
import type { RunPlanAttempt } from './types/runPlans'

type StoragePort = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>
export function verifyRunPlanAttempt(value: unknown): RunPlanAttempt {
  const v = value as RunPlanAttempt
  const id = (item: unknown): item is string => scriptId(item) && item.trim() === item && !Array.from(item).some((char) => {
    const code = char.charCodeAt(0); return code < 32 || code >= 127 && code <= 159
  })
  requireRunPlan(v && ['projectId', 'scriptId', 'reviewId', 'requestKey'].every((key) => id(v[key as keyof typeof v]))
    && generationDigest(v.requestHash) && (v.commandId === undefined || scriptId(v.commandId))
    && Object.keys(v).every((key) => ['projectId', 'scriptId', 'reviewId', 'requestKey', 'requestHash', 'commandId'].includes(key)))
  return v
}
export function createRunPlanRecovery(storage: () => StoragePort) {
  const key = (actor: string, project: string, script: string, review: string) => {
    requireRunPlan([actor, project, script, review].every(scriptId))
    return 'nasus.run-plan.v1:' + JSON.stringify([actor, project, script, review])
  }
  const read = (actor: string, project: string, script: string, review: string) => {
    const raw = storage().getItem(key(actor, project, script, review))
    if (raw === null) return null
    requireRunPlan(raw.length <= 4096)
    const value = verifyRunPlanAttempt(JSON.parse(raw))
    requireRunPlan(value.projectId === project && value.scriptId === script && value.reviewId === review)
    return value
  }
  const write = (actor: string, value: RunPlanAttempt) => {
    verifyRunPlanAttempt(value)
    const name = key(actor, value.projectId, value.scriptId, value.reviewId), raw = JSON.stringify(value)
    storage().setItem(name, raw); requireRunPlan(storage().getItem(name) === raw)
  }
  return { read,
    save(actor: string, value: RunPlanAttempt) {
      requireRunPlan(!read(actor, value.projectId, value.scriptId, value.reviewId) && !value.commandId); write(actor, value)
    },
    acknowledge(actor: string, value: RunPlanAttempt) {
      const prior = read(actor, value.projectId, value.scriptId, value.reviewId)
      requireRunPlan(prior && prior.requestKey === value.requestKey && prior.requestHash === value.requestHash && value.commandId
        && (!prior.commandId || prior.commandId === value.commandId)); write(actor, value)
    },
    clear(actor: string, value: RunPlanAttempt) {
      const prior = read(actor, value.projectId, value.scriptId, value.reviewId)
      requireRunPlan(prior && prior.requestKey === value.requestKey && prior.requestHash === value.requestHash && prior.commandId === value.commandId)
      const name = key(actor, value.projectId, value.scriptId, value.reviewId)
      storage().removeItem(name); requireRunPlan(storage().getItem(name) === null)
    },
  }
}
export const runPlanRecovery = createRunPlanRecovery(() => window.sessionStorage)
