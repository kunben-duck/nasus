import type { AgentGoal, ConversationMessage, ConversationSession, EventPayload } from '../features/types'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function asConversationMessage(value: unknown): ConversationMessage | null {
  if (!isRecord(value) || typeof value.id !== 'string') return null
  return value as unknown as ConversationMessage
}

function asAgentGoal(value: unknown): AgentGoal | null {
  if (!isRecord(value) || typeof value.id !== 'string') return null
  return value as unknown as AgentGoal
}

function upsertById<T extends { id: string }>(items: T[], nextItem: T): T[] {
  const index = items.findIndex((item) => item.id === nextItem.id)
  if (index < 0) return [...items, nextItem]
  return items.map((item, itemIndex) => (itemIndex === index ? nextItem : item))
}

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

  if (event.entity_type === 'agent_goal') {
    const goal = asAgentGoal(event.payload.agent_goal)
    if (!goal) return conversation
    return {
      ...conversation,
      agent_goals: upsertById(conversation.agent_goals, goal),
    }
  }

  return conversation
}
