export interface AgentStep {
  id: string
  title: string
  status: 'pending' | 'running' | 'completed' | 'blocked'
  phase?: 'thinking' | 'acting' | 'observing' | 'deciding' | null
  reasoning?: string | null
  memory_context_hash?: string | null
  memory_context_summary?: string | null
  memory_retrieval_query?: string | null
  memory_retrieval_run_refs?: string[]
  retrieved_context_refs?: string[]
  retrieved_context_summary?: string | null
  memory_recent_turn_count?: number
  memory_checkpoint_count?: number
  available_tool_ids?: string[]
  selected_tool_id?: string | null
  tool_input_payload?: Record<string, unknown>
  tool_target_scope?: 'central' | 'edge'
  tool_invocation_id?: string | null
  observation_summary?: string | null
  decision?: 'continue' | 'pause' | 'complete' | 'fail' | 'escalate' | null
  decision_rationale?: string | null
  next_plan_hint?: string | null
}

export interface AgentGoal {
  id: string
  conversation_id: string
  project_id?: string
  us_id?: string
  goal_template?: string | null
  goal_description?: string | null
  target_refs?: string[]
  query_keys?: string[][]
  planner_kind?: string | null
  planning_summary?: string | null
  title: string
  status: 'draft' | 'pending' | 'running' | 'paused' | 'blocked' | 'completed' | 'failed' | 'cancelled'
  summary: string
  steps: AgentStep[]
  autonomy_level: 'full_auto' | 'semi_auto' | 'step_by_step'
  max_steps: number
  max_model_calls: number
  max_thinking_tokens: number
  max_runtime_seconds: number
  max_no_progress_observations: number
  steps_completed: number
  model_calls_used: number
  thinking_input_tokens_used: number
  thinking_output_tokens_used: number
  thinking_tokens_used: number
  no_progress_observations: number
  started_at?: string | null
  last_progress_at?: string | null
  last_progress_fingerprint?: string | null
  budget_exhausted_reason?: string | null
  pause_reason?: string | null
  workflow_id?: string | null
}

export interface AgentGoalExplanationStep {
  step_id: string
  title: string
  status: AgentStep['status']
  phase?: AgentStep['phase']
  selected_tool_id?: string | null
  tool_invocation_id?: string | null
  reasoning?: string | null
  observation_summary?: string | null
  decision?: AgentStep['decision']
  decision_rationale?: string | null
  next_plan_hint?: string | null
}

export interface AgentGoalExplanation {
  goal_id: string
  conversation_id: string
  project_id?: string | null
  goal_template?: string | null
  goal_description?: string | null
  target_refs: string[]
  query_keys: string[][]
  planner_kind?: string | null
  planning_summary?: string | null
  title: string
  status: AgentGoal['status']
  phase: 'pending' | 'thinking' | 'acting' | 'observing' | 'deciding' | 'completed' | 'failed' | 'paused'
  pause_reason?: string | null
  budget: {
    max_steps: number
    max_model_calls: number
    max_thinking_tokens: number
    max_runtime_seconds: number
    max_no_progress_observations: number
    steps_completed: number
    model_calls_used: number
    thinking_input_tokens_used: number
    thinking_output_tokens_used: number
    thinking_tokens_used: number
    no_progress_observations: number
    started_at?: string | null
    last_progress_at?: string | null
    exhausted_reason?: string | null
  }
  steps_completed: number
  current_step?: AgentGoalExplanationStep | null
  blocked_step?: AgentGoalExplanationStep | null
  plan: AgentGoalExplanationStep[]
  waiting_on: string
  next_action: string
  reasoning_summary: string
  memory_context: {
    context_hash?: string | null
    summary?: string | null
    retrieval_query?: string | null
    retrieval_run_refs: string[]
    retrieved_context_refs: string[]
    retrieved_context_summary?: string | null
  }
  tool_invocation_refs: string[]
  executed_tool_ids: string[]
  memory_refs: string[]
  audit_event_refs: string[]
}
