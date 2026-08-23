import { agentApi } from '../../agent/api'
import { platformApi } from '../api'
import type { ProjectCard } from '../types'
import { buildStudioActionCommand } from './studioActionCommand'
import { buildSystemImageSourceActionPlan } from './systemImageSourcePlan'
import type { StudioActionCommand, StudioActionId, StudioSourceBindingValues } from './types'

type ProjectActionExecutionResult = {
  conversationId: string
}

export async function executeProjectActionCommand(
  activeProject: ProjectCard,
  actionId: StudioActionId,
  input: Record<string, unknown> = {},
): Promise<ProjectActionExecutionResult> {
  const conversation = await agentApi.ensureConversation('project', activeProject.id, activeProject.name)
  const command = buildStudioActionCommand(actionId, {
    projectId: activeProject.id,
    projectName: activeProject.name,
    input,
  })
  await executeActionCommand(conversation.id, command)
  return { conversationId: conversation.id }
}

export async function executeSystemImageSourceActionPlan(
  activeProject: ProjectCard,
  sources: StudioSourceBindingValues,
): Promise<ProjectActionExecutionResult> {
  const conversation = await agentApi.ensureConversation('project', activeProject.id, activeProject.name)
  const plan = buildSystemImageSourceActionPlan(activeProject.id, sources)
  for (const command of plan) {
    await executeActionCommand(conversation.id, command)
  }
  return { conversationId: conversation.id }
}

async function executeActionCommand(conversationId: string, command: StudioActionCommand) {
  if (command.kind === 'conversation_message') {
    return agentApi.postMessage(conversationId, command.content, {
      canonicalActionId: command.actionId,
    })
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
