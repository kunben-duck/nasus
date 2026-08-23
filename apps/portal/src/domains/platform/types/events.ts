export interface EventPayload {
  event_id: string
  event_type: string
  occurred_at: string
  correlation_id: string
  conversation_id?: string | null
  tool_invocation_id?: string | null
  agent_goal_id?: string | null
  agent_step_id?: string | null
  swarm_run_id?: string | null
  assignment_id?: string | null
  task_id?: string | null
  run_id?: string | null
  entity_type: string
  entity_id: string
  entity_version: number
  mutation_kind: 'replace' | 'patch' | 'append' | 'invalidate'
  patch: Record<string, unknown>
  query_keys: string[][]
  snapshot_hint: boolean
  payload: Record<string, unknown>
}
