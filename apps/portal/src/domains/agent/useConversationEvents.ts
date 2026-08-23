import { useEffect, useRef } from 'react'

import { useQueryClient } from '@tanstack/react-query'

import { platformApiAuthToken } from '../platform/authTokenStorage'
import type { EventPayload } from '../platform/types'
import { reduceConversationEvent } from './conversationEventReducer'
import { shouldInvalidateDomainQueries } from './eventQueryInvalidation'
import type { ConversationSession } from './types'

export function useConversationEvents({
  conversationId,
  enabled,
}: {
  conversationId?: string
  enabled: boolean
}) {
  const queryClient = useQueryClient()
  const seenEventIds = useRef(new Set<string>())
  const entityVersions = useRef(new Map<string, number>())

  useEffect(() => {
    if (!enabled || !conversationId) return

    seenEventIds.current.clear()
    entityVersions.current.clear()
    const pendingInvalidations = new Map<string, string[]>()
    let invalidationTimer: ReturnType<typeof setTimeout> | null = null
    const scheduleInvalidation = (queryKey: string[]) => {
      pendingInvalidations.set(JSON.stringify(queryKey), queryKey)
      if (invalidationTimer) clearTimeout(invalidationTimer)
      invalidationTimer = setTimeout(() => {
        const queryKeys = [...pendingInvalidations.values()]
        pendingInvalidations.clear()
        invalidationTimer = null
        void Promise.all(
          queryKeys.map((key) => queryClient.invalidateQueries({ queryKey: key })),
        )
      }, 200)
    }
    const token = platformApiAuthToken()
    const eventUrl = token
      ? `/v1/conversations/${conversationId}/events?access_token=${encodeURIComponent(token)}`
      : `/v1/conversations/${conversationId}/events`
    const source = new EventSource(eventUrl)
    source.onmessage = () => {
      queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] })
    }
    const typedHandler = (event: MessageEvent<string>) => {
      const payload = JSON.parse(event.data) as EventPayload
      if (seenEventIds.current.has(payload.event_id)) return
      const entityKey = `${payload.entity_type}:${payload.entity_id}`
      const currentVersion = entityVersions.current.get(entityKey) ?? 0
      if (payload.entity_version <= currentVersion) return
      seenEventIds.current.add(payload.event_id)
      entityVersions.current.set(entityKey, payload.entity_version)
      if (seenEventIds.current.size > 2_000) {
        const oldestEventId = seenEventIds.current.values().next().value
        if (oldestEventId) seenEventIds.current.delete(oldestEventId)
      }
      let reduced = false
      queryClient.setQueryData<ConversationSession | undefined>(['conversation', conversationId], (current) => {
        const next = reduceConversationEvent(current, payload)
        reduced = next !== current
        return next
      })
      if (shouldInvalidateDomainQueries(payload)) {
        payload.query_keys.forEach((key) => {
          if (key[0] !== 'conversation' && key[0] !== 'agent-goal') {
            scheduleInvalidation(key)
          }
        })
      }
      if (!reduced || payload.snapshot_hint) {
        queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] })
      }
    }
    source.addEventListener('conversation.message.created', typedHandler)
    source.addEventListener('agent.step.updated', typedHandler)
    source.addEventListener('agent.step.thinking.delta', typedHandler)
    source.addEventListener('agent.step.observation.delta', typedHandler)
    source.addEventListener('agent.step.decision.delta', typedHandler)
    source.addEventListener('agent.swarm.updated', typedHandler)
    // Compatibility listeners for events persisted before the canonical
    // `agent.step.*` contract was introduced.
    source.addEventListener('runtime.thinking.delta', typedHandler)
    source.addEventListener('runtime.observation.delta', typedHandler)
    source.addEventListener('runtime.decision.delta', typedHandler)
    source.addEventListener('agent.goal.updated', typedHandler)
    source.addEventListener('tool.invocation.updated', typedHandler)

    return () => {
      source.close()
      if (invalidationTimer) clearTimeout(invalidationTimer)
      invalidationTimer = null
      pendingInvalidations.clear()
    }
  }, [conversationId, enabled, queryClient])
}
