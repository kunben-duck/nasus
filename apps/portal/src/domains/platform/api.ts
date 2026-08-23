import { request } from '../../shared/api/client'
import type {
  AuthLoginPayload,
  AuthRegisterPayload,
  AuthSession,
  AccessSessionView,
  AccountStatus,
  BuildData,
  DashboardData,
  DocumentationEntry,
  ModelConfigCreateRequest,
  ModelConfigTestRequest,
  ModelConfigUpdateRequest,
  ModelRoute,
  ProjectCard,
  ProjectMemberCandidate,
  ProjectMemberView,
  ProjectRole,
  SettingsConnectionResult,
  StudioSettings,
  StudioSettingsConnectionTestRequest,
  ToolDefinition,
  ToolInvocation,
  UserProfile,
  UserAdministrationPage,
  UserAdministrationRecord,
  GlobalRole,
} from './types'

export const platformApi = {
  authMe: () => request<UserProfile>('/v1/auth/me'),
  register: (payload: AuthRegisterPayload) =>
    request<AuthSession>('/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  login: (payload: AuthLoginPayload) =>
    request<AuthSession>('/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  logout: () =>
    request<{ ok: boolean }>('/v1/auth/logout', {
      method: 'POST',
    }),
  updateAvatar: (payload: { avatar_url?: string | null; avatar_preset?: string | null }) =>
    request<UserProfile>('/v1/auth/me/avatar', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  getSettings: () => request<StudioSettings>('/v1/settings'),
  listMySessions: () => request<AccessSessionView[]>('/v1/auth/sessions'),
  revokeMySession: (sessionId: string) =>
    request<AccessSessionView>(`/v1/auth/sessions/${sessionId}`, { method: 'DELETE' }),
  listUsers: (query = '') => {
    const params = new URLSearchParams({ limit: '100', offset: '0' })
    if (query.trim()) params.set('q', query.trim())
    return request<UserAdministrationPage>(`/v1/admin/users?${params.toString()}`)
  },
  updateUser: (userId: string, payload: { display_name?: string; role?: GlobalRole; status?: AccountStatus }) =>
    request<UserAdministrationRecord>(`/v1/admin/users/${userId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  listProjectMembers: (projectId: string) =>
    request<ProjectMemberView[]>(`/v1/projects/${projectId}/members`),
  searchProjectMemberCandidates: (projectId: string, query: string) =>
    request<ProjectMemberCandidate[]>(
      `/v1/projects/${projectId}/member-candidates?q=${encodeURIComponent(query.trim())}`,
    ),
  upsertProjectMember: (projectId: string, userId: string, role: ProjectRole) =>
    request<ProjectMemberView>(`/v1/projects/${projectId}/members/${userId}`, {
      method: 'PUT',
      body: JSON.stringify({ role }),
    }),
  revokeProjectMember: (projectId: string, userId: string) =>
    request<{ ok: boolean }>(`/v1/projects/${projectId}/members/${userId}`, { method: 'DELETE' }),
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
  testModelConfig: (payload: ModelConfigTestRequest) =>
    request<SettingsConnectionResult>('/v1/settings/model-configs/test', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  createModelConfig: (payload: ModelConfigCreateRequest) =>
    request<StudioSettings>('/v1/settings/model-configs', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateModelConfig: (configId: string, payload: ModelConfigUpdateRequest) =>
    request<StudioSettings>(`/v1/settings/model-configs/${configId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  activateModelConfig: (configId: string) =>
    request<StudioSettings>(`/v1/settings/model-configs/${configId}/activate`, {
      method: 'POST',
    }),
  useSystemDefaultModel: (route: ModelRoute) =>
    request<StudioSettings>(`/v1/settings/model-configs/${route}/use-system-default`, {
      method: 'POST',
    }),
  getWelcome: () => request('/v1/welcome'),
  getBuild: () => request<BuildData>('/v1/build'),
  getDashboard: () => request<DashboardData>('/v1/dashboard'),
  getDocumentation: () => request<DocumentationEntry[]>('/v1/documentation'),
  createProject: (name: string) =>
    request<ProjectCard>('/v1/projects', {
      method: 'POST',
      body: JSON.stringify({ name }),
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
  listToolInvocations: (filters?: {
    conversation_id?: string
    agent_goal_id?: string
    tool_id?: string
    status?: ToolInvocation['status']
  }) => {
    const params = new URLSearchParams()
    Object.entries(filters ?? {}).forEach(([key, value]) => {
      if (value) {
        params.set(key, value)
      }
    })
    const query = params.toString()
    return request<ToolInvocation[]>(`/v1/tool-invocations${query ? `?${query}` : ''}`)
  },
  confirmToolInvocation: (invocationId: string) =>
    request<ToolInvocation>(`/v1/tool-invocations/${invocationId}/confirm`, {
      method: 'POST',
    }),
  getTools: () => request<ToolDefinition[]>('/v1/tools/catalog'),
}
