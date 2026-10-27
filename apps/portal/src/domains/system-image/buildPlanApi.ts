import { request } from '../../shared/api/client'
import { platformApi } from '../platform/api'
import type { BuildPlan, BuildPlanInput, BuildPlanSummary, BuildPlanRevision, BuildTarget } from './types/buildPlan'
import type { AgentGoal } from '../agent/types'

const root = (projectId: string) => `/v1/projects/${encodeURIComponent(projectId)}/system-image/build-plans`
const validHash = (value: unknown) => typeof value === 'string' && /^sha256:[a-f0-9]{64}$/.test(value)
const validId = (value: unknown) => typeof value === 'string' && value.length > 0 && value.length <= 128
  && Array.from(value).every((character) => character.charCodeAt(0) >= 32 && character.charCodeAt(0) !== 127)

export function verifyBuildTarget(target: BuildTarget, projectId: string, baselineId: string) {
  if (!target || target.project_id !== projectId || target.target_baseline_id !== baselineId || !validId(baselineId)
    || (target.target_version_id !== null && !validId(target.target_version_id))
    || (target.expected_head_id === null ? target.expected_head_hash !== null
      : !validId(target.expected_head_id) || !validHash(target.expected_head_hash))) throw new Error('Build target scope mismatch')
  return target
}

export function verifyRevisionHistory(history: BuildPlanRevision[], projectId: string, planId: string, goalId: string) {
  if (!Array.isArray(history) || history.length > 80) throw new Error('Revision history exceeds its bounded ledger')
  const revisions = new Set<string>()
  const plans = new Set([planId])
  for (const [index, item] of history.entries()) {
    const revision = item?.revision
    const parent = history[index - 1]
    if (!revision || revision.project_id !== projectId || revision.goal_id !== goalId || revision.root_plan_id !== planId
      || revision.revision_number !== index + 1 || revision.execution_authorized !== false || revision.publication_authorized !== false
      || revision.parent_revision_id !== (parent?.revision.revision_id ?? null)
      || revision.parent_revision_hash !== (parent?.revision_hash ?? null)
      || revision.from_plan_id !== (parent?.revision.plan_id ?? planId)
      || (parent && revision.from_plan_digest !== parent.revision.plan_digest)
      || ![item.revision_hash, revision.from_plan_digest, revision.plan_digest, revision.source_manifest_hash].every(validHash)
      || ![revision.revision_id, revision.plan_id, revision.source_manifest_id, revision.invocation_id].every(validId)
      || revisions.has(revision.revision_id) || plans.has(revision.plan_id)) throw new Error('Revision history scope mismatch')
    revisions.add(revision.revision_id)
    plans.add(revision.plan_id)
  }
}

