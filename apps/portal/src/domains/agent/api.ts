import { request } from '../../shared/api/client'
import type {
  AgentGoal,
  AgentGoalExplanation,
  AgentMemoryContextView,
  AgentSwarmRun,
  ConversationSession,
  ConversationTurn,
  ConversationTurnAccepted,
  ConversationSummaryCheckpoint,
} from './types'

export const agentApi = {
  readProjectConversation: async (projectId: string, signal: AbortSignal) => {
    const sessions = await request<ConversationSession[]>(`/v1/conversations?${new URLSearchParams({ project_id: projectId, space_type: 'project' })}`,
      { signal, cache: 'no-store' })
    const matches = sessions.filter((session) => session.project_id === projectId && session.space_type === 'project'
      && session.space_id === projectId)
    if (matches.length > 1) throw new Error('The existing project conversation is ambiguous')
    return matches[0] ?? null
  },
  ensureConversation: (spaceType: string, spaceId: string, title: string, signal?: AbortSignal) =>
    request<ConversationSession>('/v1/conversations', {
      method: 'POST',
      signal,
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
    options?: {
      canonicalActionId?: 'system-image.build-goal' | 'quality-loop.continue-goal'
      idempotencyKey?: string
    },
  ) =>
    request<ConversationTurnAccepted>(`/v1/conversations/${conversationId}/messages`, {
      method: 'POST',
      headers: {
        'Idempotency-Key': options?.idempotencyKey ?? crypto.randomUUID(),
      },
      body: JSON.stringify({
        content,
        canonical_action_id: options?.canonicalActionId,
      }),
    }),
  getConversationTurn: (conversationId: string, turnId: string) =>
    request<ConversationTurn>(`/v1/conversations/${conversationId}/turns/${turnId}`),
  cancelConversationTurn: (conversationId: string, turnId: string) =>
    request<ConversationTurn>(`/v1/conversations/${conversationId}/turns/${turnId}/cancel`, {
      method: 'POST',
    }),
  getAgentGoal: (goalId: string) => request<AgentGoal>(`/v1/agent-goals/${goalId}`),
  getAgentMemoryContext: (filters: {
    conversation_id?: string
    agent_goal_id?: string
    space_ref?: string
  }, signal?: AbortSignal) => {
    const params = new URLSearchParams()
    Object.entries(filters).forEach(([key, value]) => {
      if (value) {
        params.set(key, value)
      }
    })
    return request<AgentMemoryContextView>(`/v1/agent-memory/context?${params.toString()}`, { signal })
  },
  getAgentGoalExplanation: (goalId: string, signal?: AbortSignal) =>
    request<AgentGoalExplanation>(`/v1/agent-goals/${goalId}/explanation`, { signal }),
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
  resumeAgentGoal: (goalId: string, expected: AgentGoal) =>
    request<AgentGoal>(`/v1/agent-goals/${goalId}/resume`, {
      method: 'POST',
      body: JSON.stringify({ expected_goal: expected }),
    }),
  feedbackAgentGoal: (goalId: string, feedback: string) =>
    request<AgentGoal>(`/v1/agent-goals/${goalId}/feedback`, {
      method: 'POST',
      body: JSON.stringify({ feedback }),
    }),
  getAgentSwarm: (swarmId: string) => request<AgentSwarmRun>(`/v1/agent-swarms/${swarmId}`),
  listAgentSwarms: (filters: { conversation_id?: string; parent_goal_id?: string }, signal?: AbortSignal) => {
    const params = new URLSearchParams()
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params.set(key, value)
    })
    return request<AgentSwarmRun[]>(`/v1/agent-swarms?${params.toString()}`, { signal })
  },
  getAgentSwarmEventsUrl: (swarmId: string) => `/v1/agent-swarms/${swarmId}/events`,
}
