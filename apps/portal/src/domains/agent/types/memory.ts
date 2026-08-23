export interface AgentMemoryContextView {
  conversation_id: string
  agent_goal_id?: string | null
  context_hash: string
  context_summary: string
  recent_turn_count: number
  checkpoint_count: number
  working_memory: Record<string, unknown>
  conversation_memory: Record<string, unknown>
  retrieved_context: {
    query: string
    refs: string[]
    summary: string
  }
  project_long_term_memory: Record<string, unknown>
  candidate_memory: Record<string, unknown>
  tool_catalog: {
    tool_count: number
    tool_ids: string[]
  }
}

export interface ConversationSummaryCheckpoint {
  id: string
  conversation_id: string
  message_range_start?: string | null
  message_range_end?: string | null
  summary_text: string
  summary_object_refs: string[]
  summary_token_count: number
  created_by: 'system' | 'user'
  created_at: string
}
