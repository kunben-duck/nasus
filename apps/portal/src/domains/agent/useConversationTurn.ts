import { useMutation, type QueryClient } from '@tanstack/react-query'

import { agentApi } from './api'
import type { ConversationSession, ConversationTurn } from './types'
import { waitForConversationTurn } from './conversationTurns'
import type { ConversationMessageInput as SendInput } from './conversationMessageSender'

export function useConversationTurn({
  conversationId,
  activeTurn,
  queryClient,
}: {
  conversationId?: string
  activeTurn?: ConversationTurn | null
  queryClient: QueryClient
}) {
  const mutation = useMutation({
    mutationFn: ({ conversationId: targetId, content, idempotencyKey, canonicalActionId }: SendInput) =>
      agentApi.postMessage(targetId, content, { idempotencyKey, canonicalActionId }),
    onMutate: ({ conversationId: targetId, content, idempotencyKey }: SendInput) => {
      queryClient.setQueryData<ConversationSession | undefined>(['conversation', targetId], (current) => current ? ({
        ...current,
        messages: [...current.messages, {
          id: `pending_${idempotencyKey}`,
          role: 'user',
          status: 'accepted',
          content_type: 'text',
          created_at: new Date().toISOString(),
          blocks: [{ type: 'text', text: content }],
          metadata: { idempotency_key: idempotencyKey, optimistic: true },
        }],
      }) : current)
    },
    onSuccess: (accepted, { conversationId: targetId }: SendInput) => {
      queryClient.setQueryData<ConversationSession | undefined>(['conversation', targetId], (current) => current ? ({
        ...current,
        active_turn: {
          id: accepted.turn_id,
          conversation_id: accepted.conversation_id,
          user_message_id: accepted.user_message_id,
          status: 'accepted',
          result: {},
        },
      }) : current)
      queryClient.invalidateQueries({ queryKey: ['conversation', targetId] })
    },
  })

  async function waitForTurn(turnId: string, timeoutMs = 30 * 60 * 1000): Promise<ConversationTurn> {
    if (!conversationId) throw new Error('The conversation is not ready.')
    return waitForConversationTurn(conversationId, turnId, timeoutMs)
  }

  async function cancelActiveTurn() {
    if (!conversationId || !activeTurn?.id) return
    const turn = await agentApi.cancelConversationTurn(conversationId, activeTurn.id)
    queryClient.setQueryData<ConversationSession | undefined>(['conversation', conversationId], (current) => (
      current ? { ...current, active_turn: turn } : current
    ))
  }

  return { mutation, waitForTurn, cancelActiveTurn }
}
