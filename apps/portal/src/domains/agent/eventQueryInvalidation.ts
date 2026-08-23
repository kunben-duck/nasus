import type { EventPayload } from '../platform/types'

const TERMINAL_TOOL_STATUSES = new Set(['completed', 'failed', 'cancelled'])
const SNAPSHOT_GOAL_STATUSES = new Set(['completed', 'failed', 'cancelled', 'paused', 'blocked'])

export function shouldInvalidateDomainQueries(event: EventPayload): boolean {
  if (event.snapshot_hint) return true

  if (event.event_type === 'tool.invocation.updated') {
    return TERMINAL_TOOL_STATUSES.has(String(event.patch.status ?? ''))
  }

  if (event.event_type === 'agent.goal.updated') {
    return Boolean(event.patch.lifecycle_transition)
      || SNAPSHOT_GOAL_STATUSES.has(String(event.patch.status ?? ''))
  }

  return false
}
