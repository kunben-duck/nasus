import type { EventPayload } from '../platform/types'
import type { ConversationMessage, ConversationSession, ConversationTurn } from './types'
import { asConversationMessage } from './eventPayloadReaders'
import { upsertById } from '../../shared/event-reducer/eventUpsert'

export function reduceConversationStreamingEvent(
  conversation: ConversationSession,
  event: EventPayload,
): ConversationSession | undefined {
  if (event.event_type === 'conversation.message.started') {
    const message = asConversationMessage(event.payload.message)
    return message ? { ...conversation, messages: upsertById(conversation.messages, message) } : conversation
  }

  if (event.event_type === 'conversation.message.delta') {
    const messageId = String(event.payload.message_id ?? event.entity_id)
    const streamId = String(event.payload.stream_id ?? '')
    const sequence = Number(event.payload.sequence ?? 0)
    const delta = String(event.payload.delta ?? '')
    const current = conversation.messages.find((item) => item.id === messageId)
    if (!current || current.stream_id !== streamId || sequence <= (current.sequence_max ?? 0)) return conversation
    const blocks = current.blocks.length > 0
      ? current.blocks.map((block, index) => index === 0 ? { ...block, text: `${block.text}${delta}` } : block)
      : [{ type: 'text' as const, text: delta }]
    const message: ConversationMessage = { ...current, status: 'streaming', sequence_max: sequence, blocks }
    return { ...conversation, messages: upsertById(conversation.messages, message) }
  }

  if (['conversation.message.completed', 'conversation.message.interrupted', 'conversation.message.failed'].includes(event.event_type)) {
    const message = asConversationMessage(event.payload.message)
    return message ? { ...conversation, messages: upsertById(conversation.messages, message) } : conversation
  }

  if (event.event_type === 'conversation.turn.accepted') {
    return {
      ...conversation,
      active_turn: {
        id: String(event.payload.turn_id ?? event.entity_id),
        conversation_id: conversation.id,
        user_message_id: String(event.payload.user_message_id ?? ''),
        status: 'accepted',
        result: {},
      },
    }
  }

  if (event.event_type.startsWith('conversation.turn.')) {
    const status = String(event.payload.status ?? event.patch.status ?? '') as ConversationTurn['status']
    if (!['completed', 'interrupted', 'failed'].includes(status)) return conversation
    return {
      ...conversation,
      active_turn: {
        id: String(event.payload.turn_id ?? event.entity_id),
        conversation_id: conversation.id,
        user_message_id: conversation.active_turn?.user_message_id ?? '',
        assistant_message_id: typeof event.payload.assistant_message_id === 'string' ? event.payload.assistant_message_id : null,
        status,
        result: typeof event.payload.result === 'object' && event.payload.result ? event.payload.result as Record<string, unknown> : {},
        error: typeof event.payload.error === 'string' ? event.payload.error : null,
      },
    }
  }

  return undefined
}
