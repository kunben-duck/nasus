import { useQuery } from '@tanstack/react-query'

import { agentApi } from './api'
import type { AgentGoal } from './types'
import { requireActiveQueryScope } from '../../shared/api/queryScope'

export function useAgentRuntimeDetails(conversationId?: string, goal?: AgentGoal, canReadWorkspace?: () => boolean) {
  const memoryQuery = useQuery({
    queryKey: ['agent-memory', goal?.id],
    queryFn: async ({ signal }) => {
      requireActiveQueryScope(canReadWorkspace, signal)
      const memory = await agentApi.getAgentMemoryContext({ conversation_id: conversationId, agent_goal_id: goal!.id }, signal)
      requireActiveQueryScope(canReadWorkspace, signal)
      return memory
    },
    enabled: Boolean(conversationId && goal?.id),
    staleTime: 5_000,
  })

  const swarmsQuery = useQuery({
    queryKey: ['agent-swarms', conversationId],
    queryFn: async ({ signal }) => {
      requireActiveQueryScope(canReadWorkspace, signal)
      const swarms = await agentApi.listAgentSwarms({ conversation_id: conversationId }, signal)
      requireActiveQueryScope(canReadWorkspace, signal)
      return swarms
    },
    enabled: Boolean(conversationId),
    staleTime: 2_000,
  })

  return {
    memoryContext: memoryQuery.data,
    swarmRuns: swarmsQuery.data ?? [],
  }
}
