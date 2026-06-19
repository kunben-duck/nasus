import type { AgentGoal, ConversationMessage, ConversationSession, EventPayload, ToolInvocation } from '../features/types'

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

function asToolInvocation(value: unknown): ToolInvocation | null {
  if (!isRecord(value) || typeof value.id !== 'string') return null
  return value as unknown as ToolInvocation
}

function toolInvocationFromEvent(event: EventPayload, current?: ToolInvocation): ToolInvocation | null {
  const fullInvocation = asToolInvocation(event.payload.tool_invocation)
  if (fullInvocation) return fullInvocation
  if (event.entity_type !== 'tool_invocation' || !event.entity_id) return null

  const patch = event.patch
  if (!current && typeof patch.tool_id !== 'string') return null

  return {
    id: event.entity_id,
    conversation_id: event.conversation_id ?? current?.conversation_id ?? null,
    tool_id: typeof patch.tool_id === 'string' ? patch.tool_id : current?.tool_id ?? event.entity_id,
    status: typeof patch.status === 'string' ? (patch.status as ToolInvocation['status']) : current?.status ?? 'pending',
    summary: typeof patch.summary === 'string' ? patch.summary : current?.summary ?? '',
    initiator_surface: current?.initiator_surface ?? 'chat',
    initiator_actor: current?.initiator_actor ?? 'agent',
    target_scope: current?.target_scope ?? 'central',
    input_payload: current?.input_payload ?? {},
    result: current?.result ?? null,
  }
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
