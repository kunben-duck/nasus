import { useQuery } from '@tanstack/react-query'

import { agentApi } from './api'
import type { AgentGoal } from './types'

export function useAgentGoalExplanation(goal?: AgentGoal) {
  const shouldPoll = goal?.status === 'pending' || goal?.status === 'running'

  return useQuery({
    queryKey: [
      'agent-goal-explanation',
      goal?.id,
      goal?.status,
      goal?.steps_completed,
      goal?.pause_reason,
    ],
    queryFn: () => agentApi.getAgentGoalExplanation(goal!.id),
    enabled: Boolean(goal?.id),
    refetchInterval: shouldPoll ? 1500 : false,
  })
}
