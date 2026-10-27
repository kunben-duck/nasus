import { useQuery } from '@tanstack/react-query'

import { qualityLoopApi } from '../quality-loop/api'
import { systemImageApi } from '../system-image/api'
import { requireActiveQueryScope } from '../../shared/api/queryScope'

export function useProjectWorkspaceData(projectId: string | null, options: {
  reviewingBuild?: boolean; canReadWorkspace?: () => boolean
} = {}) {
  const reviewingBuild = options.reviewingBuild === true
  const canRead = () => !reviewingBuild && options.canReadWorkspace?.() !== false
  const projectWorkspaceQuery = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => qualityLoopApi.getProject(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  })
  const project = projectWorkspaceQuery.data?.project
  const systemImageQuery = useQuery({
    queryKey: ['system-image', project?.id],
    queryFn: async ({ signal }) => {
      requireActiveQueryScope(canRead, signal)
      const image = await systemImageApi.getSystemImage(project!.id, signal)
      requireActiveQueryScope(canRead, signal)
      return image
    },
    enabled: Boolean(project?.id) && !reviewingBuild,
    retry: false,
  })
  const releaseReadinessQuery = useQuery({
    queryKey: ['release-readiness', project?.id],
    queryFn: async ({ signal }) => {
      requireActiveQueryScope(canRead, signal)
      const readiness = await qualityLoopApi.getReleaseReadiness(project!.id, signal)
      requireActiveQueryScope(canRead, signal)
      return readiness
    },
    enabled: Boolean(project?.id) && !reviewingBuild,
    retry: false,
  })

  return {
    project,
    workspace: projectWorkspaceQuery.data,
    // Exact build review has its own private reads. Never display a cached
    // whole-project projection or let unrelated queries gate that review.
    systemImage: reviewingBuild || systemImageQuery.isError ? undefined : systemImageQuery.data,
    systemImageError: !reviewingBuild && systemImageQuery.isError,
    releaseReadiness: reviewingBuild ? undefined : releaseReadinessQuery.data,
    statusDependency: {
      // Readiness is optional until the first quality assessment exists. Its
      // absence must not make an otherwise healthy project workspace offline.
      isLoading: projectWorkspaceQuery.isLoading || (!reviewingBuild && systemImageQuery.isLoading),
      isError: Boolean(
        projectWorkspaceQuery.isError
        || (!reviewingBuild && systemImageQuery.isError)
      ),
    },
    projectLoading: projectWorkspaceQuery.isLoading,
  }
}
