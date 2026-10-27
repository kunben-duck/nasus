import { request } from '../../shared/api/client'
import { platformApi } from '../platform/api'
import type { AgentGoal } from '../agent/types'
import { activeGoalSteps } from '../agent/activePlanPhase'
import { verifyRevisionHistory } from './buildPlanApi'
import type { BuildPlan, BuildPlanRevision } from './types/buildPlan'

export interface BuildPlanPhase {
  phase_hash: string
  phase: {
    phase_id: string; project_id: string; goal_id: string; root_plan_id: string
    revision_id: string; revision_hash: string; plan_id: string; plan_digest: string
    source_manifest_id: string; source_manifest_hash: string; phase_number: number; start_index: number
    parent_phase_id: string | null; parent_phase_hash: string | null; prefix_hash: string
    invocation_id: string; created_at: string; policy_version: 'nasus.agent-image-plan-phase.v1'
  }
}

export interface PhaseCheckpoint { goal: AgentGoal; history: BuildPlanRevision[]; phases: BuildPlanPhase[] }
const toolId = 'system_image.build.plan.activate_revision'
const hash = (value: unknown) => typeof value === 'string' && /^sha256:[a-f0-9]{64}$/.test(value)

export function verifyPhaseCheckpoint(plan: BuildPlan, checkpoint: PhaseCheckpoint) {
  const { goal, history, phases } = checkpoint
  if (goal.project_id !== plan.project_id || !goal.target_refs?.includes(`build_plan:${plan.plan_id}`)
    || goal.status !== 'paused' || !Array.isArray(phases) || phases.length > 80) throw new Error('Phase checkpoint scope changed')
  verifyRevisionHistory(history, plan.project_id, plan.plan_id, goal.id)
  if (history.length && history[0].revision.from_plan_digest !== plan.plan_digest) {
    throw new Error('Phase revision root digest changed')
  }
  const ids = new Set<string>()
  for (const [index, item] of phases.entries()) {
    const phase = item.phase, previous = phases[index - 1]?.phase
    const revision = history.find((entry) => entry.revision.revision_id === phase?.revision_id)
    const marker = goal.steps[phase?.start_index]
    if (!phase || !revision || phase.project_id !== plan.project_id || phase.root_plan_id !== plan.plan_id
      || phase.goal_id !== goal.id || phase.phase_number !== index + 1 || ids.has(phase.phase_id)
      || phase.policy_version !== 'nasus.agent-image-plan-phase.v1'
      || phase.parent_phase_id !== (previous?.phase_id ?? null) || phase.parent_phase_hash !== (phases[index - 1]?.phase_hash ?? null)
      || phase.revision_hash !== revision.revision_hash || phase.plan_id !== revision.revision.plan_id
      || phase.plan_digest !== revision.revision.plan_digest || phase.source_manifest_id !== revision.revision.source_manifest_id
      || phase.source_manifest_hash !== revision.revision.source_manifest_hash
      || ![item.phase_hash, phase.prefix_hash, phase.plan_digest, phase.source_manifest_hash].every(hash)
      || !Number.isInteger(phase.start_index) || phase.start_index < 1 || phase.start_index > 503
      || (previous && phase.start_index <= previous.start_index)
      || marker?.id !== `build_plan_phase:${phase.phase_id}` || marker.status !== 'completed'
      || marker.tool_input_payload?.phase_hash !== item.phase_hash || marker.tool_input_payload?.plan_id !== phase.plan_id
      || marker.tool_input_payload?.source_manifest_id !== phase.source_manifest_id) throw new Error('Phase ledger differs from its displayed goal')
    ids.add(phase.phase_id)
  }
  const markers = goal.steps.filter((step) => step.id.startsWith('build_plan_phase:')).map((step) => step.id)
  if (JSON.stringify(markers) !== JSON.stringify(phases.map((item) => `build_plan_phase:${item.phase.phase_id}`))) {
    throw new Error('Phase ledger is incomplete')
  }
  activeGoalSteps(goal)
}

export const buildPlanPhaseApi = {
  async history(plan: BuildPlan, goal: AgentGoal, history: BuildPlanRevision[], signal: AbortSignal) {
    const phases = await request<BuildPlanPhase[]>(`/v1/projects/${encodeURIComponent(plan.project_id)}/system-image/build-plans/${encodeURIComponent(plan.plan_id)}/phases?${new URLSearchParams({ goal_id: goal.id })}`,
      { signal, cache: 'no-store' })
    const checkpoint = { goal, history, phases }
    verifyPhaseCheckpoint(plan, checkpoint)
    return checkpoint
  },
  async prepare(plan: BuildPlan, checkpoint: PhaseCheckpoint, maxSeconds: number, key: string) {
    verifyPhaseCheckpoint(plan, checkpoint)
    const revision = checkpoint.history.at(-1), parent = checkpoint.phases.at(-1)
    if (!revision || revision.revision.plan_id === parent?.phase.plan_id
      || (parent && revision.revision.from_plan_id !== parent.phase.plan_id)
      || !['structural_candidate_review', 'build_completion_review'].includes(checkpoint.goal.pause_reason ?? '')
      || !Number.isInteger(maxSeconds) || maxSeconds < 1 || maxSeconds > plan.proposal.intent.budget.max_active_seconds) {
      throw new Error('Phase revision or budget changed')
    }
    return platformApi.invokeTool({ tool_id: toolId, conversation_id: checkpoint.goal.conversation_id, idempotency_key: key,
      input: { project_id: plan.project_id, root_plan_id: plan.plan_id, goal_id: checkpoint.goal.id,
        revision_id: revision.revision.revision_id, revision_hash: revision.revision_hash,
        expected_goal: checkpoint.goal, parent_phase_id: parent?.phase.phase_id ?? null, parent_phase_hash: parent?.phase_hash ?? null,
        budget: { max_tool_calls: 1, max_model_calls: 0, max_active_seconds: maxSeconds, max_cost_microusd: 0 } } })
  },
  async confirm(id: string, checkpoint: PhaseCheckpoint) {
    const command = await platformApi.confirmToolInvocation(id)
    const refs = command.result?.object_refs ?? [], revision = checkpoint.history.at(-1)
    if (command.id !== id || command.tool_id !== toolId || command.status !== 'completed'
      || command.result?.invocation_id !== id || command.result.status !== 'completed' || refs.length !== 3
      || !refs.includes(`build_plan:${revision?.revision.plan_id}`) || !refs.includes(`agent_goal:${checkpoint.goal.id}`)
      || refs.filter((ref) => ref.startsWith('build_plan_phase:') && ref.length > 'build_plan_phase:'.length).length !== 1) {
      throw new Error('Phase confirmation outcome could not be verified')
    }
    return command
  },
}
