import { useQuery } from '@tanstack/react-query'
import { readBuildReviewHandoff } from './buildReviewHandoffApi'
import type { BuildReviewSelection } from './buildReviewHandoff'

export function useBuildReviewHandoff(projectId: string, selection: BuildReviewSelection, sessionId: string) {
  return useQuery({
    queryKey: ['build-review-handoff', projectId, selection.goalId, selection.invocationId, sessionId],
    gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always',
    queryFn: ({ signal }) => readBuildReviewHandoff(projectId, selection, signal),
  })
}
