import { useQueryClient } from '@tanstack/react-query'

import type { AgentGoal } from '../../domains/agent/types'
import type { ProjectCard } from '../../domains/platform/types'
import { createProjectRouteActionHandlers } from './projectRouteActionHandlers'
import { useProjectActionLock } from './useProjectActionLock'
import type { ProjectConversationController } from './useProjectConversationModel'
import { useProjectPromptRunner } from './useProjectPromptRunner'
import { useProjectToolConfirmation } from './useProjectToolConfirmation'

type ProjectRouteActionArgs = {
  project?: ProjectCard
  projectConversation: ProjectConversationController
  pausedProjectGoal?: AgentGoal
}

export function useProjectRouteActions({
  project,
  projectConversation,
  pausedProjectGoal,
}: ProjectRouteActionArgs) {
  const queryClient = useQueryClient()
  const projectActionLock = useProjectActionLock()
  const promptRunner = useProjectPromptRunner({
    project,
    projectConversation,
    queryClient,
  })
  const toolConfirmation = useProjectToolConfirmation({ project, queryClient, projectActionLock })
  const actionHandlers = createProjectRouteActionHandlers({
    project,
    pausedProjectGoal,
    projectConversation,
    queryClient,
    projectActionLock,
  })

  return {
    ...promptRunner,
    ...actionHandlers,
    confirmToolInvocation: toolConfirmation.confirmToolInvocation,
    loading:
      promptRunner.isPromptRunning ||
      projectConversation.isSending ||
      toolConfirmation.isConfirmingToolInvocation ||
      projectActionLock.actionRunning,
    activeActionId: projectActionLock.activeActionId,
  }
}
