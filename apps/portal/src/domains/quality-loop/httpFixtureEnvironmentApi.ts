import { request } from '../../shared/api/client'
import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { platformApi } from '../platform/api'
import { environmentRecordApi, requireEnvironmentCommand } from './environmentRecordApi'
import { environmentRequestKeys, identity } from './environmentRecordValidation'
import { runPlanBuildApi } from './runPlanBuildApi'
import { buildRequestKeys } from './runPlanBuildValidation'
import { requireRunPlan } from './runPlanValidation'
import type { RunPlanArchive } from './types/runPlans'
import type { RunPlanBuildArchive } from './types/runPlanBuilds'
import type { EnvironmentRecordRequest } from './types/environmentRecords'

// Follow original commands through their full native-build parents; IDs alone are not evidence.
export async function readFixtureEnvironment(plan: RunPlanArchive, commandId: string, signal: AbortSignal) {
  requireRunPlan(identity(commandId)); signal.throwIfAborted()
  const command = await platformApi.getToolInvocation(commandId, { signal }), body = command?.input_payload
  const input = Object.fromEntries(environmentRequestKeys.map((key) => [key, body?.[key]])) as unknown as EnvironmentRecordRequest
  const p = plan.metadata, attempt = { projectId: p.project_id, planId: p.run_plan_id, planHash: p.artifact_hash,
    bindingId: input.build_binding_id, bindingHash: input.build_binding_artifact_hash, commandId,
    requestKey: body?.idempotency_key as string, requestHash: await canonicalDigest(input) }
  await requireEnvironmentCommand(command, attempt)
  requireRunPlan(command.status === 'completed' && identity(input.build_binding_id)); signal.throwIfAborted()
  const path = `/v1/projects/${encodeURIComponent(p.project_id)}/quality/run-plan-builds/${encodeURIComponent(input.build_binding_id)}`
  const hint = await request<RunPlanBuildArchive>(path, { signal, cache: 'no-store' })
  requireRunPlan(hint?.metadata?.project_id === p.project_id && hint.metadata.binding_id === input.build_binding_id
    && hint.metadata.artifact_hash === input.build_binding_artifact_hash && identity(hint.metadata.invocation_id))
  signal.throwIfAborted()
  const build = await platformApi.getToolInvocation(hint.metadata.invocation_id, { signal })
  const buildInput = Object.fromEntries(buildRequestKeys.map((key) => [key, build?.input_payload?.[key]]))
  const original = await runPlanBuildApi.recover({ projectId: p.project_id, planId: p.run_plan_id, planHash: p.artifact_hash,
    commandId: hint.metadata.invocation_id, requestKey: build.input_payload.idempotency_key as string,
    requestHash: await canonicalDigest(buildInput) }, plan, signal)
  requireRunPlan(original.command.status === 'completed')
  const binding = await runPlanBuildApi.read(original.command, original.input, plan, original.builds, signal)
  requireRunPlan(binding.metadata.binding_id === input.build_binding_id && binding.metadata.artifact_hash === input.build_binding_artifact_hash)
  return environmentRecordApi.read(command, plan, binding, signal)
}
