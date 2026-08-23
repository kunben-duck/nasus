import type { ToolInvocation } from '../platform/types'
import type { AgentGoal, AgentStep, AgentSwarmRun, ConversationMessage } from './types'

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function asConversationMessage(value: unknown): ConversationMessage | null {
  if (!isRecord(value) || typeof value.id !== 'string') return null
  return value as unknown as ConversationMessage
}

export function asAgentGoal(value: unknown): AgentGoal | null {
  if (!isRecord(value) || typeof value.id !== 'string') return null
  return value as unknown as AgentGoal
}

export function asAgentStep(value: unknown): AgentStep | null {
  if (!isRecord(value) || typeof value.id !== 'string') return null
  return value as unknown as AgentStep
}

export function asAgentSwarm(value: unknown): AgentSwarmRun | null {
  if (!isRecord(value) || typeof value.id !== 'string') return null
  return value as unknown as AgentSwarmRun
}

export function asToolInvocation(value: unknown): ToolInvocation | null {
  if (!isRecord(value) || typeof value.id !== 'string') return null
  return value as unknown as ToolInvocation
}
