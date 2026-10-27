import { generationDigest } from './testDesignGenerationValidation'
import { identity, exactKeys } from './environmentRecordValidation'
import { requireRunPlan } from './runPlanValidation'
import type { LocatorRecordAttempt } from './types/runPlanLocatorRecords'

export function verifyLocatorAttempt(value: unknown): LocatorRecordAttempt {
  const v = value as LocatorRecordAttempt
  exactKeys(v, ['projectId', 'planId', 'planHash', 'requestKey', 'requestHash', ...(v?.commandId === undefined ? [] : ['commandId'])])
  requireRunPlan([v.projectId, v.planId, v.requestKey].every(identity) && [v.planHash, v.requestHash].every(generationDigest)
    && (v.commandId === undefined || identity(v.commandId)))
  return v
}
export function createLocatorRecovery(storage: () => Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>,
  namespace: 'nasus.locator-record.v1:' | 'nasus.http-fixture-recipe.v1:' = 'nasus.locator-record.v1:') {
  const key = (actor: string, project: string, plan: string) => {
    requireRunPlan([actor, project, plan].every(identity))
    return namespace + JSON.stringify([actor, project, plan])
  }
  const read = (actor: string, project: string, plan: string, hash: string) => {
    const raw = storage().getItem(key(actor, project, plan))
    if (raw === null) return null
    requireRunPlan(raw.length <= 4096)
    const v = verifyLocatorAttempt(JSON.parse(raw))
    requireRunPlan(v.projectId === project && v.planId === plan && v.planHash === hash)
    return v
  }
  const prior = (actor: string, v: LocatorRecordAttempt) => read(actor, v.projectId, v.planId, v.planHash)
  const write = (actor: string, value: LocatorRecordAttempt) => {
    verifyLocatorAttempt(value)
    const name = key(actor, value.projectId, value.planId), raw = JSON.stringify(value)
    storage().setItem(name, raw); requireRunPlan(storage().getItem(name) === raw)
  }
  return { read,
    save(actor: string, v: LocatorRecordAttempt) { requireRunPlan(!prior(actor, v) && !v.commandId); write(actor, v) },
    acknowledge(actor: string, v: LocatorRecordAttempt) {
      const old = prior(actor, v)
      requireRunPlan(old && old.requestKey === v.requestKey && old.requestHash === v.requestHash && v.commandId
        && (!old.commandId || old.commandId === v.commandId)); write(actor, v)
    },
    clear(actor: string, v: LocatorRecordAttempt) {
      const old = prior(actor, v)
      requireRunPlan(old && old.requestKey === v.requestKey && old.requestHash === v.requestHash && old.commandId === v.commandId)
      const name = key(actor, v.projectId, v.planId)
      storage().removeItem(name); requireRunPlan(storage().getItem(name) === null)
    },
  }
}
export const locatorRecovery = createLocatorRecovery(() => window.sessionStorage)
