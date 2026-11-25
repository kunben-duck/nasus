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
  options: { enabled?: boolean; existingOnly?: boolean; canReadWorkspace?: () => boolean; requestedId?: string } = {},
) {
  const queryClient = useQueryClient()
  const enabled = options.enabled ?? true, existingOnly = options.existingOnly ?? false
  const conversationQuery = useQuery({
    queryKey: ['conversation-scope', spaceType, spaceId, existingOnly],
    queryFn: ({ signal }) => readConversationScope(spaceType, spaceId, title, existingOnly, signal, options.canReadWorkspace),
    gcTime: existingOnly ? 0 : undefined,
    retry: existingOnly ? false : undefined,
    enabled: enabled && options.requestedId === undefined,
  })
  const conversationId = options.requestedId ?? conversationQuery.data?.id
  const snapshotQuery = useQuery({
    queryKey: ['conversation', conversationId],
    queryFn: () => agentApi.getConversation(conversationId!),
    enabled: enabled && Boolean(conversationId),
  })
  const wrongSpace = Boolean(options.requestedId && snapshotQuery.data && snapshotQuery.data.space_type !== spaceType)
  useConversationEvents({ conversationId, enabled: enabled && !wrongSpace && (!options.requestedId || snapshotQuery.isSuccess), existingOnly, canReadWorkspace: options.canReadWorkspace })
  const activeTurn = snapshotQuery.data?.active_turn
  const turn = useConversationTurn({ conversationId, activeTurn, queryClient })
  const turnIsActive = Boolean(activeTurn && !['completed', 'delegated', 'interrupted', 'failed'].includes(activeTurn.status))

  return {
    conversation: snapshotQuery.isError || wrongSpace ? undefined : snapshotQuery.data as ConversationSession | undefined,
    unavailable: wrongSpace || snapshotQuery.isError || (!options.requestedId && conversationQuery.isError),
    conversationId,
    isLoading: conversationQuery.isLoading || snapshotQuery.isLoading,
    sendMessage: createConversationMessageSender({ conversationId, enabled, existingOnly,
      isError: conversationQuery.isError || snapshotQuery.isError || wrongSpace, canReadWorkspace: options.canReadWorkspace,
      send: turn.mutation.mutateAsync }),
    waitForTurn: turn.waitForTurn,
    activeTurn,
    cancelActiveTurn: turn.cancelActiveTurn,
    refreshConversation: async () => (await snapshotQuery.refetch({ throwOnError: true })).data,
    isSending: turn.mutation.isPending || turnIsActive,
  }
}

export type ConversationController = ReturnType<typeof useConversation>
