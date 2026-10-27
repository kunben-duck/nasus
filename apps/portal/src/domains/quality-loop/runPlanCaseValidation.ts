import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { exactKeys, utc } from './environmentRecordValidation'
import { generationDigest, generationEqual } from './testDesignGenerationValidation'
import { requireRunPlan } from './runPlanValidation'
import { scriptProtocol } from './automationScriptValidation'
import type { ToolInvocation } from '../platform/types'
import type { RunPlanArchive } from './types/runPlans'
import type { CaseCommandAttempt, CaseCommandStage, CaseExecutionFields, CaseExecutionSelection } from './types/runPlanCaseJobs'

export const caseTools = { execute: 'quality.run_plan.execute_http', cancel: 'quality.run_plan.cancel_http' } as const
export const caseSelectionKeys = ['project_id', 'run_id', 'run_plan_id', 'run_plan_artifact_hash', 'plan_digest', 'timeout_ms',
  'build_binding_id', 'build_binding_artifact_hash', 'environment_record_id', 'environment_record_artifact_hash',
  'locator_record_id', 'locator_record_artifact_hash', 'fixture_setups'] as const
export const caseId = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0
  && Array.from(value).length <= 128 && !Array.from(value).some((char) => {
    const point = char.codePointAt(0)!
    return point < 32 || point === 127 || point >= 0xd800 && point <= 0xdfff
  })
const coordinator = new Set(['idempotency_key', 'agent_goal_id', 'agent_step_id', 'agent_plan_step_id', 'requested_tool_id', 'user_message',
  'planner_kind', 'stream_reply', 'version_id', 'us_id', 'task_id', 'conversation_id', 'agent_loop_iteration_id', 'agent_loop_attempt',
  'goal_template', 'goal_description', 'tool_plan_index', 'tool_plan_reason', 'confirmed_actor_id', 'confirmed_by_user', 'confirmed_at', 'case_claim_protocol'])
