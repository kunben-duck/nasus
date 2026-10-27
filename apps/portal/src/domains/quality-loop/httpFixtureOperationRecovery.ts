import { generationDigest, generationEqual } from './testDesignGenerationValidation'
import { exactKeys, identity } from './environmentRecordValidation'
import { requireRunPlan } from './runPlanValidation'
import type { FixtureCommandAttempt, FixtureCommandStage, FixtureOperationAttempt } from './types/httpFixtureOperations'

export function verifyOperationAttempt(value: unknown): FixtureOperationAttempt {
  const v = value as FixtureOperationAttempt
  exactKeys(v, ['projectId', 'planId', 'planHash', 'recipeId', 'recipeHash', 'environmentCommandId', 'attemptId', 'operation', 'timeoutMs',
    'grant', ...(v?.execute === undefined ? [] : ['execute']), ...(v?.cancel === undefined ? [] : ['cancel'])])
  requireRunPlan([v.projectId, v.planId, v.recipeId, v.environmentCommandId, v.attemptId].every(identity)
    && [v.planHash, v.recipeHash].every(generationDigest) && ['setup', 'cleanup'].includes(v.operation)
    && Number.isInteger(v.timeoutMs) && v.timeoutMs >= 1000 && v.timeoutMs <= 120000)
  for (const stage of ['grant', 'execute', 'cancel'] as const) {
    const item = v[stage]
    if (item === undefined) continue
    exactKeys(item, ['requestKey', 'requestHash', ...(item.commandId === undefined ? [] : ['commandId'])])
    requireRunPlan(identity(item.requestKey) && generationDigest(item.requestHash) && (item.commandId === undefined || identity(item.commandId)))
  }
  requireRunPlan(v.grant && (!v.execute || v.grant.commandId) && (!v.cancel || v.execute?.commandId))
  return v
}
export function createFixtureOperationRecovery(storage: () => Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>) {
  const key = (actor: string, project: string, plan: string, recipe: string) => {
    requireRunPlan([actor, project, plan, recipe].every(identity))
    return 'nasus.http-fixture-operation.v1:' + JSON.stringify([actor, project, plan, recipe])
  }
  const read = (actor: string, project: string, plan: string, planHash: string, recipe: string, recipeHash: string) => {
    const raw = storage().getItem(key(actor, project, plan, recipe))
    if (raw === null) return null
    requireRunPlan(raw.length <= 4096)
    const v = verifyOperationAttempt(JSON.parse(raw))
    requireRunPlan(v.projectId === project && v.planId === plan && v.planHash === planHash && v.recipeId === recipe && v.recipeHash === recipeHash)
    return v
  }
  const prior = (actor: string, v: FixtureOperationAttempt) => read(actor, v.projectId, v.planId, v.planHash, v.recipeId, v.recipeHash)
  const write = (actor: string, v: FixtureOperationAttempt) => {
    verifyOperationAttempt(v)
    const raw = JSON.stringify(v), name = key(actor, v.projectId, v.planId, v.recipeId)
    requireRunPlan(raw.length <= 4096); storage().setItem(name, raw); requireRunPlan(storage().getItem(name) === raw)
  }
  return { read,
    save(actor: string, v: FixtureOperationAttempt) { requireRunPlan(!prior(actor, v) && !v.grant.commandId && !v.execute && !v.cancel); write(actor, v) },
    add(actor: string, v: FixtureOperationAttempt, stage: 'execute' | 'cancel', attempt: FixtureCommandAttempt) {
      requireRunPlan(generationEqual(prior(actor, v), v) && !v[stage] && !attempt.commandId)
      const next = { ...v, [stage]: attempt }; write(actor, next); return next
    },
    acknowledge(actor: string, v: FixtureOperationAttempt, stage: FixtureCommandStage, commandId: string) {
      const old = prior(actor, v), attempt = v[stage]
      requireRunPlan(generationEqual(old, v) && attempt && identity(commandId) && (!attempt.commandId || attempt.commandId === commandId))
      const next = { ...v, [stage]: { ...attempt, commandId } }; write(actor, next); return next
    },
    clear(actor: string, v: FixtureOperationAttempt) {
      requireRunPlan(generationEqual(prior(actor, v), v))
      const name = key(actor, v.projectId, v.planId, v.recipeId)
      storage().removeItem(name); requireRunPlan(storage().getItem(name) === null)
    },
  }
}
export const fixtureOperationRecovery = createFixtureOperationRecovery(() => window.sessionStorage)
