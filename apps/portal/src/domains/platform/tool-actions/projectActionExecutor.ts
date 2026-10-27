import { agentApi } from '../../agent/api'
import { waitForConversationTurn } from '../../agent/conversationTurns'
import { platformApi } from '../api'
import type { ProjectCard } from '../types'
import { buildStudioActionCommand } from './studioActionCommand'
import { buildSystemImageSourceActionPlan } from './systemImageSourcePlan'
import type { StudioActionCommand, StudioActionId, StudioSourceBindingValues } from './types'
import type { Locale } from '../../../shared/i18n/I18nProvider'

type ProjectActionExecutionResult = {
  conversationId: string
}

export async function executeProjectActionCommand(
  activeProject: ProjectCard,
  actionId: StudioActionId,
  input: Record<string, unknown> = {},
  locale: Locale = 'en',
): Promise<ProjectActionExecutionResult> {
  const conversation = await agentApi.ensureConversation('project', activeProject.id, activeProject.name)
  const command = buildStudioActionCommand(actionId, {
    projectId: activeProject.id,
    projectName: activeProject.name,
    input,
  }, locale)
  await executeActionCommand(conversation.id, command)
  return { conversationId: conversation.id }
}

export async function executeSystemImageSourceActionPlan(
  activeProject: ProjectCard,
  sources: StudioSourceBindingValues,
  locale: Locale = 'en',
): Promise<ProjectActionExecutionResult> {
  if (!sources.code.trim()) throw new Error('A code source is required before preparing a system image.')
  const conversation = await agentApi.ensureConversation('project', activeProject.id, activeProject.name)
  const plan = buildSystemImageSourceActionPlan(activeProject.id, sources)
  for (const command of plan) {
    const invocation = await executeActionCommand(conversation.id, command)
    if (!invocation || !('status' in invocation) || invocation.status !== 'completed') {
      throw new Error('Source preparation did not complete. Review the original command before building.')
    }
  }
  const result = await executeActionCommand(conversation.id, buildStudioActionCommand('system-image.build-goal', {
    projectId: activeProject.id,
    projectName: activeProject.name,
  }, locale))
  const goal = result && 'agent_goal' in result ? result.agent_goal : undefined
  if (!goal || typeof goal !== 'object' || !('id' in goal) || typeof goal.id !== 'string' || !goal.id
    || !('project_id' in goal) || goal.project_id !== activeProject.id
    || !('conversation_id' in goal) || goal.conversation_id !== conversation.id
    || !('goal_template' in goal) || goal.goal_template !== 'system_image_build') {
    throw new Error('Sources were captured, but the build goal could not be verified. Review the conversation before continuing.')
  }
  return { conversationId: conversation.id }
}

async function executeActionCommand(conversationId: string, command: StudioActionCommand) {
  if (command.kind === 'conversation_message') {
    const accepted = await agentApi.postMessage(conversationId, command.content, {
      canonicalActionId: command.actionId,
    })
    const turn = await waitForConversationTurn(conversationId, accepted.turn_id)
    if (!['completed', 'delegated'].includes(turn.status)) throw new Error(turn.error || 'Conversation turn did not complete.')
    return turn.result
  }

  return platformApi.invokeTool({
    conversation_id: conversationId,
    tool_id: command.tool_id,
    input: command.input,
    initiator_surface: command.initiator_surface,
    initiator_actor: command.initiator_actor,
    target_scope: command.target_scope,
  })
}
