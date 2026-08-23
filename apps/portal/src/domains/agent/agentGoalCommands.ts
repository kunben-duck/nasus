import { agentApi } from './api'

export function resumeAgentGoal(goalId: string) {
  return agentApi.resumeAgentGoal(goalId)
}
