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

export interface MessageBlock {
  type: 'text' | 'structured_card' | 'tool_progress'
  text: string
  tone?: string
}

export interface ConversationMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
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
  selected_tool_id?: string | null
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
  target_scope: 'central'
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
}

export interface StudioSettingsConnectionTestRequest {
  model_preset: ModelPreset
  custom_provider_kind?: CustomModelConfig['provider_kind']
  custom_base_url?: string
  custom_model_name?: string
  custom_api_key?: string
}

export interface SettingsConnectionResult {
  ok: boolean
  provider: ProviderName
  model_name: string
  runtime_mode: 'live' | 'fallback'
  fallback_provider?: 'mock' | null
  latency_ms?: number | null
  message: string
}

export interface EventPayload {
  event_id: string
  event_type: string
  entity_type: string
  entity_id: string
  entity_version: number
  mutation_kind: 'replace' | 'patch' | 'append' | 'invalidate'
  patch: Record<string, unknown>
  query_keys: string[][]
}
