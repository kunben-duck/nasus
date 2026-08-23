import { useQuery } from '@tanstack/react-query'

import { agentApi } from './api'
import type { AgentGoal } from './types'

export function useAgentRuntimeDetails(conversationId?: string, goal?: AgentGoal) {
  const memoryQuery = useQuery({
    queryKey: ['agent-memory', goal?.id],
    queryFn: () => agentApi.getAgentMemoryContext({
      conversation_id: conversationId,
      agent_goal_id: goal!.id,
    }),
    enabled: Boolean(conversationId && goal?.id),
    staleTime: 5_000,
  })

  const swarmsQuery = useQuery({
    queryKey: ['agent-swarms', conversationId],
    queryFn: () => agentApi.listAgentSwarms({ conversation_id: conversationId }),
    enabled: Boolean(conversationId),
    staleTime: 2_000,
  })

  return {
    memoryContext: memoryQuery.data,
    swarmRuns: swarmsQuery.data ?? [],
  }
}
