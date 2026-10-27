import { request } from '../../shared/api/client'
import type { AgentGoal } from '../agent/types'
import type { ToolInvocation } from '../platform/types'
import { buildPlanApi } from './buildPlanApi'
import { imageRevisionApi } from './imageRevisionApi'
import { completionReviewStep, validReviewId, validReviewHash, type BuildReviewSelection,
  type BuildReviewHandoff, type BuildInvestigationReport } from './buildReviewHandoff'

const canonical = (value: unknown) => JSON.stringify(value, (_, item) => item && typeof item === 'object' && !Array.isArray(item)
  ? Object.fromEntries(Object.keys(item).sort().map((key) => [key, item[key]])) : item)
const same = (left: unknown, right: unknown) => canonical(left) === canonical(right)
// Match the backend's fixed coordination envelope; unknown business fields
// must still fail the comparison against the saved step and report.
const coordinationKeys = new Set(['idempotency_key', 'agent_goal_id', 'agent_step_id', 'agent_plan_step_id',
  'requested_tool_id', 'user_message', 'planner_kind', 'stream_reply', 'version_id', 'us_id', 'task_id',
  'conversation_id', 'agent_loop_iteration_id', 'agent_loop_attempt', 'goal_template', 'goal_description',
  'tool_plan_index', 'tool_plan_reason', 'confirmed_actor_id', 'confirmed_at', 'confirmed_by_user', 'fixture_claim_protocol', 'case_claim_protocol'])
const input = (payload: Record<string, unknown>) => Object.fromEntries(Object.entries(payload)
  .filter(([key]) => !coordinationKeys.has(key)))

export async function readBuildReviewHandoff(projectId: string, selection: BuildReviewSelection, signal: AbortSignal): Promise<BuildReviewHandoff> {
  signal.throwIfAborted()
  if (![projectId, selection.goalId, selection.invocationId].every(validReviewId)) throw new Error('Invalid build review identity')
  const read = <T>(path: string) => request<T>(path, { signal, cache: 'no-store' })
  const goalPath = `/v1/agent-goals/${encodeURIComponent(selection.goalId)}`
  const goal = await read<AgentGoal>(goalPath)
  const step = completionReviewStep(goal)
  if (goal.id !== selection.goalId || goal.project_id !== projectId || step?.tool_invocation_id !== selection.invocationId) {
    throw new Error('The original build review checkpoint changed')
  }
  const command = await read<ToolInvocation & { result?: { investigation?: {
    kind: string; project_id: string; revision_id: string; revision_hash: string
  } } }>(`/v1/tool-invocations/${encodeURIComponent(selection.invocationId)}`)
  const receipt = command.result?.investigation
  if (command.id !== selection.invocationId || command.conversation_id !== goal.conversation_id
      || command.tool_id !== 'system_image.build.investigate' || command.status !== 'completed'
      || command.result?.status !== 'completed' || command.result.invocation_id !== command.id
      || command.input_payload.agent_goal_id !== goal.id
      || (command.input_payload.agent_step_id !== undefined && command.input_payload.agent_step_id !== step.id)
      || !step.tool_input_payload
      || !same(input(command.input_payload), input(step.tool_input_payload))
      || receipt?.kind !== 'investigation_revision' || receipt.project_id !== projectId
      || !validReviewId(receipt.revision_id) || !validReviewHash(receipt.revision_hash)
      || !same(command.result.object_refs, [`image_investigation:${receipt.revision_id}`])) {
    throw new Error('The saved investigation command could not be verified')
  }
  const report = await read<BuildInvestigationReport>(`/v1/projects/${encodeURIComponent(projectId)}/system-image/build-investigations/${encodeURIComponent(receipt.revision_id)}`)
  const body = report.request
  if (report.revision_id !== receipt.revision_id || report.revision_hash !== receipt.revision_hash
      || body.project_id !== projectId || body.goal_id !== goal.id
      || !validReviewId(body.plan_id) || !validReviewId(body.image_revision_id)
      || !validReviewHash(body.plan_digest) || !validReviewHash(body.image_artifact_hash)
      || !same(input(command.input_payload), Object.fromEntries(Object.entries(body).filter(([, value]) => value !== null)))
      || report.review.image_revision_id !== body.image_revision_id || report.review.image_artifact_hash !== body.image_artifact_hash
      || !['nasus.image-investigation-revision.v1', 'nasus.image-investigation-revision.v2'].includes(report.review.policy_version)
      || report.review.publication_allowed !== false
      || !Array.isArray(report.review.gaps)) throw new Error('The saved investigation report changed')
  const plan = await buildPlanApi.read(projectId, body.plan_id, signal)
  const target = plan.proposal.intent.target
  if (plan.plan_digest !== body.plan_digest || !target || target.project_id !== projectId
      || !validReviewId(target.target_baseline_id)) throw new Error('The original fixed build target changed')
  const page = await imageRevisionApi.page(projectId, body.image_revision_id, { section: 'source_members', offset: 0 }, signal, 1)
  const image = page.revision
  if (image.project_id !== projectId || image.image_revision_id !== body.image_revision_id
      || image.artifact_hash !== body.image_artifact_hash || image.manifest_id !== plan.proposal.intent.source_manifest_id
      || image.manifest_hash !== plan.proposal.intent.source_manifest_hash
      || image.baseline_id !== target.target_baseline_id) {
    throw new Error('The reviewed image differs from the original plan')
  }
  const currentTarget = await buildPlanApi.target(projectId, target.target_baseline_id, signal)
  if (currentTarget.project_id !== projectId || currentTarget.target_baseline_id !== target.target_baseline_id
      || currentTarget.target_version_id !== target.target_version_id) throw new Error('The original build target scope changed')
  // A later publication may change the head without changing this historical
  // review. The publication command independently checks its current CAS pin.
  // Navigation never consumes a checkpoint. Do not show a prior phase if it
  // changed while the separately authorized private reads were in flight.
  const current = await read<AgentGoal>(goalPath)
  signal.throwIfAborted()
  if (!same(goal, current)) throw new Error('The original build review checkpoint changed during verification')
  return { projectId, selection, image, investigation: report, goal,
    targetBaseline: { id: target.target_baseline_id, project_id: projectId } }
}
