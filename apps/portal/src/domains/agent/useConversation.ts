import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { SpaceType } from '../platform/types'
import { agentApi } from './api'
import { readConversationScope } from './conversationScopeQuery'
import type { ConversationSession } from './types'
import { useConversationEvents } from './useConversationEvents'
import { useConversationTurn } from './useConversationTurn'
import { createConversationMessageSender } from './conversationMessageSender'
export function useConversation(
  spaceType: SpaceType,
  spaceId: string,
  title: string,
  options: { enabled?: boolean; existingOnly?: boolean; canReadWorkspace?: () => boolean } = {},
) {
  const queryClient = useQueryClient()
  const enabled = options.enabled ?? true, existingOnly = options.existingOnly ?? false
  const conversationQuery = useQuery({
    queryKey: ['conversation-scope', spaceType, spaceId, existingOnly],
    queryFn: ({ signal }) => readConversationScope(spaceType, spaceId, title, existingOnly, signal, options.canReadWorkspace),
    gcTime: existingOnly ? 0 : undefined,
    retry: existingOnly ? false : undefined,
    enabled,
  })
  const conversationId = conversationQuery.data?.id
  const snapshotQuery = useQuery({
    queryKey: ['conversation', conversationId],
    queryFn: () => agentApi.getConversation(conversationId!),
    enabled: enabled && Boolean(conversationId),
  })
  useConversationEvents({ conversationId, enabled, existingOnly, canReadWorkspace: options.canReadWorkspace })
  const activeTurn = snapshotQuery.data?.active_turn
  const turn = useConversationTurn({ conversationId, activeTurn, queryClient })
  const turnIsActive = Boolean(activeTurn && !['completed', 'interrupted', 'failed'].includes(activeTurn.status))

  return {
    conversation: snapshotQuery.isError ? undefined : snapshotQuery.data as ConversationSession | undefined,
    conversationId,
    isLoading: conversationQuery.isLoading || snapshotQuery.isLoading,
    sendMessage: createConversationMessageSender({ conversationId, enabled, existingOnly,
      isError: conversationQuery.isError, canReadWorkspace: options.canReadWorkspace,
      send: turn.mutation.mutateAsync }),
    waitForTurn: turn.waitForTurn,
    activeTurn,
    cancelActiveTurn: turn.cancelActiveTurn,
    refreshConversation: async () => (await snapshotQuery.refetch({ throwOnError: true })).data,
    isSending: turn.mutation.isPending || turnIsActive,
  }
}

export type ConversationController = ReturnType<typeof useConversation>
