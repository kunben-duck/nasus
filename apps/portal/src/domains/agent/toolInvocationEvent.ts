import type { EventPayload, ToolInvocation } from '../platform/types'
import { asToolInvocation } from './eventPayloadReaders'

export function toolInvocationFromEvent(event: EventPayload, current?: ToolInvocation): ToolInvocation | null {
  const fullInvocation = asToolInvocation(event.payload.tool_invocation)
  if (fullInvocation) return fullInvocation
  if (event.entity_type !== 'tool_invocation' || !event.entity_id) return null

  const patch = event.patch
  if (!current && typeof patch.tool_id !== 'string') return null

  return {
    id: event.entity_id,
    conversation_id: event.conversation_id ?? current?.conversation_id ?? null,
    tool_id: typeof patch.tool_id === 'string' ? patch.tool_id : current?.tool_id ?? event.entity_id,
    status: typeof patch.status === 'string' ? (patch.status as ToolInvocation['status']) : current?.status ?? 'pending',
    summary: typeof patch.summary === 'string' ? patch.summary : current?.summary ?? '',
    initiator_surface: current?.initiator_surface ?? 'chat',
    initiator_actor: current?.initiator_actor ?? 'agent',
    target_scope: current?.target_scope ?? 'central',
    input_payload: current?.input_payload ?? {},
    result: current?.result ?? null,
  }
}
