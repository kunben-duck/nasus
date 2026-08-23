import type { ConversationSession } from '../../domains/agent/types'
import type { MessageRow } from '../project-overview/ProjectWorkspaceTypes'

export const fallbackProjectMessages: MessageRow[] = [
  {
    role: 'assistant',
    text: 'Tell me what you want to ship. I can inspect the system image, continue the quality loop, and route every write action through tools.',
  },
]

export function toMessageRows(conversation?: ConversationSession): MessageRow[] {
  if (!conversation) return []
  return conversation.messages
    .filter((message) => message.role !== 'system')
    .map((message) => ({
      role: message.role,
      text: message.blocks.map((block) => block.text).filter(Boolean).join('\n'),
    }))
    .filter((message) => message.text.trim().length > 0)
}
