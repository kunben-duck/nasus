import { agentApi } from './api'
import type { AgentGoal } from './types'
import { activeGoalSteps } from './activePlanPhase'

export async function resumeAgentGoal(goalId: string, expected?: AgentGoal) {
  if (expected) {
    const current = await agentApi.getAgentGoal(goalId)
    const saved = activeGoalSteps(expected).filter((step) => step.phase === 'acting' && step.status === 'blocked')
    const blocked = activeGoalSteps(current).filter((step) => step.phase === 'acting' && step.status === 'blocked')
    const prepared = expected.pause_reason === 'build_plan_phase_prepared'
    if (expected.id !== goalId || expected.status !== 'paused' || current.id !== goalId || current.status !== 'paused'
      || current.project_id !== expected.project_id || current.conversation_id !== expected.conversation_id
      || current.pause_reason !== expected.pause_reason
      || (prepared ? saved.length !== 0 || blocked.length !== 0 || !expected.target_refs?.some((ref) => ref.startsWith('build_plan_phase:'))
          || JSON.stringify(activeGoalSteps(current)) !== JSON.stringify(activeGoalSteps(expected))
        : saved.length !== 1 || blocked.length !== 1 || blocked[0].id !== saved[0].id
          || blocked[0].tool_invocation_id !== saved[0].tool_invocation_id || blocked[0].selected_tool_id !== saved[0].selected_tool_id)) {
      throw new Error('The goal checkpoint changed. Reload before continuing.')
    }
  }
  const checkpoint = expected ?? await agentApi.getAgentGoal(goalId)
  return agentApi.resumeAgentGoal(goalId, checkpoint)
}
