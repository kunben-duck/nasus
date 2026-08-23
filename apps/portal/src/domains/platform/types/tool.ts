export interface ToolDefinition {
  tool_id: string
  label: string
  tool_kind: string
  scope: 'central' | 'edge' | 'either'
  risk_level: 'low' | 'medium' | 'high' | 'critical'
  confirmation_mode: 'none' | 'user_confirm' | 'approval_required' | 'policy_only'
  description: string
  required_context: string[]
  produced_objects: string[]
  input_schema_ref?: string | null
  output_schema_ref?: string | null
}

export interface ToolResult {
  invocation_id: string
  status: 'completed' | 'failed' | 'cancelled'
  summary: string
  object_refs: string[]
  evidence_refs: string[]
  requires_followup: boolean
  followup_reason?: string | null
  followup_prompt?: string | null
  next_recommended_tools: string[]
}

export interface ToolInvocation {
  id: string
  conversation_id?: string | null
  tool_id: string
  status: 'pending' | 'running' | 'waiting_confirmation' | 'waiting_approval' | 'completed' | 'failed' | 'cancelled'
  summary: string
  initiator_surface: 'chat' | 'ui' | 'api' | 'agent_loop'
  initiator_actor: 'user' | 'agent'
  target_scope: 'central' | 'edge'
  input_payload: Record<string, unknown>
  result?: ToolResult | null
}
