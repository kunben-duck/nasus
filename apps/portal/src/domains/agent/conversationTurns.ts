import { agentApi } from './api'
import type { ConversationTurn } from './types'

const terminalTurnStatuses = new Set<ConversationTurn['status']>([
  'completed',
  'interrupted',
  'failed',
])

export function conversationTurnIsTerminal(turn: ConversationTurn): boolean {
  return terminalTurnStatuses.has(turn.status)
}

export async function waitForConversationTurn(
  conversationId: string,
  turnId: string,
  timeoutMs = 30 * 60 * 1000,
): Promise<ConversationTurn> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const turn = await agentApi.getConversationTurn(conversationId, turnId)
    if (conversationTurnIsTerminal(turn)) return turn
    await new Promise((resolve) => globalThis.setTimeout(resolve, 100))
  }
  throw new Error('Conversation turn timed out.')
}
