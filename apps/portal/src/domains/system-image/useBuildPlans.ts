import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { buildPlanApi } from './buildPlanApi'
import type { ImageReadScope } from './useImageRevisions'

const sensitiveRead = { staleTime: 0, gcTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }
export function useBuildPlans(scope: ImageReadScope, cursor: string) {
  const query = useQuery({ ...sensitiveRead,
    queryKey: ['system-image-build-plans', scope.projectId, scope.sessionId, cursor],
    queryFn: ({ signal }) => buildPlanApi.list(scope.projectId, cursor, signal),
  })
  const { onFailure } = scope
  useEffect(() => { if (query.isError) onFailure(true) }, [query.isError, onFailure])
  return query
}
export function useBuildPlan(scope: ImageReadScope, planId: string) {
  const query = useQuery({ ...sensitiveRead,
    queryKey: ['system-image-build-plans', scope.projectId, scope.sessionId, 'detail', planId],
    queryFn: ({ signal }) => buildPlanApi.read(scope.projectId, planId, signal),
  })
  const { onFailure } = scope
  useEffect(() => { if (query.isError) onFailure(true) }, [query.isError, onFailure])
  return query
}
