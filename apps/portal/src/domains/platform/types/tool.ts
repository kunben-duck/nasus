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
  semantic_preview?: unknown
  index_preview?: unknown
  test_design_execution_preview?: unknown
  test_design_job?: unknown
  automation_execution_preview?: unknown
  automation_script_history?: unknown
  automation_script_review?: unknown
  run_plan_preview?: unknown
  run_plan_build_preview?: unknown
  run_plan_build?: unknown
  run_plan_environment?: unknown
  run_plan_environment_record?: unknown
  run_plan_health_record?: unknown
  run_plan_locator_record?: unknown
  http_fixture_recipe?: unknown
  http_fixture_grant?: unknown
  http_fixture_job?: unknown
  run_plan_case_job?: unknown
  native_build_preview?: unknown
  native_build_job?: unknown
  code_index?: unknown
  structure_cancel?: unknown
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
