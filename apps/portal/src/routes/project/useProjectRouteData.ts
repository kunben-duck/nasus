import { useNavigate, useParams } from 'react-router-dom'
import { useCallback } from 'react'

import { useProjectWorkspaceData } from '../../domains/platform/useProjectWorkspaceData'

export function isCurrentProjectWorkspace(projectId: string | null, location: { pathname: string; search: string }) {
  const params = new URLSearchParams(location.search)
  const path = projectId ? `/projects/${encodeURIComponent(projectId)}` : null
  return Boolean(path && (location.pathname === path || location.pathname.startsWith(`${path}/`)))
    && !params.has('build_review_goal') && !params.has('build_review_invocation')
}

export function useProjectRouteData(options: { reviewingBuild?: boolean } = {}) {
  const params = useParams()
  const navigate = useNavigate()
  const projectId = params.projectId ? decodeURIComponent(params.projectId) : null
  // Browser history changes before React retires outgoing query observers.
  const canReadWorkspace = useCallback(() => isCurrentProjectWorkspace(projectId, window.location), [projectId])
  const projectWorkspace = useProjectWorkspaceData(projectId, { ...options, canReadWorkspace })

  return {
    projectId,
    project: projectWorkspace.project,
    workspace: projectWorkspace.workspace,
    systemImage: projectWorkspace.systemImage,
    systemImageError: projectWorkspace.systemImageError,
    releaseReadiness: projectWorkspace.releaseReadiness ?? undefined,
    projectStatusDependency: projectWorkspace.statusDependency,
    projectLoading: projectWorkspace.projectLoading,
    canReadWorkspace,
    backToDashboard: () => navigate('/dashboard'),
  }
}
