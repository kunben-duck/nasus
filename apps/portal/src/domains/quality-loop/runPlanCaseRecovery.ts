import { generationDigest, generationEqual } from './testDesignGenerationValidation'
import { exactKeys } from './environmentRecordValidation'
import { requireRunPlan } from './runPlanValidation'
import { caseId, requireCaseFields, requireCaseSelection } from './runPlanCaseValidation'
import type { CaseCommandStage, CaseExecutionAttempt } from './types/runPlanCaseJobs'

export function verifyCaseAttempt(value: unknown): CaseExecutionAttempt {
  const v = value as CaseExecutionAttempt
  exactKeys(v, ['projectId', 'planId', 'planHash', 'fields', 'input', 'execute', ...(v?.cancel === undefined ? [] : ['cancel'])])
  requireCaseFields(v.fields); requireCaseSelection(v.input)
  requireRunPlan(caseId(v.projectId) && caseId(v.planId) && generationDigest(v.planHash)
    && v.input.project_id === v.projectId && v.input.run_plan_id === v.planId && v.input.run_plan_artifact_hash === v.planHash
    && v.fields.runId === v.input.run_id && v.fields.timeoutMs === v.input.timeout_ms
    && generationEqual(v.fields.setups.map((item) => ({ case_id: item.caseId, invocation_id: item.commandId })), v.input.fixture_setups))
  for (const stage of ['execute', 'cancel'] as const) {
    const a = v[stage]
    if (a === undefined) continue
    exactKeys(a, ['requestKey', 'requestHash', ...(a.commandId === undefined ? [] : ['commandId'])])
    requireRunPlan(caseId(a.requestKey) && generationDigest(a.requestHash) && (a.commandId === undefined || caseId(a.commandId)))
  }
  requireRunPlan(v.execute && (!v.cancel || v.execute.commandId))
  return v
}
export function createCaseRecovery(storage: () => Pick<Storage, 'getItem' | 'setItem'>) {
  const key = (actor: string, project: string, plan: string) => {
    requireRunPlan([actor, project, plan].every(caseId))
    return 'nasus.run-plan-case-job.v1:' + JSON.stringify([actor, project, plan])
  }
  const read = (actor: string, project: string, plan: string, planHash: string) => {
    const raw = storage().getItem(key(actor, project, plan))
    if (raw === null) return null
    requireRunPlan(raw.length <= 262144)
    const v = verifyCaseAttempt(JSON.parse(raw))
    requireRunPlan(v.projectId === project && v.planId === plan && v.planHash === planHash)
    return v
  }
  const prior = (actor: string, v: CaseExecutionAttempt) => read(actor, v.projectId, v.planId, v.planHash)
  const write = (actor: string, v: CaseExecutionAttempt) => {
    verifyCaseAttempt(v)
    const raw = JSON.stringify(v), name = key(actor, v.projectId, v.planId)
    requireRunPlan(raw.length <= 262144); storage().setItem(name, raw); requireRunPlan(storage().getItem(name) === raw)
    return v
  }
  return { read,
    save(actor: string, v: CaseExecutionAttempt) { requireRunPlan(!prior(actor, v) && !v.execute.commandId && !v.cancel); return write(actor, v) },
    addCancel(actor: string, v: CaseExecutionAttempt, requestKey: string, requestHash: string) {
      requireRunPlan(generationEqual(prior(actor, v), v) && v.execute.commandId && !v.cancel)
      return write(actor, { ...v, cancel: { requestKey, requestHash } })
    },
    acknowledge(actor: string, v: CaseExecutionAttempt, stage: CaseCommandStage, commandId: string) {
      const original = prior(actor, v), a = v[stage]
      requireRunPlan(generationEqual(original, v) && a && caseId(commandId) && (!a.commandId || a.commandId === commandId))
      return write(actor, { ...v, [stage]: { ...a, commandId } })
    },
  }
}
export const caseRecovery = createCaseRecovery(() => window.sessionStorage)
