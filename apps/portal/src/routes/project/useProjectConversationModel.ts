import { useMemo } from 'react'

import type { ProjectCard } from '../../domains/platform/types'
import { useConversation } from '../../domains/agent/useConversation'
import { useAgentGoalExplanation } from '../../domains/agent/useAgentGoalExplanation'
import { useAgentRuntimeDetails } from '../../domains/agent/useAgentRuntimeDetails'
import { fallbackProjectMessages, toMessageRows } from './projectRouteMessages'
import { useI18n } from '../../shared/i18n/I18nProvider'

export type ProjectConversationController = ReturnType<typeof useConversation>

export function useProjectConversationModel(project?: ProjectCard, options: {
  existingOnly?: boolean; canReadWorkspace?: () => boolean
} = {}) {
  const { t } = useI18n()
  const projectConversation = useConversation('project', project?.id ?? 'project', project?.name ?? 'Project', {
    enabled: Boolean(project?.id),
    existingOnly: options.existingOnly,
    canReadWorkspace: options.canReadWorkspace,
  })
  const pausedProjectGoal = useMemo(
    () => projectConversation.conversation?.agent_goals.filter((goal) => goal.status === 'paused').at(-1),
    [projectConversation.conversation],
  )
  const latestProjectGoal = projectConversation.conversation?.agent_goals.at(-1)
  const detailGoal = options.existingOnly ? undefined : latestProjectGoal
  const agentGoalExplanationQuery = useAgentGoalExplanation(detailGoal, options.canReadWorkspace)
  const runtimeDetails = useAgentRuntimeDetails(options.existingOnly ? undefined : projectConversation.conversationId,
    detailGoal, options.canReadWorkspace)
  const visibleMessages = useMemo(() => {
    const rows = toMessageRows(projectConversation.conversation)
    return rows.length
      ? rows
      : fallbackProjectMessages(t('Tell me what you want to ship. I can inspect the system image, continue the quality loop, and route every write action through tools.'))
  }, [projectConversation.conversation, t])

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
