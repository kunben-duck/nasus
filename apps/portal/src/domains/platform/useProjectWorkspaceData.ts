import { useQuery } from '@tanstack/react-query'

import { qualityLoopApi } from '../quality-loop/api'
import { systemImageApi } from '../system-image/api'

export function useProjectWorkspaceData(projectId: string | null) {
  const projectWorkspaceQuery = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => qualityLoopApi.getProject(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  })
  const project = projectWorkspaceQuery.data?.project
  const systemImageQuery = useQuery({
    queryKey: ['system-image', project?.id],
    queryFn: () => systemImageApi.getSystemImage(project!.id),
    enabled: Boolean(project?.id),
  })
  const releaseReadinessQuery = useQuery({
    queryKey: ['release-readiness', project?.id],
    queryFn: () => qualityLoopApi.getReleaseReadiness(project!.id),
    enabled: Boolean(project?.id),
    retry: false,
  })

  return {
    project,
    workspace: projectWorkspaceQuery.data,
    systemImage: systemImageQuery.data,
    releaseReadiness: releaseReadinessQuery.data,
    statusDependency: {
      // Readiness is optional until the first quality assessment exists. Its
      // absence must not make an otherwise healthy project workspace offline.
      isLoading: projectWorkspaceQuery.isLoading || systemImageQuery.isLoading,
      isError: Boolean(
        projectWorkspaceQuery.isError
        || systemImageQuery.isError
      ),
    },
    projectLoading: projectWorkspaceQuery.isLoading,
  }
}
