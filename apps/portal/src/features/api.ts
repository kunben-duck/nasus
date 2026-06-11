import type {
  AgentGoal,
  ApprovalDetail,
  BuildData,
  ConversationSession,
  DashboardData,
  DocumentationEntry,
  KnowledgeObject,
  ProjectCard,
  ProjectWorkspaceData,
  ReleaseReadiness,
  SettingsConnectionResult,
  StudioSettingsConnectionTestRequest,
  StudioSettings,
  SystemImageData,
  ToolDefinition,
  ToolInvocation,
  RunDetail,
  WelcomeData,
  WorkspaceData,
} from './types'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: {
      'Content-Type': 'application/json',
    },
    ...options,
  })

  if (!response.ok) {
    let message = `Request failed for ${path}`
    const contentType = response.headers.get('content-type') ?? ''

    if (contentType.includes('application/json')) {
      const payload = await response.json().catch(() => null) as
        | { detail?: { error?: { message?: string } }; message?: string }
        | null
      message = payload?.detail?.error?.message ?? payload?.message ?? message
    } else {
      const text = await response.text().catch(() => '')
      if (text.trim()) {
        message = text.trim()
      }
    }

    throw new Error(message)
  }

  return response.json() as Promise<T>
}

export const api = {
  authMe: () => request('/v1/auth/me'),
  getSettings: () => request<StudioSettings>('/v1/settings'),
  updateSettings: (payload: Record<string, unknown>) =>
    request<StudioSettings>('/v1/settings', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  testSettingsConnection: (payload: StudioSettingsConnectionTestRequest) =>
    request<SettingsConnectionResult>('/v1/settings/test-connection', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getWelcome: () => request<WelcomeData>('/v1/welcome'),
  getBuild: () => request<BuildData>('/v1/build'),
  getDashboard: () => request<DashboardData>('/v1/dashboard'),
  getDocumentation: () => request<DocumentationEntry[]>('/v1/documentation'),
  createProject: (name: string) =>
    request<ProjectCard>('/v1/projects', {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),
  getProject: (projectId: string) => request<ProjectWorkspaceData>(`/v1/projects/${projectId}`),
  getVersions: (projectId: string) => request(`/v1/projects/${projectId}/versions`),
  createVersion: (projectId: string, name: string) =>
    request(`/v1/projects/${projectId}/versions`, {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),
  getWorkspace: (projectId: string, usId: string) =>
    request<WorkspaceData>(`/v1/projects/${projectId}/workspaces/${usId}`),
  getKnowledge: (projectId: string) => request<KnowledgeObject[]>(`/v1/projects/${projectId}/knowledge`),
  getSystemImage: (projectId: string) => request<SystemImageData>(`/v1/projects/${projectId}/system-image`),
  getKnowledgeDetail: (projectId: string, objectId: string) =>
    request<KnowledgeObject>(`/v1/projects/${projectId}/knowledge/${objectId}`),
  getProjectRuns: (projectId: string) => request(`/v1/projects/${projectId}/runs`),
  getRunDetail: (projectId: string, runId: string) => request<RunDetail>(`/v1/projects/${projectId}/runs/${runId}`),
  getProjectApprovals: (projectId: string) => request(`/v1/projects/${projectId}/approvals`),
  getApprovalDetail: (projectId: string, approvalId: string) =>
    request<ApprovalDetail>(`/v1/projects/${projectId}/approvals/${approvalId}`),
  getReleaseReadiness: (projectId: string) =>
    request<ReleaseReadiness>(`/v1/projects/${projectId}/release-readiness`),
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
  postMessage: (conversationId: string, content: string) =>
    request(`/v1/conversations/${conversationId}/messages`, {
      method: 'POST',
      body: JSON.stringify({ content }),
    }),
  invokeTool: (payload: {
    conversation_id?: string
    tool_id: string
    input?: Record<string, unknown>
    initiator_surface?: 'chat' | 'ui' | 'api' | 'agent_loop'
    initiator_actor?: 'user' | 'agent'
    target_scope?: 'central'
  }) =>
    request<ToolInvocation>('/v1/tool-invocations', {
      method: 'POST',
      body: JSON.stringify({
        initiator_surface: 'ui',
        initiator_actor: 'user',
        target_scope: 'central',
        input: {},
        ...payload,
      }),
    }),
  getToolInvocation: (invocationId: string) => request<ToolInvocation>(`/v1/tool-invocations/${invocationId}`),
  getAgentGoal: (goalId: string) => request<AgentGoal>(`/v1/agent-goals/${goalId}`),
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
  getTools: () => request<ToolDefinition[]>('/v1/tools/catalog'),
}