export const buildPlanApi = {
  async target(projectId: string, baselineId: string, signal: AbortSignal) {
    const target = await request<BuildTarget>(`/v1/projects/${encodeURIComponent(projectId)}/system-image/build-targets/${encodeURIComponent(baselineId)}`,
      { signal, cache: 'no-store' })
    return verifyBuildTarget(target, projectId, baselineId)
  },
  revisionGoals(projectId: string, planId: string, signal: AbortSignal) {
    return request<{ goal_id: string; title: string; pause_reason: string }[]>(
      `${root(projectId)}/${encodeURIComponent(planId)}/revision-goals`, { signal, cache: 'no-store' })
  },
  async revisionCheckpoint(projectId: string, planId: string, goalId: string, signal: AbortSignal) {
    const goal = await request<AgentGoal>(`/v1/agent-goals/${encodeURIComponent(goalId)}`, { signal, cache: 'no-store' })
    if (goal.id !== goalId || goal.project_id !== projectId || !goal.target_refs?.includes(`build_plan:${planId}`)
      || goal.status !== 'paused' || !['structural_candidate_review', 'build_completion_review', 'build_plan_phase_prepared'].includes(goal.pause_reason ?? '')) {
      throw new Error('Original goal checkpoint changed')
    }
    const history = await request<BuildPlanRevision[]>(`${root(projectId)}/${encodeURIComponent(planId)}/revisions?${new URLSearchParams({ goal_id: goalId })}`,
      { signal, cache: 'no-store' })
    verifyRevisionHistory(history, projectId, planId, goalId)
    return { goal, history }
  },
  async prepareRevision(plan: BuildPlan, manifestId: string, checkpoint: { goal: AgentGoal; history: BuildPlanRevision[] }, key: string) {
    verifyRevisionHistory(checkpoint.history, plan.project_id, plan.plan_id, checkpoint.goal.id)
    if (checkpoint.goal.project_id !== plan.project_id || !checkpoint.goal.target_refs?.includes(`build_plan:${plan.plan_id}`)
      || checkpoint.goal.status !== 'paused' || !['structural_candidate_review', 'build_completion_review'].includes(checkpoint.goal.pause_reason ?? '')
      || (checkpoint.history.length && checkpoint.history[0].revision.from_plan_digest !== plan.plan_digest)) {
      throw new Error('Revision checkpoint differs from its displayed root plan')
    }
    const previous = checkpoint.history.at(-1)
    return platformApi.invokeTool({ conversation_id: checkpoint.goal.conversation_id, idempotency_key: key,
      tool_id: 'system_image.build.plan.revise', input: {
        project_id: plan.project_id, goal_id: checkpoint.goal.id, root_plan_id: plan.plan_id,
        from_plan_id: previous?.revision.plan_id ?? plan.plan_id,
        from_plan_digest: previous?.revision.plan_digest ?? plan.plan_digest,
        source_manifest_id: manifestId, parent_revision_id: previous?.revision.revision_id ?? null,
        parent_revision_hash: previous?.revision_hash ?? null, expected_goal: checkpoint.goal,
      } })
  },
  async confirmRevision(commandId: string) {
    if (!validId(commandId)) throw new Error('Revision command identity is invalid')
    const command = await platformApi.confirmToolInvocation(commandId)
    const refs = command.result?.object_refs ?? []
    if (command.id !== commandId || command.tool_id !== 'system_image.build.plan.revise' || command.status !== 'completed'
      || command.result?.invocation_id !== commandId || command.result.status !== 'completed' || refs.length !== 2
      || refs.filter((ref) => ref.startsWith('build_plan_revision:') && validId(ref.slice('build_plan_revision:'.length))).length !== 1
      || refs.filter((ref) => ref.startsWith('build_plan:') && validId(ref.slice('build_plan:'.length))).length !== 1) {
      throw new Error('Revision confirmation outcome could not be verified')
    }
    return command
  },
  list(projectId: string, cursor: string, signal: AbortSignal) {
    return request<{ items: BuildPlanSummary[]; next_after_id: string | null }>(
      `${root(projectId)}?${new URLSearchParams({ after_id: cursor, limit: '20' })}`, { signal, cache: 'no-store' })
  },
  async read(projectId: string, planId: string, signal: AbortSignal) {
    const plan = await request<BuildPlan>(`${root(projectId)}/${encodeURIComponent(planId)}`, { signal, cache: 'no-store' })
    if (plan.project_id !== projectId || plan.plan_id !== planId || plan.proposal.intent.project_id !== projectId
      || plan.proposal.state !== 'draft' || plan.proposal.execution_ready !== false || plan.proposal.authorization_state !== 'not_granted') {
      throw new Error('Build plan scope mismatch')
    }
    const intent = plan.proposal.intent
    if (plan.proposal.policy_version === 'nasus.image-investigation-plan.v3') {
      verifyBuildTarget(intent.target!, projectId, intent.target?.target_baseline_id ?? '')
      const bindings = intent.sources.map((item) => item.binding_id)
      if (intent.expected_head_status !== 'resolved' || intent.expected_head !== intent.target!.expected_head_id
        || JSON.stringify(intent.scope_binding_ids) !== JSON.stringify(bindings)
        || bindings.length !== new Set(bindings).size) throw new Error('Build intent scope mismatch')
    } else if (intent.target) throw new Error('Unexpected target on a legacy build plan')
    return plan
  },
  async propose(input: BuildPlanInput, key: string) {
    const invocation = await platformApi.invokeTool({ tool_id: 'system_image.build.plan', input: { ...input, idempotency_key: key } })
    const refs = invocation.result?.object_refs.filter((ref) => ref.startsWith('build_plan:')) ?? []
    if (invocation.status !== 'completed' || refs.length !== 1) throw new Error('Build plan could not be verified')
    if (input.target && (invocation.tool_id !== 'system_image.build.plan' || invocation.result?.invocation_id !== invocation.id
      || Object.entries(input.target).some(([name, value]) => (invocation.input_payload.target as BuildTarget | undefined)?.[name as keyof BuildTarget] !== value))) {
      throw new Error('Build command differs from the displayed target')
    }
    return refs[0].slice('build_plan:'.length)
  },
}
