import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { SpaceType } from '../platform/types'
import { agentApi } from './api'
import type { ConversationSession } from './types'
import { useConversationEvents } from './useConversationEvents'

export function useConversation(
  spaceType: SpaceType,
  spaceId: string,
  title: string,
  options: { enabled?: boolean } = {},
) {
  const queryClient = useQueryClient()
  const enabled = options.enabled ?? true

  const conversationQuery = useQuery({
    queryKey: ['conversation-scope', spaceType, spaceId],
    queryFn: () => agentApi.ensureConversation(spaceType, spaceId, title),
    enabled,
  })

  const conversationId = conversationQuery.data?.id

  const snapshotQuery = useQuery({
    queryKey: ['conversation', conversationId],
    queryFn: () => agentApi.getConversation(conversationId!),
    enabled: enabled && Boolean(conversationId),
  })

  useConversationEvents({ conversationId, enabled })

  const sendMutation = useMutation({
    mutationFn: (content: string) => agentApi.postMessage(conversationId!, content),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] })
    },
  })

  return {
    conversation: snapshotQuery.data as ConversationSession | undefined,
    conversationId,
    isLoading: conversationQuery.isLoading || snapshotQuery.isLoading,
    sendMessage: sendMutation.mutateAsync,
    isSending: sendMutation.isPending,
  }
}

export type ConversationController = ReturnType<typeof useConversation>
