import type { ConversationMessage } from './types'

export function recentUserPrompts(messages: readonly ConversationMessage[] = []): string[] {
  return messages.filter((message) => message.role === 'user')
    .map((message) => message.blocks.filter((block) => block.type === 'text').map((block) => block.text).join('\n'))
    .filter((text) => text.trim().length > 0)
    .slice(-5)
}
