import type { EventPayload } from '../platform/types'

const TERMINAL_TOOL_STATUSES = new Set(['completed', 'failed', 'cancelled'])
const SNAPSHOT_GOAL_STATUSES = new Set(['completed', 'failed', 'cancelled', 'paused', 'blocked'])
const SCRIPT_SNAPSHOT_EVENTS = new Set(['quality.automation.call_reserved', 'quality.automation.reply_archived',
  'quality.automation.draft_saved', 'quality.automation.script_reviewed', 'quality.test_design_cases.reviewed'])

export function shouldInvalidateDomainQueries(event: EventPayload): boolean {
  if (event.snapshot_hint || SCRIPT_SNAPSHOT_EVENTS.has(event.event_type)) return true

  if (event.event_type === 'tool.invocation.updated') {
    return TERMINAL_TOOL_STATUSES.has(String(event.patch.status ?? ''))
  }

  if (event.event_type === 'agent.goal.updated') {
    return Boolean(event.patch.lifecycle_transition)
      || SNAPSHOT_GOAL_STATUSES.has(String(event.patch.status ?? ''))
  }

  return false
}
