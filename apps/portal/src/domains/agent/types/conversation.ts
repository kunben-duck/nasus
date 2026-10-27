import type { SpaceType, ToolInvocation } from '../../platform/types'
import type { AgentGoal } from './goal'
import type { AgentSwarmRun } from './swarm'

export interface MessageBlock {
  type: 'text' | 'structured_card' | 'tool_progress'
  text: string
  tone?: string
}

export interface ConversationMessage {
  id: string
  role: 'user' | 'assistant' | 'system' | 'tool'
  status: 'accepted' | 'streaming' | 'completed' | 'interrupted' | 'failed' | 'archived'
  content_type: 'text' | 'markdown' | 'structured_card' | 'tool_progress' | 'thinking' | 'image_ref' | 'file_ref' | 'diff_ref' | 'approval_card' | 'conflict_card' | 'evidence_ref'
  created_at: string
  blocks: MessageBlock[]
  metadata?: Record<string, unknown>
  stream_id?: string | null
  sequence_max?: number | null
  tool_refs?: string[]
  object_refs?: string[]
}

export interface ConversationTurn {
  id: string
  conversation_id: string
  user_message_id: string
  assistant_message_id?: string | null
  workflow_id?: string | null
  status: 'accepted' | 'planning' | 'streaming' | 'delegated' | 'completed' | 'interrupted' | 'failed'
  result: Record<string, unknown>
  error?: string | null
}

export interface ConversationTurnAccepted {
  turn_id: string
  conversation_id: string
  user_message_id: string
  status: 'accepted'
  events_url: string
}

export interface ConversationSession {
  id: string
  title: string
  space_type: SpaceType
  space_id: string
  project_id?: string | null
  messages: ConversationMessage[]
  agent_goals: AgentGoal[]
  agent_swarms?: AgentSwarmRun[]
  tool_invocations: ToolInvocation[]
  active_turn?: ConversationTurn | null
}
