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
import type { Locale } from '../../shared/i18n/I18nProvider'

export function createProjectRouteActionHandlers({
  project,
  pausedProjectGoal,
  projectConversation,
  queryClient,
  projectActionLock,
  locale,
}: {
  project?: ProjectCard
  pausedProjectGoal?: AgentGoal
  projectConversation: ProjectConversationController
  queryClient: QueryClient
  projectActionLock: ProjectActionLockController
  locale: Locale
}) {
  async function invokeProjectAction(actionId: StudioActionId, input: Record<string, unknown> = {}) {
    if (!project) return
    await projectActionLock.runLockedAction(actionId, async () => {
      const result = await executeProjectActionCommand(project, actionId, input, locale)
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
        await projectConversation.sendMessage(buildSystemImageSourceBindingMessage(sources, locale))
        await invalidateProjectWorkspaceQueries(
          queryClient,
          project,
          projectConversation.conversationId,
        )
        return
      }
      if (pausedProjectGoal?.target_refs?.some((ref) => ref.startsWith('source_manifest:')
        || ref.startsWith('build_plan:') || ref.startsWith('image_revision:'))) {
        throw new Error('This goal already has fixed sources. Use its saved plan to prepare a separately confirmed enrichment phase.')
      }
      const result = await executeSystemImageSourceActionPlan(project, sources, locale)
      await invalidateProjectWorkspaceQueries(queryClient, project, result.conversationId)
    })
  }

  async function refreshGoalCheckpoint(goal: AgentGoal) {
    const checkpoint = await projectConversation.refreshConversation()
    if (
      !checkpoint || checkpoint.id !== goal.conversation_id || checkpoint.project_id !== goal.project_id ||
      !checkpoint.agent_goals.some((current) => current.id === goal.id &&
        current.conversation_id === goal.conversation_id && current.project_id === goal.project_id)
    ) {
      throw new Error('The goal checkpoint could not be verified. Reload before continuing.')
    }
    // Only the verified conversation controls consent; auxiliary panels refresh independently.
    if (project) void invalidateProjectWorkspaceQueries(queryClient, project).catch(() => undefined)
  }

  async function confirmPendingGoal() {
    if (!pausedProjectGoal || !['waiting_confirmation', 'build_plan_phase_prepared', 'reference_candidate_review'].includes(pausedProjectGoal.pause_reason ?? '')) return
    await projectActionLock.runLockedAction(`agent-goal-resume:${pausedProjectGoal.id}`, async () => {
      try {
        await resumeAgentGoal(pausedProjectGoal.id, pausedProjectGoal)
      } finally {
        await refreshGoalCheckpoint(pausedProjectGoal)
      }
    })
  }

  async function continueStructuralInvestigation() {
    if (!pausedProjectGoal || pausedProjectGoal.pause_reason !== 'structural_candidate_review') return
    await projectActionLock.runLockedAction(`agent-goal-investigate:${pausedProjectGoal.id}`, async () => {
      try {
        await resumeAgentGoal(pausedProjectGoal.id, pausedProjectGoal)
      } finally {
        await refreshGoalCheckpoint(pausedProjectGoal)
      }
    })
  }

  return {
    invokeProjectAction,
    initializeSystemImage,
    buildSystemImageFromSources,
    confirmPendingGoal,
    continueStructuralInvestigation,
  }
}
