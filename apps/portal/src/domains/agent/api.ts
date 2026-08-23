import { request } from '../../shared/api/client'
import type {
  AgentGoal,
  AgentGoalExplanation,
  AgentMemoryContextView,
  AgentSwarmRun,
  ConversationSession,
  ConversationSummaryCheckpoint,
} from './types'

export const agentApi = {
  ensureConversation: (spaceType: string, spaceId: string, title: string) =>
    request<ConversationSession>('/v1/conversations', {
      method: 'POST',
      body: JSON.stringify({
        space_type: spaceType,
        space_id: spaceId,
        title,
      }),
    }),
  getConversation: (conversationId: string) => request<ConversationSession>(`/v1/conversations/${conversationId}`),
  postMessage: (
    conversationId: string,
    content: string,
    options?: { canonicalActionId?: 'system-image.build-goal' | 'quality-loop.continue-goal' },
  ) =>
    request(`/v1/conversations/${conversationId}/messages`, {
      method: 'POST',
      body: JSON.stringify({
        content,
        canonical_action_id: options?.canonicalActionId,
      }),
    }),
  getAgentGoal: (goalId: string) => request<AgentGoal>(`/v1/agent-goals/${goalId}`),
  getAgentMemoryContext: (filters: {
    conversation_id?: string
    agent_goal_id?: string
    space_ref?: string
  }) => {
    const params = new URLSearchParams()
    Object.entries(filters).forEach(([key, value]) => {
      if (value) {
        params.set(key, value)
      }
    })
    return request<AgentMemoryContextView>(`/v1/agent-memory/context?${params.toString()}`)
  },
  getAgentGoalExplanation: (goalId: string) =>
    request<AgentGoalExplanation>(`/v1/agent-goals/${goalId}/explanation`),
  createAgentMemoryCheckpoint: (payload: {
    conversation_id?: string
    agent_goal_id?: string
    space_ref?: string
    created_by?: 'system' | 'user'
  }) =>
    request<ConversationSummaryCheckpoint>('/v1/agent-memory/checkpoints', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  interruptAgentGoal: (goalId: string) =>
    request<AgentGoal>(`/v1/agent-goals/${goalId}/interrupt`, {
      method: 'POST',
    }),
  resumeAgentGoal: (goalId: string) =>
    request<AgentGoal>(`/v1/agent-goals/${goalId}/resume`, {
      method: 'POST',
    }),
  feedbackAgentGoal: (goalId: string, feedback: string) =>
    request<AgentGoal>(`/v1/agent-goals/${goalId}/feedback`, {
      method: 'POST',
      body: JSON.stringify({ feedback }),
    }),
  getAgentSwarm: (swarmId: string) => request<AgentSwarmRun>(`/v1/agent-swarms/${swarmId}`),
  listAgentSwarms: (filters: { conversation_id?: string; parent_goal_id?: string }) => {
    const params = new URLSearchParams()
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params.set(key, value)
    })
    return request<AgentSwarmRun[]>(`/v1/agent-swarms?${params.toString()}`)
  },
  getAgentSwarmEventsUrl: (swarmId: string) => `/v1/agent-swarms/${swarmId}/events`,
}
