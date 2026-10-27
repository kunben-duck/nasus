import { useEffect, useRef } from 'react'

import { useQueryClient } from '@tanstack/react-query'

import { platformApiAuthToken } from '../platform/authTokenStorage'
import type { EventPayload } from '../platform/types'
import { reduceConversationEvent } from './conversationEventReducer'
import { shouldInvalidateDomainQueries } from './eventQueryInvalidation'
import { createConversationQueryRefresh } from './conversationQueryRefresh'
import type { ConversationSession } from './types'

export function useConversationEvents({
  conversationId,
  enabled,
  existingOnly = false,
  canReadWorkspace,
}: {
  conversationId?: string
  enabled: boolean
  existingOnly?: boolean
  canReadWorkspace?: () => boolean
}) {
  const queryClient = useQueryClient()
  const seenEventIds = useRef(new Set<string>())
  const entityVersions = useRef(new Map<string, number>())

  useEffect(() => {
    if (!enabled || !conversationId) return

    seenEventIds.current.clear()
    entityVersions.current.clear()
    const refreshes = createConversationQueryRefresh(queryClient,
      (key) => key[0] === 'conversation' || (!existingOnly && canReadWorkspace?.() !== false))
    const token = platformApiAuthToken()
    const eventUrl = token
      ? `/v1/conversations/${conversationId}/events?access_token=${encodeURIComponent(token)}`
      : `/v1/conversations/${conversationId}/events`
    const source = new EventSource(eventUrl)
    source.onmessage = () => {
      refreshes.schedule(['conversation', conversationId])
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
            refreshes.schedule(key)
          }
        })
        if (payload.event_type === 'quality.test_design_cases.reviewed') {
          const project = payload.patch.project_id
          if (typeof project === 'string' && project === payload.correlation_id) {
            for (const prefix of ['automation-script-revisions', 'automation-script-reviews', 'run-plans']) {
              refreshes.schedule([prefix, project])
            }
          }
        }
      }
      if (!reduced || payload.snapshot_hint) {
        refreshes.schedule(['conversation', conversationId])
      }
    }
    source.addEventListener('conversation.message.created', typedHandler)
    source.addEventListener('conversation.message.started', typedHandler)
    source.addEventListener('conversation.message.delta', typedHandler)
    source.addEventListener('conversation.message.completed', typedHandler)
    source.addEventListener('conversation.message.interrupted', typedHandler)
    source.addEventListener('conversation.message.failed', typedHandler)
    source.addEventListener('conversation.turn.accepted', typedHandler)
    source.addEventListener('conversation.turn.completed', typedHandler)
    source.addEventListener('conversation.turn.interrupted', typedHandler)
    source.addEventListener('conversation.turn.failed', typedHandler)
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
    source.addEventListener('system_image.context.invalidated', typedHandler)
    source.addEventListener('quality.test_design_mapping.reviewed', typedHandler)
    source.addEventListener('quality.test_design_cases.reviewed', typedHandler)
    source.addEventListener('quality.automation.call_reserved', typedHandler)
    source.addEventListener('quality.automation.reply_archived', typedHandler)
    source.addEventListener('quality.automation.draft_saved', typedHandler)
    source.addEventListener('quality.automation.script_reviewed', typedHandler)

    return () => {
      source.close()
      refreshes.close()
    }
  }, [conversationId, enabled, queryClient, existingOnly, canReadWorkspace])
}
