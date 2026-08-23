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
  created_at: string
  blocks: MessageBlock[]
  metadata?: Record<string, unknown>
}

export interface ConversationSession {
  id: string
  title: string
  space_type: SpaceType
  space_id: string
  messages: ConversationMessage[]
  agent_goals: AgentGoal[]
  agent_swarms?: AgentSwarmRun[]
  tool_invocations: ToolInvocation[]
}
