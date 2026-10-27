import { useQuery } from '@tanstack/react-query'

import { agentApi } from './api'
import type { AgentGoal } from './types'
import { requireActiveQueryScope } from '../../shared/api/queryScope'

export function useAgentGoalExplanation(goal?: AgentGoal, canReadWorkspace?: () => boolean) {
  const shouldPoll = goal?.status === 'pending' || goal?.status === 'running'

  return useQuery({
    queryKey: [
      'agent-goal-explanation',
      goal?.id,
      goal?.status,
      goal?.steps_completed,
      goal?.pause_reason,
    ],
    queryFn: async ({ signal }) => {
      requireActiveQueryScope(canReadWorkspace, signal)
      const explanation = await agentApi.getAgentGoalExplanation(goal!.id, signal)
      requireActiveQueryScope(canReadWorkspace, signal)
      return explanation
    },
    enabled: Boolean(goal?.id),
    refetchInterval: shouldPoll ? 1500 : false,
  })
}
