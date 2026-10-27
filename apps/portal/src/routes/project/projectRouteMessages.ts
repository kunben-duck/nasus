import type { ConversationSession } from '../../domains/agent/types'
import type { MessageRow } from '../project-overview/ProjectWorkspaceTypes'

export function fallbackProjectMessages(message: string): MessageRow[] {
  return [{ id: 'project-conversation-placeholder', role: 'assistant', text: message }]
}

export function toMessageRows(conversation?: ConversationSession): MessageRow[] {
  if (!conversation) return []
  return conversation.messages
    .filter((message) => message.role !== 'system')
    .map((message) => ({
      id: message.id,
      role: message.role,
      text: message.blocks.map((block) => block.text).filter(Boolean).join('\n'),
      status: message.status,
    }))
    .filter((message) => message.text.trim().length > 0)
}
