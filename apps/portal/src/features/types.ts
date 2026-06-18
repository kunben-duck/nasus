export type SpaceType =
  | 'welcome'
  | 'build'
  | 'dashboard'
  | 'documentation'
  | 'project'
  | 'version'
  | 'workspace'
  | 'knowledge'
  | 'runs'
  | 'governance'

export interface ProjectCard {
  id: string
  name: string
  code: string
  summary: string
  status: string
  risk: string
  progress: number
  active_version: string
  blocked_items: number
  pending_approvals: number
  system_image_status: string
}

export interface VersionSummary {
  id: string
  name: string
  status: string
  branch_name: string
  us_total: number
  us_closed: number
  pending_runs: number
  pending_approvals: number
}

export interface USItem {
  id: string
  title: string
  owner: string
  status: string
  risk: string
  progress: number
  next_action: string
}

export interface AssetLane {
  id: string
  label: string
  status: string
  summary: string
  updated_at: string
}

export interface RunSummary {
  id: string
  status: string
  channel: 'web_runner'
  title: string
  summary: string
  started_at: string
}

export interface ApprovalSummary {
  id: string
  title: string
  status: string
  summary: string
}

export interface ApprovalDetail extends ApprovalSummary {
  policy_reason: string
  conflict_fields: string[]
  recommended_resolution: string
  evidence: string[]
}

export interface KnowledgeObject {
  id: string
  name: string
  type: string
  branch: string
  confidence: string
  relations: string[]
  evidence: string[]
  freshness: string
}

export interface RawAssetRecord {
  id: string
  project_id: string
  version_id?: string | null
  source_type: 'code' | 'us_doc' | 'test_asset'
  source_uri: string
  ingestion_status: 'pending' | 'indexed' | 'failed' | 'stale'
  content_hash: string
  content_ref?: string | null
  evidence_refs: string[]
  last_ingested_at?: string | null
}

export interface BaselineRecord {
  id: string
  project_id: string
  kind: 'official' | 'version_working' | 'version_shared'
  status: 'draft' | 'building' | 'ready' | 'stale' | 'pending_merge' | 'promoted'
  source_version_id?: string | null
  parent_baseline_id?: string | null
  fork_strategy: 'copy_on_write' | 'materialized_snapshot'
  object_count: number
  relationship_count: number
  metric_snapshot_count: number
  updated_at: string
}

export interface ContextRelationship {
  id: string
  project_id: string
  baseline_id: string
  from_object_id: string
  relationship_type: 'implements' | 'depends_on' | 'covers' | 'validates' | 'impacts' | 'evidenced_by' | 'belongs_to'
  to_object_id: string
  confidence: number
  source_refs: string[]
}

export interface ContextObjectOverlay {
  id: string
  project_id: string
  baseline_id: string
  object_id: string
  field_path: string
  operation: 'add' | 'replace' | 'remove'
  value_ref?: string | null
  source_refs: string[]
  status: 'candidate' | 'merged' | 'rejected'
}

export interface QualityMetricSnapshot {
  id: string
  project_id: string
  baseline_id: string
  version_id?: string | null
  us_id?: string | null
  task_id?: string | null
  metric_group: 'code_quality' | 'us_completion_quality' | 'test_quality' | 'release_readiness'
  metrics: Record<string, unknown>
  evidence_refs: string[]
  captured_at: string
}

export interface SystemImageData {
  project: ProjectCard
  summary: string
  baselines: BaselineRecord[]
  sources: RawAssetRecord[]
  objects: KnowledgeObject[]
  relationships: ContextRelationship[]
  overlays: ContextObjectOverlay[]
  metric_snapshots: QualityMetricSnapshot[]
}

export interface MessageBlock {
  type: 'text' | 'structured_card' | 'tool_progress'
  text: string
  tone?: string
}

export interface ConversationMessage {
  id: string
  role: 'user' | 'assistant' | 'system' | 'tool'
  created_at: string
  blocks: MessageBlock[]
  metadata?: Record<string, unknown>
}

export interface AgentStep {
  id: string
  title: string
  status: 'pending' | 'running' | 'completed' | 'blocked'
  phase?: 'thinking' | 'acting' | 'observing' | 'deciding' | null
  reasoning?: string | null
  memory_context_hash?: string | null
  memory_context_summary?: string | null
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
  title: string
  status: 'draft' | 'pending' | 'running' | 'paused' | 'blocked' | 'completed' | 'failed' | 'cancelled'
  summary: string
  steps: AgentStep[]
  autonomy_level: 'full_auto' | 'semi_auto' | 'step_by_step'
  max_steps: number
  steps_completed: number
  pause_reason?: string | null
  workflow_id?: string | null
}

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
  status: 'pending' | 'running' | 'merging' | 'completed' | 'failed' | 'cancelled'
  max_parallel_agents: number
  merge_strategy: string
  target_refs: string[]
  result_summary: string
  assignments: AgentWorkerAssignment[]
  created_at: string
  completed_at?: string | null
}

