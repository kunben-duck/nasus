import { useQuery } from '@tanstack/react-query'
import { buildPlanApi } from './buildPlanApi'
import type { ImageReadScope } from './useImageRevisions'

export function useBuildTarget(scope: ImageReadScope, baselineId: string) {
  return useQuery({
    queryKey: ['system-image-build-target', scope.projectId, scope.sessionId, baselineId],
    enabled: Boolean(baselineId), retry: false, staleTime: 0, gcTime: 0, refetchOnWindowFocus: 'always',
    queryFn: ({ signal }) => buildPlanApi.target(scope.projectId, baselineId, signal),
  })
}
