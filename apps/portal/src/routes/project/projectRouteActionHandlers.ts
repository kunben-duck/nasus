import type { QueryClient } from '@tanstack/react-query'

import { resumeAgentGoal } from '../../domains/agent/agentGoalCommands'
import type { AgentGoal } from '../../domains/agent/types'
import { invalidateProjectWorkspaceQueries } from '../../domains/platform/projectWorkspaceInvalidation'
import type { ProjectCard } from '../../domains/platform/types'
import {
  buildSystemImageSourceBindingMessage,
  executeProjectActionCommand,
  executeSystemImageSourceActionPlan,
  type StudioActionId,
  type StudioSourceBindingValues,
} from '../../domains/platform/tool-actions'
import type { ProjectActionLockController } from './useProjectActionLock'
import type { ProjectConversationController } from './useProjectConversationModel'

export function createProjectRouteActionHandlers({
  project,
  pausedProjectGoal,
  projectConversation,
  queryClient,
  projectActionLock,
}: {
  project?: ProjectCard
  pausedProjectGoal?: AgentGoal
  projectConversation: ProjectConversationController
  queryClient: QueryClient
  projectActionLock: ProjectActionLockController
}) {
  async function invokeProjectAction(actionId: StudioActionId, input: Record<string, unknown> = {}) {
    if (!project) return
    await projectActionLock.runLockedAction(actionId, async () => {
      const result = await executeProjectActionCommand(project, actionId, input)
      await invalidateProjectWorkspaceQueries(queryClient, project, result.conversationId)
    })
  }

  async function initializeSystemImage() {
    await invokeProjectAction('system-image.build-goal')
  }

  async function buildSystemImageFromSources(sources: StudioSourceBindingValues) {
    if (!project) return
    await projectActionLock.runLockedAction('system-image.source-chain', async () => {
      if (
        pausedProjectGoal?.pause_reason === 'missing_source_binding' &&
        projectConversation.conversationId
      ) {
        await projectConversation.sendMessage(buildSystemImageSourceBindingMessage(sources))
        await invalidateProjectWorkspaceQueries(
          queryClient,
          project,
          projectConversation.conversationId,
        )
        return
      }
      const result = await executeSystemImageSourceActionPlan(project, sources)
      await invalidateProjectWorkspaceQueries(queryClient, project, result.conversationId)
    })
  }

  async function confirmPendingGoal() {
    if (!pausedProjectGoal || pausedProjectGoal.pause_reason !== 'waiting_confirmation') return
    await projectActionLock.runLockedAction(`agent-goal-resume:${pausedProjectGoal.id}`, async () => {
      await resumeAgentGoal(pausedProjectGoal.id)
      if (project) {
        await invalidateProjectWorkspaceQueries(queryClient, project)
      }
    })
  }

  return {
    invokeProjectAction,
    initializeSystemImage,
    buildSystemImageFromSources,
    confirmPendingGoal,
  }
}
