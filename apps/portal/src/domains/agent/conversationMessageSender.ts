import { requireActiveQueryScope } from '../../shared/api/queryScope'

export type ConversationMessageInput = {
  conversationId: string
  content: string
  idempotencyKey: string
  canonicalActionId?: 'system-image.build-goal' | 'quality-loop.continue-goal'
}

export function createConversationMessageSender<Result>({
  conversationId, enabled, existingOnly, isError, canReadWorkspace, send,
}: {
  conversationId?: string
  enabled: boolean
  existingOnly: boolean
  isError: boolean
  canReadWorkspace?: () => boolean
  send: (input: ConversationMessageInput) => Promise<Result>
}) {
  return async (content: string, options?: Pick<ConversationMessageInput, 'canonicalActionId'>) => {
    requireActiveQueryScope(canReadWorkspace)
    if (!enabled || existingOnly || isError || !conversationId) {
      throw new Error('The conversation is not ready for messages.')
    }
    return send({ conversationId, content, idempotencyKey: crypto.randomUUID(),
      canonicalActionId: options?.canonicalActionId })
  }
}
