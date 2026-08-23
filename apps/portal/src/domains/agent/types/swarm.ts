export interface AgentWorkerAssignment {
  id: string
  swarm_run_id: string
  worker_agent_kind: 'context' | 'impact' | 'scenario' | 'case' | 'execution' | 'failure' | 'release'
  target_refs: string[]
  input_context_refs: string[]
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  agent_goal_id?: string | null
  tool_invocation_refs: string[]
  candidate_result_ref?: string | null
  confidence: number
  summary: string
  created_at: string
  completed_at?: string | null
}

export interface AgentSwarmRun {
  id: string
  parent_goal_id: string
  conversation_id: string
  swarm_kind: 'impact' | 'scenario' | 'case' | 'failure' | 'release' | 'ingestion'
  status: 'pending' | 'running' | 'merging' | 'completed' | 'partially_failed' | 'failed' | 'cancelled'
  max_parallel_agents: number
  merge_strategy: string
  target_refs: string[]
  result_summary: string
  assignments: AgentWorkerAssignment[]
  created_at: string
  completed_at?: string | null
}
