import { useNavigate, useParams } from 'react-router-dom'

import { useProjectWorkspaceData } from '../../domains/platform/useProjectWorkspaceData'

export function useProjectRouteData() {
  const params = useParams()
  const navigate = useNavigate()
  const projectId = params.projectId ? decodeURIComponent(params.projectId) : null
  const projectWorkspace = useProjectWorkspaceData(projectId)

  return {
    projectId,
    project: projectWorkspace.project,
    workspace: projectWorkspace.workspace,
    systemImage: projectWorkspace.systemImage,
    releaseReadiness: projectWorkspace.releaseReadiness ?? undefined,
    projectStatusDependency: projectWorkspace.statusDependency,
    projectLoading: projectWorkspace.projectLoading,
    backToDashboard: () => navigate('/dashboard'),
  }
}
