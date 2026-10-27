import { useQueryClient } from '@tanstack/react-query'

import type { AgentGoal } from '../../domains/agent/types'
import type { ProjectCard } from '../../domains/platform/types'
import { createProjectRouteActionHandlers } from './projectRouteActionHandlers'
import { useProjectActionLock } from './useProjectActionLock'
import type { ProjectConversationController } from './useProjectConversationModel'
import { useProjectPromptRunner } from './useProjectPromptRunner'
import { useProjectToolConfirmation } from './useProjectToolConfirmation'
import { useI18n } from '../../shared/i18n/I18nProvider'

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
  const { locale } = useI18n()
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
    locale,
  })

  return {
    ...promptRunner,
    ...actionHandlers,
    confirmToolInvocation: toolConfirmation.confirmToolInvocation,
    loading:
      projectConversation.isLoading ||
      !projectConversation.conversationId ||
      promptRunner.isPromptRunning ||
      projectConversation.isSending ||
      toolConfirmation.isConfirmingToolInvocation ||
      projectActionLock.actionRunning,
    activeActionId: projectActionLock.activeActionId,
    streaming: Boolean(projectConversation.activeTurn && !['completed', 'interrupted', 'failed'].includes(projectConversation.activeTurn.status)),
  }
}
