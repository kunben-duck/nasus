import { useMemo } from 'react'

import type { ProjectCard } from '../../domains/platform/types'
import { useConversation } from '../../domains/agent/useConversation'
import { useAgentGoalExplanation } from '../../domains/agent/useAgentGoalExplanation'
import { useAgentRuntimeDetails } from '../../domains/agent/useAgentRuntimeDetails'
import { fallbackProjectMessages, toMessageRows } from './projectRouteMessages'

export type ProjectConversationController = ReturnType<typeof useConversation>

export function useProjectConversationModel(project?: ProjectCard) {
  const projectConversation = useConversation('project', project?.id ?? 'project', project?.name ?? 'Project', {
    enabled: Boolean(project?.id),
  })
  const pausedProjectGoal = useMemo(
    () => projectConversation.conversation?.agent_goals.find((goal) => goal.status === 'paused'),
    [projectConversation.conversation],
  )
  const latestProjectGoal = projectConversation.conversation?.agent_goals.at(-1)
  const agentGoalExplanationQuery = useAgentGoalExplanation(latestProjectGoal)
  const runtimeDetails = useAgentRuntimeDetails(projectConversation.conversationId, latestProjectGoal)
  const visibleMessages = useMemo(() => {
    const rows = toMessageRows(projectConversation.conversation)
    return rows.length ? rows : fallbackProjectMessages
  }, [projectConversation.conversation])

  return {
    projectConversation,
    pausedProjectGoal,
    latestProjectGoal,
    agentGoalExplanation: agentGoalExplanationQuery.data,
    memoryContext: runtimeDetails.memoryContext,
    swarmRuns: runtimeDetails.swarmRuns,
    visibleMessages,
  }
}