export interface ConversationSession {
  id: string
  title: string
  space_type: SpaceType
  space_id: string
  messages: ConversationMessage[]
  agent_goals: AgentGoal[]
}

export interface WelcomeData {
  recent_projects: ProjectCard[]
  recent_versions: VersionSummary[]
  recent_conversations: ConversationSession[]
}

export interface BuildData {
  drafts: ProjectCard[]
  imports_health: string[]
  provider_health: string
}

export interface DashboardData {
  active_projects: number
  running_versions: number
  blocked_items: number
  pending_approvals: number
  failed_runs: number
  projects: ProjectCard[]
}

export interface ProjectWorkspaceData {
  project: ProjectCard
  versions: VersionSummary[]
  current_version_id: string
  us_items: USItem[]
  asset_lanes: AssetLane[]
  runs: RunSummary[]
  approvals: ApprovalSummary[]
}

export interface WorkspaceData {
  project: ProjectCard
  version: VersionSummary
  us_item: USItem
  asset_lanes: AssetLane[]
  conversation: ConversationSession
  runs: RunSummary[]
  approvals: ApprovalSummary[]
}

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

export interface RunDetail extends RunSummary {
  timeline: string[]
  evidence: string[]
  failure_summary: string
  healing_status: string
}

export interface ReleaseReadiness {
  version_id: string
  status: string
  score: number
  blockers: number
  approvals_open: number
  pending_merge: number
  execution_health: string
  summary: string
  blocker_items: string[]
}

export interface DocumentationEntry {
  id: string
  title: string
  copy: string
  category: string
}

export type ProviderName = 'mock' | 'openai' | 'gemini' | 'anthropic' | 'openai_compatible'
export type ModelPreset = 'system_default' | 'custom'
export type ModelRoute = 'chat' | 'embedding' | 'rerank'

export interface ProviderStatus {
  provider: ProviderName
  available: boolean
  configured_via: 'builtin' | 'system_default' | 'custom'
  mode: 'live' | 'fallback'
  fallback_provider?: 'mock' | null
  reason: string
}

export interface CustomModelConfig {
  provider_kind: 'openai_compatible' | 'openai' | 'gemini' | 'anthropic'
  base_url?: string | null
  model_name: string
  has_api_key: boolean
  api_key_masked?: string | null
}

export interface StudioSettings {
  language: 'en' | 'zh'
  theme: 'dark' | 'light' | 'system'
  model_preset: ModelPreset
  notification_mode: 'important' | 'all' | 'muted'
  model_provider: ProviderName
  model_name: string
  runtime_mode: 'live' | 'fallback'
  fallback_provider: 'mock'
  provider_statuses: ProviderStatus[]
  active_provider_status: ProviderStatus
  custom_model: CustomModelConfig
  model_profiles: Record<ModelRoute, ModelProviderProfile>
}

export interface StudioSettingsConnectionTestRequest {
  model_route?: ModelRoute
  model_preset: ModelPreset
  custom_provider_kind?: CustomModelConfig['provider_kind']
  custom_base_url?: string
  custom_model_name?: string
  custom_api_key?: string
}

export interface SettingsConnectionResult {
  ok: boolean
  model_route?: ModelRoute
  provider: ProviderName
  model_name: string
  runtime_mode: 'live' | 'fallback'
  fallback_provider?: 'mock' | null
  latency_ms?: number | null
  message: string
}

export interface ModelProviderProfile {
  route: ModelRoute
  model_preset: ModelPreset
  model_provider: ProviderName
  model_name: string
  runtime_mode: 'live' | 'fallback'
  fallback_provider: 'mock'
  provider_statuses: ProviderStatus[]
  active_provider_status: ProviderStatus
  custom_model: CustomModelConfig
}

export interface AgentMemoryContextView {
  conversation_id: string
  agent_goal_id?: string | null
  context_hash: string
  context_summary: string
  recent_turn_count: number
  checkpoint_count: number
  working_memory: Record<string, unknown>
  conversation_memory: Record<string, unknown>
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
