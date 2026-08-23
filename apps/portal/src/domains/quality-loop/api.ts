import { request } from '../../shared/api/client'
import type {
  ApprovalDetail,
  ProjectWorkspaceData,
  ReleaseReadiness,
  RunDetail,
  WorkspaceData,
} from './types'

export const qualityLoopApi = {
  getProject: (projectId: string) => request<ProjectWorkspaceData>(`/v1/projects/${projectId}`),
  getVersions: (projectId: string) => request(`/v1/projects/${projectId}/versions`),
  createVersion: (projectId: string, name: string) =>
    request(`/v1/projects/${projectId}/versions`, {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),
  getWorkspace: (projectId: string, usId: string) =>
    request<WorkspaceData>(`/v1/projects/${projectId}/workspaces/${usId}`),
  getProjectRuns: (projectId: string) => request(`/v1/projects/${projectId}/runs`),
  getRunDetail: (projectId: string, runId: string) => request<RunDetail>(`/v1/projects/${projectId}/runs/${runId}`),
  getProjectApprovals: (projectId: string) => request(`/v1/projects/${projectId}/approvals`),
  getApprovalDetail: (projectId: string, approvalId: string) =>
    request<ApprovalDetail>(`/v1/projects/${projectId}/approvals/${approvalId}`),
  getReleaseReadiness: (projectId: string) =>
    request<ReleaseReadiness | null>(`/v1/projects/${projectId}/release-readiness`),
}
