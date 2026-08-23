import type { EventPayload } from '../platform/types'
import type { ConversationSession } from './types'
import { asAgentGoal, asAgentStep, asAgentSwarm, asConversationMessage } from './eventPayloadReaders'
import { toolInvocationFromEvent } from './toolInvocationEvent'
import { upsertById } from '../../shared/event-reducer/eventUpsert'

export function reduceConversationEvent(
  conversation: ConversationSession | undefined,
  event: EventPayload,
): ConversationSession | undefined {
  if (!conversation || event.snapshot_hint || event.mutation_kind === 'invalidate') {
    return conversation
  }

  if (event.event_type === 'conversation.message.created') {
    const message = asConversationMessage(event.payload.message)
    if (!message || conversation.messages.some((item) => item.id === message.id)) {
      return conversation
    }
    return {
      ...conversation,
      messages: [...conversation.messages, message],
    }
  }

  if (event.event_type.startsWith('agent.step.')) {
    const step = asAgentStep(event.patch.agent_step)
    const goalId = event.agent_goal_id
    if (!step || !goalId) return conversation
    const currentGoal = (conversation.agent_goals ?? []).find((goal) => goal.id === goalId)
    if (!currentGoal) return conversation
    return {
      ...conversation,
      agent_goals: upsertById(conversation.agent_goals ?? [], {
        ...currentGoal,
        steps: upsertById(currentGoal.steps, step),
      }),
    }
  }

  if (event.entity_type === 'agent_swarm') {
    const swarm = asAgentSwarm(event.payload.agent_swarm ?? event.patch.agent_swarm)
    if (!swarm) return conversation
    return {
      ...conversation,
      agent_swarms: upsertById(conversation.agent_swarms ?? [], swarm),
    }
  }

  if (event.entity_type === 'agent_goal') {
    const goal = asAgentGoal(event.payload.agent_goal)
    if (!goal) return conversation
    return {
      ...conversation,
      agent_goals: upsertById(conversation.agent_goals ?? [], goal),
    }
  }

  if (event.entity_type === 'tool_invocation') {
    const currentInvocations = conversation.tool_invocations ?? []
    const currentInvocation = currentInvocations.find((item) => item.id === event.entity_id)
    const invocation = toolInvocationFromEvent(event, currentInvocation)
    if (!invocation) return conversation
    return {
      ...conversation,
      tool_invocations: upsertById(currentInvocations, invocation),
    }
  }

  return conversation
}
