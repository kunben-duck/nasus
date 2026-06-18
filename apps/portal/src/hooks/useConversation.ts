import { useEffect } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../features/api'
import type { ConversationSession, EventPayload, SpaceType } from '../features/types'
import { reduceConversationEvent } from './conversation-event-reducer'

export function useConversation(spaceType: SpaceType, spaceId: string, title: string) {
  const queryClient = useQueryClient()

  const conversationQuery = useQuery({
    queryKey: ['conversation-scope', spaceType, spaceId],
    queryFn: () => api.ensureConversation(spaceType, spaceId, title),
  })

  const conversationId = conversationQuery.data?.id

  const snapshotQuery = useQuery({
    queryKey: ['conversation', conversationId],
    queryFn: () => api.getConversation(conversationId!),
    enabled: Boolean(conversationId),
  })

  useEffect(() => {
    if (!conversationId) return

    const source = new EventSource(`/v1/conversations/${conversationId}/events`)
    source.onmessage = () => {
      queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] })
    }
    const typedHandler = (event: MessageEvent<string>) => {
      const payload = JSON.parse(event.data) as EventPayload
      let reduced = false
      queryClient.setQueryData<ConversationSession | undefined>(['conversation', conversationId], (current) => {
        const next = reduceConversationEvent(current, payload)
        reduced = next !== current
        return next
      })
      payload.query_keys.forEach((key) => {
        if (key[0] !== 'conversation' || key[1] !== conversationId) {
          queryClient.invalidateQueries({ queryKey: key })
        }
      })
      if (!reduced || payload.snapshot_hint) {
        queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] })
      }
    }
    source.addEventListener('conversation.message.created', typedHandler)
    source.addEventListener('agent.goal.updated', typedHandler)
    source.addEventListener('tool.invocation.updated', typedHandler)

    return () => {
      source.close()
    }
  }, [conversationId, queryClient])

  const sendMutation = useMutation({
    mutationFn: (content: string) => api.postMessage(conversationId!, content),
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
