import { toolIdForAction } from './toolActionMap'
import type { StudioActionCommand, StudioActionContext, StudioActionId } from './types'

export function buildStudioActionCommand(
  actionId: StudioActionId,
  context: StudioActionContext,
): StudioActionCommand {
  const baseInput = {
    project_id: context.projectId,
    ...(context.input ?? {}),
  }

  if (actionId === 'system-image.build-goal') {
    return {
      kind: 'conversation_message',
      actionId,
      content: 'Build the official system image from code, historical US documents, and historical test assets.',
    }
  }

  if (actionId === 'quality-loop.continue-goal') {
    return {
      kind: 'conversation_message',
      actionId,
      content: 'Complete the end-to-end quality loop for the riskiest open US through scope, scenarios, verification planning, cases, automation evidence, a change document, and release readiness.',
    }
  }

  return {
    kind: 'tool_invocation',
    actionId,
    tool_id: toolIdForAction(actionId),
    input: baseInput,
    initiator_surface: 'ui',
    initiator_actor: 'user',
    target_scope: 'central',
  }
}