export function requireCaseSelection(value: unknown): asserts value is CaseExecutionSelection {
  const v = value as CaseExecutionSelection
  exactKeys(v, [...caseSelectionKeys])
  requireRunPlan([v.project_id, v.run_id, v.run_plan_id, v.build_binding_id, v.environment_record_id, v.locator_record_id].every(caseId)
    && [v.run_plan_artifact_hash, v.plan_digest, v.build_binding_artifact_hash, v.environment_record_artifact_hash, v.locator_record_artifact_hash].every(generationDigest)
    && Number.isInteger(v.timeout_ms) && v.timeout_ms >= 1000 && v.timeout_ms <= 120000
    && Array.isArray(v.fixture_setups) && v.fixture_setups.length >= 1 && v.fixture_setups.length <= 512)
  for (const item of v.fixture_setups) {
    exactKeys(item, ['case_id', 'invocation_id'])
    requireRunPlan(caseId(item.case_id) && caseId(item.invocation_id))
  }
  requireRunPlan(new Set(v.fixture_setups.map((v) => v.case_id)).size === v.fixture_setups.length
    && new Set(v.fixture_setups.map((v) => v.invocation_id)).size === v.fixture_setups.length)
}
export function requireCaseFields(value: unknown, plan?: RunPlanArchive): asserts value is CaseExecutionFields {
  const v = value as CaseExecutionFields
  exactKeys(v, ['runId', 'environmentCommandId', 'locatorCommandId', 'timeoutMs', 'setups'])
  requireRunPlan([v.runId, v.environmentCommandId, v.locatorCommandId].every(caseId)
    && Number.isInteger(v.timeoutMs) && v.timeoutMs >= 1000 && v.timeoutMs <= 120000
    && Array.isArray(v.setups) && v.setups.length >= 1 && v.setups.length <= 512)
  for (const item of v.setups) { exactKeys(item, ['caseId', 'commandId']); requireRunPlan(caseId(item.caseId) && caseId(item.commandId)) }
  requireRunPlan(new Set(v.setups.map((v) => v.caseId)).size === v.setups.length && new Set(v.setups.map((v) => v.commandId)).size === v.setups.length)
  if (plan) requireRunPlan(generationEqual(v.setups.map((v) => v.caseId), plan.artifact.plan.prepared.cases.map((v) => v.case_id)))
}
export function requireCaseParent(input: CaseExecutionSelection, plan: RunPlanArchive) {
  requireCaseSelection(input)
  requireRunPlan(input.project_id === plan.metadata.project_id && input.run_plan_id === plan.metadata.run_plan_id
    && input.run_plan_artifact_hash === plan.metadata.artifact_hash && input.plan_digest === plan.metadata.plan_digest
    && generationEqual(input.fixture_setups.map((v) => v.case_id), plan.artifact.plan.prepared.cases.map((v) => v.case_id)))
}
export function caseControlInput(input: CaseExecutionSelection, invocationId: string) {
  requireCaseSelection(input); requireRunPlan(caseId(invocationId))
  return { project_id: input.project_id, invocation_id: invocationId }
}
export function requireCaseInput(stage: CaseCommandStage, input: Record<string, unknown>) {
  if (stage === 'execute') requireCaseSelection(input)
  else { exactKeys(input, ['project_id', 'invocation_id']); requireRunPlan(caseId(input.project_id) && caseId(input.invocation_id)) }
}
export async function requireCaseCommand(value: ToolInvocation, stage: CaseCommandStage, attempt: CaseCommandAttempt,
  input: Record<string, unknown>, actorId: string) {
  const body = value?.input_payload
  requireRunPlan(caseId(value?.id) && caseId(actorId) && caseId(attempt.requestKey) && generationDigest(attempt.requestHash)
    && (!attempt.commandId || value.id === attempt.commandId) && value.tool_id === caseTools[stage]
    && body && typeof body === 'object' && !Array.isArray(body) && body.idempotency_key === attempt.requestKey
    && ['pending', 'waiting_confirmation', 'running', 'completed', 'failed', 'cancelled'].includes(value.status))
  const raw = Object.fromEntries(Object.entries(body).filter(([key]) => !coordinator.has(key)))
  requireCaseInput(stage, raw)
  requireRunPlan(generationEqual(raw, input) && await canonicalDigest(input) === attempt.requestHash)
  if (['running', 'completed', 'failed', 'cancelled'].includes(value.status)) {
    requireRunPlan(body.confirmed_by_user === true && body.confirmed_actor_id === actorId && utc(body.confirmed_at))
    if (stage === 'execute') requireRunPlan(body.case_claim_protocol === 'nasus.run-plan-case-preparation.v1')
  }
  if (value.result) requireRunPlan(value.result.invocation_id === value.id && value.result.status === value.status)
  return value
}
export async function caseJob(plan: RunPlanArchive, input: CaseExecutionSelection, ordinal: number) {
  requireCaseParent(input, plan)
  const p = plan.artifact.plan, c = p.prepared.cases[ordinal], script = p.proposal.scripts.find((v) => v.case_id === c?.case_id)
  requireRunPlan(c && script?.case_id === c.case_id)
  return { job_id: 'run-plan-case-' + (await canonicalDigest([input.run_id, input.plan_digest, c.case_id, input.timeout_ms])).slice(7),
    project_id: input.project_id, us_id: c.case_id, execution_kind: 'http', receipt_protocol: scriptProtocol(p.proposal),
    metadata: { run_id: input.run_id, plan_digest: input.plan_digest, case_id: c.case_id, case_digest: await canonicalDigest(c),
      script_revision_id: p.script_pin.script_revision_id, review_revision_id: p.review_pin.revision_id, context_id: p.prepared.context_pin.context_id },
    base_url: p.selection.environment.base_url, steps: script.actions, timeout_ms: input.timeout_ms }
}
