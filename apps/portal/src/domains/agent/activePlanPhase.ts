import type { AgentGoal } from './types'

export function activeGoalSteps(goal: AgentGoal) {
  const refs = (goal.target_refs ?? []).filter((ref) => ref.startsWith('build_plan_phase:'))
  const markers = goal.steps.filter((step) => step.id.startsWith('build_plan_phase:'))
  if (!refs.length && !markers.length) return goal.steps
  if (refs.length !== 1 || markers.at(-1)?.id !== refs[0]
    || goal.steps.filter((step) => step.id === refs[0]).length !== 1) {
    throw new Error('The active phase checkpoint is missing or ambiguous')
  }
  return goal.steps.slice(goal.steps.findIndex((step) => step.id === refs[0]) + 1)
}
