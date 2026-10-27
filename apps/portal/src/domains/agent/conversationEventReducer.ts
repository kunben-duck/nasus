import type { EventPayload } from '../platform/types'
import type { ConversationSession } from './types'
import { asAgentSwarm, asConversationMessage } from './eventPayloadReaders'
import { toolInvocationFromEvent } from './toolInvocationEvent'
import { reduceConversationStreamingEvent } from './conversationStreamingEventReducer'
import { reduceAgentStepEvent } from './conversationGoalEventReducer'
import { upsertById } from '../../shared/event-reducer/eventUpsert'
export function reduceConversationEvent(
  conversation: ConversationSession | undefined,
  event: EventPayload,
): ConversationSession | undefined {
  if (!conversation || event.snapshot_hint || event.mutation_kind === 'invalidate') {
    return conversation
  }
  const streamingUpdate = reduceConversationStreamingEvent(conversation, event)
  if (streamingUpdate) return streamingUpdate
  if (event.event_type === 'conversation.message.created') {
    const message = asConversationMessage(event.payload.message)
    if (!message || conversation.messages.some((item) => item.id === message.id)) {
      return conversation
    }
    const idempotencyKey = message.metadata?.idempotency_key
    return {
      ...conversation,
      messages: [
        ...conversation.messages.filter((item) => (
          item.id !== message.id
          && !(idempotencyKey && item.metadata?.idempotency_key === idempotencyKey)
        )),
        message,
      ],
    }
  }

  if (event.event_type.startsWith('agent.step.')) {
    return reduceAgentStepEvent(conversation, event)
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
    // Replayed goals can precede the loaded snapshot. Returning it unchanged
    // makes the event hook re-read the authorized checkpoint, not an old gate.
    return conversation
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
