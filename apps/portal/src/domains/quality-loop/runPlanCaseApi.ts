import { request } from '../../shared/api/client'
import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { platformApi } from '../platform/api'
import { readFixtureEnvironment } from './httpFixtureEnvironmentApi'
import { verifyFixtureHistoryItem } from './httpFixtureHistoryValidation'
import { locatorRecordApi } from './runPlanLocatorRecordApi'
import { generationEqual } from './testDesignGenerationValidation'
import { requireRunPlan } from './runPlanValidation'
import { caseTools, caseId, requireCaseCommand, requireCaseFields, requireCaseParent, requireCaseInput } from './runPlanCaseValidation'
import { verifyCaseHistory } from './runPlanCaseHistoryValidation'
import type { ToolInvocation } from '../platform/types'
import type { RunPlanArchive } from './types/runPlans'
import type { CaseCommandAttempt, CaseCommandStage, CaseExecutionFields, CaseExecutionSelection } from './types/runPlanCaseJobs'

export const caseExecutionApi = {
  async prepare(plan: RunPlanArchive, fields: CaseExecutionFields, signal: AbortSignal): Promise<CaseExecutionSelection> {
    requireCaseFields(fields, plan); signal.throwIfAborted()
    const p = plan.metadata, environment = await readFixtureEnvironment(plan, fields.environmentCommandId, signal)
    const locatorCommand = await platformApi.getToolInvocation(fields.locatorCommandId, { signal })
    const locators = await locatorRecordApi.read(locatorCommand, plan, signal)
    requireRunPlan(locators.archive.report.locators.every((v) => v.status === 'static_match'))
    for (const selected of fields.setups) {
      signal.throwIfAborted()
      const item = verifyFixtureHistoryItem(await request<unknown>(`/v1/projects/${encodeURIComponent(p.project_id)}/quality/http-fixture-operations/${encodeURIComponent(selected.commandId)}`,
        { signal, cache: 'no-store' }), p.project_id)
      requireRunPlan(item.invocation_id === selected.commandId && item.stage === 'execute' && item.operation === 'setup' && item.status === 'completed'
        && item.case_id === selected.caseId && item.run_plan_id === p.run_plan_id && item.run_plan_artifact_hash === p.artifact_hash)
    }
    signal.throwIfAborted()
    const e = environment.metadata, l = locators.metadata
    const input: CaseExecutionSelection = { project_id: p.project_id, run_id: fields.runId, run_plan_id: p.run_plan_id,
      run_plan_artifact_hash: p.artifact_hash, plan_digest: p.plan_digest, timeout_ms: fields.timeoutMs,
      build_binding_id: e.build_binding_id, build_binding_artifact_hash: e.build_binding_artifact_hash,
      environment_record_id: e.record_id, environment_record_artifact_hash: e.artifact_hash,
      locator_record_id: l.record_id, locator_record_artifact_hash: l.artifact_hash,
      fixture_setups: fields.setups.map((v) => ({ case_id: v.caseId, invocation_id: v.commandId })) }
    requireCaseParent(input, plan)
    // References are not a live grant: the backend rechecks every native setup,
    // cleanup slot, source permission and target epoch after independent consent.
    return input
  },
  async submit(stage: CaseCommandStage, attempt: CaseCommandAttempt, input: Record<string, unknown>, actorId: string,
    acknowledge: (commandId: string) => void) {
    requireCaseInput(stage, input)
    requireRunPlan(!attempt.commandId && caseId(actorId) && attempt.requestHash === await canonicalDigest(input))
    const pending = await requireCaseCommand(await platformApi.invokeTool({ tool_id: caseTools[stage], idempotency_key: attempt.requestKey, input }),
      stage, attempt, input, actorId)
    requireRunPlan(pending.status === 'waiting_confirmation')
    acknowledge(pending.id)
    return this.confirm(stage, { ...attempt, commandId: pending.id }, input, actorId)
  },
  async confirm(stage: CaseCommandStage, attempt: CaseCommandAttempt, input: Record<string, unknown>, actorId: string) {
    requireCaseInput(stage, input)
    requireRunPlan(caseId(attempt.commandId))
    const original = await requireCaseCommand(await platformApi.getToolInvocation(attempt.commandId), stage, attempt, input, actorId)
    requireRunPlan(original.status === 'waiting_confirmation')
    return requireCaseCommand(await platformApi.confirmToolInvocation(attempt.commandId), stage, attempt, input, actorId)
  },
  async recover(stage: CaseCommandStage, attempt: CaseCommandAttempt, input: Record<string, unknown>, actorId: string, signal: AbortSignal) {
    requireCaseInput(stage, input)
    requireRunPlan(caseId(actorId) && caseId(attempt.requestKey) && attempt.requestHash === await canonicalDigest(input)); signal.throwIfAborted()
    const command = attempt.commandId ? await platformApi.getToolInvocation(attempt.commandId, { signal })
      : await request<ToolInvocation>(`/v1/tool-invocations/resolve?${new URLSearchParams({ project_id: input.project_id as string,
        tool_id: caseTools[stage], request_key: attempt.requestKey })}`, { signal, cache: 'no-store' })
    const value = await requireCaseCommand(command, stage, attempt, input, actorId)
    signal.throwIfAborted(); return value
  },
  async read(attempt: CaseCommandAttempt, input: CaseExecutionSelection, plan: RunPlanArchive, actorId: string, signal: AbortSignal) {
    requireCaseParent(input, plan)
    for (let count = 0; count < 3; count++) {
      const command = await this.recover('execute', attempt, { ...input }, actorId, signal)
      if (['pending', 'waiting_confirmation'].includes(command.status)) return { command, history: undefined }
      const value = await request<unknown>(`/v1/projects/${encodeURIComponent(input.project_id)}/quality/run-plan-case-executions/${encodeURIComponent(command.id)}`,
        { signal, cache: 'no-store' })
      signal.throwIfAborted()
      if (!generationEqual((value as { status?: unknown })?.status, command.status) && count < 2) continue
      const history = await verifyCaseHistory(value, command, input, plan)
      signal.throwIfAborted(); return { command, history }
    }
    throw new Error('Original case execution status could not be verified')
  },
}
